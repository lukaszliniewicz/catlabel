from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from catlabel.mcp.auth import credential_path, load_credential
from catlabel.mcp.configuration import generate_connection_files


class MCPConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="catlabel-mcp-config-")
        self.data = Path(self.temporary.name) / "data"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_generation_is_idempotent_private_and_port_specific(self) -> None:
        first = generate_connection_files(self.data, 18261)
        repeated = generate_connection_files(self.data, 18261)
        second = generate_connection_files(self.data, 18262)
        token_file = self.data / "mcp-token.txt"
        credential = load_credential(credential_path(self.data))

        self.assertEqual(first, repeated)
        self.assertEqual(first.name, "mcp-opencode-18261.json")
        self.assertEqual(second.name, "mcp-opencode-18262.json")
        self.assertEqual(token_file.read_text(encoding="ascii"), credential.token)
        self.assertEqual(first.read_bytes(), repeated.read_bytes())

        first_config = json.loads(first.read_text(encoding="utf-8"))
        second_config = json.loads(second.read_text(encoding="utf-8"))
        first_server = first_config["mcp"]["servers"]["catlabel"]
        second_server = second_config["mcp"]["servers"]["catlabel"]
        self.assertEqual(first_server["url"], "http://127.0.0.1:18261/mcp/")
        self.assertEqual(second_server["url"], "http://127.0.0.1:18262/mcp/")
        self.assertEqual(
            first_server["headers"]["Authorization"],
            "Bearer {file:" + str(token_file.resolve()) + "}",
        )
        self.assertNotIn(credential.token, first.read_text(encoding="utf-8"))

        if os.name != "nt":
            for path in (token_file, first, second):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_generation_preserves_the_existing_default_user_config(self) -> None:
        self.data.mkdir(parents=True)
        user_config = self.data / "mcp-opencode.json"
        user_config.write_text('{"user":"keep"}\n', encoding="utf-8")

        generated = generate_connection_files(self.data, 18261)

        self.assertTrue(generated.is_file())
        self.assertEqual(user_config.read_text(encoding="utf-8"), '{"user":"keep"}\n')

    def test_different_existing_port_config_is_rejected_without_overwrite(self) -> None:
        config = generate_connection_files(self.data, 18261)
        original = b"user changed this file\n"
        config.write_bytes(original)

        with self.assertRaises(RuntimeError):
            generate_connection_files(self.data, 18261)

        self.assertEqual(config.read_bytes(), original)

    @unittest.skipIf(os.name == "nt", "Requires privileged Windows symlink acceptance")
    def test_symlink_config_is_rejected_without_modifying_its_target(self) -> None:
        self.data.mkdir(parents=True)
        target = self.data / "target.json"
        target.write_text("leave this alone", encoding="utf-8")
        link = self.data / "mcp-opencode-18261.json"
        link.symlink_to(target)

        with self.assertRaises(RuntimeError):
            generate_connection_files(self.data, 18261)

        self.assertEqual(target.read_text(encoding="utf-8"), "leave this alone")
        self.assertTrue(link.is_symlink())

    def test_invalid_port_is_rejected_before_creating_files(self) -> None:
        with self.assertRaises(ValueError):
            generate_connection_files(self.data, 0)

        self.assertFalse(self.data.exists())
