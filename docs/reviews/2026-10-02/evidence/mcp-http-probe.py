import asyncio
import json

import httpx2
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.types import CallToolResult, ImageContent, ResourceLink, TextContent

server = MCPServer("CatLabel HTTP probe", version="0.0.0")


@server.tool()
def inspect_fixture(name: str) -> dict[str, str]:
    return {"name": name, "hardware": "disabled"}


@server.tool()
def preview_fixture() -> CallToolResult:
    return CallToolResult(
        structuredContent={"preview_id": "fixture", "hardware": "disabled"},
        content=[
            TextContent(text="A one-pixel preview fixture; no CatLabel rendering."),
            ImageContent(
                data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                mimeType="image/png",
            ),
            ResourceLink(
                name="Fixture PNG",
                uri="catlabel://artifacts/fixture",
                mimeType="image/png",
            ),
        ],
    )


mcp_app = server.streamable_http_app(
    streamable_http_path="/", json_response=True, stateless_http=True
)
app = FastAPI()
app.mount("/mcp", mcp_app)


async def main() -> None:
    requests = []

    async def capture(request) -> None:
        body = json.loads(request.content) if request.content else {}
        requests.append(
            {
                "method": request.method,
                "rpc": body.get("method"),
                "protocol_header": request.headers.get("mcp-protocol-version"),
                "metadata_keys": sorted(body.get("params", {}).get("_meta", {})),
            }
        )

    receipt = {"hardware_calls": 0, "cases": []}
    async with (
        server.session_manager.run(),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://127.0.0.1:18261",
            event_hooks={"request": [capture]},
        ) as http,
    ):
        for mode in ["auto", "legacy"]:
            start = len(requests)
            transport = streamable_http_client(
                "http://127.0.0.1:18261/mcp/", http_client=http
            )
            async with Client(transport, mode=mode) as client:
                tools = await client.list_tools()
                result = await client.call_tool("inspect_fixture", {"name": "test"})
                assert result.structured_content == {
                    "name": "test",
                    "hardware": "disabled",
                }
                assert not result.is_error
                preview = await client.call_tool("preview_fixture", {})
                content_types = [item.type for item in preview.content]
                assert content_types == ["text", "image", "resource_link"]
                assert preview.structured_content == {
                    "preview_id": "fixture",
                    "hardware": "disabled",
                }
                receipt["cases"].append(
                    {
                        "mode": mode,
                        "protocol": client.protocol_version,
                        "tools": [tool.name for tool in tools.tools],
                        "structured_content": result.structured_content,
                        "preview_content_types": content_types,
                        "requests": requests[start:],
                    }
                )
        hostile = await http.post(
            "/mcp/",
            headers={
                "Origin": "https://untrusted.example",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 100, "method": "server/discover"},
        )
        receipt["untrusted_origin_status"] = hostile.status_code
        assert hostile.status_code == 403
        hostile_host = await http.post(
            "/mcp/",
            headers={
                "Host": "untrusted.example",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 101, "method": "server/discover"},
        )
        receipt["untrusted_host_status"] = hostile_host.status_code
        assert hostile_host.status_code == 421
    assert receipt["cases"][0]["protocol"] == "2026-07-28"
    assert receipt["cases"][1]["protocol"] == "2025-11-25"
    print(json.dumps(receipt, indent=2))


asyncio.run(main())
