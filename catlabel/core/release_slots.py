"""Install and select immutable, hash-addressed CatLabel release slots."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from catlabel.core.release_artifacts import (
    MAX_MANIFEST_BYTES,
    ReleaseManifest,
    backup_database,
    extract_artifact,
    load_release_manifest,
    verify_artifact_directory,
)
from catlabel.core.runtime_lease import RuntimeLease

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_STATE_FIELDS = {"schema_version", "active", "previous"}
_MAX_STATE_BYTES = 16 * 1024
_MANIFEST_NAME = "release-manifest.json"


class _DuplicateJSONKey(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey("duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class InstalledRelease:
    archive_sha256: str
    path: Path
    manifest: ReleaseManifest


def _require_sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("invalid release archive digest")
    return value


def _require_real_directory(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise ValueError(f"release directory is missing: {path}") from error
    if not stat.S_ISDIR(mode):
        raise ValueError(f"release path is not a real directory: {path}")


def _ensure_release_root(root: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    _require_real_directory(root)

    releases = root / ".releases"
    releases.mkdir(exist_ok=True)
    _require_real_directory(releases)
    return releases


def _read_limited_regular_file(path: Path, maximum_bytes: int, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise ValueError(f"cannot safely read {label}") from error

    try:
        file_info = os.fstat(descriptor)
        if not stat.S_ISREG(file_info.st_mode):
            raise ValueError(f"{label} is not a regular file")

        # O_NOFOLLOW is not available on every supported platform.  This second
        # lstat also rejects a symlink if it was substituted before open.
        path_info = path.lstat()
        if not stat.S_ISREG(path_info.st_mode) or (
            path_info.st_dev != file_info.st_dev or path_info.st_ino != file_info.st_ino
        ):
            raise ValueError(f"{label} changed while opening")

        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        contents = b"".join(chunks)
        if len(contents) > maximum_bytes:
            raise ValueError(f"{label} exceeds its size limit")
        return contents
    finally:
        os.close(descriptor)


def _read_state_bytes(root: Path) -> bytes | None:
    state_path = root / "active.json"
    try:
        state_info = state_path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(state_info.st_mode):
        raise ValueError("active release state is not a regular file")
    return _read_limited_regular_file(
        state_path, _MAX_STATE_BYTES, "active release state"
    )


def _parse_state(raw_state: bytes) -> tuple[str, str | None]:
    try:
        payload = json.loads(
            raw_state.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKey) as error:
        raise ValueError("invalid active release state") from error

    if type(payload) is not dict:
        raise ValueError("invalid active release state")
    state = cast(dict[str, object], payload)
    if state.keys() != _STATE_FIELDS:
        raise ValueError("invalid active release state")
    version = state["schema_version"]
    active = state["active"]
    previous = state["previous"]
    if type(version) is not int or version != 1:
        raise ValueError("invalid active release state")
    active_digest = _require_sha256(active)
    previous_digest = None if previous is None else _require_sha256(previous)
    return active_digest, previous_digest


def _read_manifest(slot_path: Path) -> ReleaseManifest:
    manifest_path = slot_path / _MANIFEST_NAME
    initial_stat = manifest_path.lstat()
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ValueError("release manifest is not a regular file")
    if initial_stat.st_size > MAX_MANIFEST_BYTES:
        raise ValueError("release manifest exceeds its size limit")
    try:
        manifest = load_release_manifest(manifest_path)
        final_stat = manifest_path.lstat()
        if (
            not stat.S_ISREG(final_stat.st_mode)
            or final_stat.st_dev != initial_stat.st_dev
            or final_stat.st_ino != initial_stat.st_ino
        ):
            raise ValueError("release manifest changed while opening")
        return manifest
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("invalid release manifest") from error


def _load_slot(root: Path, archive_sha256: str) -> InstalledRelease:
    digest = _require_sha256(archive_sha256)
    root = Path(root)
    _require_real_directory(root)
    releases = root / ".releases"
    _require_real_directory(releases)
    slot_path = releases / digest
    _require_real_directory(slot_path)
    manifest = _read_manifest(slot_path)
    verify_artifact_directory(slot_path, manifest)
    return InstalledRelease(digest, slot_path, manifest)


def _active_release_from_bytes(
    root: Path, raw_state: bytes | None
) -> InstalledRelease | None:
    if raw_state is None:
        return None
    active_digest, _ = _parse_state(raw_state)
    return _load_slot(root, active_digest)


def load_active(root: Path) -> InstalledRelease | None:
    """Read the atomically published release pointer, validating its slot."""
    root = Path(root)
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(root_mode):
        raise ValueError("release state root is not a real directory")
    raw_state = _read_state_bytes(root)
    return _active_release_from_bytes(root, raw_state)


def _install_or_reuse_slot(
    root: Path, releases: Path, archive: Path, archive_sha256: str
) -> InstalledRelease:
    digest = _require_sha256(archive_sha256)
    slot_path = releases / digest

    try:
        slot_path.lstat()
    except FileNotFoundError:
        slot_exists = False
    else:
        slot_exists = True

    if slot_exists:
        installed = _load_slot(root, digest)
        verification_stage: Path | None = None
        try:
            verification_stage, archive_manifest = extract_artifact(
                archive, digest, releases
            )
            if archive_manifest.to_dict() != installed.manifest.to_dict():
                raise ValueError("existing release slot does not match the archive")
            return installed
        finally:
            if verification_stage is not None:
                shutil.rmtree(verification_stage, ignore_errors=True)

    stage: Path | None = None
    try:
        stage, archive_manifest = extract_artifact(archive, digest, releases)
        # The state lease serializes cooperating writers.  Refuse an already
        # present destination rather than allowing rename to replace it.
        try:
            slot_path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("release slot appeared during installation")
        stage.rename(slot_path)
        stage = None
        installed = _load_slot(root, digest)
        if installed.manifest.to_dict() != archive_manifest.to_dict():
            raise ValueError("installed release manifest does not match the archive")
        return installed
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def _make_database_backup(data_directory: Path) -> Path | None:
    source = data_directory / "catlabel.db"
    if not source.exists():
        return None

    backups = data_directory / "backups"
    while True:
        backup_path = backups / f"before-update-{uuid.uuid4().hex}.sqlite"
        if backup_path.exists():
            continue
        if backup_database(source, backup_path):
            return backup_path
        return None


def _verify_expected_slot(
    root: Path, archive_sha256: str, expected_manifest: dict[str, object]
) -> None:
    current = _load_slot(root, archive_sha256)
    if current.manifest.to_dict() != expected_manifest:
        raise ValueError("release manifest metadata changed during preparation")


def _make_probe_database(backup_path: Path | None, probe_directory: Path) -> None:
    if backup_path is not None:
        backup_database(backup_path, probe_directory / "catlabel.db")


def _cleanup_owned_directory(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def _state_json(active: str, previous: str | None) -> bytes:
    value = {"schema_version": 1, "active": active, "previous": previous}
    return (json.dumps(value, separators=(",", ":")) + "\n").encode("utf-8")


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_state(root: Path, expected_state: bytes | None, new_state: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".active-", suffix=".tmp", dir=root
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            if stream.write(new_state) != len(new_state):
                raise OSError("incomplete active state write")
            stream.flush()
            os.fsync(stream.fileno())

        if _read_state_bytes(root) != expected_state:
            raise RuntimeError("active release state changed during the operation")
        os.replace(temporary_path, root / "active.json")
        _fsync_directory(root)
    except BaseException:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)
        raise


def activate_artifact(
    root: Path,
    data_directory: Path,
    archive: Path,
    sha256: str,
    prepare: Callable[[Path], None],
    probe: Callable[[Path, ReleaseManifest, Path], None],
) -> InstalledRelease:
    """Install, prepare, and probe an artifact before publishing its pointer."""
    root = Path(root)
    data_directory = Path(data_directory)
    archive = Path(archive)
    digest = _require_sha256(sha256)

    with RuntimeLease(root / ".update-state"), RuntimeLease(data_directory):
        releases = _ensure_release_root(root)
        original_state = _read_state_bytes(root)
        active = _active_release_from_bytes(root, original_state)
        installed = _install_or_reuse_slot(root, releases, archive, digest)
        expected_manifest = installed.manifest.to_dict()

        database_backup = _make_database_backup(data_directory)
        prepare(installed.path)
        _verify_expected_slot(root, digest, expected_manifest)

        probe_directory = Path(tempfile.mkdtemp(prefix=".probe-", dir=data_directory))
        try:
            _make_probe_database(database_backup, probe_directory)
            probe(
                installed.path,
                ReleaseManifest.from_dict(expected_manifest),
                probe_directory,
            )
            _verify_expected_slot(root, digest, expected_manifest)
        finally:
            _cleanup_owned_directory(probe_directory)

        previous_digest: str | None
        if active is None:
            previous_digest = None
        elif active.archive_sha256 == digest:
            if original_state is None:
                previous_digest = None
            else:
                _, previous_digest = _parse_state(original_state)
        else:
            previous_digest = active.archive_sha256

        _publish_state(root, original_state, _state_json(digest, previous_digest))
        return installed


def rollback(root: Path, data_directory: Path) -> InstalledRelease:
    """Select the previous verified release without changing application data."""
    root = Path(root)
    data_directory = Path(data_directory)

    with RuntimeLease(root / ".update-state"), RuntimeLease(data_directory):
        _ensure_release_root(root)
        original_state = _read_state_bytes(root)
        if original_state is None:
            raise ValueError("there is no previous release to restore")
        active_digest, previous_digest = _parse_state(original_state)
        if previous_digest is None:
            raise ValueError("there is no previous release to restore")

        # Validate both sides before publishing a code-only pointer swap.
        _load_slot(root, active_digest)
        previous_release = _load_slot(root, previous_digest)
        _publish_state(
            root,
            original_state,
            _state_json(previous_digest, active_digest),
        )
        return previous_release
