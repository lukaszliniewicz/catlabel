"""Pure ASGI request-body ceiling for API endpoints."""

from __future__ import annotations

from collections import deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..core.resource_limits import MAX_REQUEST_BYTES


class RequestLimitsMiddleware:
    """Buffer bounded API request bodies before invoking their handlers."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (
            path == "/api"
            or path.startswith("/api/")
            or path == "/mcp"
            or path.startswith("/mcp/")
        ):
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == b"content-length"
        ]
        if len(content_lengths) > 1:
            await _send_error(send, 400, "Invalid Content-Length.")
            return
        if content_lengths:
            content_length = content_lengths[0]
            if not content_length or not content_length.isdigit():
                await _send_error(send, 400, "Invalid Content-Length.")
                return
            normalized_length = content_length.lstrip(b"0") or b"0"
            maximum_length = str(self.max_bytes).encode("ascii")
            if len(normalized_length) > len(maximum_length) or (
                len(normalized_length) == len(maximum_length)
                and normalized_length > maximum_length
            ):
                await _send_error(send, 413, "Request body is too large.")
                return

        buffered: deque[Message] = deque()
        total_bytes = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] == "http.request":
                body = message.get("body", b"")
                if not isinstance(body, bytes):
                    raise TypeError("ASGI http.request body must be bytes.")
                total_bytes += len(body)
                if total_bytes > self.max_bytes:
                    await _send_error(send, 413, "Request body is too large.")
                    return
            buffered.append(message)
            if message["type"] == "http.request" and not message.get(
                "more_body", False
            ):
                break

        async def replay_receive() -> Message:
            if buffered:
                return buffered.popleft()
            return await receive()

        await self.app(scope, replay_receive, send)


async def _send_error(send: Send, status_code: int, detail: str) -> None:
    body = ('{"detail":"' + detail + '"}').encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})
