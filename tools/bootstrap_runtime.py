"""Identify and verify a Catlabel bootstrap environment."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

BOOTSTRAP_VERSION = "0.72.2"
ENVIRONMENTS = ("default", "headless", "ai", "ai-headless")
RUNTIME_MODULES = (
    "fastapi",
    "uvicorn",
    "sqlmodel",
    "PIL",
    "pypdfium2",
    "bleak",
    "serial",
    "crc8",
)
AI_MODULES = ("litellm", "google.cloud.aiplatform")
PLATFORM_MODULES = {
    "win32": (
        "winsdk.windows.devices.bluetooth",
        "winsdk.windows.devices.enumeration",
    ),
    "darwin": ("IOBluetooth",),
}


def _validate_environment(environment: str) -> None:
    if environment not in ENVIRONMENTS:
        raise ValueError(f"unsupported environment: {environment!r}")


def environment_identity(root: Path, environment: str) -> str:
    """Return the content identity for the selected managed environment."""
    _validate_environment(environment)
    pixi_hash = hashlib.sha256((root / "pixi.toml").read_bytes()).hexdigest()
    lock_hash = hashlib.sha256((root / "pixi.lock").read_bytes()).hexdigest()
    canonical = (
        f"catlabel-bootstrap-v1\n{BOOTSTRAP_VERSION}\n{environment}\n"
        f"{pixi_hash}\n{lock_hash}\n"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_runtime(environment: str) -> None:
    """Check the Python version and required imports without starting the app."""
    _validate_environment(environment)
    version = sys.version_info
    if version[:2] != (3, 11):
        raise RuntimeError(f"Python 3.11 is required; found {version[0]}.{version[1]}")

    for module_name in RUNTIME_MODULES:
        importlib.import_module(module_name)

    for module_name in PLATFORM_MODULES.get(sys.platform, ()):
        importlib.import_module(module_name)

    if environment in ("ai", "ai-headless"):
        for module_name in AI_MODULES:
            importlib.import_module(module_name)

    if environment in ("headless", "ai-headless"):
        playwright = importlib.import_module("playwright.sync_api")
        with playwright.sync_playwright() as playwright_runtime:
            executable = Path(playwright_runtime.chromium.executable_path)
            if not executable.is_file():
                raise RuntimeError(
                    f"Playwright Chromium executable is missing: {executable}"
                )


def _publish_stamp(stamp: Path, identity: str) -> None:
    stamp.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="ascii",
            newline="\n",
            dir=stamp.parent,
            prefix=f".{stamp.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(identity + "\n")
            temporary_file.flush()
        os.replace(temporary_path, stamp)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    parser.add_argument("--stamp", type=Path)
    arguments = parser.parse_args(argv)

    identity = environment_identity(arguments.root, arguments.environment)
    verify_runtime(arguments.environment)
    if arguments.stamp is not None:
        _publish_stamp(arguments.stamp, identity)


if __name__ == "__main__":
    main()
