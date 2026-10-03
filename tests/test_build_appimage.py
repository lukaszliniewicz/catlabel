from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from tools import build_appimage


class _Response:
    def __init__(self, contents: bytes) -> None:
        self.contents = contents
        self.offset = 0
        self.headers = {"Content-Length": str(len(contents))}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_arguments: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        chunk = self.contents[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class AppImagePinTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="catlabel-appimage-pins-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_manifest_matches_the_reviewed_x86_64_pins(self) -> None:
        pins = build_appimage.load_tool_pins()
        self.assertEqual(pins["appimagetool"].version, "1.9.1")
        self.assertEqual(
            pins["appimagetool"].size_bytes,
            15092216,
        )
        self.assertEqual(
            pins["appimagetool"].sha256,
            "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0",
        )
        self.assertEqual(pins["runtime"].version, "20251108")
        self.assertEqual(pins["runtime"].size_bytes, 944632)
        self.assertEqual(
            pins["runtime"].sha256,
            "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d",
        )

    def test_changed_pin_metadata_is_not_an_override(self) -> None:
        payload = json.loads(build_appimage.TOOL_MANIFEST.read_text(encoding="utf-8"))
        payload["runtime"]["sha256"] = "0" * 64
        manifest = self.root / "pins.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs from trusted pins"):
            build_appimage.load_tool_pins(manifest)

    def test_pinned_file_rejects_wrong_size_hash_and_symlink(self) -> None:
        contents = b"pinned bytes"
        pin = build_appimage.PinnedTool(
            name="runtime",
            filename="runtime-test",
            version="fixture",
            source_url="https://example.invalid/runtime",
            size_bytes=len(contents),
            sha256=hashlib.sha256(contents).hexdigest(),
        )
        valid = self.root / "valid-runtime"
        valid.write_bytes(contents)
        self.assertEqual(build_appimage.verify_pinned_file(valid, pin), pin.sha256)

        wrong_size = self.root / "wrong-size"
        wrong_size.write_bytes(contents[:-1])
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            build_appimage.verify_pinned_file(wrong_size, pin)

        wrong_hash = self.root / "wrong-hash"
        wrong_hash.write_bytes(b"x" * len(contents))
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            build_appimage.verify_pinned_file(wrong_hash, pin)

        link = self.root / "runtime-link"
        link.symlink_to(valid)
        with self.assertRaisesRegex(ValueError, "not a regular file"):
            build_appimage.verify_pinned_file(link, pin)

    def test_explicit_runtime_path_is_verified_without_cache_fallback(self) -> None:
        contents = b"runtime fixture"
        pin = build_appimage.PinnedTool(
            name="runtime",
            filename="runtime-test",
            version="fixture",
            source_url="https://example.invalid/runtime",
            size_bytes=len(contents),
            sha256=hashlib.sha256(contents).hexdigest(),
        )
        explicit = self.root / "provided-runtime"
        explicit.write_bytes(contents)
        with mock.patch.object(
            build_appimage,
            "_download_pinned_file",
            side_effect=AssertionError("explicit paths must not download"),
        ):
            resolved = build_appimage.resolve_pinned_tool(
                "runtime", self.root / "cache", explicit, pins={"runtime": pin}
            )
        self.assertEqual(resolved, explicit.absolute())

        explicit.write_bytes(b"x" * len(contents))
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            build_appimage.resolve_pinned_tool(
                "runtime", self.root / "cache", explicit, pins={"runtime": pin}
            )

    def test_missing_pinned_file_download_is_bounded_and_atomic(self) -> None:
        contents = b"verified downloaded runtime"
        pin = build_appimage.PinnedTool(
            name="runtime",
            filename="runtime-test",
            version="fixture",
            source_url="https://example.invalid/runtime",
            size_bytes=len(contents),
            sha256=hashlib.sha256(contents).hexdigest(),
        )
        cache = self.root / "cache"
        with mock.patch.object(
            build_appimage.urllib.request,
            "urlopen",
            return_value=_Response(contents),
        ) as urlopen:
            downloaded = build_appimage.resolve_pinned_tool(
                "runtime", cache, pins={"runtime": pin}
            )
        self.assertEqual(downloaded.read_bytes(), contents)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)
        self.assertEqual(list(cache.iterdir()), [downloaded])

    def test_bad_download_does_not_leave_a_cache_file(self) -> None:
        contents = b"downloaded bytes"
        pin = build_appimage.PinnedTool(
            name="runtime",
            filename="runtime-test",
            version="fixture",
            source_url="https://example.invalid/runtime",
            size_bytes=len(contents),
            sha256="0" * 64,
        )
        cache = self.root / "cache"
        with (
            mock.patch.object(
                build_appimage.urllib.request,
                "urlopen",
                return_value=_Response(contents),
            ),
            self.assertRaisesRegex(ValueError, "SHA-256 mismatch"),
        ):
            build_appimage.resolve_pinned_tool("runtime", cache, pins={"runtime": pin})
        self.assertEqual(list(cache.iterdir()), [])

    def test_pyinstaller_version_must_match_the_package_pin(self) -> None:
        with (
            mock.patch.object(
                build_appimage.importlib.metadata, "version", return_value="6.20.0"
            ),
            self.assertRaisesRegex(RuntimeError, "6.21.0 is required"),
        ):
            build_appimage._require_pyinstaller_version()
        with mock.patch.object(
            build_appimage.importlib.metadata, "version", return_value="6.21.0"
        ):
            build_appimage._require_pyinstaller_version()

    def test_pyinstaller_license_file_is_located_from_distribution_metadata(
        self,
    ) -> None:
        distribution_root = self.root / "site-packages"
        license_path = (
            distribution_root
            / "pyinstaller-6.21.0.dist-info"
            / "licenses"
            / "COPYING.txt"
        )
        license_path.parent.mkdir(parents=True)
        license_path.write_bytes(b"opaque fixture license")
        distribution = SimpleNamespace(
            metadata=SimpleNamespace(
                get_all=lambda _field, _default=None: ["COPYING.txt"]
            ),
            files=["pyinstaller-6.21.0.dist-info/licenses/COPYING.txt"],
            locate_file=lambda path: distribution_root / str(path),
        )
        with mock.patch.object(
            build_appimage.importlib.metadata,
            "distribution",
            return_value=distribution,
        ):
            self.assertEqual(
                build_appimage._pyinstaller_license_paths(), [license_path]
            )


class AppImageMaterializationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="catlabel-appimage-source-")
        self.addCleanup(temporary.cleanup)
        self.scratch = Path(temporary.name)
        self.root = self.scratch / "repo"
        self.root.mkdir()
        self.committed: dict[str, bytes] = {
            "launcher.py": b"committed launcher bytes",
            "catlabel/__init__.py": b"committed package bytes",
            "catlabel/core/release_artifacts.py": b"committed artifacts module",
            "catlabel/core/release_slots.py": b"committed slots module",
            "catlabel/core/runtime_lease.py": b"committed lease module",
            "packaging/linux/AppRun": b"opaque committed AppRun",
            "packaging/linux/catlabel.desktop": b"opaque committed desktop bytes",
            "packaging/linux/catlabel.png": b"opaque committed icon bytes",
            "packaging/linux/AppImage-runtime.LICENSE": b"opaque runtime license bytes",
            "LICENSE": b"opaque project license bytes",
            "NOTICE": b"opaque project notice bytes",
        }
        for relative, contents in self.committed.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
            if relative == "packaging/linux/AppRun":
                path.chmod(0o755)
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
        self.source_commit = self.git("rev-parse", "HEAD").decode("ascii").strip()

    def git(self, *arguments: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments], check=True, capture_output=True
        ).stdout

    def test_only_requested_committed_blobs_are_materialized(self) -> None:
        (self.root / "launcher.py").write_bytes(b"dirty launcher must not ship")
        (self.root / "packaging/linux/AppRun").write_bytes(b"dirty AppRun")
        optional_init = self.root / "catlabel/core/__init__.py"
        optional_init.write_bytes(b"uncommitted optional module")
        source_root = self.scratch / "source"
        appdir = self.scratch / "AppDir"
        source_root.mkdir()
        appdir.mkdir()

        build_appimage.materialize_committed_inputs(
            self.root, self.source_commit, source_root, appdir
        )

        self.assertEqual(
            (source_root / "launcher.py").read_bytes(), self.committed["launcher.py"]
        )
        self.assertFalse((source_root / "catlabel/core/__init__.py").exists())
        self.assertEqual(
            (appdir / "AppRun").read_bytes(), self.committed["packaging/linux/AppRun"]
        )
        self.assertEqual((appdir / "AppRun").stat().st_mode & 0o777, 0o755)
        self.assertEqual(
            (appdir / "catlabel.desktop").read_bytes(),
            self.committed["packaging/linux/catlabel.desktop"],
        )
        self.assertEqual(
            (appdir / "catlabel.png").read_bytes(),
            self.committed["packaging/linux/catlabel.png"],
        )
        self.assertEqual(
            (appdir / ".DirIcon").read_bytes(),
            self.committed["packaging/linux/catlabel.png"],
        )
        self.assertEqual(
            (
                appdir / "usr/share/licenses/catlabel/AppImage-runtime.LICENSE"
            ).read_bytes(),
            self.committed["packaging/linux/AppImage-runtime.LICENSE"],
        )
        self.assertEqual(
            (appdir / "usr/share/licenses/catlabel/LICENSE").read_bytes(),
            self.committed["LICENSE"],
        )
        self.assertEqual(
            (appdir / "usr/share/licenses/catlabel/NOTICE").read_bytes(),
            self.committed["NOTICE"],
        )

    def test_symlinked_committed_source_is_rejected(self) -> None:
        self.git("rm", "-q", "launcher.py")
        self.git("commit", "-qm", "remove launcher")
        launcher = self.root / "launcher.py"
        launcher.symlink_to("catlabel/__init__.py")
        self.git("add", "launcher.py")
        self.git("commit", "-qm", "symlink launcher")
        source_root = self.scratch / "source"
        appdir = self.scratch / "AppDir"
        source_root.mkdir()
        appdir.mkdir()
        with self.assertRaisesRegex(ValueError, "regular blob"):
            build_appimage.materialize_committed_inputs(
                self.root,
                self.git("rev-parse", "HEAD").decode().strip(),
                source_root,
                appdir,
            )


class AppImageBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="catlabel-appimage-build-")
        self.addCleanup(temporary.cleanup)
        self.scratch = Path(temporary.name)
        self.root = self.scratch / "repo"
        self.root.mkdir()
        source = AppImageMaterializationTests()
        source.setUp()
        self.addCleanup(source.doCleanups)
        self.root = source.root
        self.source_commit = source.source_commit
        self.output = self.scratch / "CatLabel.AppImage"
        self.cache = self.scratch / "cache"
        self.appimagetool = self.scratch / "provided-appimagetool.AppImage"
        self.runtime = self.scratch / "provided-runtime"
        self.appimagetool.write_bytes(b"verified tool placeholder")
        self.runtime.write_bytes(b"verified runtime placeholder")
        self.frontend_sha256 = "a" * 64

    def _install_build_mocks(
        self, appimage_tool_failure: bool = False
    ) -> list[tuple[list[str], dict[str, str]]]:
        calls: list[tuple[list[str], dict[str, str]]] = []
        real_subprocess_run = subprocess.run

        def fake_build_release(
            root: Path,
            source_ref: str,
            release_id: str,
            frontend_sha256: str,
            archive: Path,
        ) -> tuple[SimpleNamespace, str]:
            archive.write_bytes(b"fixture committed release archive")
            return (
                SimpleNamespace(
                    release_id=release_id,
                    source_commit=self.source_commit,
                    frontend_sha256=frontend_sha256,
                ),
                "b" * 64,
            )

        def fake_subprocess_run(
            command: list[str], **kwargs: Any
        ) -> SimpleNamespace | subprocess.CompletedProcess[bytes]:
            if command[0] == "git":
                return real_subprocess_run(command, **kwargs)
            cwd = kwargs["cwd"]
            env = kwargs["env"]
            assert isinstance(cwd, Path)
            assert isinstance(env, dict)
            calls.append((command, env))
            if command[0] == str(self.appimagetool):
                self.assertEqual(env["ARCH"], "x86_64")
                self.assertEqual(env["APPIMAGE_EXTRACT_AND_RUN"], "1")
                self.assertEqual(
                    command[1:5],
                    ["--runtime-file", str(self.runtime), "--comp", "zstd"],
                )
                if appimage_tool_failure:
                    raise subprocess.CalledProcessError(1, command)
                appdir = Path(command[-2])
                self.assertEqual(
                    (appdir / "AppRun").read_bytes(),
                    b"opaque committed AppRun",
                )
                self.assertTrue(
                    (
                        appdir / "usr/share/licenses/catlabel/AppImage-runtime.LICENSE"
                    ).is_file()
                )
                Path(command[-1]).write_bytes(
                    b"\x7fELF" + b"\0" * 4 + b"AI\x02" + b"type two fixture"
                )
                return SimpleNamespace(returncode=0)

            self.assertEqual(command[2], "PyInstaller")
            self.assertNotIn("PYTHONPATH", env)
            frozen = (
                Path(command[command.index("--distpath") + 1]) / "CatLabel-Launcher"
            )
            frozen.mkdir(parents=True)
            (frozen / "CatLabel-Launcher").write_bytes(b"frozen launcher fixture")
            return SimpleNamespace(returncode=0)

        self.enterContext(
            mock.patch.object(build_appimage, "_require_pyinstaller_version")
        )
        self.enterContext(
            mock.patch.object(build_appimage, "_copy_optional_build_licenses")
        )
        self.enterContext(
            mock.patch.object(
                build_appimage, "build_release", side_effect=fake_build_release
            )
        )
        self.enterContext(
            mock.patch.object(
                build_appimage.subprocess, "run", side_effect=fake_subprocess_run
            )
        )
        self.enterContext(
            mock.patch.object(
                build_appimage,
                "resolve_pinned_tool",
                side_effect=lambda name, cache, explicit, pins: {
                    "appimagetool": self.appimagetool.absolute(),
                    "runtime": self.runtime.absolute(),
                }[name],
            )
        )
        return calls

    def test_success_builds_and_publishes_checked_type2_image(self) -> None:
        calls = self._install_build_mocks()
        result = build_appimage.build_appimage(
            self.root,
            self.source_commit,
            "fixture-release",
            self.frontend_sha256,
            self.output,
            self.cache,
            self.appimagetool,
            self.runtime,
        )
        self.assertEqual(result["source_commit"], self.source_commit)
        self.assertEqual(result["release_id"], "fixture-release")
        self.assertEqual(result["archive_sha256"], "b" * 64)
        self.assertEqual(
            result["appimage_sha256"],
            hashlib.sha256(self.output.read_bytes()).hexdigest(),
        )
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o755)
        self.assertEqual(
            self.output.with_suffix(".AppImage.sha256").read_text(encoding="ascii"),
            result["appimage_sha256"] + "\n",
        )
        self.assertTrue(any(command[0] == sys.executable for command, _ in calls))
        pyi_command = next(
            command for command, _ in calls if command[0] == sys.executable
        )
        self.assertIn("--onedir", pyi_command)
        self.assertIn("--noupx", pyi_command)
        self.assertTrue(
            any(argument.endswith("CatLabel-release.zip:.") for argument in pyi_command)
        )
        self.assertTrue(
            any(
                argument.endswith("CatLabel-release.zip.sha256:.")
                for argument in pyi_command
            )
        )
        image_command = next(
            command for command, _ in calls if command[0] == str(self.appimagetool)
        )
        self.assertEqual(
            image_command[1:5], ["--runtime-file", str(self.runtime), "--comp", "zstd"]
        )

    def test_appimagetool_failure_preserves_existing_output_and_sidecar(self) -> None:
        previous_image = b"previous image bytes"
        previous_sidecar = b"previous checksum\n"
        self.output.write_bytes(previous_image)
        sidecar = self.output.with_suffix(".AppImage.sha256")
        sidecar.write_bytes(previous_sidecar)
        calls = self._install_build_mocks(appimage_tool_failure=True)
        with self.assertRaises(subprocess.CalledProcessError):
            build_appimage.build_appimage(
                self.root,
                self.source_commit,
                "fixture-release",
                self.frontend_sha256,
                self.output,
                self.cache,
                self.appimagetool,
                self.runtime,
            )
        self.assertEqual(self.output.read_bytes(), previous_image)
        self.assertEqual(sidecar.read_bytes(), previous_sidecar)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
