"""Publish only the immutable, selected Luck A4 catalog update from local Git."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catlabel.vendors.generic.catalog_snapshot import load_snapshot  # noqa: E402, I001
from catlabel.vendors.generic.catalog_updates import (  # noqa: E402, I001
    ALLOWED_MODEL_KEYS,
    ALLOWED_PROFILE_KEYS,
    BASE_COMMIT,
    BASE_PROFILE_KEYS,
    LUCK_UPDATE_COMMIT,
    LUCK_UPDATE_FILENAME,
    apply_luck_updates,
)

DATA_DIR = ROOT / "catlabel" / "vendors" / "generic" / "data"
DEFAULT_REVISION = LUCK_UPDATE_COMMIT
SOURCE_DIRECTORY = "timiniprint/data"


def _read_source(repository_path: Path, commit: str, filename: str) -> Any:
    result = subprocess.run(
        ["git", "show", f"{commit}:{SOURCE_DIRECTORY}/{filename}"],
        cwd=repository_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def _records(raw: object, key: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("Expected upstream catalog list")
    result: list[dict[str, Any]] = []
    for value in cast(list[object], raw):
        if not isinstance(value, dict):
            raise ValueError("Expected upstream catalog object")
        record = cast(dict[str, Any], value)
        if not isinstance(record.get(key), str):
            raise ValueError(f"Expected upstream catalog {key}")
        result.append(record)
    return result


def build_updates(repository_path: Path) -> dict[str, Any]:
    """Read literal records from both exact pinned Git objects, without fetching."""
    base_profiles = _records(
        _read_source(repository_path, BASE_COMMIT, "printer_profiles.json"),
        "profile_key",
    )
    base_luck_keys = {
        profile["profile_key"]
        for profile in base_profiles
        if profile.get("protocol_default", {}).get("type") == "luck_normal_a4"
    }
    if frozenset(base_luck_keys) != BASE_PROFILE_KEYS:
        raise ValueError(
            "Pinned base no longer contains exactly the 15 approved Luck A4 profiles"
        )
    selected_models = _records(
        _read_source(repository_path, LUCK_UPDATE_COMMIT, "printer_models.json"),
        "model_key",
    )
    selected_profiles = _records(
        _read_source(repository_path, LUCK_UPDATE_COMMIT, "printer_profiles.json"),
        "profile_key",
    )
    models = [
        item for item in selected_models if item["model_key"] in ALLOWED_MODEL_KEYS
    ]
    profiles = [
        item
        for item in selected_profiles
        if item["profile_key"] in ALLOWED_PROFILE_KEYS
    ]
    if len(models) != 2 or len(profiles) != 16:
        raise ValueError(
            "Pinned update model/profile counts differ from the approved scope"
        )
    referenced = {key for profile in profiles for key in profile["paper_presets"]}
    presets = _read_source(
        repository_path, LUCK_UPDATE_COMMIT, "printer_paper_presets.json"
    )
    return {
        "schema_version": 1,
        "base_commit": BASE_COMMIT,
        "commit": LUCK_UPDATE_COMMIT,
        "models": models,
        "profiles": profiles,
        "paper_presets": {key: presets[key] for key in sorted(referenced)},
    }


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        with suppress(OSError):
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sync(
    revision: str = DEFAULT_REVISION,
    repository_path: Path = ROOT,
    *,
    output_path: Path | None = None,
    snapshot_path: Path | None = None,
) -> str:
    """Validate the complete merge before atomically replacing only the overlay."""
    if revision != LUCK_UPDATE_COMMIT:
        raise ValueError(
            "Only the exact selected Luck A4 commit is accepted; moving references are not allowed"
        )
    destination = (
        DATA_DIR / LUCK_UPDATE_FILENAME if output_path is None else output_path
    )
    base_path = (
        DATA_DIR / "catalog_snapshot.json" if snapshot_path is None else snapshot_path
    )
    overlay = build_updates(repository_path)
    apply_luck_updates(load_snapshot(base_path), overlay)
    serialized = json.dumps(overlay, indent=2, ensure_ascii=False) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
    _fsync_directory(destination.parent)
    return LUCK_UPDATE_COMMIT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "revision",
        nargs="?",
        default=DEFAULT_REVISION,
        help="Exact pinned Luck A4 update commit",
    )
    parser.add_argument(
        "--repository-path",
        type=Path,
        default=ROOT,
        help="Existing local TiMini-Print checkout; no fetch",
    )
    args = parser.parse_args()
    print(
        f"Published Luck A4 catalog updates from {sync(args.revision, args.repository_path)}"
    )


if __name__ == "__main__":
    main()
