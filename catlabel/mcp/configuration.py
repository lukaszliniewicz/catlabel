"""Private OpenCode configuration files for the local MCP connection."""

from __future__ import annotations

import json
import os
from pathlib import Path

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


def generate_connection_files(data_directory: Path, port: int) -> Path:
    """Create the immutable, port-specific MCP client config and return its path."""
    if not 1 <= port <= 65535:
        raise ValueError("Port must be 1..65535.")

    credential = load_credential(credential_path(data_directory), create=True)
    token_file = data_directory / "mcp-token.txt"
    write_private_file(token_file, credential.token.encode("ascii"))

    config_path = data_directory / f"mcp-opencode-{port}.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(opencode_config(port, token_file), indent=2) + "\n"
    write_private_file(config_path, payload.encode("utf-8"))
    return config_path
