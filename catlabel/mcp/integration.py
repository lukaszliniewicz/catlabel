"""Host lifecycle and mounted ASGI delegation, without another app owner."""

from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..services.harness import HarnessServices
from .auth import Credential, MCPAuthentication
from .server import Registry


def build_mcp(
    services: HarnessServices, credential: Credential, port: int
) -> tuple[Registry, ASGIApp]:
    registry = Registry(services)
    inner = registry.server.streamable_http_app(
        streamable_http_path="/", json_response=True, stateless_http=True
    )
    return registry, MCPAuthentication(inner, credential, port=port)


class MCPMount:
    def __init__(self, host: Any) -> None:
        self.host = host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        app = getattr(self.host.state, "mcp_asgi", None)
        if app is None:
            await JSONResponse({"error": "mcp_not_ready"}, status_code=503)(
                scope, receive, send
            )
            return
        await app(scope, receive, send)
