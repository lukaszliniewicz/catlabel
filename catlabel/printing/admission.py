"""Single-process admission control for printer jobs."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from threading import Lock

_COLON_MAC_PATTERN = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\Z")
_HYPHEN_MAC_PATTERN = re.compile(r"(?:[0-9a-f]{2}-){5}[0-9a-f]{2}\Z")
_COMPACT_MAC_PATTERN = re.compile(r"[0-9a-f]{12}\Z")


def canonical_device_address(address: str) -> str:
    """Normalize MAC spellings while retaining opaque platform identifiers."""
    normalized = address.strip().casefold()
    if not normalized:
        raise ValueError("device address must not be empty")

    if _COLON_MAC_PATTERN.fullmatch(normalized) or _HYPHEN_MAC_PATTERN.fullmatch(
        normalized
    ):
        return normalized.replace(":", "").replace("-", "")
    if _COMPACT_MAC_PATTERN.fullmatch(normalized):
        return normalized
    return normalized


class DeviceBusyError(RuntimeError):
    """Raised when another job already owns a printer address."""

    def __init__(self, address: str) -> None:
        self.address = address
        super().__init__(f"Printer {address!r} is already claimed")


class DeviceAdmission:
    """Track active device claims in this process without queuing contenders."""

    def __init__(self) -> None:
        self._claimed_addresses: set[str] = set()
        self._lock = Lock()

    @asynccontextmanager
    async def claim(self, address: str) -> AsyncGenerator[str, None]:
        """Claim an address until the async context exits or is cancelled."""
        normalized = canonical_device_address(address)
        with self._lock:
            if normalized in self._claimed_addresses:
                raise DeviceBusyError(normalized)
            self._claimed_addresses.add(normalized)

        try:
            yield normalized
        finally:
            with self._lock:
                self._claimed_addresses.remove(normalized)


printer_admission = DeviceAdmission()
