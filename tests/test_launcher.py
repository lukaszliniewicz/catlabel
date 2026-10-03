from __future__ import annotations

import io
import os
import tempfile
import unittest
from collections.abc import Callable
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
        self.root = Path(temporary.name).resolve()
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

    def invoke_bundle_install(
        self,
        *options: str,
        current: SimpleNamespace | None = None,
        legacy_evidence: tuple[str, ...] = (),
    ) -> tuple[int, list[str], list[str]]:
        if legacy_evidence:
            self.data.mkdir()
            for name in legacy_evidence:
                (self.data / name).touch()

        prepared_options: list[str] = []
        installed = current or self.current

        def accept_bundle(
            _root: Path,
            _data_directory: Path,
            _archive: Path,
            _digest: str,
            prepare: Callable[..., None],
            _probe: Callable[..., None],
        ) -> SimpleNamespace:
            with mock.patch.object(launcher, "prepare_release") as prepare_release:
                prepare(self.root / "staged slot")
            prepared_options.extend(prepare_release.call_args.args[2])
            return installed

        bundle = self.root / "CatLabel-release.zip"
        with (
            mock.patch.object(launcher, "load_active", return_value=current),
            mock.patch.object(
                launcher, "_bundled_artifact", return_value=(bundle, "b" * 64)
            ),
            mock.patch.object(launcher, "activate_artifact", side_effect=accept_bundle),
            mock.patch.object(launcher, "run_app", return_value=0) as run,
            mock.patch.object(launcher.sys, "frozen", True, create=True),
        ):
            status = self.invoke(*options)
        return status, prepared_options, run.call_args.args[2]

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
        (candidate / "run.ps1").touch()
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

    def test_mcp_config_uses_selected_release_state_and_returns_child_status(
        self,
    ) -> None:
        target = self.root / "accepted release with spaces"
        state = target / ".bootstrap-state"
        runtime = target / ".pixi" / "envs" / "ai-mcp-headless" / "bin" / "python"
        state.mkdir(parents=True)
        runtime.parent.mkdir(parents=True)
        runtime.touch()
        (target / "release-manifest.json").touch()
        (state / ".ai-enabled").touch()
        (state / ".mcp-enabled").touch()
        # Conflicting data markers must not select the source checkout's environment.
        self.data.mkdir()
        (self.data / ".mcp-enabled").touch()
        output = self.root / "config output with spaces" / "opencode config.json"
        current = SimpleNamespace(path=target, manifest=self.current.manifest)
        with (
            mock.patch.object(launcher, "load_active", return_value=current),
            mock.patch.dict(os.environ, {"PYTHONPATH": "unrelated-checkout"}),
            mock.patch.object(
                launcher.subprocess, "run", return_value=SimpleNamespace(returncode=23)
            ) as run,
            mock.patch.object(launcher.subprocess, "Popen") as popen,
            mock.patch.object(launcher, "run_app") as run_app,
            mock.patch.object(launcher.platform, "system", return_value="Linux"),
        ):
            status = self.invoke("--mcp-config", "--mcp-output", str(output))

        self.assertEqual(status, 23)
        self.assertEqual(
            run.call_args.args[0],
            [
                str(runtime),
                "-m",
                "catlabel.mcp",
                "config",
                "--port",
                "8000",
                "--output",
                str(output.resolve()),
            ],
        )
        self.assertEqual(run.call_args.kwargs["cwd"], target)
        self.assertEqual(run.call_args.kwargs["timeout"], 60)
        self.assertFalse(run.call_args.kwargs["check"])
        child_environment = run.call_args.kwargs["env"]
        self.assertNotIn("PYTHONPATH", child_environment)
        self.assertEqual(child_environment["PLAYWRIGHT_BROWSERS_PATH"], "0")
        self.assertEqual(child_environment["CATLABEL_DATA_DIR"], str(self.data))
        self.assertEqual(child_environment["CATLABEL_BOOTSTRAP_STATE_DIR"], str(state))
        self.assertEqual(child_environment["CATLABEL_MCP_ENABLED"], "1")
        popen.assert_not_called()
        run_app.assert_not_called()

    def test_disabled_release_mcp_does_not_use_data_marker_or_fall_back(self) -> None:
        target = self.current.path
        state = target / ".bootstrap-state"
        state.mkdir(parents=True)
        (target / "release-manifest.json").touch()
        self.data.mkdir()
        (self.data / ".mcp-enabled").touch()
        with (
            mock.patch.object(launcher, "load_active", return_value=self.current),
            mock.patch.object(launcher, "_bundled_artifact") as bundled,
            mock.patch.object(launcher.subprocess, "run") as run,
            mock.patch.object(launcher, "run_app") as run_app,
        ):
            self.assertEqual(self.invoke("--mcp-doctor"), 1)
        bundled.assert_not_called()
        run.assert_not_called()
        run_app.assert_not_called()

    def test_mcp_without_selected_or_source_installation_does_not_bundle(self) -> None:
        with (
            mock.patch.object(launcher, "load_active", return_value=None),
            mock.patch.object(launcher, "_bundled_artifact") as bundled,
            mock.patch.object(launcher.subprocess, "run") as run,
            mock.patch.object(launcher, "run_app") as run_app,
        ):
            self.assertEqual(self.invoke("--mcp-config"), 1)
        bundled.assert_not_called()
        run.assert_not_called()
        run_app.assert_not_called()

    def test_mcp_source_installation_uses_data_marker_and_environment_port(
        self,
    ) -> None:
        (self.root / "run.sh").touch()
        self.data.mkdir()
        (self.data / ".mcp-enabled").touch()
        runtime = self.root / ".pixi" / "envs" / "mcp-headless" / "bin" / "python"
        runtime.parent.mkdir(parents=True)
        runtime.touch()
        with (
            mock.patch.object(launcher, "load_active", return_value=None),
            mock.patch.object(launcher, "_bundled_artifact") as bundled,
            mock.patch.dict(os.environ, {"CATLABEL_PORT": "4629"}),
            mock.patch.object(
                launcher.subprocess, "run", return_value=SimpleNamespace(returncode=0)
            ) as run,
            mock.patch.object(launcher.platform, "system", return_value="Linux"),
        ):
            self.assertEqual(self.invoke("--mcp-doctor"), 0)
        bundled.assert_not_called()
        self.assertEqual(
            run.call_args.args[0],
            [str(runtime), "-m", "catlabel.mcp", "doctor", "--port", "4629"],
        )
        self.assertEqual(run.call_args.kwargs["cwd"], self.root)

    def test_mcp_uses_windows_python_executable(self) -> None:
        target = self.current.path
        state = target / ".bootstrap-state"
        runtime = target / ".pixi" / "envs" / "mcp-headless" / "python.exe"
        state.mkdir(parents=True)
        runtime.parent.mkdir(parents=True)
        runtime.touch()
        (target / "release-manifest.json").touch()
        (state / ".mcp-enabled").touch()
        with (
            mock.patch.object(launcher, "load_active", return_value=self.current),
            mock.patch.object(
                launcher.subprocess, "run", return_value=SimpleNamespace(returncode=0)
            ) as run,
            mock.patch.object(launcher.platform, "system", return_value="Windows"),
        ):
            self.assertEqual(self.invoke("--mcp-doctor"), 0)
        self.assertEqual(run.call_args.args[0][0], str(runtime))
        self.assertEqual(
            run.call_args.kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"],
            str(self.data / "playwright-browsers"),
        )

    def test_windows_child_uses_data_directory_for_playwright_cache(self) -> None:
        data_directory = self.root / "Data directory with spaces"
        target = self.root / ".releases" / ("a" * 64) / ".pixi" / "deep"
        with mock.patch.object(launcher.platform, "system", return_value="Windows"):
            environment = launcher._child_environment(data_directory, target)
        self.assertEqual(
            environment["PLAYWRIGHT_BROWSERS_PATH"],
            str(data_directory / "playwright-browsers"),
        )

    def test_nonwindows_child_uses_hermetic_playwright_cache(self) -> None:
        with mock.patch.object(launcher.platform, "system", return_value="Linux"):
            environment = launcher._child_environment(self.data, self.root)
        self.assertEqual(environment["PLAYWRIGHT_BROWSERS_PATH"], "0")

    def test_mcp_missing_runtime_fails_without_launching_or_setup(self) -> None:
        target = self.current.path
        state = target / ".bootstrap-state"
        state.mkdir(parents=True)
        (target / "release-manifest.json").touch()
        (state / ".mcp-enabled").touch()
        with (
            mock.patch.object(launcher, "load_active", return_value=self.current),
            mock.patch.object(launcher.subprocess, "run") as run,
            mock.patch.object(launcher, "run_app") as run_app,
            mock.patch.object(launcher, "prepare_release") as prepare,
        ):
            self.assertEqual(self.invoke("--mcp-config"), 1)
        run.assert_not_called()
        run_app.assert_not_called()
        prepare.assert_not_called()

    def test_mcp_and_update_conflicts_fail_before_filesystem_mutation(self) -> None:
        conflicting_options = (
            ("--mcp-config", "--install-mcp"),
            ("--mcp-doctor", "--setup-only"),
            ("--mcp-config", "--update-bundled"),
            ("--update-bundled", "--artifact", "candidate.zip", "--sha256", "a" * 64),
            ("--update-bundled", "--rollback"),
            ("--update-bundled", "--diagnose"),
        )
        with (
            mock.patch.object(launcher, "load_active") as load_active,
            mock.patch.object(launcher, "activate_artifact") as activate,
            mock.patch.object(launcher, "run_app") as run_app,
        ):
            for options in conflicting_options:
                with (
                    self.subTest(options=options),
                    self.assertRaises(SystemExit) as caught,
                ):
                    self.invoke(*options)
                self.assertEqual(caught.exception.code, 2)
                self.assertEqual(list(self.root.iterdir()), [])
        load_active.assert_not_called()
        activate.assert_not_called()
        run_app.assert_not_called()

    def test_mcp_parameter_validation_and_environment_default(self) -> None:
        invalid_options = (
            ("--mcp-port", "4000"),
            ("--mcp-output", "config.json"),
            ("--mcp-config", "--mcp-port", "0"),
            ("--mcp-doctor", "--mcp-port", "65536"),
            ("--mcp-doctor", "--mcp-output", "config.json"),
        )
        for options in invalid_options:
            with self.subTest(options=options), self.assertRaises(SystemExit) as caught:
                self.invoke(*options)
            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_windows_bootstrap_reconstructs_powershell_module_path(self) -> None:
        (self.root / "run.ps1").touch()
        (self.root / "release-manifest.json").write_text("{}", encoding="utf-8")
        for key in ("PSModulePath", "PSMODULEPATH", "psmodulepath"):
            with (
                self.subTest(key=key),
                mock.patch.dict(
                    os.environ, {key: "PowerShell-7-only", "UNRELATED": "keep"}
                ),
                mock.patch.object(launcher.platform, "system", return_value="Windows"),
                mock.patch.object(launcher.subprocess, "run") as run,
            ):
                launcher.prepare_release(self.root, self.data, [])
                self.assertEqual(run.call_args.args[0][0], "powershell.exe")
                environment = run.call_args.kwargs["env"]
                self.assertFalse(
                    any(name.casefold() == "psmodulepath" for name in environment)
                )
                self.assertEqual(environment["UNRELATED"], "keep")
                self.assertEqual(environment["CATLABEL_DATA_DIR"], str(self.data))

    def test_nonwindows_child_preserves_powershell_module_path(self) -> None:
        module_key = "PSMODULEPATH" if os.name == "nt" else "PSModulePath"
        with (
            mock.patch.dict(os.environ, {module_key: "existing-path"}),
            mock.patch.object(launcher.platform, "system", return_value="Linux"),
        ):
            environment = launcher._child_environment(self.data, self.root)
        self.assertEqual(environment[module_key], "existing-path")

    def test_frozen_linux_child_restores_original_library_path(self) -> None:
        with (
            mock.patch.dict(
                os.environ,
                {
                    "LD_LIBRARY_PATH": "/appimage/private-libraries",
                    "LD_LIBRARY_PATH_ORIG": "/usr/lib:/lib",
                },
                clear=True,
            ),
            mock.patch.object(launcher.sys, "frozen", True, create=True),
            mock.patch.object(launcher.platform, "system", return_value="Linux"),
        ):
            environment = launcher._child_environment(self.data, self.root)
        self.assertEqual(environment["LD_LIBRARY_PATH"], "/usr/lib:/lib")

    def test_frozen_linux_child_drops_private_library_path_without_original(
        self,
    ) -> None:
        with (
            mock.patch.dict(
                os.environ,
                {"LD_LIBRARY_PATH": "/appimage/private-libraries"},
                clear=True,
            ),
            mock.patch.object(launcher.sys, "frozen", True, create=True),
            mock.patch.object(launcher.platform, "system", return_value="Linux"),
        ):
            environment = launcher._child_environment(self.data, self.root)
        self.assertNotIn("LD_LIBRARY_PATH", environment)

    def test_nonfrozen_linux_child_preserves_library_path(self) -> None:
        with (
            mock.patch.dict(
                os.environ,
                {"LD_LIBRARY_PATH": "/user/configured/libraries"},
                clear=True,
            ),
            mock.patch.object(launcher.sys, "frozen", False, create=True),
            mock.patch.object(launcher.platform, "system", return_value="Linux"),
        ):
            environment = launcher._child_environment(self.data, self.root)
        self.assertEqual(environment["LD_LIBRARY_PATH"], "/user/configured/libraries")

    def test_update_bundled_selects_bundle_even_with_current_release(self) -> None:
        bundle = self.root / "CatLabel-release.zip"
        replacement = SimpleNamespace(
            path=self.root / "replacement",
            manifest=SimpleNamespace(release_id="replacement-1"),
        )
        with (
            mock.patch.object(launcher, "load_active", return_value=self.current),
            mock.patch.object(
                launcher, "_bundled_artifact", return_value=(bundle, "b" * 64)
            ) as bundled,
            mock.patch.object(
                launcher, "activate_artifact", return_value=replacement
            ) as activate,
            mock.patch.object(launcher, "run_app", return_value=0) as run,
        ):
            self.assertEqual(self.invoke("--update-bundled"), 0)
        bundled.assert_called_once_with(self.root)
        self.assertEqual(activate.call_args.args[2:4], (bundle, "b" * 64))
        run.assert_called_once_with(replacement.path, self.data, [])

    def test_update_bundled_without_bundle_fails_without_normal_run(self) -> None:
        with (
            mock.patch.object(launcher, "load_active", return_value=self.current),
            mock.patch.object(launcher, "_bundled_artifact", return_value=None),
            mock.patch.object(launcher, "activate_artifact") as activate,
            mock.patch.object(launcher, "run_app") as run,
        ):
            self.assertEqual(self.invoke("--update-bundled"), 1)
        activate.assert_not_called()
        run.assert_not_called()

    def test_first_frozen_bundle_install_enables_mcp_only_during_preparation(
        self,
    ) -> None:
        status, prepared_options, run_options = self.invoke_bundle_install()
        self.assertEqual(status, 0)
        self.assertEqual(prepared_options, ["--install-mcp"])
        self.assertEqual(run_options, [])

        status, prepared_options, _ = self.invoke_bundle_install("--install-mcp")
        self.assertEqual(status, 0)
        self.assertEqual(prepared_options.count("--install-mcp"), 1)

    def test_explicit_skip_options_suppress_frozen_mcp_default(self) -> None:
        for option in ("--skip-mcp", "--skip-headless"):
            with self.subTest(option=option):
                status, prepared_options, run_options = self.invoke_bundle_install(
                    option
                )
                self.assertEqual(status, 0)
                self.assertNotIn("--install-mcp", prepared_options)
                self.assertEqual(prepared_options, [option])
                self.assertEqual(run_options, [option])

    def test_existing_selected_release_update_does_not_add_mcp_default(self) -> None:
        status, prepared_options, _ = self.invoke_bundle_install(
            "--update-bundled", current=self.current
        )
        self.assertEqual(status, 0)
        self.assertEqual(prepared_options, [])

    def test_legacy_data_selection_prevents_frozen_mcp_default(self) -> None:
        status, prepared_options, _ = self.invoke_bundle_install(
            legacy_evidence=(
                ".ai-enabled",
                ".headless-enabled",
                ".mcp-enabled",
                "bootstrap-last-run.sha256",
            )
        )
        self.assertEqual(status, 0)
        self.assertEqual(prepared_options, [])

    def test_unfrozen_source_install_does_not_add_mcp_default(self) -> None:
        (self.root / "run.sh").touch()
        with (
            mock.patch.object(launcher, "load_active", return_value=None),
            mock.patch.object(launcher, "_bundled_artifact", return_value=None),
            mock.patch.object(launcher, "activate_artifact") as activate,
            mock.patch.object(launcher, "run_app", return_value=0) as run,
            mock.patch.object(launcher.sys, "frozen", False, create=True),
        ):
            self.assertEqual(self.invoke(), 0)
        activate.assert_not_called()
        run.assert_called_once_with(self.root, self.data, [])

    def test_invalid_environment_port_fails_mcp_command_but_not_normal_launch(
        self,
    ) -> None:
        with mock.patch.dict(os.environ, {"CATLABEL_PORT": "not-a-port"}):
            with self.assertRaises(SystemExit) as caught:
                self.invoke("--mcp-doctor")
            self.assertEqual(caught.exception.code, 2)

        with (
            mock.patch.dict(os.environ, {"CATLABEL_PORT": "not-a-port"}),
            mock.patch.object(launcher, "load_active", return_value=self.current),
            mock.patch.object(launcher, "run_app", return_value=0) as run,
        ):
            self.assertEqual(self.invoke(), 0)
        run.assert_called_once_with(self.current.path, self.data, [])

    def test_interrupt_terminates_and_waits_for_owned_child(self) -> None:
        (self.root / "run.sh").touch()
        (self.root / "run.ps1").touch()
        process = mock.Mock()
        process.wait.side_effect = [KeyboardInterrupt, 0]
        with mock.patch.object(launcher.subprocess, "Popen", return_value=process):
            self.assertEqual(launcher.run_app(self.root, self.data), 130)
        process.terminate.assert_called_once()
        process.kill.assert_not_called()
        self.assertEqual(process.wait.call_args_list[-1], mock.call(timeout=5))


if __name__ == "__main__":
    unittest.main()
