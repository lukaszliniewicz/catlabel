from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from typing import Any

import httpx2
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from catlabel.api.request_limits import RequestLimitsMiddleware
from catlabel.api.routes_harness import router
from catlabel.api.security import LocalSecurityMiddleware
from catlabel.core.server_security import ServerSecurity
from catlabel.services.artifacts import ArtifactStore
from catlabel.services.harness import HarnessServices

SDK_AVAILABLE = importlib.util.find_spec("mcp") is not None
GUI_TOKEN = "g" * 48
CLIENT_HEADERS = {
    "Authorization": f"Bearer {GUI_TOKEN}",
    "X-CatLabel-Client": "1",
}


def _app(port: int = 18261) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.add_middleware(RequestLimitsMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-CatLabel-Client"],
    )
    application.add_middleware(
        LocalSecurityMiddleware,
        settings=ServerSecurity(port=port, access_token=GUI_TOKEN),
    )
    application.state.mcp_registry = None
    application.state.mcp_port = port
    application.state.mcp_config_path = None
    application.state.mcp_configuration_error = False
    return application


class HarnessBridgeDisabledTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.application = _app()
        self.client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.application),
            base_url="http://127.0.0.1:18261",
            headers=CLIENT_HEADERS,
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_disabled_connection_and_tools_are_explicit(self) -> None:
        connection = await self.client.get("/api/harness/connection")
        tools = await self.client.get("/api/harness/tools")
        call = await self.client.post(
            "/api/harness/tools/catlabel_server_info", json={"arguments": {}}
        )

        self.assertEqual(connection.status_code, 200)
        self.assertEqual(
            connection.json(),
            {
                "enabled": False,
                "url": None,
                "opencode_config_path": None,
                "configuration_error": False,
            },
        )
        self.assertEqual(tools.status_code, 200)
        self.assertEqual(tools.json(), {"enabled": False, "tools": []})
        self.assertEqual(call.status_code, 503)

    async def test_existing_gui_middleware_still_guards_the_routes(self) -> None:
        missing_client_header = await self.client.get(
            "/api/harness/connection", headers={"X-CatLabel-Client": ""}
        )
        cross_origin = await self.client.get(
            "/api/harness/connection",
            headers={**CLIENT_HEADERS, "Origin": "http://untrusted.invalid"},
        )

        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.application),
            base_url="http://127.0.0.1:18261",
            headers={"X-CatLabel-Client": "1"},
        ) as tokenless_client:
            tokenless = await tokenless_client.get("/api/harness/connection")

        self.assertEqual(missing_client_header.status_code, 403)
        self.assertEqual(cross_origin.status_code, 403)
        self.assertEqual(tokenless.status_code, 401)

    async def test_call_body_rejects_extra_fields(self) -> None:
        extra = await self.client.post(
            "/api/harness/tools/catlabel_server_info",
            json={"arguments": {}, "unexpected": True},
        )
        missing = await self.client.post(
            "/api/harness/tools/catlabel_server_info", json={}
        )

        self.assertEqual(extra.status_code, 422)
        self.assertEqual(missing.status_code, 422)


@unittest.skipUnless(SDK_AVAILABLE, "MCP optional dependency is not installed")
class HarnessBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from catlabel.mcp.auth import Credential
        from catlabel.mcp.integration import build_mcp

        self.temporary = tempfile.TemporaryDirectory(prefix="catlabel-harness-bridge-")
        self.root = Path(self.temporary.name)
        self.engine = create_engine(
            f"sqlite:///{self.root / 'app.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)
        self.artifacts = ArtifactStore(self.engine, self.root / "artifacts")
        self.services = HarnessServices(
            self.engine, self.artifacts, principal="fixture"
        )
        self.registry, _ = build_mcp(
            self.services, Credential("fixture", "x" * 48), 18261
        )
        self.application = _app()
        self.application.state.mcp_registry = self.registry
        self.application.state.mcp_config_path = self.root / "mcp-opencode-18261.json"
        self.application.state.mcp_configuration_error = True
        self.client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.application),
            base_url="http://127.0.0.1:18261",
            headers=CLIENT_HEADERS,
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await self.services.jobs.close()
        self.artifacts.close()
        self.engine.dispose()
        self.temporary.cleanup()

    async def _call(self, name: str, arguments: dict[str, Any]):
        return await self.client.post(
            f"/api/harness/tools/{name}", json={"arguments": arguments}
        )

    async def test_list_tools_matches_the_registered_sdk_models(self) -> None:
        response = await self.client.get("/api/harness/tools")
        expected = [
            tool.model_dump(mode="json", by_alias=True, exclude_none=True)
            for tool in await self.registry.server.list_tools()
        ]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"enabled": True, "tools": expected})
        self.assertTrue(all(tool["name"].startswith("catlabel_") for tool in expected))
        physical = next(
            tool for tool in expected if tool["name"] == "catlabel_print_start"
        )
        self.assertTrue(physical["annotations"]["destructiveHint"])

    async def test_connection_reports_loopback_endpoint_and_private_config_path(
        self,
    ) -> None:
        response = await self.client.get("/api/harness/connection")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "enabled": True,
                "url": "http://127.0.0.1:18261/mcp/",
                "opencode_config_path": str(self.root / "mcp-opencode-18261.json"),
                "configuration_error": True,
            },
        )

    async def test_create_apply_and_get_use_the_same_saved_registry(self) -> None:
        created = await self._call("catlabel_design_create", {"name": "Bridge"})
        self.assertEqual(created.status_code, 200)
        design = created.json()["structuredContent"]["data"]
        self.assertEqual(design["revision"], 1)

        applied = await self._call(
            "catlabel_design_apply",
            {
                "design_id": design["id"],
                "expected_revision": 1,
                "operations": [{"op": "add_page"}],
            },
        )
        self.assertEqual(applied.status_code, 200)
        updated = applied.json()["structuredContent"]["data"]
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(len(updated["canvas_state"]["pageLayouts"]), 2)

        fetched = await self._call("catlabel_design_get", {"design_id": design["id"]})
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["structuredContent"]["data"]["revision"], 2)

    async def test_unknown_and_invalid_calls_are_rejected_without_internal_errors(
        self,
    ) -> None:
        unknown = await self._call("delete_everything", {})
        invalid = await self._call("catlabel_design_create", {})
        tool_error = await self._call("catlabel_design_get", {"design_id": 999999})

        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json(), {"detail": "Invalid tool request."})
        self.assertEqual(tool_error.status_code, 200)
        self.assertTrue(tool_error.json()["isError"])
        self.assertIn("content", tool_error.json())
        self.assertIn("structuredContent", tool_error.json())
