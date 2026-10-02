from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .. import reporting
from ..transport.bluetooth.constants import IS_MACOS, IS_WINDOWS

_WARNED = False
_REQUIREMENTS_PATH = Path(__file__).resolve().parents[2] / "requirements.txt"
_IMPORT_NAMES = {
    "google-cloud-aiplatform": "google.cloud.aiplatform",
    "python-multipart": "multipart",
}


def emit_startup_warnings(reporter: reporting.Reporter | None = None) -> None:
    global _WARNED
    if _WARNED:
        return
    _WARNED = True
    if reporter is None:
        reporter = reporting.Reporter([reporting.StderrSink()])
    for message in collect_dependency_warnings():
        reporter.warning(
            reporting.WARNING_DEPENDENCY,
            short=reporting.summarize_detail(message),
            detail=message,
        )


def collect_dependency_warnings() -> list[str]:
    try:
        lines = _REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
        requirements = [
            requirement_line.split(";", 1)[0]
            .split("#", 1)[0]
            .split("[", 1)[0]
            .strip()
            .split("=", 1)[0]
            .split(">", 1)[0]
            .split("<", 1)[0]
            .lower()
            for requirement_line in (line.strip() for line in lines)
            if requirement_line
            and not requirement_line.startswith(("#", "-"))
            and (
                "sys_platform" not in requirement_line
                or (
                    "==" in requirement_line
                    and sys.platform
                    == requirement_line.split("==", 1)[1].split()[0].strip("'\"")
                )
                or (
                    "!=" in requirement_line
                    and sys.platform
                    != requirement_line.split("!=", 1)[1].split()[0].strip("'\"")
                )
            )
        ]
    except OSError:
        requirements = []
    warnings: list[str] = []
    for requirement in requirements:
        if requirement == "pillow":
            if not _has_module("PIL"):
                warnings.append(
                    "Missing Pillow (PIL). Image/text rendering will not work, and PDF raster output will fail."
                )
        elif requirement == "pypdfium2":
            if not _has_module("pypdfium2"):
                warnings.append("Missing pypdfium2. PDF rendering will not work.")
        elif requirement == "crc8":
            if not _has_module("crc8"):
                warnings.append(
                    "Missing crc8. Printer protocol encoding will not work."
                )
        elif requirement == "bleak":
            if not _has_module("bleak"):
                warnings.append("Missing bleak. BLE scanning/printing will not work.")
        elif requirement == "pyserial":
            if not _has_module("serial"):
                warnings.append(
                    "Missing pyserial. Serial printing via --serial will not work."
                )
        elif requirement == "winsdk":
            if IS_WINDOWS and not _has_module("winsdk"):
                warnings.append(
                    "Missing winsdk. Windows Bluetooth SPP scanning/connection will not work."
                )
        elif requirement == "pyobjc-framework-iobluetooth":
            if IS_MACOS and (not _has_module("objc") or not _has_module("IOBluetooth")):
                warnings.append(
                    "Missing pyobjc-framework-IOBluetooth. "
                    "macOS Classic Bluetooth SPP scanning/connection will not work."
                )
        elif not _has_module(_IMPORT_NAMES.get(requirement, requirement)):
            warnings.append(f"Missing dependency: {requirement}.")
    return warnings


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError):
        return False
