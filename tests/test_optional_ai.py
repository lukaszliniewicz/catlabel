"""The core application must remain usable without provider SDKs."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

from fastapi import HTTPException

from catlabel.api import routes_ai
from catlabel.core.models import AIModelConfig, AIProvider


class OptionalAITests(unittest.TestCase):
    def test_api_import_does_not_import_provider_sdks(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = """
import importlib.abc
import sys
class NoProviderSDKs(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "litellm" or fullname.startswith("litellm.") or fullname == "google" or fullname.startswith("google."):
            raise ModuleNotFoundError("Provider SDK forbidden in core startup")
sys.meta_path.insert(0, NoProviderSDKs())
from catlabel.api.main import app
assert app.title == "CatLabel Server"
assert "litellm" not in sys.modules
assert "google.cloud.aiplatform" not in sys.modules
"""
        with tempfile.TemporaryDirectory(prefix="catlabel-without-ai-") as scratch:
            allowed = ("PATH", "SYSTEMROOT", "WINDIR")
            environment = {
                name: os.environ[name] for name in allowed if name in os.environ
            }
            environment.update(
                PYTHONPATH=str(root),
                PYTHONDONTWRITEBYTECODE="1",
                CATLABEL_DATA_DIR=str(Path(scratch) / "isolated-data"),
                PYTHON_DOTENV_DISABLED="1",
                LITELLM_MODE="PROD",
                LITELLM_LOCAL_MODEL_COST_MAP="True",
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=scratch,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_sdk_fails_before_context_or_provider_work(self) -> None:
        from catlabel.core import database
        from catlabel.services import agent_context

        self.assertIsNotNone(database.engine)
        request = routes_ai.ChatRequest(messages=[], canvas_state={})
        with (
            mock.patch.object(agent_context, "build_agent_context") as context,
            mock.patch.object(
                routes_ai.importlib,
                "import_module",
                side_effect=ModuleNotFoundError("missing"),
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            routes_ai._chat_with_provider(
                request,
                AIProvider(name="fixture", provider="openai"),
                AIModelConfig(provider_id=1, model_name="fixture"),
                (),
            )
        self.assertEqual(caught.exception.status_code, 503)
        detail = cast(object, caught.exception.detail)
        if not isinstance(detail, dict):
            raise AssertionError("Expected structured AI add-on response")
        self.assertEqual(detail["code"], "ai_addon_required")
        context.assert_not_called()


if __name__ == "__main__":
    unittest.main()
