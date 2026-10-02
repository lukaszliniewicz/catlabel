from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from catlabel.core.release_artifacts import extract_artifact, frontend_digest
from tools.build_release import build_release


class BuildReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="catlabel-build-release-")
        self.addCleanup(temporary.cleanup)
        self.scratch = Path(temporary.name)
        self.root = self.scratch / "repo"
        self.root.mkdir()
        self.contents = {
            "catlabel/__main__.py": b"entry",
            "catlabel/api/main.py": b"api",
            "tools/bootstrap_runtime.py": b"verify",
            "run.sh": b"shell",
            "run.bat": b"batch",
            "run.ps1": b"powershell",
            "pixi.toml": b"manifest",
            "pixi.lock": b"locked",
            "frontend/dist/index.html": b"accepted frontend",
        }
        for path, value in self.contents.items():
            destination = self.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(value)
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=CatLabel fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )
        self.frontend = frontend_digest(
            {
                path: hashlib.sha256(value).hexdigest()
                for path, value in self.contents.items()
            }
        )

    def git(self, *arguments: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments], check=True, capture_output=True
        ).stdout

    def test_build_uses_committed_bytes_and_reproduces_exact_archive(self) -> None:
        (self.root / "frontend/dist/index.html").write_bytes(
            b"dirty frontend must not ship"
        )
        (self.root / "data").mkdir()
        (self.root / "data/secret").write_bytes(b"untracked data must not ship")
        first = self.scratch / "first.zip"
        second = self.scratch / "second.zip"
        manifest, digest = build_release(
            self.root, "HEAD", "fixture-release", self.frontend, first
        )
        _, repeated_digest = build_release(
            self.root, "HEAD", "fixture-release", self.frontend, second
        )
        self.assertEqual(digest, repeated_digest)
        staging = self.scratch / "staging"
        staging.mkdir()
        stage, extracted = extract_artifact(first, digest, staging)
        self.assertEqual(extracted.to_dict(), manifest.to_dict())
        self.assertEqual(
            (stage / "frontend/dist/index.html").read_bytes(), b"accepted frontend"
        )
        self.assertFalse((stage / "data").exists())
        self.assertEqual(
            manifest.source_commit, self.git("rev-parse", "HEAD").decode().strip()
        )

    def test_frontend_mismatch_preserves_existing_output(self) -> None:
        output = self.scratch / "existing.zip"
        output.write_bytes(b"previous archive")
        with self.assertRaisesRegex(ValueError, "accepted frontend digest"):
            build_release(self.root, "HEAD", "fixture-release", "0" * 64, output)
        self.assertEqual(output.read_bytes(), b"previous archive")


if __name__ == "__main__":
    unittest.main()
