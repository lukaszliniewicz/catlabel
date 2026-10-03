"""Build a verified CatLabel launcher AppImage from committed source blobs."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))
build_release = importlib.import_module("tools.build_release").build_release

DEFAULT_CACHE_DIR = ROOT / ".launcher-build" / "appimage-tools"
TOOL_MANIFEST = Path(__file__).with_name("appimage_tool.json")
PYINSTALLER_VERSION = "6.21.0"
DOWNLOAD_TIMEOUT_SECONDS = 30
DOWNLOAD_CHUNK_BYTES = 64 * 1024
MAX_PIN_MANIFEST_BYTES = 16 * 1024
MAX_SOURCE_BLOB_BYTES = 128 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 512 * 1024 * 1024
MAX_APPIMAGE_BYTES = 300 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

_TRUSTED_TOOL_METADATA: dict[str, dict[str, object]] = {
    "appimagetool": {
        "filename": "appimagetool-x86_64.AppImage",
        "version": "1.9.1",
        "source_url": "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage",
        "size_bytes": 15092216,
        "sha256": "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0",
    },
    "runtime": {
        "filename": "runtime-x86_64",
        "version": "20251108",
        "source_url": "https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64",
        "size_bytes": 944632,
        "sha256": "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d",
    },
}

_REQUIRED_SOURCE_BLOBS = (
    "launcher.py",
    "catlabel/__init__.py",
    "catlabel/core/release_artifacts.py",
    "catlabel/core/release_slots.py",
    "catlabel/core/runtime_lease.py",
)
_OPTIONAL_SOURCE_BLOBS = ("catlabel/core/__init__.py",)
_OPTIONAL_LICENSE_BLOBS = ("LICENSE", "NOTICE")
_REQUIRED_PACKAGING_BLOBS = (
    "packaging/linux/AppRun",
    "packaging/linux/catlabel.desktop",
    "packaging/linux/catlabel.png",
    "packaging/linux/AppImage-runtime.LICENSE",
)


@dataclass(frozen=True, slots=True)
class PinnedTool:
    name: str
    filename: str
    version: str
    source_url: str
    size_bytes: int
    sha256: str


class _DuplicateJSONKey(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey("duplicate JSON key")
        result[key] = value
    return result


def load_tool_pins(manifest_path: Path | None = None) -> dict[str, PinnedTool]:
    """Load the reviewed pin record and reject any unreviewed trust override."""
    path = TOOL_MANIFEST if manifest_path is None else Path(manifest_path)
    with path.open("rb") as stream:
        payload = stream.read(MAX_PIN_MANIFEST_BYTES + 1)
    if len(payload) > MAX_PIN_MANIFEST_BYTES:
        raise ValueError("AppImage tool pin manifest is too large")
    try:
        decoded = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKey) as error:
        raise ValueError("invalid AppImage tool pin manifest") from error
    if decoded != _TRUSTED_TOOL_METADATA:
        raise ValueError("AppImage tool pin manifest differs from trusted pins")
    return {
        name: PinnedTool(
            name=name,
            filename=cast(str, metadata["filename"]),
            version=cast(str, metadata["version"]),
            source_url=cast(str, metadata["source_url"]),
            size_bytes=cast(int, metadata["size_bytes"]),
            sha256=cast(str, metadata["sha256"]),
        )
        for name, metadata in _TRUSTED_TOOL_METADATA.items()
    }


def verify_pinned_file(
    path: Path, pin: PinnedTool, *, require_executable: bool = False
) -> str:
    """Verify a regular, non-symlink file against a pinned size and SHA-256."""
    path = Path(path)
    try:
        initial_info = path.lstat()
    except OSError as error:
        raise ValueError(f"pinned {pin.name} file is unavailable: {path}") from error
    if not stat.S_ISREG(initial_info.st_mode):
        raise ValueError(f"pinned {pin.name} is not a regular file: {path}")
    if initial_info.st_size != pin.size_bytes:
        raise ValueError(f"pinned {pin.name} size mismatch: {path}")
    if require_executable and initial_info.st_mode & 0o111 == 0:
        raise ValueError(f"pinned {pin.name} is not executable: {path}")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"cannot safely open pinned {pin.name}: {path}") from error
    try:
        opened_info = os.fstat(descriptor)
        current_info = path.lstat()
        if (
            not stat.S_ISREG(opened_info.st_mode)
            or opened_info.st_dev != initial_info.st_dev
            or opened_info.st_ino != initial_info.st_ino
            or current_info.st_dev != opened_info.st_dev
            or current_info.st_ino != opened_info.st_ino
            or not stat.S_ISREG(current_info.st_mode)
        ):
            raise ValueError(f"pinned {pin.name} changed while opening: {path}")
        digest = hashlib.sha256()
        total = 0
        while chunk := os.read(descriptor, DOWNLOAD_CHUNK_BYTES):
            total += len(chunk)
            if total > pin.size_bytes:
                raise ValueError(f"pinned {pin.name} size mismatch: {path}")
            digest.update(chunk)
        if total != pin.size_bytes:
            raise ValueError(f"pinned {pin.name} size mismatch: {path}")
        actual = digest.hexdigest()
        if actual != pin.sha256:
            raise ValueError(f"pinned {pin.name} SHA-256 mismatch: {path}")
        return actual
    finally:
        os.close(descriptor)


def _ensure_cache_directory(cache_dir: Path) -> None:
    cache_dir = Path(cache_dir)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ValueError(f"cannot create AppImage tool cache: {cache_dir}") from error
    try:
        info = cache_dir.lstat()
    except OSError as error:
        raise ValueError(f"AppImage tool cache is unavailable: {cache_dir}") from error
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"AppImage tool cache is not a real directory: {cache_dir}")


def _download_pinned_file(pin: PinnedTool, destination: Path) -> Path:
    destination = Path(destination)
    _ensure_cache_directory(destination.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    total = 0
    digest = hashlib.sha256()
    try:
        request = urllib.request.Request(
            pin.source_url,
            headers={"User-Agent": "CatLabel-AppImage-builder/1"},
        )
        with os.fdopen(descriptor, "wb") as output:
            try:
                response = urllib.request.urlopen(
                    request, timeout=DOWNLOAD_TIMEOUT_SECONDS
                )
            except (OSError, urllib.error.URLError) as error:
                raise ValueError(f"could not download pinned {pin.name}") from error
            with response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError as error:
                        raise ValueError(
                            f"invalid download length for pinned {pin.name}"
                        ) from error
                    if declared_length != pin.size_bytes:
                        raise ValueError(f"pinned {pin.name} download size mismatch")
                while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                    total += len(chunk)
                    if total > pin.size_bytes:
                        raise ValueError(f"pinned {pin.name} download is too large")
                    output.write(chunk)
                    digest.update(chunk)
            if total != pin.size_bytes:
                raise ValueError(f"pinned {pin.name} download size mismatch")
            if digest.hexdigest() != pin.sha256:
                raise ValueError(f"pinned {pin.name} download SHA-256 mismatch")
            output.flush()
            os.fsync(output.fileno())

        os.chmod(temporary, 0o755 if pin.name == "appimagetool" else 0o644)
        os.replace(temporary, destination)
        verify_pinned_file(
            destination, pin, require_executable=pin.name == "appimagetool"
        )
        return destination
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def resolve_pinned_tool(
    name: str,
    cache_dir: Path,
    explicit_path: Path | None = None,
    *,
    pins: dict[str, PinnedTool] | None = None,
) -> Path:
    """Resolve one fixed pin, verifying explicit paths without changing them."""
    selected_pins = load_tool_pins() if pins is None else pins
    try:
        pin = selected_pins[name]
    except KeyError as error:
        raise ValueError(f"unknown pinned AppImage tool: {name}") from error
    require_executable = name == "appimagetool"
    if explicit_path is not None:
        path = Path(explicit_path).expanduser()
        verify_pinned_file(path, pin, require_executable=require_executable)
        return path.absolute()

    cache_dir = Path(cache_dir).expanduser()
    _ensure_cache_directory(cache_dir)
    cached = cache_dir / pin.filename
    if cached.exists() or cached.is_symlink():
        verify_pinned_file(cached, pin)
        if require_executable:
            cached.chmod(0o755)
            verify_pinned_file(cached, pin, require_executable=True)
        return cached.absolute()
    return _download_pinned_file(pin, cached).absolute()


def _run_git(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], check=True, capture_output=True
    )
    return result.stdout


def _resolve_source_commit(root: Path, source_ref: str) -> str:
    if not source_ref or source_ref.startswith("-"):
        raise ValueError("source commit must be a nonempty Git commit reference")
    resolved = (
        _run_git(root, "rev-parse", "--verify", f"{source_ref}^{{commit}}")
        .decode("ascii")
        .strip()
    )
    if re.fullmatch(r"[0-9a-f]{40}", resolved) is None:
        raise ValueError("Git did not resolve the source reference to a commit")
    return resolved


def _git_blob_entries(root: Path, source_commit: str) -> dict[str, tuple[str, str]]:
    paths = (
        *_REQUIRED_SOURCE_BLOBS,
        *_OPTIONAL_SOURCE_BLOBS,
        *_OPTIONAL_LICENSE_BLOBS,
        *_REQUIRED_PACKAGING_BLOBS,
    )
    tree = _run_git(root, "ls-tree", "-r", "-z", source_commit, "--", *paths)
    entries: dict[str, tuple[str, str]] = {}
    for raw_entry in tree.split(b"\0"):
        if not raw_entry:
            continue
        raw_metadata, raw_path = raw_entry.split(b"\t", 1)
        mode, kind, object_id = raw_metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if path not in paths:
            raise ValueError(f"unexpected Git source path: {path}")
        if path in entries:
            raise ValueError(f"duplicate Git source path: {path}")
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"Git source is not a regular blob: {path}")
        if path == "packaging/linux/AppRun" and mode != "100755":
            raise ValueError("committed AppRun must have executable mode 0755")
        entries[path] = (mode, object_id)
    return entries


def _read_committed_blob(
    root: Path, object_id: str, total_so_far: int
) -> tuple[bytes, int]:
    size_bytes = int(_run_git(root, "cat-file", "-s", object_id).decode("ascii"))
    if size_bytes < 0 or size_bytes > MAX_SOURCE_BLOB_BYTES:
        raise ValueError("committed AppImage input exceeds the per-file size limit")
    total = total_so_far + size_bytes
    if total > MAX_SOURCE_TOTAL_BYTES:
        raise ValueError("committed AppImage inputs exceed the total size limit")
    contents = _run_git(root, "cat-file", "blob", object_id)
    if len(contents) != size_bytes:
        raise ValueError("Git blob size changed while materializing AppImage inputs")
    return contents, total


def materialize_committed_inputs(
    root: Path, source_commit: str, source_root: Path, appdir: Path
) -> None:
    """Copy only named regular blobs from the requested commit into build staging."""
    root = Path(root).resolve()
    source_root = Path(source_root)
    appdir = Path(appdir)
    entries = _git_blob_entries(root, source_commit)
    missing = sorted(
        path
        for path in (*_REQUIRED_SOURCE_BLOBS, *_REQUIRED_PACKAGING_BLOBS)
        if path not in entries
    )
    if missing:
        raise ValueError(
            "source commit is missing required AppImage input: " + ", ".join(missing)
        )

    source_destinations = {
        "launcher.py": source_root / "launcher.py",
        "catlabel/__init__.py": source_root / "catlabel" / "__init__.py",
        "catlabel/core/__init__.py": source_root / "catlabel" / "core" / "__init__.py",
        "catlabel/core/release_artifacts.py": source_root
        / "catlabel"
        / "core"
        / "release_artifacts.py",
        "catlabel/core/release_slots.py": source_root
        / "catlabel"
        / "core"
        / "release_slots.py",
        "catlabel/core/runtime_lease.py": source_root
        / "catlabel"
        / "core"
        / "runtime_lease.py",
    }
    packaging_destinations = {
        "packaging/linux/AppRun": appdir / "AppRun",
        "packaging/linux/catlabel.desktop": appdir / "catlabel.desktop",
        "packaging/linux/catlabel.png": appdir / "catlabel.png",
        "packaging/linux/AppImage-runtime.LICENSE": appdir
        / "usr"
        / "share"
        / "licenses"
        / "catlabel"
        / "AppImage-runtime.LICENSE",
        "LICENSE": appdir / "usr" / "share" / "licenses" / "catlabel" / "LICENSE",
        "NOTICE": appdir / "usr" / "share" / "licenses" / "catlabel" / "NOTICE",
    }
    total = 0
    for repository_path, (mode, object_id) in sorted(entries.items()):
        contents, total = _read_committed_blob(root, object_id, total)
        destinations: list[Path] = []
        if repository_path in source_destinations:
            destinations.append(source_destinations[repository_path])
        if repository_path in packaging_destinations:
            destinations.append(packaging_destinations[repository_path])
        if repository_path == "packaging/linux/catlabel.png":
            destinations.append(appdir / ".DirIcon")
        for destination in destinations:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)
            destination.chmod(
                0o755
                if repository_path == "packaging/linux/AppRun"
                else int(mode, 8) & 0o777
            )


def _require_linux_x86_64() -> None:
    if platform.system() != "Linux" or platform.machine().lower() not in {
        "x86_64",
        "amd64",
    }:
        raise RuntimeError("AppImage builds are supported only on Linux x86_64")


def _require_pyinstaller_version() -> None:
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("AppImage launcher builds require Python 3.11")
    try:
        installed = importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(
            f"PyInstaller {PYINSTALLER_VERSION} must be installed in this Python"
        ) from error
    if installed != PYINSTALLER_VERSION:
        raise RuntimeError(
            f"PyInstaller {PYINSTALLER_VERSION} is required; found {installed}"
        )


def _copy_optional_regular_file(source: Path, destination: Path) -> bool:
    source = Path(source)
    try:
        info = source.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"optional license source is not a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o644)
    return True


def _pyinstaller_license_paths() -> list[Path]:
    try:
        distribution = importlib.metadata.distribution("pyinstaller")
    except importlib.metadata.PackageNotFoundError:
        return []

    paths: list[Path] = []
    distribution_files = list(distribution.files or [])
    for license_name in distribution.metadata.get_all("License-File", []) or []:
        relative = PurePosixPath(license_name)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        candidates = [str(relative)]
        candidates.extend(
            str(distribution_file)
            for distribution_file in distribution_files
            if PurePosixPath(str(distribution_file)).name == relative.name
            and "licenses" in PurePosixPath(str(distribution_file)).parts
        )
        for candidate_name in candidates:
            candidate = Path(str(distribution.locate_file(candidate_name)))
            if candidate.exists() or candidate.is_symlink():
                paths.append(candidate)
                break
    if not paths:
        package_root = Path(str(distribution.locate_file("PyInstaller")))
        for filename in ("LICENSE.txt", "LICENSE", "COPYING.txt", "COPYING"):
            candidate = package_root / filename
            if candidate.exists() or candidate.is_symlink():
                paths.append(candidate)
                break
    return paths


def _copy_optional_build_licenses(appdir: Path) -> None:
    license_dir = appdir / "usr" / "share" / "licenses" / "catlabel"
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    _copy_optional_regular_file(python_license, license_dir / "LICENSE.txt")
    for index, source in enumerate(_pyinstaller_license_paths(), start=1):
        basename = source.name or f"LICENSE-{index}.txt"
        destination = license_dir / f"PyInstaller-{basename}"
        _copy_optional_regular_file(source, destination)


def _pyinstaller_command(
    source_root: Path,
    workspace: Path,
    archive: Path,
    checksum: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onedir",
        "--name",
        "CatLabel-Launcher",
        "--noconfirm",
        "--clean",
        "--noupx",
        "--distpath",
        str(workspace / "frozen"),
        "--workpath",
        str(workspace / "pyi"),
        "--specpath",
        str(workspace),
        "--paths",
        str(source_root),
        "--add-data",
        f"{archive}:.",
        "--add-data",
        f"{checksum}:.",
        str(source_root / "launcher.py"),
    ]


def _run_pyinstaller(
    source_root: Path, workspace: Path, archive: Path, checksum: Path
) -> Path:
    command = _pyinstaller_command(source_root, workspace, archive, checksum)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    subprocess.run(command, cwd=workspace, env=environment, check=True)
    return workspace / "frozen" / "CatLabel-Launcher"


def _validate_appimage(path: Path) -> str:
    path = Path(path)
    try:
        initial_info = path.lstat()
    except OSError as error:
        raise ValueError(f"appimagetool did not produce an AppImage: {path}") from error
    if not stat.S_ISREG(initial_info.st_mode):
        raise ValueError("appimagetool output is not a regular file")
    if initial_info.st_size >= MAX_APPIMAGE_BYTES:
        raise ValueError("AppImage exceeds the 300 MiB size limit")
    if initial_info.st_size < 11:
        raise ValueError("appimagetool output is too small to be an AppImage")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("cannot safely open appimagetool output") from error
    try:
        opened_info = os.fstat(descriptor)
        current_info = path.lstat()
        if (
            not stat.S_ISREG(opened_info.st_mode)
            or opened_info.st_dev != initial_info.st_dev
            or opened_info.st_ino != initial_info.st_ino
            or current_info.st_dev != opened_info.st_dev
            or current_info.st_ino != opened_info.st_ino
            or opened_info.st_size != initial_info.st_size
        ):
            raise ValueError("appimagetool output changed while opening")
        header = os.read(descriptor, 11)
        if header[:4] != b"\x7fELF" or header[8:11] != b"AI\x02":
            raise ValueError("appimagetool output is not a type 2 ELF AppImage")
        digest = hashlib.sha256()
        os.lseek(descriptor, 0, os.SEEK_SET)
        while chunk := os.read(descriptor, DOWNLOAD_CHUNK_BYTES):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _existing_output_is_safe(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"output path is not a regular file: {path}")


def _publish_appimage(source: Path, output: Path, expected_sha256: str) -> str:
    output = Path(output)
    if output.suffix != ".AppImage":
        raise ValueError("output must have the .AppImage suffix")
    output.parent.mkdir(parents=True, exist_ok=True)
    sidecar = output.with_suffix(output.suffix + ".sha256")
    _existing_output_is_safe(output)
    _existing_output_is_safe(sidecar)

    image_descriptor, image_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    sidecar_descriptor, sidecar_name = tempfile.mkstemp(
        prefix=f".{sidecar.name}.", suffix=".tmp", dir=output.parent
    )
    staged_image = Path(image_name)
    staged_sidecar = Path(sidecar_name)
    output_backup: Path | None = None
    sidecar_backup: Path | None = None
    image_published = False
    sidecar_published = False
    source_descriptor = -1
    try:
        source_info = Path(source).lstat()
        if not stat.S_ISREG(source_info.st_mode):
            raise ValueError("validated AppImage staging output changed type")
        source_flags = (
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        source_descriptor = os.open(source, source_flags)
        with os.fdopen(image_descriptor, "wb") as image_stream:
            image_descriptor = -1
            opened_info = os.fstat(source_descriptor)
            if (
                opened_info.st_dev != source_info.st_dev
                or opened_info.st_ino != source_info.st_ino
            ):
                raise ValueError("validated AppImage staging output changed")
            total = 0
            while chunk := os.read(source_descriptor, DOWNLOAD_CHUNK_BYTES):
                total += len(chunk)
                if total >= MAX_APPIMAGE_BYTES:
                    raise ValueError("AppImage exceeds the 300 MiB size limit")
                image_stream.write(chunk)
            image_stream.flush()
            os.fsync(image_stream.fileno())
        os.close(source_descriptor)
        source_descriptor = -1
        staged_hash = _validate_appimage(staged_image)
        if staged_hash != expected_sha256:
            raise ValueError("AppImage changed while staging for publication")
        os.chmod(staged_image, 0o755)

        with os.fdopen(sidecar_descriptor, "w", encoding="ascii") as sidecar_stream:
            sidecar_descriptor = -1
            sidecar_stream.write(staged_hash + "\n")
            sidecar_stream.flush()
            os.fsync(sidecar_stream.fileno())
        os.chmod(staged_sidecar, 0o644)

        if output.exists():
            output_backup = _make_hardlink_backup(output)
        if sidecar.exists():
            sidecar_backup = _make_hardlink_backup(sidecar)
        os.replace(staged_image, output)
        image_published = True
        os.replace(staged_sidecar, sidecar)
        sidecar_published = True
        return staged_hash
    except BaseException:
        if image_published:
            if output_backup is None:
                output.unlink(missing_ok=True)
            else:
                os.replace(output_backup, output)
                output_backup = None
        if sidecar_published:
            if sidecar_backup is None:
                sidecar.unlink(missing_ok=True)
            else:
                os.replace(sidecar_backup, sidecar)
                sidecar_backup = None
        raise
    finally:
        if image_descriptor >= 0:
            os.close(image_descriptor)
        if sidecar_descriptor >= 0:
            os.close(sidecar_descriptor)
        if source_descriptor >= 0:
            os.close(source_descriptor)
        staged_image.unlink(missing_ok=True)
        staged_sidecar.unlink(missing_ok=True)
        if output_backup is not None:
            output_backup.unlink(missing_ok=True)
        if sidecar_backup is not None:
            sidecar_backup.unlink(missing_ok=True)


def _make_hardlink_backup(path: Path) -> Path:
    descriptor, backup_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".backup", dir=path.parent
    )
    os.close(descriptor)
    backup = Path(backup_name)
    backup.unlink()
    try:
        os.link(path, backup, follow_symlinks=False)
    except OSError as error:
        raise ValueError(
            f"cannot preserve existing output before replacement: {path}"
        ) from error
    return backup


def _run_appimagetool(
    appimagetool: Path, runtime_file: Path, appdir: Path, output: Path, cwd: Path
) -> None:
    environment = os.environ.copy()
    environment["ARCH"] = "x86_64"
    environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    subprocess.run(
        [
            str(appimagetool),
            "--runtime-file",
            str(runtime_file),
            "--comp",
            "zstd",
            str(appdir),
            str(output),
        ],
        cwd=cwd,
        env=environment,
        check=True,
    )


def build_appimage(
    root: Path,
    source_ref: str,
    release_id: str,
    frontend_sha256: str,
    output: Path,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    appimagetool_path: Path | None = None,
    runtime_file: Path | None = None,
) -> dict[str, str]:
    """Build one AppImage from a committed launcher and release archive."""
    _require_linux_x86_64()
    _require_pyinstaller_version()
    if _SHA256.fullmatch(frontend_sha256) is None:
        raise ValueError("frontend SHA-256 must be 64 lowercase hexadecimal characters")
    output = Path(output).expanduser().absolute()
    if output.suffix != ".AppImage":
        raise ValueError("output must have the .AppImage suffix")

    root = Path(root).expanduser().resolve()
    source_commit = _resolve_source_commit(root, source_ref)
    pins = load_tool_pins()
    appimagetool = resolve_pinned_tool(
        "appimagetool", cache_dir, appimagetool_path, pins=pins
    )
    selected_runtime = resolve_pinned_tool(
        "runtime", cache_dir, runtime_file, pins=pins
    )

    with tempfile.TemporaryDirectory(prefix="catlabel-appimage-") as temporary_name:
        workspace = Path(temporary_name)
        source_root = workspace / "source"
        appdir = workspace / "AppDir"
        source_root.mkdir()
        appdir.mkdir()
        materialize_committed_inputs(root, source_commit, source_root, appdir)

        archive = source_root / "CatLabel-release.zip"
        manifest, archive_sha256 = build_release(
            root, source_commit, release_id, frontend_sha256, archive
        )
        if (
            manifest.source_commit != source_commit
            or manifest.frontend_sha256 != frontend_sha256
        ):
            raise ValueError("release archive metadata differs from AppImage inputs")
        checksum = archive.with_suffix(archive.suffix + ".sha256")
        checksum.write_text(archive_sha256 + "\n", encoding="ascii")

        frozen = _run_pyinstaller(source_root, workspace, archive, checksum)
        if not frozen.is_dir():
            raise ValueError("PyInstaller did not produce the expected onedir output")
        usr_bin = appdir / "usr" / "bin"
        shutil.copytree(frozen, usr_bin, dirs_exist_ok=True)
        _copy_optional_build_licenses(appdir)

        appimage_staging = workspace / "CatLabel-x86_64.AppImage"
        _run_appimagetool(
            appimagetool, selected_runtime, appdir, appimage_staging, workspace
        )
        appimage_sha256 = _validate_appimage(appimage_staging)
        published_sha256 = _publish_appimage(appimage_staging, output, appimage_sha256)
        if published_sha256 != appimage_sha256:
            raise ValueError("AppImage changed while publishing")

    return {
        "archive_sha256": archive_sha256,
        "appimage": str(output),
        "appimage_sha256": appimage_sha256,
        "frontend_sha256": frontend_sha256,
        "release_id": manifest.release_id,
        "source_commit": source_commit,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-commit", default="HEAD")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--frontend-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--appimagetool", type=Path)
    parser.add_argument("--runtime-file", type=Path)
    arguments = parser.parse_args(argv)
    try:
        result = build_appimage(
            arguments.root,
            arguments.source_commit,
            arguments.release_id,
            arguments.frontend_sha256,
            arguments.output,
            arguments.cache_dir,
            arguments.appimagetool,
            arguments.runtime_file,
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        urllib.error.URLError,
    ) as error:
        print(f"AppImage build failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
