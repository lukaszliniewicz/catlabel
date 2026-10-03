"""Build a selected immutable release from committed Git blobs, without rebuilding assets."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

from catlabel.core.release_artifacts import (
    MAX_ARCHIVE_BYTES,
    MAX_INFLATED_FILE_BYTES,
    MAX_INFLATED_TOTAL_BYTES,
    ReleaseManifest,
    frontend_digest,
    hash_file,
)

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = frozenset(
    {
        "run.sh",
        "run.ps1",
        "run.bat",
        "pixi.toml",
        "pixi.lock",
        "pyproject.toml",
        "requirements.txt",
        "requirements-ai.txt",
        "README.md",
        "API_REFERENCE.md",
        "logo.webp",
        "NOTICE",
        "LICENSE",
        "LICENSE.txt",
        "LICENSE.md",
    }
)
TOOL_FILES = frozenset({"tools/bootstrap_runtime.py", "tools/probe_release.py"})


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def build_release(
    root: Path,
    source_ref: str,
    release_id: str,
    expected_frontend_sha256: str,
    output: Path,
) -> tuple[ReleaseManifest, str]:
    import hashlib

    source_commit = (
        _git(root, "rev-parse", "--verify", f"{source_ref}^{{commit}}")
        .decode("ascii")
        .strip()
    )
    tree = _git(root, "ls-tree", "-r", "-z", source_commit)
    blobs: dict[str, str] = {}
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if not (
            path in ROOT_FILES
            or path in TOOL_FILES
            or path.startswith(("catlabel/", "frontend/dist/"))
            or (
                path.startswith("docs/")
                and path.endswith(".md")
                and not path.startswith(("docs/reviews/", "docs/internal/"))
                and path
                not in {"docs/maintenance-progress.md", "docs/mcp-architecture.md"}
            )
        ):
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"Release input is not a regular Git blob: {path}")
        blobs[path] = object_id

    # Materialize only committed input bytes; a dirty working tree is never a release source.
    contents: dict[str, bytes] = {}
    total = 0
    for path, object_id in sorted(blobs.items()):
        size = int(_git(root, "cat-file", "-s", object_id))
        if size > MAX_INFLATED_FILE_BYTES or total + size > MAX_INFLATED_TOTAL_BYTES:
            raise ValueError("Release input exceeds artifact bounds")
        contents[path] = _git(root, "cat-file", "blob", object_id)
        total += size
    files = {
        path: hashlib.sha256(value).hexdigest() for path, value in contents.items()
    }
    digest = frontend_digest(files)
    if digest != expected_frontend_sha256:
        raise ValueError("Committed frontend differs from the accepted frontend digest")
    manifest = ReleaseManifest.from_dict(
        {
            "schema_version": 1,
            "release_id": release_id,
            "source_commit": source_commit,
            "database_epoch": 1,
            "frontend_sha256": digest,
            "files": files,
        }
    )
    manifest_bytes = (
        json.dumps(manifest.to_dict(), sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        os.close(descriptor)
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path, payload in sorted(
                {**contents, "release-manifest.json": manifest_bytes}.items()
            ):
                info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, payload)
        if temporary.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("Release archive exceeds artifact bounds")
        archive_sha256 = hash_file(temporary)
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return manifest, archive_sha256


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-commit", default="HEAD")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--frontend-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    manifest, digest = build_release(
        arguments.root,
        arguments.source_commit,
        arguments.release_id,
        arguments.frontend_sha256,
        arguments.output,
    )
    arguments.output.with_suffix(arguments.output.suffix + ".sha256").write_text(
        digest + "\n", encoding="ascii"
    )
    print(
        json.dumps(
            {
                "archive": str(arguments.output),
                "archive_sha256": digest,
                "release_id": manifest.release_id,
                "source_commit": manifest.source_commit,
                "frontend_sha256": manifest.frontend_sha256,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
