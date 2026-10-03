"""Local MCP credentials and authentication at the ASGI boundary."""

from __future__ import annotations

import json
import os
import secrets
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True)
class Credential:
    principal: str
    token: str


def credential_path(data_directory: Path) -> Path:
    return data_directory / "mcp-credential.json"


def load_credential(path: Path, *, create: bool = False) -> Credential:
    if create and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"principal": uuid.uuid4().hex, "token": secrets.token_urlsafe(48)}
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream)
                stream.flush()
                os.fsync(stream.fileno())
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("MCP credential is missing or not a regular private file.")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise RuntimeError("MCP credential permissions must be owner-only (chmod 600).")
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("Invalid MCP credential file.")
    value = cast(dict[str, object], raw)
    if (
        not isinstance(value.get("principal"), str)
        or not isinstance(value.get("token"), str)
        or len(cast(str, value["token"])) < 32
    ):
        raise RuntimeError("Invalid MCP credential file.")
    return Credential(
        principal=cast(str, value["principal"]), token=cast(str, value["token"])
    )


class MCPAuthentication:
    def __init__(self, app: ASGIApp, credential: Credential, *, port: int) -> None:
        self.app = app
        self.credential = credential
        self.authorities = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        self.origins = {f"http://{authority}" for authority in self.authorities}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = [(k.lower(), v) for k, v in scope.get("headers", [])]

        def values(key: bytes) -> list[str]:
            return [v.decode("latin-1") for k, v in headers if k == key]

        hosts = values(b"host")
        origins = values(b"origin")
        authorization = values(b"authorization")
        status, code = 200, ""
        if len(hosts) != 1 or hosts[0] not in self.authorities:
            status, code = 421, "untrusted_host"
        elif origins and (len(origins) != 1 or origins[0] not in self.origins):
            status, code = 403, "untrusted_origin"
        elif len(authorization) != 1 or not secrets.compare_digest(
            authorization[0], f"Bearer {self.credential.token}"
        ):
            status, code = 401, "authentication_required"
        if status != 200:
            await JSONResponse({"error": code}, status_code=status)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)
