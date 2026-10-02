"""Exercise candidate startup and exact health/frontend identity on disposable data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from catlabel.core.release_artifacts import (
    load_release_manifest,
    verify_artifact_directory,
)


def probe(
    root: Path,
    data_directory: Path,
    expected_identity: dict[str, str | int],
    *,
    deadline_seconds: float = 60.0,
) -> None:
    root = root.resolve()
    data_directory = data_directory.resolve()
    if root != Path(__file__).resolve().parents[1]:
        raise ValueError("Probe must run from the selected release runtime")
    manifest = load_release_manifest(root / "release-manifest.json")
    verify_artifact_directory(root, manifest)
    if expected_identity != {
        "release_id": manifest.release_id,
        "source_commit": manifest.source_commit,
        "frontend_sha256": manifest.frontend_sha256,
        "database_epoch": manifest.database_epoch,
    }:
        raise ValueError("Candidate manifest differs from selected artifact")
    # A private token prevents accepting an unrelated local server if port allocation races.
    with socket.socket() as allocation:
        allocation.bind(("127.0.0.1", 0))
        port = allocation.getsockname()[1]
    token = secrets.token_urlsafe(32)
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")
        if key in os.environ
    }
    environment.update(
        CATLABEL_DATA_DIR=str(data_directory),
        CATLABEL_HOST="127.0.0.1",
        CATLABEL_PORT=str(port),
        CATLABEL_ACCESS_TOKEN=token,
        CATLABEL_ACCEPTANCE_PROBE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHON_DOTENV_DISABLED="1",
        LITELLM_MODE="PROD",
        LITELLM_LOCAL_MODEL_COST_MAP="True",
        PLAYWRIGHT_BROWSERS_PATH="0",
    )
    data_directory.mkdir(parents=True, exist_ok=True)
    process: subprocess.Popen[bytes] | None = None
    deadline = time.monotonic() + deadline_seconds
    headers = {"X-CatLabel-Client": "1", "Authorization": f"Bearer {token}"}
    with (data_directory / "candidate-startup.log").open("wb") as log:
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "catlabel.api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                cwd=root,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            endpoint = f"http://127.0.0.1:{port}"
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Candidate exited before health acceptance")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Candidate health acceptance deadline exceeded")
                try:
                    request = urllib.request.Request(
                        endpoint + "/api/health", headers=headers
                    )
                    with urllib.request.urlopen(request, timeout=1) as response:
                        health = json.loads(response.read(16_384))
                    break
                except urllib.error.URLError:
                    time.sleep(0.1)
            if health != {"status": "ok", "release": expected_identity}:
                raise ValueError(
                    "Candidate health identity differs from selected artifact"
                )
            with urllib.request.urlopen(
                urllib.request.Request(endpoint + "/", headers=headers), timeout=5
            ) as response:
                index = response.read(2 * 1024 * 1024 + 1)
            if (
                hashlib.sha256(index).hexdigest()
                != manifest.files["frontend/dist/index.html"]
            ):
                raise ValueError("Served frontend differs from selected artifact")
            verify_artifact_directory(root, manifest)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    print(
        json.dumps(
            {
                "accepted": True,
                "release_id": manifest.release_id,
                "frontend_sha256": manifest.frontend_sha256,
                "scope": "Disposable database startup, health and served frontend identity; no provider or printer calls",
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--data-directory", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--frontend-sha256", required=True)
    arguments = parser.parse_args()
    probe(
        arguments.root,
        arguments.data_directory,
        {
            "release_id": arguments.release_id,
            "source_commit": arguments.source_commit,
            "frontend_sha256": arguments.frontend_sha256,
            "database_epoch": 1,
        },
    )


if __name__ == "__main__":
    main()
