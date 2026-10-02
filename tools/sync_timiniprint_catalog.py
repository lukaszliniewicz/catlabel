"""Publish one validated TiMini-Print catalog snapshot for CatLabel.

This is a maintainer tool, not an installation/runtime dependency. It reads a
Git revision already available locally and atomically writes a JSON bundle under
``catlabel/vendors/generic/data``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catlabel.vendors.generic.catalog_snapshot import validate_snapshot  # noqa: E402, I001


DATA_DIR = ROOT / "catlabel" / "vendors" / "generic" / "data"
SNAPSHOT_FILENAME = "catalog_snapshot.json"
UPSTREAM_REPOSITORY = "https://github.com/Dejniel/TiMini-Print"
DEFAULT_REVISION = "v0.7.3"

SOURCE_PATHS = {
    "catalog_models.json": "timiniprint/data/printer_models.json",
    "catalog_unsupported.json": "timiniprint/data/printer_models_unsupported.json",
    "catalog_profiles.json": "timiniprint/data/printer_profiles.json",
    "catalog_paper_presets.json": "timiniprint/data/printer_paper_presets.json",
}
MODERN_ORIGIN_SOURCE = "timiniprint/data/origins.json"
LEGACY_ORIGIN_SOURCE = "timiniprint/data/origin_apps.json"
ORIGIN_DESTINATION = "catalog_origin_apps.json"
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _git(repository_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout


def _source_exists(repository_path: Path, commit: str, source: str) -> bool:
    listed = _git(
        repository_path,
        "ls-tree",
        "-r",
        "--name-only",
        "--full-tree",
        commit,
        "--",
        source,
    )
    return source in listed.splitlines()


def _fsync_directory(directory: Path) -> None:
    if os.name != "posix":
        return
    try:
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        with suppress(OSError):
            os.fsync(directory_fd)
    finally:
        with suppress(OSError):
            os.close(directory_fd)


def _source_paths(repository_path: Path, commit: str) -> dict[str, str]:
    origin_source = (
        MODERN_ORIGIN_SOURCE
        if _source_exists(repository_path, commit, MODERN_ORIGIN_SOURCE)
        else LEGACY_ORIGIN_SOURCE
    )
    return {
        **SOURCE_PATHS,
        ORIGIN_DESTINATION: origin_source,
    }


def _acquire_sources(
    repository_path: Path,
    commit: str,
    paths: dict[str, str],
) -> dict[str, str]:
    return {
        destination: _git(repository_path, "show", f"{commit}:{source}")
        for destination, source in paths.items()
    }


def sync(revision: str, repository_path: Path = ROOT) -> str:
    """Publish ``revision`` as one validated snapshot and return its commit."""

    commit = _git(
        repository_path,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{revision}^{{commit}}",
    ).strip()
    if not _COMMIT_RE.fullmatch(commit):
        raise ValueError(f"Git resolved {revision!r} to an invalid 40-character commit")

    paths = _source_paths(repository_path, commit)
    raw_sources = _acquire_sources(repository_path, commit, paths)
    catalogs = {
        destination: json.loads(raw) for destination, raw in raw_sources.items()
    }
    snapshot = {
        "schema_version": 1,
        "source": {
            "repository": UPSTREAM_REPOSITORY,
            "revision": revision,
            "commit": commit,
            "license": "Apache-2.0",
            "files": paths,
        },
        "catalogs": catalogs,
    }
    validated = validate_snapshot(snapshot)
    serialized = json.dumps(validated, indent=2, ensure_ascii=False) + "\n"

    snapshot_path = DATA_DIR / SNAPSHOT_FILENAME
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=DATA_DIR,
            prefix=f".{snapshot_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, snapshot_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)

    _fsync_directory(DATA_DIR)
    return commit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "revision",
        nargs="?",
        default=DEFAULT_REVISION,
        help=f"TiMini-Print Git revision (default: {DEFAULT_REVISION})",
    )
    parser.add_argument(
        "--repository-path",
        type=Path,
        default=ROOT,
        help="Local TiMini-Print Git checkout (no fetch is performed)",
    )
    args = parser.parse_args()
    commit = sync(args.revision, repository_path=args.repository_path)
    print(f"Published TiMini-Print catalog snapshot from {commit}")


if __name__ == "__main__":
    main()
