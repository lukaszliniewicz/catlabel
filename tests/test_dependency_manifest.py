from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from tools.sync_dependencies import (
    GENERATED_HEADER,
    DependencyManifestError,
    expected_outputs,
    main,
)

BASE_REQUIREMENTS = [
    "fastapi>=0.115.6",
    "Pillow>=11.1.0",
    "winpkg>=1.2; sys_platform == 'win32'",
    "darwinpkg>=1.0; sys_platform == 'darwin'",
    "google-cloud-aiplatform",
]
LAUNCHER_REQUIREMENTS = [
    "dulwich==1.2.10",
    "pyinstaller==6.21.0",
    "urllib3==2.7.0",
]


def _write_pyproject(root: Path, dependencies: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    quoted_dependencies = ",\n  ".join(
        json.dumps(requirement) for requirement in dependencies
    )
    root.joinpath("pyproject.toml").write_text(
        "[project]\n"
        'name = "fixture-catlabel"\n'
        "dependencies = [\n  "
        f"{quoted_dependencies}\n"
        "]\n\n"
        "[project.optional-dependencies]\n"
        'headless = ["playwright>=1.40.0"]\n'
        'launcher = ["dulwich==1.2.10", "pyinstaller==6.21.0", "urllib3==2.7.0"]\n',
        encoding="utf-8",
    )


class DependencyManifestTests(unittest.TestCase):
    def test_fixture_outputs_match_canonical_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_pyproject(root, BASE_REQUIREMENTS)

            outputs = expected_outputs(root)
            requirements_text = outputs[root / "requirements.txt"].decode("utf-8")
            launcher_text = outputs[root / "launcher-requirements.txt"].decode("utf-8")
            self.assertEqual(
                requirements_text.splitlines(), [GENERATED_HEADER, *BASE_REQUIREMENTS]
            )
            self.assertEqual(
                launcher_text.splitlines(), [GENERATED_HEADER, *LAUNCHER_REQUIREMENTS]
            )

            pixi = tomllib.loads(outputs[root / "pixi.toml"].decode("utf-8"))
            self.assertEqual(pixi["workspace"]["name"], "fixture-catlabel")
            self.assertEqual(pixi["workspace"]["channels"], ["conda-forge"])
            self.assertEqual(pixi["workspace"]["platforms"], ["win-64"])
            self.assertEqual(pixi["dependencies"]["python"], "3.11.*")
            self.assertEqual(
                pixi["pypi-dependencies"],
                {
                    "fastapi": ">=0.115.6",
                    "pillow": ">=11.1.0",
                    "winpkg": ">=1.2",
                    "google-cloud-aiplatform": "*",
                },
            )
            self.assertEqual(
                pixi["feature"]["headless"]["pypi-dependencies"],
                {"playwright": ">=1.40.0"},
            )
            self.assertEqual(pixi["environments"], {"headless": ["headless"]})
            self.assertEqual(
                pixi["tasks"],
                {
                    "start": "python -m catlabel",
                    "test": "python -m unittest discover -s tests -v",
                },
            )
            self.assertNotIn("darwinpkg", pixi["pypi-dependencies"])

    def test_missing_or_unsupported_marker_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for requirement in ("badpkg>=1;", "badpkg>=1; sys_platform == 'linux'"):
                with self.subTest(requirement=requirement):
                    _write_pyproject(root, [requirement])
                    with self.assertRaises(DependencyManifestError):
                        expected_outputs(root)

    def test_unsupported_extras_and_direct_references_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for requirement in (
                "badpkg[extra]>=1",
                "badpkg @ https://example.invalid/pkg.whl",
            ):
                with self.subTest(requirement=requirement):
                    _write_pyproject(root, [requirement])
                    with self.assertRaises(DependencyManifestError):
                        expected_outputs(root)

    def test_check_mode_reports_drift_without_mutating_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_pyproject(root, BASE_REQUIREMENTS)
            paths = [
                root / "requirements.txt",
                root / "launcher-requirements.txt",
                root / "pixi.toml",
            ]
            for path in paths:
                path.write_bytes(b"divergent\n")
            before = {path: path.read_bytes() for path in paths}

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = main(["--check", "--root", str(root)])

            self.assertEqual(result, 1)
            self.assertIn("requirements.txt", stderr.getvalue())
            self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_write_then_default_check_succeeds_and_preserves_pip_semantics(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_pyproject(root, BASE_REQUIREMENTS)

            self.assertEqual(main(["--write", "--root", str(root)]), 0)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["--root", str(root)]), 0)
            self.assertIn("match pyproject.toml", stdout.getvalue())

            requirements = (
                (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
            )
            launcher = (
                (root / "launcher-requirements.txt")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            self.assertEqual(requirements, [GENERATED_HEADER, *BASE_REQUIREMENTS])
            self.assertEqual(launcher, [GENERATED_HEADER, *LAUNCHER_REQUIREMENTS])

    def test_cli_defaults_to_its_project_root_from_another_working_directory(
        self,
    ) -> None:
        source_script = (
            Path(__file__).resolve().parents[1] / "tools" / "sync_dependencies.py"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            working_directory = Path(temporary_directory)
            root = working_directory / "project"
            script = root / "tools" / "sync_dependencies.py"
            script.parent.mkdir(parents=True)
            shutil.copyfile(source_script, script)
            _write_pyproject(root, BASE_REQUIREMENTS)

            written = subprocess.run(
                [sys.executable, str(script), "--write"],
                cwd=working_directory,
                check=False,
                capture_output=True,
                text=True,
            )
            checked = subprocess.run(
                [sys.executable, str(script)],
                cwd=working_directory,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(written.returncode, 0, written.stderr)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn("match pyproject.toml", checked.stdout)


if __name__ == "__main__":
    unittest.main()
