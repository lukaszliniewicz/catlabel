"""Protect all API methods, private assets and explicitly enabled LAN access."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..core.server_security import ServerSecurity
from .auth_page import sign_in_page

CLIENT_HEADER = "x-catlabel-client"
SESSION_COOKIE = "catlabel_session"


class LocalSecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: ServerSecurity) -> None:
        self.app = app
        self.settings = settings
        self.session = hmac.new(
            secrets.token_bytes(32), settings.access_token.encode(), hashlib.sha256
        ).hexdigest()

    def _authorized(self, request: Request) -> bool:
        if not self.settings.access_token:
            return True
        bearer = request.headers.get("authorization", "")
        if bearer.startswith("Bearer ") and hmac.compare_digest(
            bearer[7:].encode(), self.settings.access_token.encode()
        ):
            return True
        return hmac.compare_digest(
            request.cookies.get(SESSION_COOKIE, "").encode(), self.session.encode()
        )

    async def _login(self, request: Request) -> Response:
        if not self.settings.access_token:
            return RedirectResponse("/", status_code=303)
        if request.method == "GET":
            return HTMLResponse(sign_in_page())
        if request.method != "POST":
            return JSONResponse({"detail": "Method not allowed."}, status_code=405)
        if (
            not request.headers.get("origin")
            and request.headers.get(CLIENT_HEADER) != "1"
        ):
            return JSONResponse(
                {"detail": "A same-origin sign-in is required."}, status_code=403
            )
        if (
            request.headers.get("content-type", "").split(";", 1)[0]
            != "application/x-www-form-urlencoded"
        ):
            return JSONResponse({"detail": "Invalid sign-in form."}, status_code=400)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 4096:
                return JSONResponse(
                    {"detail": "Sign-in form is too large."}, status_code=413
                )
            body.extend(chunk)
        try:
            fields = parse_qs(
                body.decode("utf-8"), strict_parsing=True, max_num_fields=2
            )
            tokens = fields.get("token", [])
            valid = (
                set(fields) == {"token"}
                and len(tokens) == 1
                and hmac.compare_digest(
                    tokens[0].encode(), self.settings.access_token.encode()
                )
            )
        except (UnicodeError, ValueError):
            valid = False
        if not valid:
            return HTMLResponse(
                sign_in_page("The access token is incorrect."), status_code=401
            )
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            self.session,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
        )
        return response

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        headers = Headers(scope=scope)
        authority = headers.get("host", "")
        origin = headers.get("origin")
        response: Response | None = None
        if len(headers.getlist("host")) != 1 or not self.settings.permits_host(
            authority, request.url.scheme
        ):
            response = JSONResponse(
                {"detail": "Untrusted request host."}, status_code=400
            )
        elif origin is not None and not self.settings.permits_origin(
            origin, authority, request.url.scheme
        ):
            response = JSONResponse(
                {"detail": "Untrusted request origin."}, status_code=403
            )
        elif (
            headers.get("sec-fetch-site") == "cross-site"
            and origin not in self.settings.allowed_origins
        ):
            response = JSONResponse(
                {"detail": "Cross-site requests are not allowed."}, status_code=403
            )
        elif request.url.path == "/auth/login":
            response = await self._login(request)
        elif request.method == "OPTIONS":
            pass  # Validated preflight; the inner CORS middleware handles it.
        elif not self._authorized(request):
            if (
                request.method == "GET"
                and request.url.path == "/"
                and "text/html" in headers.get("accept", "")
            ):
                response = HTMLResponse(sign_in_page(), status_code=401)
            else:
                response = JSONResponse(
                    {
                        "detail": "Sign in at the CatLabel home page or supply a Bearer access token."
                    },
                    status_code=401,
                )
        elif (
            request.url.path == "/api" or request.url.path.startswith("/api/")
        ) and headers.get(CLIENT_HEADER) != "1":
            response = JSONResponse(
                {"detail": "The X-CatLabel-Client: 1 header is required."},
                status_code=403,
            )

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-content-type-options", b"nosniff"))
                if (
                    request.url.path.startswith(("/api", "/auth"))
                    or response is not None
                ):
                    response_headers.append((b"cache-control", b"no-store"))
                if response is not None and response.headers.get(
                    "content-type", ""
                ).startswith("text/html"):
                    response_headers.append(
                        (
                            b"content-security-policy",
                            b"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
                        )
                    )
                    response_headers.append((b"referrer-policy", b"no-referrer"))
                message = {**message, "headers": response_headers}
            await send(message)

        if response is not None:
            await response(scope, receive, private_send)
        else:
            await self.app(scope, receive, private_send)
