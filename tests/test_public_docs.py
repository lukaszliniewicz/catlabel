from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.check_docs import public_docs_errors

ROOT = Path(__file__).resolve().parents[1]


class PublicDocsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="catlabel-public-docs-")
        self.root = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def write(self, path: str, contents: str) -> None:
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")

    def test_local_links_images_root_paths_and_tracked_directories_pass(self) -> None:
        self.write(
            "docs/start.md",
            "[guide](guide/?mode=full#start)\n"
            "![icon](../assets/icon%20one.png)\n"
            "[root](/docs/other.md#part)\n"
            "[reference][chapter]\n"
            "[chapter]: guide/chapter.md\n",
        )
        self.write("docs/other.md", "# Other\n")
        self.write("docs/guide/chapter.md", "# Chapter\n")
        self.write("assets/icon one.png", "synthetic fixture\n")
        tracked = [
            "docs/start.md",
            "docs/other.md",
            "docs/guide/chapter.md",
            "assets/icon one.png",
        ]

        self.assertEqual(public_docs_errors(self.root, tracked), [])

    def test_code_remote_mailto_and_fragment_destinations_are_ignored(self) -> None:
        self.write(
            "index.md",
            "`[inline](missing.md) ![image](missing.png)`\n"
            "``[double](missing.md)``\n"
            "~~~markdown\n[tilde](missing.md)\n~~~\n"
            "```md\n![fenced](missing.png)\n```\n"
            "[web](https://example.invalid/page)\n"
            "[mail](mailto:someone@example.invalid)\n"
            "[same](#section)\n"
            "[network](//example.invalid/page)\n",
        )

        self.assertEqual(public_docs_errors(self.root, ["index.md"]), [])

    def test_reference_link_definition_is_checked(self) -> None:
        self.write("index.md", "[manual][guide]\n\n[guide]: missing.md\n")

        errors = public_docs_errors(self.root, ["index.md"])

        self.assertEqual(len(errors), 1)
        self.assertIn("missing.md", errors[0])
        self.assertIn("link target is not tracked", errors[0])

    def test_private_missing_and_escaping_targets_are_reported_without_content(
        self,
    ) -> None:
        self.write(
            "docs/index.md",
            "[private](/docs/maintenance-progress.md)\n"
            "![private image](../.local-notes/secret.md)\n"
            "[missing](absent.md)\n"
            "[outside](../../outside.md)\n"
            "PUBLIC LINK LABEL ONLY\n",
        )
        self.write("docs/maintenance-progress.md", "PRIVATE FILE CONTENT\n")
        self.write("docs/mcp-architecture.md", "PRIVATE FILE CONTENT\n")
        self.write("docs/internal/secret.md", "PRIVATE FILE CONTENT\n")
        self.write("docs/reviews/report.md", "PRIVATE FILE CONTENT\n")
        self.write(".local-notes/secret.md", "PRIVATE FILE CONTENT\n")
        self.write("check-results/report.md", "PRIVATE FILE CONTENT\n")
        self.write("graphify-out/graph.md", "PRIVATE FILE CONTENT\n")
        tracked = [
            "docs/index.md",
            "docs/maintenance-progress.md",
            "docs/mcp-architecture.md",
            "docs/internal/secret.md",
            "docs/reviews/report.md",
            ".local-notes/secret.md",
            "check-results/report.md",
            "graphify-out/graph.md",
        ]

        errors = public_docs_errors(self.root, tracked)

        self.assertEqual(errors, sorted(errors))
        self.assertTrue(any("link target is not tracked" in error for error in errors))
        self.assertTrue(any("escapes repository root" in error for error in errors))
        self.assertTrue(any("link targets a private path" in error for error in errors))
        self.assertTrue(any("tracked path is private" in error for error in errors))
        self.assertFalse(any("PRIVATE FILE CONTENT" in error for error in errors))
        self.assertFalse(any("PUBLIC LINK LABEL ONLY" in error for error in errors))

    def test_cli_uses_index_after_staged_deletion_and_keeps_worktree_file(self) -> None:
        self.write("index.md", "# Public\n")
        self.write("deleted.md", "[missing](not-tracked.md)\n")
        self._git("init", "-q")
        self._git("add", "index.md", "deleted.md")
        self._git(
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        )
        self._git("rm", "--cached", "deleted.md")

        self.assertTrue((self.root / "deleted.md").exists())
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.check_docs",
                "--root",
                str(self.root),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("not-tracked.md", result.stderr)

    def test_cli_returns_two_when_root_is_not_a_git_repository(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.check_docs",
                "--root",
                str(self.root),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertNotIn("PRIVATE FILE CONTENT", result.stderr)

    def test_cli_returns_two_when_an_indexed_markdown_file_cannot_be_read(self) -> None:
        self.write("index.md", "# Public\n")
        self._git("init", "-q")
        self._git("add", "index.md")
        (self.root / "index.md").unlink()

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.check_docs",
                "--root",
                str(self.root),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("index.md", result.stderr)
        self.assertNotIn("# Public", result.stderr)

    def test_cli_returns_one_for_a_force_added_private_path(self) -> None:
        self.write("index.md", "# Public\n")
        self.write("docs/internal/secret.md", "PRIVATE FILE CONTENT\n")
        self._git("init", "-q")
        self._git("add", "index.md")
        self._git("add", "-f", "docs/internal/secret.md")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.check_docs",
                "--root",
                str(self.root),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/internal/secret.md", result.stderr)
        self.assertNotIn("PRIVATE FILE CONTENT", result.stderr)

    def _git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
