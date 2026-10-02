"""Explicit binding and browser-origin policy for the single-process server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def normalized_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "*" in value
        or any(char.isspace() for char in value)
    ):
        raise ValueError(
            "Origins must be explicit HTTP(S) URLs without credentials or paths."
        )
    port = parsed.port
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port is not None and port != (443 if parsed.scheme == "https" else 80):
        host = f"{host}:{port}"
    return f"{parsed.scheme}://{host}"


@dataclass(frozen=True)
class ServerSecurity:
    host: str = "127.0.0.1"
    port: int = 8000
    access_token: str = ""
    allowed_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.host
            or self.host != self.host.strip()
            or any(char in self.host for char in "/@?#")
        ):
            raise ValueError("CATLABEL_HOST must be a host or bind address.")
        if not 1 <= self.port <= 65535:
            raise ValueError("CATLABEL_PORT must be between 1 and 65535.")
        if self.access_token and (
            len(self.access_token) < 32
            or any(not 33 <= ord(char) <= 126 for char in self.access_token)
        ):
            raise ValueError(
                "CATLABEL_ACCESS_TOKEN must contain at least 32 ASCII characters."
            )
        origins = tuple(
            dict.fromkeys(normalized_origin(value) for value in self.allowed_origins)
        )
        object.__setattr__(self, "allowed_origins", origins)
        if self.host.lower() not in LOOPBACK_HOSTS and (
            not self.access_token or not origins
        ):
            raise ValueError(
                "LAN binding requires CATLABEL_ACCESS_TOKEN and CATLABEL_ALLOWED_ORIGINS."
            )

    @classmethod
    def from_environment(cls) -> ServerSecurity:
        return cls(
            host=os.environ.get("CATLABEL_HOST", "127.0.0.1"),
            port=int(os.environ.get("CATLABEL_PORT", "8000")),
            access_token=os.environ.get("CATLABEL_ACCESS_TOKEN", ""),
            allowed_origins=tuple(
                value.strip()
                for value in os.environ.get("CATLABEL_ALLOWED_ORIGINS", "").split(",")
                if value.strip()
            ),
        )

    @property
    def browser_url(self) -> str:
        if self.host.lower() not in LOOPBACK_HOSTS:
            return self.allowed_origins[0]
        host = "[::1]" if self.host == "::1" else "localhost"
        return f"http://{host}:{self.port}"

    def permits_host(self, authority: str, scheme: str) -> bool:
        try:
            origin = normalized_origin(f"{scheme}://{authority}")
            hostname = urlsplit(origin).hostname
        except ValueError:
            return False
        if hostname in LOOPBACK_HOSTS:
            return True
        return origin in self.allowed_origins

    def permits_origin(self, origin: str, authority: str, scheme: str) -> bool:
        try:
            normalized = normalized_origin(origin)
            request_origin = normalized_origin(f"{scheme}://{authority}")
        except ValueError:
            return False
        return normalized == request_origin or normalized in self.allowed_origins
