from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import unicodedata
import zipfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

_MANIFEST_NAME = "release-manifest.json"
_MANIFEST_FIELDS = {
    "schema_version",
    "release_id",
    "source_commit",
    "database_epoch",
    "frontend_sha256",
    "files",
}
_RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_RESERVED_WINDOWS_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_REQUIRED_PATHS = {
    "catlabel/__main__.py",
    "catlabel/api/main.py",
    "tools/bootstrap_runtime.py",
    "run.sh",
    "run.bat",
    "run.ps1",
    "pixi.toml",
    "pixi.lock",
    "frontend/dist/index.html",
}

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_INFLATED_FILE_BYTES = 128 * 1024 * 1024
MAX_INFLATED_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 10_001
_IO_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    schema_version: int
    release_id: str
    source_commit: str
    database_epoch: int
    frontend_sha256: str
    files: dict[str, str]

    @classmethod
    def from_dict(cls, payload: object) -> ReleaseManifest:
        if type(payload) is not dict:
            raise ValueError("invalid release manifest")

        data = cast(dict[str, object], payload)
        if data.keys() != _MANIFEST_FIELDS:
            raise ValueError("invalid release manifest")

        schema_version = data["schema_version"]
        database_epoch = data["database_epoch"]
        release_id = data["release_id"]
        source_commit = data["source_commit"]
        frontend_sha256 = data["frontend_sha256"]
        raw_files = data["files"]

        if type(schema_version) is not int or schema_version != 1:
            raise ValueError("invalid release manifest")
        if type(database_epoch) is not int or database_epoch != 1:
            raise ValueError("invalid release manifest")
        if not isinstance(release_id, str) or _RELEASE_ID.fullmatch(release_id) is None:
            raise ValueError("invalid release manifest")
        if (
            not isinstance(source_commit, str)
            or _SOURCE_COMMIT.fullmatch(source_commit) is None
        ):
            raise ValueError("invalid release manifest")
        if (
            not isinstance(frontend_sha256, str)
            or _SHA256.fullmatch(frontend_sha256) is None
        ):
            raise ValueError("invalid release manifest")
        if type(raw_files) is not dict:
            raise ValueError("invalid release manifest")
        raw_file_map = cast(dict[object, object], raw_files)
        if not 1 <= len(raw_file_map) <= 10_000:
            raise ValueError("invalid release manifest")

        files: dict[str, str] = {}
        for raw_path, raw_digest in raw_file_map.items():
            if not isinstance(raw_path, str) or not isinstance(raw_digest, str):
                raise ValueError("invalid release manifest")
            _validate_relative_path(raw_path)
            if _SHA256.fullmatch(raw_digest) is None:
                raise ValueError("invalid release manifest")
            files[raw_path] = raw_digest

        _validate_path_set(files)
        if not _REQUIRED_PATHS.issubset(files):
            raise ValueError("invalid release manifest")
        if frontend_digest(files) != frontend_sha256:
            raise ValueError("invalid release manifest")

        return cls(
            schema_version=schema_version,
            release_id=release_id,
            source_commit=source_commit,
            database_epoch=database_epoch,
            frontend_sha256=frontend_sha256,
            files=files,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "source_commit": self.source_commit,
            "database_epoch": self.database_epoch,
            "frontend_sha256": self.frontend_sha256,
            "files": dict(self.files),
        }


def frontend_digest(files: Mapping[str, str]) -> str:
    frontend_files = sorted(
        (path, digest)
        for path, digest in files.items()
        if path.startswith("frontend/dist/")
    )
    if not any(path == "frontend/dist/index.html" for path, _ in frontend_files):
        raise ValueError("frontend index is missing")

    digest = hashlib.sha256()
    for path, file_digest in frontend_files:
        if _SHA256.fullmatch(file_digest) is None:
            raise ValueError("invalid frontend digest")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_IO_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def load_release_manifest(path: Path) -> ReleaseManifest:
    with path.open("rb") as stream:
        payload = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("release manifest is too large")
    return ReleaseManifest.from_dict(
        json.loads(
            payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    )


def _hash_archive_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    total = 0
    while chunk := stream.read(_IO_CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_ARCHIVE_BYTES:
            raise ValueError("archive is too large")
        digest.update(chunk)
    return digest.hexdigest()


def extract_artifact(
    archive: Path,
    expected_sha256: str,
    staging_parent: Path,
) -> tuple[Path, ReleaseManifest]:
    if _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError("invalid archive digest")
    stage: Path | None = None
    try:
        with archive.open("rb") as archive_stream:
            source_info = os.fstat(archive_stream.fileno())
            if not stat.S_ISREG(source_info.st_mode):
                raise ValueError("archive is not a regular file")
            if source_info.st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("archive is too large")
            if _hash_archive_stream(archive_stream) != expected_sha256:
                raise ValueError("archive digest mismatch")
            archive_stream.seek(0)
            with zipfile.ZipFile(archive_stream, "r") as archive_file:
                infos = archive_file.infolist()
                if len(infos) > MAX_ARCHIVE_ENTRIES:
                    raise ValueError("archive has too many entries")

                names: list[str] = []
                info_by_name: dict[str, zipfile.ZipInfo] = {}
                manifest_info: zipfile.ZipInfo | None = None
                total_declared = 0

                for info in infos:
                    name = info.filename
                    if info.orig_filename != name or info.is_dir():
                        raise ValueError("invalid archive entry")
                    if info.flag_bits & 0x1:
                        raise ValueError("encrypted archive entry")
                    if info.file_size < 0 or info.file_size > MAX_INFLATED_FILE_BYTES:
                        raise ValueError("archive entry is too large")
                    if name == _MANIFEST_NAME:
                        if (
                            info.file_size > MAX_MANIFEST_BYTES
                            or manifest_info is not None
                        ):
                            raise ValueError("invalid archive manifest entry")
                        manifest_info = info
                    else:
                        _validate_relative_path(name)

                    unix_mode = info.external_attr >> 16
                    if info.create_system == 3:
                        file_type = stat.S_IFMT(unix_mode)
                        if file_type not in (0, stat.S_IFREG):
                            raise ValueError("nonregular archive entry")

                    names.append(name)
                    info_by_name[name] = info
                    total_declared += info.file_size
                    if total_declared > MAX_INFLATED_TOTAL_BYTES:
                        raise ValueError("archive is too large when expanded")

                _validate_path_set(names)
                if manifest_info is None:
                    raise ValueError("archive manifest is missing")

                with archive_file.open(manifest_info, "r") as manifest_stream:
                    manifest_bytes = manifest_stream.read(MAX_MANIFEST_BYTES + 1)
                if (
                    len(manifest_bytes) > MAX_MANIFEST_BYTES
                    or len(manifest_bytes) != manifest_info.file_size
                ):
                    raise ValueError("invalid archive manifest size")
                try:
                    payload = json.loads(
                        manifest_bytes.decode("utf-8"),
                        object_pairs_hook=_reject_duplicate_json_keys,
                    )
                    manifest = ReleaseManifest.from_dict(payload)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                    raise ValueError("invalid archive manifest") from error

                expected_names = set(manifest.files) | {_MANIFEST_NAME}
                if set(names) != expected_names:
                    raise ValueError("archive entries do not match manifest")

                stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=staging_parent))
                total_actual = 0
                for name, expected_digest in manifest.files.items():
                    info = info_by_name[name]
                    target = stage.joinpath(*name.split("/"))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    file_digest = hashlib.sha256()
                    actual_size = 0
                    with (
                        archive_file.open(info, "r") as source,
                        target.open("xb") as destination,
                    ):
                        while chunk := source.read(_IO_CHUNK_BYTES):
                            next_size = actual_size + len(chunk)
                            next_total = total_actual + len(chunk)
                            if (
                                next_size > info.file_size
                                or next_size > MAX_INFLATED_FILE_BYTES
                                or next_total > MAX_INFLATED_TOTAL_BYTES
                            ):
                                raise ValueError(
                                    "archive entry expanded beyond its limits"
                                )
                            written = destination.write(chunk)
                            if written != len(chunk):
                                raise OSError("incomplete artifact write")
                            actual_size = next_size
                            total_actual = next_total
                            file_digest.update(chunk)
                    if (
                        actual_size != info.file_size
                        or file_digest.hexdigest() != expected_digest
                    ):
                        raise ValueError("artifact file digest mismatch")

                manifest_path = stage / _MANIFEST_NAME
                with manifest_path.open("xb") as destination:
                    if destination.write(manifest_bytes) != len(manifest_bytes):
                        raise OSError("incomplete manifest write")
                archive_stream.seek(0)
                if _hash_archive_stream(archive_stream) != expected_sha256:
                    raise ValueError("archive digest changed during extraction")
                return stage, manifest
    except BaseException:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        raise


def verify_artifact_directory(root: Path, manifest: ReleaseManifest) -> None:
    validated_manifest = ReleaseManifest.from_dict(manifest.to_dict())
    root_mode = root.lstat().st_mode
    if not stat.S_ISDIR(root_mode):
        raise ValueError("artifact root is not a directory")

    for relative_path, expected_digest in validated_manifest.files.items():
        current = root
        components = relative_path.split("/")
        for index, component in enumerate(components):
            current = current / component
            mode = current.lstat().st_mode
            is_leaf = index == len(components) - 1
            if is_leaf:
                if not stat.S_ISREG(mode):
                    raise ValueError("artifact entry is not a regular file")
            elif not stat.S_ISDIR(mode):
                raise ValueError("artifact parent is not a directory")

        if hash_file(current) != expected_digest:
            raise ValueError("artifact file digest mismatch")


def backup_database(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    source_path = source.resolve()
    destination_path = destination.resolve()
    if source_path == destination_path:
        raise ValueError("database source and destination must differ")

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary_path = Path(temporary_name)
    deadline = time.monotonic() + 30.0
    source_connection: sqlite3.Connection | None = None
    destination_connection: sqlite3.Connection | None = None

    def check_deadline(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() > deadline:
            raise TimeoutError("database backup deadline exceeded")

    try:
        os.close(descriptor)
        source_uri = f"{source_path.as_uri()}?mode=ro"
        source_connection = sqlite3.connect(source_uri, uri=True, timeout=5)
        destination_connection = sqlite3.connect(str(temporary_path), timeout=5)
        source_connection.backup(
            destination_connection,
            pages=256,
            progress=check_deadline,
            sleep=0.1,
        )
        if time.monotonic() > deadline:
            raise TimeoutError("database backup deadline exceeded")
        if destination_connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise sqlite3.DatabaseError("database backup quick_check failed")
        if time.monotonic() > deadline:
            raise TimeoutError("database backup deadline exceeded")
        destination_connection.close()
        destination_connection = None
        source_connection.close()
        source_connection = None
        os.replace(temporary_path, destination)
        return True
    except BaseException:
        for connection in (destination_connection, source_connection):
            if connection is not None:
                with suppress(BaseException):
                    connection.close()
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)
        raise


def _validate_relative_path(path: str) -> None:
    if (
        not path
        or path.startswith("/")
        or path.endswith("/")
        or "\\" in path
        or ":" in path
        or unicodedata.normalize("NFC", path) != path
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
    ):
        raise ValueError("invalid artifact path")

    components = path.split("/")
    if any(
        not component
        or component in {".", ".."}
        or component.endswith((" ", "."))
        or any(character in '<>"|?*' for character in component)
        for component in components
    ):
        raise ValueError("invalid artifact path")

    for component in components:
        basename = component.split(".", 1)[0].rstrip(" .").casefold()
        if basename in _RESERVED_WINDOWS_NAMES:
            raise ValueError("invalid artifact path")

    folded_path = path.casefold()
    if folded_path in {
        _MANIFEST_NAME,
        "bin",
        "data",
        ".pixi",
        ".git",
        ".bootstrap-state",
    } or folded_path.startswith(
        ("bin/", "data/", ".pixi/", ".git/", ".bootstrap-state/")
    ):
        raise ValueError("invalid artifact path")


def _validate_path_set(paths: list[str] | dict[str, str]) -> None:
    folded_paths: set[str] = set()
    for path in paths:
        folded = path.casefold()
        if folded in folded_paths:
            raise ValueError("artifact paths collide")
        folded_paths.add(folded)

    for path in paths:
        components = path.split("/")
        for end in range(1, len(components)):
            if "/".join(components[:end]).casefold() in folded_paths:
                raise ValueError("artifact paths collide")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
