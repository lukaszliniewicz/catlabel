from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import bootstrap_runtime


class BootstrapRuntimeTests(unittest.TestCase):
    def _write_manifests(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "pixi.toml").write_bytes(b"pixi manifest\n")
        (root / "pixi.lock").write_bytes(b"pixi lock\n")

    def test_identity_changes_when_lock_or_environment_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_manifests(root)

            with mock.patch.object(bootstrap_runtime.sys, "platform", "linux"):
                default_identity = bootstrap_runtime.environment_identity(
                    root, "default"
                )
            pixi_hash = hashlib.sha256((root / "pixi.toml").read_bytes()).hexdigest()
            lock_hash = hashlib.sha256((root / "pixi.lock").read_bytes()).hexdigest()
            canonical = (
                f"catlabel-bootstrap-v1\n0.72.2\ndefault\n{pixi_hash}\n{lock_hash}\n"
            )
            self.assertEqual(
                default_identity,
                hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            )

            (root / "pixi.lock").write_bytes(b"changed lock\n")
            with mock.patch.object(bootstrap_runtime.sys, "platform", "linux"):
                self.assertNotEqual(
                    bootstrap_runtime.environment_identity(root, "default"),
                    default_identity,
                )
                self.assertNotEqual(
                    bootstrap_runtime.environment_identity(root, "headless"),
                    default_identity,
                )

    def test_windows_identity_invalidates_v1_bootstrap_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_manifests(root)
            pixi_hash = hashlib.sha256((root / "pixi.toml").read_bytes()).hexdigest()
            lock_hash = hashlib.sha256((root / "pixi.lock").read_bytes()).hexdigest()
            old_canonical = (
                f"catlabel-bootstrap-v1\n0.72.2\ndefault\n{pixi_hash}\n{lock_hash}\n"
            )
            old_identity = hashlib.sha256(old_canonical.encode("utf-8")).hexdigest()

            with mock.patch.object(bootstrap_runtime.sys, "platform", "win32"):
                windows_identity = bootstrap_runtime.environment_identity(
                    root, "default"
                )
            windows_canonical = (
                f"catlabel-bootstrap-v2\n0.72.2\ndefault\n{pixi_hash}\n{lock_hash}\n"
            )
            self.assertEqual(
                windows_identity,
                hashlib.sha256(windows_canonical.encode("utf-8")).hexdigest(),
            )
            self.assertNotEqual(windows_identity, old_identity)

    def test_identity_rejects_unknown_environment(self) -> None:
        with self.assertRaises(ValueError):
            bootstrap_runtime.environment_identity(Path("missing"), "other")

    def test_successful_stamp_publication_is_atomic_and_verifies_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            self._write_manifests(root)
            stamp = Path(temporary_directory) / "new" / "nested" / "identity.txt"
            expected_identity = bootstrap_runtime.environment_identity(root, "headless")

            def verify(environment: str) -> None:
                self.assertEqual(environment, "headless")
                self.assertFalse(stamp.parent.exists())

            with (
                mock.patch.object(
                    bootstrap_runtime, "verify_runtime", side_effect=verify
                ),
                mock.patch.object(
                    bootstrap_runtime.os, "replace", wraps=bootstrap_runtime.os.replace
                ) as replace,
            ):
                bootstrap_runtime.main(
                    [
                        "--root",
                        str(root),
                        "--environment",
                        "headless",
                        "--stamp",
                        str(stamp),
                    ]
                )

            self.assertEqual(
                stamp.read_text(encoding="ascii"), expected_identity + "\n"
            )
            replace.assert_called_once()
            temporary_path, replaced_stamp = replace.call_args.args
            self.assertEqual(Path(temporary_path).parent, stamp.parent)
            self.assertEqual(replaced_stamp, stamp)
            self.assertEqual(list(stamp.parent.iterdir()), [stamp])

    def test_verification_failure_preserves_stamp_and_does_not_create_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            self._write_manifests(root)
            existing_stamp = Path(temporary_directory) / "existing" / "identity.txt"
            existing_stamp.parent.mkdir()
            existing_stamp.write_text("old identity\n", encoding="ascii")
            missing_stamp = (
                Path(temporary_directory) / "missing" / "nested" / "stamp.txt"
            )

            with mock.patch.object(
                bootstrap_runtime,
                "verify_runtime",
                side_effect=RuntimeError("runtime check failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "runtime check failed"):
                    bootstrap_runtime.main(
                        [
                            "--root",
                            str(root),
                            "--environment",
                            "default",
                            "--stamp",
                            str(existing_stamp),
                        ]
                    )
                self.assertEqual(
                    existing_stamp.read_text(encoding="ascii"), "old identity\n"
                )

                with self.assertRaisesRegex(RuntimeError, "runtime check failed"):
                    bootstrap_runtime.main(
                        [
                            "--root",
                            str(root),
                            "--environment",
                            "default",
                            "--stamp",
                            str(missing_stamp),
                        ]
                    )

            self.assertFalse(missing_stamp.parent.exists())

    def test_platform_specific_imports_follow_runtime_platform(self) -> None:
        platform_modules = {
            "win32": (
                "winsdk.windows.devices.bluetooth",
                "winsdk.windows.devices.enumeration",
            ),
            "darwin": ("IOBluetooth",),
        }
        for platform, required_modules in platform_modules.items():
            with self.subTest(platform=platform):
                with (
                    mock.patch.object(bootstrap_runtime.sys, "version_info", (3, 11)),
                    mock.patch.object(bootstrap_runtime.sys, "platform", platform),
                    mock.patch.object(
                        bootstrap_runtime.importlib, "import_module"
                    ) as importer,
                ):
                    bootstrap_runtime.verify_runtime("default")

                imported_modules = [call.args[0] for call in importer.call_args_list]
                for module_name in (
                    *bootstrap_runtime.RUNTIME_MODULES,
                    *required_modules,
                ):
                    self.assertIn(module_name, imported_modules)

    def test_optional_ai_imports_only_for_ai_environments(self) -> None:
        for environment in ("default", "headless", "ai", "ai-headless"):
            with self.subTest(environment=environment):
                with (
                    mock.patch.object(bootstrap_runtime.sys, "version_info", (3, 11)),
                    mock.patch.object(bootstrap_runtime.sys, "platform", "linux"),
                    mock.patch.object(
                        bootstrap_runtime.importlib, "import_module"
                    ) as importer,
                    mock.patch.object(
                        bootstrap_runtime.Path, "is_file", return_value=True
                    ),
                ):
                    importer.return_value.sync_playwright.return_value.__enter__.return_value.chromium.executable_path = "/fixture/chromium"
                    bootstrap_runtime.verify_runtime(environment)
                modules = [call.args[0] for call in importer.call_args_list]
                for module in bootstrap_runtime.AI_MODULES:
                    self.assertEqual(
                        module in modules, environment in ("ai", "ai-headless")
                    )
                self.assertEqual(
                    "playwright.sync_api" in modules,
                    environment in ("headless", "ai-headless"),
                )

    def test_headless_verification_rejects_missing_chromium_executable(self) -> None:
        playwright = mock.Mock()
        runtime = mock.MagicMock()
        context = mock.MagicMock()
        context.__enter__.return_value = runtime
        runtime.chromium.executable_path = "/missing/chromium"
        playwright.sync_playwright.return_value = context

        with (
            mock.patch.object(bootstrap_runtime.sys, "version_info", (3, 11)),
            mock.patch.object(bootstrap_runtime.sys, "platform", "linux"),
            mock.patch.object(
                bootstrap_runtime.importlib,
                "import_module",
                side_effect=lambda name: (
                    playwright if name == "playwright.sync_api" else mock.Mock()
                ),
            ),
            self.assertRaisesRegex(RuntimeError, "Chromium executable is missing"),
        ):
            bootstrap_runtime.verify_runtime("headless")

        playwright.sync_playwright.assert_called_once_with()
        runtime.chromium.launch.assert_not_called()

    def test_headless_verification_launches_and_closes_chromium(self) -> None:
        playwright = mock.Mock()
        runtime = mock.MagicMock()
        context = mock.MagicMock()
        context.__enter__.return_value = runtime
        runtime.chromium.executable_path = "/fixture/chromium"
        playwright.sync_playwright.return_value = context

        with (
            mock.patch.object(bootstrap_runtime.sys, "version_info", (3, 11)),
            mock.patch.object(bootstrap_runtime.sys, "platform", "linux"),
            mock.patch.object(
                bootstrap_runtime.importlib,
                "import_module",
                side_effect=lambda name: (
                    playwright if name == "playwright.sync_api" else mock.Mock()
                ),
            ),
            mock.patch.object(bootstrap_runtime.Path, "is_file", return_value=True),
        ):
            bootstrap_runtime.verify_runtime("headless")

        runtime.chromium.launch.assert_called_once_with(headless=True)
        runtime.chromium.launch.return_value.close.assert_called_once_with()

    def test_chromium_startup_failure_does_not_publish_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_manifests(root)
            executable = root / "chromium"
            executable.touch()
            stamp = root / "bootstrap.sha256"
            playwright = mock.Mock()
            runtime = mock.MagicMock()
            context = mock.MagicMock()
            context.__enter__.return_value = runtime
            runtime.chromium.executable_path = str(executable)
            runtime.chromium.launch.side_effect = RuntimeError("browser startup failed")
            playwright.sync_playwright.return_value = context

            with (
                mock.patch.object(bootstrap_runtime.sys, "version_info", (3, 11)),
                mock.patch.object(bootstrap_runtime.sys, "platform", "linux"),
                mock.patch.object(
                    bootstrap_runtime.importlib,
                    "import_module",
                    side_effect=lambda name: (
                        playwright if name == "playwright.sync_api" else mock.Mock()
                    ),
                ),
                self.assertRaisesRegex(RuntimeError, "browser startup failed"),
            ):
                bootstrap_runtime.main(
                    [
                        "--root",
                        str(root),
                        "--environment",
                        "headless",
                        "--stamp",
                        str(stamp),
                    ]
                )

            runtime.chromium.launch.assert_called_once_with(headless=True)
            runtime.chromium.launch.return_value.close.assert_not_called()
            self.assertFalse(stamp.exists())


if __name__ == "__main__":
    unittest.main()
