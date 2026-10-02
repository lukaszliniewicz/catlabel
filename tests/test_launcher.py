from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import launcher


class LauncherTests(unittest.TestCase):
    def test_environment_exists_accepts_default_or_headless_pixi_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.assertFalse(launcher.environment_exists(target))

            python = target / ".pixi" / "envs" / "headless" / "python.exe"
            python.parent.mkdir(parents=True)
            python.touch()

            self.assertTrue(launcher.environment_exists(target))

    def test_update_repo_uses_context_manager_and_marks_changed_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            repo = mock.Mock()
            repo.head.side_effect = [b"old", b"new"]
            context = mock.MagicMock()
            context.__enter__.return_value = repo
            porcelain = mock.Mock()
            porcelain.open_repo.return_value = context

            with mock.patch.object(launcher, "porcelain", porcelain):
                self.assertTrue(launcher.update_repo(target))

            porcelain.pull.assert_called_once_with(repo, launcher.REPO_URL, ff_only=True)
            self.assertEqual((target / ".update_needed").read_text(encoding="ascii"), "1")

    def test_run_app_uses_cmd_without_autorun_and_propagates_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            script = target / "run.bat"
            script.touch()
            process = mock.Mock()
            process.wait.return_value = 8

            with mock.patch.object(launcher.platform, "system", return_value="Windows"), mock.patch.object(
                launcher.subprocess, "Popen", return_value=process
            ) as popen:
                with mock.patch.dict(os.environ, {"COMSPEC": "C:\\Windows\\System32\\cmd.exe"}):
                    self.assertEqual(launcher.run_app(target), 8)

            popen.assert_called_once_with(
                ["C:\\Windows\\System32\\cmd.exe", "/d", "/c", "run.bat"],
                cwd=str(target),
            )

    def test_clone_repo_closes_the_repository(self) -> None:
        target = Path("C:/CatLabel/catlabel")
        repo = mock.Mock()
        porcelain = mock.Mock()
        porcelain.clone.return_value = repo
        with mock.patch.object(launcher, "porcelain", porcelain):
            self.assertTrue(launcher.clone_repo(target))

        porcelain.clone.assert_called_once_with(launcher.REPO_URL, str(target))
        repo.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
