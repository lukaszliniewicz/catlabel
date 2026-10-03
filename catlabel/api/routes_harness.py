"""HTTP access to the already-registered CatLabel MCP tools."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/harness", tags=["Harness"])


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    arguments: dict[str, Any]


@router.get("/connection")
async def get_connection(request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "mcp_registry", None)
    enabled = registry is not None
    port = getattr(request.app.state, "mcp_port", None)
    config_path = getattr(request.app.state, "mcp_config_path", None)
    return {
        "enabled": enabled,
        "url": f"http://127.0.0.1:{port}/mcp/" if enabled else None,
        "opencode_config_path": str(config_path) if config_path is not None else None,
        "configuration_error": bool(
            getattr(request.app.state, "mcp_configuration_error", False)
        ),
    }


@router.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "mcp_registry", None)
    if registry is None:
        return {"enabled": False, "tools": []}

    tools = await registry.server.list_tools()
    return {
        "enabled": True,
        "tools": [
            tool.model_dump(mode="json", by_alias=True, exclude_none=True)
            for tool in tools
        ],
    }


@router.post("/tools/{name}")
async def call_tool(
    name: str, body: ToolCallRequest, request: Request
) -> dict[str, Any]:
    registry = getattr(request.app.state, "mcp_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="MCP tools are unavailable.")

    tools = await registry.server.list_tools()
    allowed_names = {tool.name for tool in tools if tool.name.startswith("catlabel_")}
    if name not in allowed_names:
        raise HTTPException(status_code=404, detail="Tool not found.")

    from mcp.server.mcpserver.exceptions import ToolError

    try:
        result = await registry.server.call_tool(name, body.arguments)
    except (ToolError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid tool request.") from None

    return result.model_dump(mode="json", by_alias=True, exclude_none=True)
