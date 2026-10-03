"""Private OpenCode configuration and redacted local readiness checks."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from importlib.metadata import version
from pathlib import Path

from ..core.paths import DATA_DIRECTORY
from .auth import credential_path, load_credential


def write_private_file(path: Path, payload: bytes) -> None:
    """Create a secret-bearing file privately; repeated identical writes are harmless."""
    if path.is_symlink():
        raise RuntimeError("Refusing a symlink as a private configuration file.")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != payload:
            raise RuntimeError(
                "Private configuration already exists with different content; choose another output."
            ) from None
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise RuntimeError(
                "Private configuration permissions must be owner-only (chmod 600)."
            ) from None
        return
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def opencode_config(port: int, token_file: Path) -> dict[str, object]:
    return {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "servers": {
                "catlabel": {
                    "type": "remote",
                    "url": f"http://127.0.0.1:{port}/mcp/",
                    "oauth": False,
                    "protocol": "auto",
                    "codemode": False,
                    "headers": {
                        "Authorization": "Bearer {file:"
                        + str(token_file.resolve())
                        + "}"
                    },
                }
            }
        },
    }


async def doctor(port: int) -> dict[str, object]:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from playwright.async_api import async_playwright

    credential = load_credential(credential_path(DATA_DIRECTORY))
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch(headless=True)
        await browser.close()
    async with (
        httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {credential.token}"}
        ) as http,
        Client(
            streamable_http_client(f"http://127.0.0.1:{port}/mcp/", http_client=http),
            mode="auto",
        ) as client,
    ):
        result = await client.call_tool("catlabel_server_info", {})
        if result.is_error:
            raise RuntimeError("MCP readiness tool failed.")
        return {
            "sdk": version("mcp"),
            "protocol": client.protocol_version,
            "chromium": "launched",
            "credential": "private file loaded",
            "server": result.structured_content,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["config", "doctor"])
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("CATLABEL_PORT", "8000"))
    )
    parser.add_argument(
        "--output", type=Path, default=DATA_DIRECTORY / "mcp-opencode.json"
    )
    arguments = parser.parse_args()
    if not 1 <= arguments.port <= 65535:
        parser.error("Port must be 1..65535.")
    if arguments.command == "doctor":
        print(json.dumps(asyncio.run(doctor(arguments.port)), indent=2))
        return
    credential = load_credential(credential_path(DATA_DIRECTORY), create=True)
    token_file = DATA_DIRECTORY / "mcp-token.txt"
    write_private_file(token_file, credential.token.encode("ascii"))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(opencode_config(arguments.port, token_file), indent=2) + "\n"
    write_private_file(arguments.output, payload.encode("utf-8"))
    print(
        f"OpenCode v2 configuration written to {arguments.output}. Credential values are not printed."
    )


if __name__ == "__main__":
    main()
