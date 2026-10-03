"""MCP adapter acceptance with real storage and a recorded hardware boundary."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from catlabel.services.artifacts import ArtifactStore
from catlabel.services.documents import apply_operations, create_document
from catlabel.services.harness import HarnessServices

SDK_AVAILABLE = importlib.util.find_spec("mcp") is not None


class DocumentEditTests(unittest.TestCase):
    def test_remove_first_page_compacts_indices_and_keeps_input_unchanged(self):
        original = create_document(48, 25, 203)
        changed = apply_operations(
            original,
            [
                {"op": "add_page"},
                {
                    "op": "add_element",
                    "element": {
                        "id": "qr",
                        "type": "qrcode",
                        "pageIndex": 1,
                        "text": "test",
                    },
                },
                {"op": "remove_page", "page_index": 0},
            ],
        )
        self.assertEqual(changed["pageLayouts"][0]["pageIndex"], 0)
        self.assertEqual(changed["items"][0]["pageIndex"], 0)
        self.assertEqual(original["items"], [])
        with self.assertRaisesRegex(ValueError, "retain at least"):
            apply_operations(original, [{"op": "remove_page", "page_index": 0}])


@unittest.skipUnless(SDK_AVAILABLE, "MCP optional dependency is not installed")
class MCPWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx2

        from catlabel.mcp.auth import Credential
        from catlabel.mcp.integration import build_mcp

        self.temporary = tempfile.TemporaryDirectory(prefix="catlabel-mcp-")
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
        self.registry, self.app = build_mcp(
            self.services, Credential("fixture", "x" * 48), 18261
        )
        self.manager = self.registry.server.session_manager.run()
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

        async def serve():
            async with self.manager:
                self.started.set()
                await self.stopped.wait()

        self.server_task = asyncio.create_task(serve())
        await self.started.wait()
        self.http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app),
            base_url="http://127.0.0.1:18261",
            headers={"Authorization": "Bearer " + "x" * 48},
        )
        await self.http.__aenter__()

    async def asyncTearDown(self):
        await self.http.__aexit__(None, None, None)
        self.stopped.set()
        await self.server_task
        await self.services.jobs.close()
        self.artifacts.close()
        self.engine.dispose()
        self.temporary.cleanup()

    def client(self, mode="auto"):
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client

        return Client(
            streamable_http_client("http://127.0.0.1:18261/", http_client=self.http),
            mode=mode,
        )

    async def call(self, client, tool, **args):
        result = await client.call_tool(tool, args)
        self.assertFalse(result.is_error, result.structured_content)
        self.assertTrue(result.structured_content["ok"])
        return result.structured_content["data"]

    async def test_protocols_resources_and_security(self):
        for mode, version in [("auto", "2026-07-28"), ("legacy", "2025-11-25")]:
            async with self.client(mode) as client:
                result = await self.call(client, "catlabel_server_info")
                self.assertEqual(client.protocol_version, version)
                self.assertFalse(result["tasks"])
                tools = await client.list_tools()
                physical = next(
                    t for t in tools.tools if t.name == "catlabel_print_start"
                )
                assert physical.annotations is not None
                self.assertTrue(physical.annotations.destructive_hint)
                self.assertTrue(physical.annotations.idempotent_hint)
                resource = await client.read_resource("catlabel://schema/document")
                from mcp.types import TextResourceContents

                assert isinstance(resource.contents[0], TextResourceContents)
                self.assertIn("document_version", resource.contents[0].text)
        for headers, expected in [
            ({"Authorization": "Bearer wrong"}, 401),
            ({"Origin": "https://evil.example"}, 403),
            ({"Host": "evil.example"}, 421),
        ]:
            response = await self.http.post(
                "/",
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
            )
            self.assertEqual(response.status_code, expected)

    async def test_saved_edits_preview_frozen_plan_and_reconnect_do_not_duplicate(self):
        executions = []

        async def recorder(address, prepare, split_mode=False, dither=True, **kwargs):
            await kwargs["on_delivery_start"]()
            images = await prepare()
            executions.append(
                {
                    "address": address,
                    "images": len(images),
                    "size": images[0].size,
                    "settings": kwargs["frozen_settings"],
                }
            )
            for image in images:
                image.close()
            return {"success": True, "count": len(images), "delivery": "submitted"}

        scan = {
            "devices": [
                {"address": "AA:BB:CC:DD:EE:FF", "vendor": "cat", "model_id": "PD01"}
            ]
        }
        async with self.client() as client:
            design = await self.call(
                client, "catlabel_design_create", name="MCP fixture"
            )
            design = await self.call(
                client,
                "catlabel_design_apply",
                design_id=design["id"],
                expected_revision=design["revision"],
                operations=[
                    {
                        "op": "add_element",
                        "element": {
                            "id": "qr",
                            "type": "qrcode",
                            "text": "MCP fixture",
                            "width": 96,
                            "height": 96,
                        },
                    }
                ],
            )
            stale = await client.call_tool(
                "catlabel_design_apply",
                {
                    "design_id": design["id"],
                    "expected_revision": 1,
                    "operations": [{"op": "remove_element", "id": "qr"}],
                },
            )
            self.assertTrue(stale.is_error)
            self.assertEqual(
                stale.structured_content["error"]["code"], "revision_conflict"
            )
            with patch(
                "catlabel.services.harness.render_via_browser_async",
                new=AsyncMock(return_value=[Image.new("RGB", (384, 200), "white")]),
            ):
                result = await client.call_tool(
                    "catlabel_preview_create",
                    {
                        "design_id": design["id"],
                        "expected_revision": design["revision"],
                    },
                )
            self.assertFalse(result.is_error, result.structured_content)
            self.assertEqual(
                [b.type for b in result.content], ["text", "image", "resource_link"]
            )
            preview = result.structured_content["data"]
            with patch(
                "catlabel.services.printers.scan_printers",
                new=AsyncMock(return_value=scan),
            ):
                plan = await self.call(
                    client,
                    "catlabel_print_prepare",
                    preview_id=preview["preview_id"],
                    expected_preview_hash=preview["preview_hash"],
                    printer_address=scan["devices"][0]["address"],
                )
            with patch(
                "catlabel.services.harness.execute_owned_print_jobs", new=recorder
            ):
                job = await self.call(
                    client,
                    "catlabel_print_start",
                    plan_id=plan["id"],
                    expected_plan_hash=plan["plan_hash"],
                    idempotency_key="fixture-once",
                )
                for _ in range(50):
                    job = await self.call(client, "catlabel_job_get", job_id=job["id"])
                    if job["state"] == "submitted":
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(job["state"], "submitted", job)
        async with self.client("legacy") as client:
            replay = await self.call(
                client,
                "catlabel_print_start",
                plan_id=plan["id"],
                expected_plan_hash=plan["plan_hash"],
                idempotency_key="fixture-once",
            )
            self.assertEqual(replay["id"], job["id"])
            self.assertEqual(len(executions), 1)
            self.assertEqual(executions[0]["size"], (384, 200))
            self.assertEqual(executions[0]["settings"], plan["manifest"]["settings"])

    async def test_asset_import_and_portable_export(self):
        output = io.BytesIO()
        with Image.new("RGB", (3, 3), "white") as image:
            image.save(output, "PNG")
        async with self.client() as client:
            imported = await self.call(
                client,
                "catlabel_asset_import",
                base64_data=base64.b64encode(output.getvalue()).decode(),
                mime_type="image/png",
            )
            asset = imported["assets"][0]
            self.assertEqual(asset["kind"], "asset")
            document = create_document(48, 25)
            document["items"] = [{"id": "img", "type": "image", "src": asset["uri"]}]
            design = await self.call(
                client, "catlabel_design_create", name="Image export", document=document
            )
            exported = await self.call(
                client, "catlabel_design_export", design_id=design["id"]
            )
            source = exported["data"]["canvas_state"]["items"][0]["src"]
            self.assertEqual(
                base64.b64decode(source.split(",", 1)[1]), output.getvalue()
            )
            original = await self.call(
                client, "catlabel_design_get", design_id=design["id"]
            )
            self.assertEqual(original["canvas_state"]["items"][0]["src"], asset["uri"])
            resource = await client.read_resource("catlabel://artifacts/" + asset["id"])
            from mcp.types import BlobResourceContents

            assert isinstance(resource.contents[0], BlobResourceContents)
            self.assertEqual(
                base64.b64decode(resource.contents[0].blob), output.getvalue()
            )

    @unittest.skipIf(os.name == "nt", "Requires privileged Windows symlink acceptance")
    async def test_private_config_rejects_symlinks(self):
        from catlabel.mcp.__main__ import write_private_file

        target = self.root / "private.txt"
        write_private_file(target, b"private")
        write_private_file(target, b"private")
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(RuntimeError):
            write_private_file(link, b"other")
        self.assertEqual(target.read_bytes(), b"private")
