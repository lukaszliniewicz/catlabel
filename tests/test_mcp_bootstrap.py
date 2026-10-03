from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import launcher
from tools import bootstrap_runtime
from tools.sync_dependencies import expected_outputs

ROOT = Path(__file__).resolve().parents[1]


class MCPDependencyTests(unittest.TestCase):
    def test_mcp_feature_generates_only_headless_runtime_environments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "fixture-catlabel"\ndependencies = []\n\n'
                "[project.optional-dependencies]\n"
                'headless = ["playwright>=1.40.0"]\n'
                'ai = ["litellm==1.103.2"]\n'
                'mcp = ["mcp==2.3.0", "jsonschema==4.25.1"]\n',
                encoding="utf-8",
            )

            outputs = expected_outputs(root)
            pixi = tomllib.loads(outputs[root / "pixi.toml"].decode("utf-8"))

        self.assertEqual(
            pixi["feature"]["mcp"]["pypi-dependencies"],
            {"mcp": "==2.3.0", "jsonschema": "==4.25.1"},
        )
        self.assertEqual(pixi["environments"]["mcp-headless"], ["mcp", "headless"])
        self.assertEqual(
            pixi["environments"]["ai-mcp-headless"], ["ai", "mcp", "headless"]
        )
        self.assertNotIn("mcp", pixi["environments"])


class MCPBootstrapRuntimeTests(unittest.TestCase):
    def test_mcp_environments_verify_mcp_modules_and_chromium(self) -> None:
        for environment in ("mcp-headless", "ai-mcp-headless"):
            with self.subTest(environment=environment):
                playwright = mock.MagicMock()
                playwright.sync_playwright.return_value.__enter__.return_value.chromium.executable_path = "/fixture/chromium"
                with (
                    mock.patch.object(bootstrap_runtime.sys, "version_info", (3, 11)),
                    mock.patch.object(bootstrap_runtime.sys, "platform", "linux"),
                    mock.patch.object(
                        bootstrap_runtime.importlib,
                        "import_module",
                        side_effect=lambda name, runtime=playwright: (
                            runtime if name == "playwright.sync_api" else mock.Mock()
                        ),
                    ) as importer,
                    mock.patch.object(
                        bootstrap_runtime.Path, "is_file", return_value=True
                    ),
                ):
                    bootstrap_runtime.verify_runtime(environment)

                imported = [call.args[0] for call in importer.call_args_list]
                for module_name in (
                    *bootstrap_runtime.MCP_MODULES,
                    "playwright.sync_api",
                ):
                    self.assertIn(module_name, imported)
                for module_name in bootstrap_runtime.AI_MODULES:
                    self.assertEqual(
                        module_name in imported, environment == "ai-mcp-headless"
                    )


class MCPLauncherTests(unittest.TestCase):
    def _fake_pixi_checkout(self, root: Path) -> tuple[Path, Path]:
        root.mkdir(parents=True)
        (root / "pixi.toml").write_text("[workspace]\nname = 'fixture'\n")
        (root / "pixi.lock").write_text("fixture lock\n")
        (root / "bin").mkdir()
        binary = root / "bin" / "pixi"
        binary.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s\\t%s\\n" "$*" "${CATLABEL_MCP_ENABLED-<unset>}" >> "$PIXILOG"\n',
            encoding="utf-8",
        )
        binary.chmod(0o755)
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        size = binary.stat().st_size
        script = (ROOT / "run.sh").read_text(encoding="utf-8")
        script = re.sub(
            r"(?m)^([ \t]*)digest=[0-9a-f]{64}\n([ \t]*)size=\d+(?= ;;)",
            f"\\g<1>digest={digest}\n\\g<2>size={size}",
            script,
        )
        run_script = root / "run.sh"
        run_script.write_text(script, encoding="utf-8")
        run_script.chmod(0o755)
        return run_script, binary

    @unittest.skipUnless(os.name == "posix", "run.sh requires a POSIX shell")
    def test_setup_only_selects_mcp_environment_without_starting_server(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            run_script, _binary = self._fake_pixi_checkout(root)
            state = Path(temporary_directory) / "state"
            data = Path(temporary_directory) / "data"
            log = Path(temporary_directory) / "pixi.log"
            environment = {
                **os.environ,
                "CATLABEL_BOOTSTRAP_STATE_DIR": str(state),
                "CATLABEL_DATA_DIR": str(data),
                "PIXILOG": str(log),
            }

            result = subprocess.run(
                [
                    "bash",
                    str(run_script),
                    "--install-mcp",
                    "--install-ai",
                    "--setup-only",
                ],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CatLabel is ready (ai-mcp-headless).", result.stdout)
            commands = log.read_text(encoding="utf-8").splitlines()
            self.assertTrue(
                any(
                    "install --environment ai-mcp-headless" in item for item in commands
                )
            )
            self.assertTrue(
                any("playwright install chromium" in item for item in commands)
            )
            self.assertTrue(all(item.endswith("\t<unset>") for item in commands))
            self.assertFalse(any("python -m catlabel" in item for item in commands))
            for marker in (".mcp-enabled", ".headless-enabled", ".ai-enabled"):
                self.assertTrue((state / marker).is_file())

            log.write_text("", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(run_script)],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = log.read_text(encoding="utf-8").splitlines()
            self.assertIn("python -m catlabel\t1", commands[-1])

    @unittest.skipUnless(os.name == "posix", "run.sh requires a POSIX shell")
    def test_skip_headless_rejects_active_mcp_before_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            run_script, _binary = self._fake_pixi_checkout(root)
            state = Path(temporary_directory) / "state"
            state.mkdir()
            (state / ".mcp-enabled").write_text("1\n", encoding="ascii")
            log = Path(temporary_directory) / "pixi.log"
            result = subprocess.run(
                ["bash", str(run_script), "--skip-headless", "--setup-only"],
                capture_output=True,
                check=False,
                env={
                    **os.environ,
                    "CATLABEL_BOOTSTRAP_STATE_DIR": str(state),
                    "CATLABEL_DATA_DIR": str(Path(temporary_directory) / "data"),
                    "PIXILOG": str(log),
                },
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("Disable MCP with --skip-mcp", result.stderr)
            self.assertFalse(log.exists())

    @unittest.skipUnless(os.name == "posix", "run.sh requires a POSIX shell")
    def test_skip_mcp_removes_only_the_mcp_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            run_script, _binary = self._fake_pixi_checkout(root)
            state = Path(temporary_directory) / "state"
            state.mkdir()
            (state / ".mcp-enabled").write_text("1\n", encoding="ascii")
            (state / ".headless-enabled").write_text("1\n", encoding="ascii")
            log = Path(temporary_directory) / "pixi.log"
            result = subprocess.run(
                ["bash", str(run_script), "--skip-mcp", "--setup-only"],
                capture_output=True,
                check=False,
                env={
                    **os.environ,
                    "CATLABEL_BOOTSTRAP_STATE_DIR": str(state),
                    "CATLABEL_DATA_DIR": str(Path(temporary_directory) / "data"),
                    "PIXILOG": str(log),
                },
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CatLabel is ready (headless).", result.stdout)
            self.assertFalse((state / ".mcp-enabled").exists())
            self.assertTrue((state / ".headless-enabled").is_file())
            commands = log.read_text(encoding="utf-8").splitlines()
            self.assertTrue(
                any("install --environment headless" in item for item in commands)
            )

    def test_power_shell_help_and_conflicting_mcp_options_are_parsed(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")

        help_result = subprocess.run(
            [powershell, "-NoProfile", "-File", str(ROOT / "run.ps1"), "--help"],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--install-mcp | --skip-mcp", help_result.stdout)

        conflict = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-File",
                str(ROOT / "run.ps1"),
                "--install-mcp",
                "--skip-mcp",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn("Choose either --install-mcp or --skip-mcp", conflict.stderr)


class MCPReleaseLauncherTests(unittest.TestCase):
    def test_runtime_environment_preserves_existing_choices_and_adds_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cases = (
                ((), "default"),
                ((".headless-enabled",), "headless"),
                ((".ai-enabled",), "ai"),
                ((".ai-enabled", ".headless-enabled"), "ai-headless"),
                ((".mcp-enabled",), "mcp-headless"),
                ((".ai-enabled", ".mcp-enabled"), "ai-mcp-headless"),
            )
            for index, (markers, expected_environment) in enumerate(cases):
                with self.subTest(markers=markers):
                    data = root / f"case-{index}"
                    data.mkdir()
                    for marker in markers:
                        (data / marker).touch()
                    self.assertEqual(
                        launcher._runtime_environment(data), expected_environment
                    )

    def test_child_environment_uses_selected_mcp_marker_and_clears_inherited_value(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data = root / "data"
            data.mkdir()
            ordinary_target = root / "ordinary-target"
            ordinary_target.mkdir()
            release_target = root / "release-target"
            release_target.mkdir()
            (release_target / "release-manifest.json").touch()
            release_state = release_target / ".bootstrap-state"
            release_state.mkdir()

            with mock.patch.dict(
                "os.environ", {"CATLABEL_MCP_ENABLED": "inherited"}, clear=True
            ):
                environment = launcher._child_environment(data, ordinary_target)
                self.assertNotIn("CATLABEL_MCP_ENABLED", environment)

                (data / ".mcp-enabled").touch()
                environment = launcher._child_environment(data, ordinary_target)
                self.assertEqual(environment["CATLABEL_MCP_ENABLED"], "1")

                # A selected release's state takes precedence over the shared data marker.
                environment = launcher._child_environment(data, release_target)
                self.assertNotIn("CATLABEL_MCP_ENABLED", environment)
                (release_state / ".mcp-enabled").touch()
                environment = launcher._child_environment(data, release_target)
                self.assertEqual(environment["CATLABEL_MCP_ENABLED"], "1")
                self.assertEqual(
                    environment["CATLABEL_BOOTSTRAP_STATE_DIR"], str(release_state)
                )

    def test_prepare_release_copies_mcp_selection_and_enables_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data = root / "data"
            data.mkdir()
            source_state = root / "source-state"
            source_state.mkdir()
            (source_state / ".mcp-enabled").write_text("1\n", encoding="ascii")
            target = root / "candidate"
            target.mkdir()
            (target / "run.sh").touch()
            (target / "release-manifest.json").touch()

            with (
                mock.patch.dict("os.environ", {}, clear=True),
                mock.patch.object(launcher.subprocess, "run") as run,
            ):
                launcher.prepare_release(target, data, [], source_state)

            selected_marker = target / ".bootstrap-state" / ".mcp-enabled"
            self.assertEqual(selected_marker.read_text(encoding="ascii"), "1\n")
            self.assertEqual(run.call_args.kwargs["env"]["CATLABEL_MCP_ENABLED"], "1")
            self.assertEqual(
                (source_state / ".mcp-enabled").read_text(encoding="ascii"), "1\n"
            )

    def test_mcp_flags_are_forwarded_and_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "accepted"
            current = SimpleNamespace(
                path=target,
                manifest=SimpleNamespace(release_id="accepted-1"),
            )
            for option in ("--install-mcp", "--skip-mcp"):
                with self.subTest(option=option):
                    with (
                        mock.patch.object(
                            launcher, "load_active", return_value=current
                        ),
                        mock.patch.object(launcher, "run_app", return_value=0) as run,
                    ):
                        self.assertEqual(
                            launcher.main(["--installation-root", str(root), option]),
                            0,
                        )
                    run.assert_called_once_with(target, root / "data", [option])

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            launcher.main(["--install-mcp", "--skip-mcp"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
