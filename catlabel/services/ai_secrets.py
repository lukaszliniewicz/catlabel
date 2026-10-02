"""Redaction for AI observability and client responses, never provider credentials."""

import json
import os
import re
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

REDACTED = "[REDACTED]"
_SECRET_FIELDS = {
    "apikey",
    "token",
    "accesstoken",
    "authorization",
    "privatekey",
    "clientsecret",
}


def secret_values(values: Iterable[str]) -> tuple[str, ...]:
    """Include credential JSON values and PEM body lines in free-text redaction."""
    secrets: set[str] = set()

    def collect(value: Any, sensitive: bool = False) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                collect(item, sensitive or _is_secret_field(str(key)))
        elif isinstance(value, list):
            for item in value:
                collect(item, sensitive)
        elif isinstance(value, str) and sensitive and value:
            secrets.add(value)
            secrets.update(
                line.strip()
                for line in value.splitlines()
                if line.strip() and not line.strip().startswith("-----")
            )

    for value in values:
        if not value:
            continue
        secrets.add(value)
        with suppress(TypeError, ValueError):
            collect(json.loads(value))
    return tuple(sorted(secrets, key=len, reverse=True))


def known_environment_secrets() -> tuple[str, ...]:
    """Collect credentials locally only for filtering logs and response data."""
    suffixes = ("_API_KEY", "_ACCESS_TOKEN", "_CLIENT_SECRET", "_PRIVATE_KEY", "_TOKEN")
    values = [
        value
        for name, value in os.environ.items()
        if name.endswith(suffixes) or name == "VERTEXAI_CREDENTIALS"
    ]
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        values.append(credentials_path)
        with suppress(OSError, UnicodeError, ValueError):
            path = Path(credentials_path)
            limit = 1024 * 1024
            if path.is_file() and path.stat().st_size <= limit:
                with path.open("rb") as stream:
                    content = stream.read(limit + 1)
                if len(content) <= limit:
                    decoded = content.decode("utf-8")
                    if isinstance(json.loads(decoded), (dict, list)):
                        values.append(decoded)
    return secret_values(values)


def _is_secret_field(key: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", key.lower()) in _SECRET_FIELDS


def redact_secrets(
    data: Any, secrets: Iterable[str] = (), *, redact_fields: bool = True
) -> Any:
    """Redact sensitive fields, encoded JSON and known secrets in free text."""
    known = tuple(value for value in secrets if value)

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: REDACTED
                if redact_fields and _is_secret_field(str(key))
                else walk(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed.startswith(("{", "[")):
                try:
                    parsed = json.loads(trimmed)
                except ValueError:
                    pass
                else:
                    if isinstance(parsed, (dict, list)):
                        sanitized = walk(parsed)
                        return json.dumps(sanitized) if sanitized != parsed else value
            for secret in known:
                value = value.replace(secret, REDACTED)
        return value

    return walk(data)
