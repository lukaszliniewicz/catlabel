import asyncio
import importlib.metadata
import json

from mcp import Client
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("CatLabel architecture probe", version="0.0.0")


@server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def inspect_fixture(name: str) -> dict[str, str]:
    return {"name": name, "hardware": "disabled"}


async def main() -> None:
    receipt = {
        "sdk": importlib.metadata.version("mcp"),
        "python": "3.11.15",
        "fastapi": importlib.metadata.version("fastapi"),
        "hardware_calls": 0,
        "cases": [],
    }
    for mode in ["auto", "legacy"]:
        async with Client(server, mode=mode) as client:
            tools = await client.list_tools()
            result = await client.call_tool("inspect_fixture", {"name": "test"})
            receipt["cases"].append(
                {
                    "mode": mode,
                    "protocol_version": client.protocol_version,
                    "tool_schema": tools.tools[0].model_dump(
                        mode="json", exclude_none=True
                    ),
                    "result": result.model_dump(mode="json", exclude_none=True),
                }
            )
            assert result.structured_content == {"name": "test", "hardware": "disabled"}
            assert result.is_error is False
            assert tools.tools[0].output_schema is not None
    assert receipt["cases"][0]["protocol_version"] == "2026-07-28"
    assert receipt["cases"][1]["protocol_version"] == "2025-11-25"
    print(json.dumps(receipt, indent=2))


asyncio.run(main())
