from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import launcher
from catlabel.core.release_artifacts import ReleaseManifest
from catlabel.core.runtime_lease import RuntimeBusyError


class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="catlabel-launcher-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.current = SimpleNamespace(
            path=self.root / "accepted",
            manifest=SimpleNamespace(release_id="accepted-1"),
        )
        environment = mock.patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def invoke(self, *options: str) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return launcher.main(["--installation-root", str(self.root), *options])

    def test_offline_restart_uses_accepted_slot_without_selecting_update(self) -> None:
        with (
            mock.patch.object(launcher, "load_active", return_value=self.current),
            mock.patch.object(launcher, "activate_artifact") as activate,
            mock.patch.object(launcher, "_bundled_artifact") as bundle,
            mock.patch.object(launcher, "run_app", return_value=8) as run,
        ):
            self.assertEqual(self.invoke(), 8)
        run.assert_called_once_with(self.current.path, self.data, [])
        activate.assert_not_called()
        bundle.assert_not_called()

    def test_failed_selected_update_preserves_local_release_and_drops_addon_changes(
        self,
    ) -> None:
        with (
            mock.patch.object(launcher, "load_active", return_value=self.current),
            mock.patch.object(
                launcher, "activate_artifact", side_effect=ValueError("bad artifact")
            ),
            mock.patch.object(launcher, "run_app", return_value=0) as run,
        ):
            self.assertEqual(
                self.invoke(
                    "--artifact",
                    str(self.root / "candidate.zip"),
                    "--sha256",
                    "a" * 64,
                    "--install-ai",
                    "--setup-only",
                ),
                0,
            )
        run.assert_called_once_with(self.current.path, self.data, ["--setup-only"])
        self.assertFalse(self.data.exists())

    def test_busy_runtime_does_not_launch_a_second_server(self) -> None:
        with (
            mock.patch.object(launcher, "load_active", return_value=self.current),
            mock.patch.object(
                launcher, "activate_artifact", side_effect=RuntimeBusyError("busy")
            ),
            mock.patch.object(launcher, "run_app") as run,
        ):
            self.assertEqual(
                self.invoke(
                    "--artifact", str(self.root / "candidate.zip"), "--sha256", "a" * 64
                ),
                1,
            )
        run.assert_not_called()

    def test_rollback_launches_selected_previous_code(self) -> None:
        previous = SimpleNamespace(
            path=self.root / "previous",
            manifest=SimpleNamespace(release_id="previous-1"),
        )
        with (
            mock.patch.object(launcher, "load_active", return_value=self.current),
            mock.patch.object(launcher, "rollback", return_value=previous) as rollback,
            mock.patch.object(launcher, "run_app", return_value=0) as run,
        ):
            self.assertEqual(self.invoke("--rollback", "--setup-only"), 0)
        rollback.assert_called_once_with(self.root, self.data)
        run.assert_called_once_with(previous.path, self.data, ["--setup-only"])

    def test_windows_script_path_and_options_are_separate_arguments(self) -> None:
        target = self.root / "Path with spaces"
        target.mkdir()
        (target / "run.ps1").touch()
        with mock.patch.object(launcher.platform, "system", return_value="Windows"):
            command = launcher._bootstrap_command(
                target, ["--setup-only", "--install-ai"]
            )
        self.assertEqual(
            command[-3:], [str(target / "run.ps1"), "--setup-only", "--install-ai"]
        )
        self.assertEqual(command[0], "powershell.exe")

    def test_missing_selection_or_conflicting_options_fail_before_mutation(
        self,
    ) -> None:
        for options in (
            ("--artifact", "candidate.zip"),
            ("--install-ai", "--skip-ai"),
            ("--rollback", "--artifact", "a.zip", "--sha256", "a" * 64),
        ):
            with self.subTest(options=options), self.assertRaises(SystemExit) as caught:
                self.invoke(*options)
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_legacy_database_location_is_preserved(self) -> None:
        database = self.root / "catlabel" / "data" / "catlabel.db"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"existing")
        self.assertEqual(launcher._data_directory(self.root, None), database.parent)
        self.assertEqual(database.read_bytes(), b"existing")

    def test_candidate_addon_selection_is_copied_without_changing_previous_slot(
        self,
    ) -> None:
        previous_state = self.current.path / ".bootstrap-state"
        previous_state.mkdir(parents=True)
        (previous_state / ".ai-enabled").write_text("1\n", encoding="ascii")
        candidate = self.root / "candidate"
        candidate.mkdir()
        (candidate / "run.sh").touch()
        (candidate / "release-manifest.json").touch()
        with mock.patch.object(launcher.subprocess, "run") as run:
            launcher.prepare_release(
                candidate, self.data, ["--skip-ai"], previous_state
            )
        self.assertEqual(
            run.call_args.kwargs["env"]["CATLABEL_BOOTSTRAP_STATE_DIR"],
            str(candidate / ".bootstrap-state"),
        )
        self.assertEqual(
            (candidate / ".bootstrap-state" / ".ai-enabled").read_text(), "1\n"
        )
        self.assertEqual((previous_state / ".ai-enabled").read_text(), "1\n")
        self.assertFalse(self.data.exists())

    def test_release_probe_uses_candidate_selection_and_removes_checkout_pythonpath(
        self,
    ) -> None:
        candidate = self.root / "candidate"
        state = candidate / ".bootstrap-state"
        state.mkdir(parents=True)
        (candidate / "release-manifest.json").touch()
        (state / ".headless-enabled").touch()
        manifest = ReleaseManifest(
            schema_version=1,
            release_id="candidate",
            source_commit="a" * 40,
            database_epoch=1,
            frontend_sha256="b" * 64,
            files={},
        )
        with (
            mock.patch.dict(os.environ, {"PYTHONPATH": "unrelated-checkout"}),
            mock.patch.object(launcher.platform, "system", return_value="Linux"),
            mock.patch.object(launcher.subprocess, "run") as run,
        ):
            launcher.probe_release(candidate, manifest, self.data)
        self.assertEqual(
            run.call_args.args[0][0],
            str(candidate / ".pixi" / "envs" / "headless" / "bin" / "python"),
        )
        self.assertNotIn("PYTHONPATH", run.call_args.kwargs["env"])

    def test_interrupt_terminates_and_waits_for_owned_child(self) -> None:
        (self.root / "run.sh").touch()
        process = mock.Mock()
        process.wait.side_effect = [KeyboardInterrupt, 0]
        with mock.patch.object(launcher.subprocess, "Popen", return_value=process):
            self.assertEqual(launcher.run_app(self.root, self.data), 130)
        process.terminate.assert_called_once()
        process.kill.assert_not_called()
        self.assertEqual(process.wait.call_args_list[-1], mock.call(timeout=5))


if __name__ == "__main__":
    unittest.main()
