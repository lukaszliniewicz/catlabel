from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[1]


class ApplicationPathsTests(unittest.TestCase):
    def _run_fresh_import(
        self,
        code: str,
        cwd: Path,
        *,
        data_directory: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            "HOME": str(cwd),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(APPLICATION_ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
            "LITELLM_MODE": "PROD",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "PYTHON_DOTENV_DISABLED": "1",
        }
        for name in ("SYSTEMROOT", "WINDIR"):
            if name in os.environ:
                environment[name] = os.environ[name]
        if data_directory is not None:
            environment["CATLABEL_DATA_DIR"] = str(data_directory)

        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=cwd,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )

    def _assert_successful_json(
        self, result: subprocess.CompletedProcess[str]
    ) -> dict[str, object]:
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        output_lines = result.stdout.splitlines()
        self.assertTrue(output_lines, msg="The subprocess returned no result.")
        parsed = json.loads(output_lines[-1])
        self.assertIsInstance(parsed, dict)
        return parsed

    def test_default_database_and_font_paths_follow_foreign_cwd(self) -> None:
        code = "\n".join(
            [
                "import json, urllib.request",
                "from pathlib import Path",
                "network_calls = []",
                "urllib.request.urlopen = lambda *args, **kwargs: network_calls.append(True)",
                "from catlabel.api import main",
                "from catlabel.core import database, paths",
                "from catlabel.core.models import Font",
                "from catlabel.services import uploads",
                "from sqlmodel import Session, select",
                "with database.engine.connect(): pass",
                "database.create_db_and_tables()",
                "(paths.FONTS_DIRECTORY / 'indexed-font.otf').write_bytes(b'fixture')",
                "main.list_fonts()",
                "with Session(database.engine) as session:",
                "    indexed = [item.name for item in session.exec(select(Font)).all()]",
                "mounts = {getattr(route, 'name'): getattr(getattr(route, 'app', None), 'directory', None) for route in main.app.routes if getattr(route, 'name', None)}",
                "print(json.dumps({",
                "    'cwd': str(Path.cwd()),",
                "    'data': str(paths.DATA_DIRECTORY),",
                "    'db': database.engine.url.database,",
                "    'db_exists': (paths.DATA_DIRECTORY / 'catlabel.db').is_file(),",
                "    'fonts': str(paths.FONTS_DIRECTORY),",
                "    'upload': str(uploads._FONT_DIRECTORY),",
                "    'indexed': indexed,",
                "    'font_mount': mounts.get('fonts'),",
                "    'frontend': str(paths.FRONTEND_DIRECTORY),",
                "    'frontend_mount': mounts.get('frontend'),",
                "    'legacy': str(paths.LEGACY_FONTS_DIRECTORY),",
                "    'network_calls': len(network_calls),",
                "}))",
            ]
        )
        with tempfile.TemporaryDirectory(prefix="catlabel-path-cwd-") as temporary:
            cwd = Path(temporary).resolve() / "default cwd ü"
            cwd.mkdir()
            payload = self._assert_successful_json(self._run_fresh_import(code, cwd))

        expected_data = cwd / "data"
        expected_fonts = expected_data / "fonts"
        expected_frontend = APPLICATION_ROOT / "frontend" / "dist"
        self.assertEqual(payload["cwd"], str(cwd))
        self.assertEqual(payload["data"], str(expected_data))
        self.assertEqual(payload["db"], str(expected_data / "catlabel.db"))
        self.assertIs(payload["db_exists"], True)
        self.assertEqual(payload["fonts"], str(expected_fonts))
        self.assertEqual(payload["upload"], str(expected_fonts))
        self.assertEqual(payload["indexed"], ["indexed-font.otf"])
        self.assertEqual(payload["font_mount"], str(expected_fonts))
        self.assertEqual(payload["frontend"], str(expected_frontend))
        self.assertIn(payload["frontend_mount"], (None, str(expected_frontend)))
        self.assertEqual(payload["legacy"], str(APPLICATION_ROOT / "fonts"))
        self.assertEqual(payload["network_calls"], 0)
        self.assertFalse((cwd / "fonts").exists())

    def test_absolute_data_directory_is_shared_across_different_cwds(self) -> None:
        code = "\n".join(
            [
                "import json, urllib.request",
                "from pathlib import Path",
                "urllib.request.urlopen = lambda *args, **kwargs: None",
                "from catlabel.api import main",
                "from catlabel.core import database, paths",
                "from catlabel.services import uploads",
                "with database.engine.connect(): pass",
                "mounts = {getattr(route, 'name'): getattr(getattr(route, 'app', None), 'directory', None) for route in main.app.routes if getattr(route, 'name', None)}",
                "print(json.dumps({",
                "    'cwd': str(Path.cwd()),",
                "    'data': str(paths.DATA_DIRECTORY),",
                "    'db': database.engine.url.database,",
                "    'fonts': str(paths.FONTS_DIRECTORY),",
                "    'upload': str(uploads._FONT_DIRECTORY),",
                "    'font_mount': mounts.get('fonts'),",
                "    'frontend': str(paths.FRONTEND_DIRECTORY),",
                "    'frontend_mount': mounts.get('frontend'),",
                "}))",
            ]
        )
        with tempfile.TemporaryDirectory(prefix="catlabel-path-shared-") as temporary:
            scratch = Path(temporary).resolve()
            shared_data = scratch / "shared data ü"
            working_directories = [scratch / "first cwd", scratch / "second cwd"]
            for cwd in working_directories:
                cwd.mkdir()

            payloads = []
            for cwd in working_directories:
                result = self._run_fresh_import(code, cwd, data_directory=shared_data)
                payloads.append(self._assert_successful_json(result))

            expected_fonts = shared_data / "fonts"
            expected_frontend = APPLICATION_ROOT / "frontend" / "dist"
            for cwd, payload in zip(working_directories, payloads, strict=True):
                self.assertEqual(payload["cwd"], str(cwd))
                self.assertEqual(payload["data"], str(shared_data))
                self.assertEqual(payload["db"], str(shared_data / "catlabel.db"))
                self.assertEqual(payload["fonts"], str(expected_fonts))
                self.assertEqual(payload["upload"], str(expected_fonts))
                self.assertEqual(payload["font_mount"], str(expected_fonts))
                self.assertEqual(payload["frontend"], str(expected_frontend))
                self.assertIn(payload["frontend_mount"], (None, str(expected_frontend)))
                self.assertFalse((cwd / "data").exists())
                self.assertFalse((cwd / "fonts").exists())

            self.assertTrue((shared_data / "catlabel.db").is_file())
            self.assertTrue(expected_fonts.is_dir())

    def test_relative_data_directory_fails_before_creating_files(self) -> None:
        code = "\n".join(
            [
                "import json",
                "from pathlib import Path",
                "try:",
                "    import catlabel.core.database",
                "except ValueError as error:",
                "    print(json.dumps({",
                "        'error': str(error),",
                "        'entries': [entry.name for entry in Path.cwd().iterdir()],",
                "    }))",
                "else:",
                "    raise AssertionError('a relative CATLABEL_DATA_DIR was accepted')",
            ]
        )
        with tempfile.TemporaryDirectory(prefix="catlabel-path-invalid-") as temporary:
            cwd = Path(temporary).resolve()
            result = self._run_fresh_import(
                code, cwd, data_directory=Path("relative-data")
            )

        payload = self._assert_successful_json(result)
        self.assertEqual(payload["error"], "CATLABEL_DATA_DIR must be an absolute path")
        self.assertEqual(payload["entries"], [])

    @unittest.skipIf(os.name == "nt", "Question marks are invalid Windows filenames")
    def test_sqlite_uses_the_literal_data_path_with_url_delimiters(self) -> None:
        code = "\n".join(
            [
                "import json",
                "from catlabel.core import database",
                "with database.engine.connect(): pass",
                "print(json.dumps({'database': database.engine.url.database}))",
            ]
        )
        with tempfile.TemporaryDirectory(prefix="catlabel-path-url-") as temporary:
            cwd = Path(temporary).resolve()
            data_directory = cwd / "data ?query#fragment ü"
            payload = self._assert_successful_json(
                self._run_fresh_import(code, cwd, data_directory=data_directory)
            )
            self.assertEqual(payload["database"], str(data_directory / "catlabel.db"))
            self.assertTrue((data_directory / "catlabel.db").is_file())

    def test_legacy_copy_and_default_downloads_use_the_configured_font_directory(
        self,
    ) -> None:
        code = "\n".join(
            [
                "import io, json, urllib.request",
                "from pathlib import Path",
                "urllib.request.urlopen = lambda *args, **kwargs: None",
                "from catlabel.api import main",
                "from catlabel.core import paths",
                "legacy = Path.cwd() / 'legacy-fonts'",
                "legacy.mkdir()",
                "(legacy / 'Migrated.OTF').write_bytes(b'legacy font')",
                "(legacy / 'Retained.ttf').write_bytes(b'must not replace')",
                "(legacy / 'directory.ttf').mkdir()",
                "(paths.FONTS_DIRECTORY / 'Retained.ttf').write_bytes(b'current font')",
                "main.LEGACY_FONTS_DIRECTORY = legacy",
                "requests = []",
                "urllib.request.urlopen = lambda request, timeout: (requests.append(request.full_url), io.BytesIO(b'downloaded font'))[1]",
                "main.download_default_fonts()",
                "downloaded = sorted(path.name for path in paths.FONTS_DIRECTORY.iterdir())",
                "print(json.dumps({",
                "    'fonts': str(paths.FONTS_DIRECTORY),",
                "    'migrated': (paths.FONTS_DIRECTORY / 'Migrated.OTF').read_bytes().decode(),",
                "    'retained': (paths.FONTS_DIRECTORY / 'Retained.ttf').read_bytes().decode(),",
                "    'directory_not_copied': not (paths.FONTS_DIRECTORY / 'directory.ttf').exists(),",
                "    'downloaded': downloaded,",
                "    'mocked_requests': len(requests),",
                "}))",
            ]
        )
        with tempfile.TemporaryDirectory(prefix="catlabel-path-download-") as temporary:
            scratch = Path(temporary).resolve()
            cwd = scratch / "foreign cwd"
            cwd.mkdir()
            data_directory = scratch / "explicit data"
            payload = self._assert_successful_json(
                self._run_fresh_import(code, cwd, data_directory=data_directory)
            )

        self.assertEqual(payload["fonts"], str(data_directory / "fonts"))
        self.assertEqual(payload["migrated"], "legacy font")
        self.assertEqual(payload["retained"], "current font")
        self.assertIs(payload["directory_not_copied"], True)
        self.assertEqual(payload["mocked_requests"], 6)
        downloaded = payload["downloaded"]
        if not isinstance(downloaded, list):
            self.fail("The downloaded font list was not a list.")
        self.assertIn("Migrated.OTF", downloaded)
        self.assertIn("Roboto.ttf", downloaded)
        self.assertFalse((cwd / "data").exists())


if __name__ == "__main__":
    unittest.main()
