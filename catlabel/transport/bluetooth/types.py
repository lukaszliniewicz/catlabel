from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any

from ...devices import BleTransportProfile

SocketLike = Any


class DeviceTransport(StrEnum):
    CLASSIC = "classic"
    BLE = "ble"

    def __str__(self) -> str:
        return Enum.__str__(self)

    def __format__(self, format_spec: str) -> str:
        return Enum.__format__(self, format_spec)


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    address: str
    paired: bool | None = None
    transport: DeviceTransport = DeviceTransport.CLASSIC
    ble_profile: BleTransportProfile | None = None

    def merge(self, other: DeviceInfo) -> DeviceInfo:
        if self.address != other.address or self.transport != other.transport:
            raise ValueError(
                "Cannot merge devices with different addresses or transports"
            )
        if self.name and other.name:
            name = self.name if len(self.name) >= len(other.name) else other.name
        else:
            name = self.name or other.name
        if self.paired is True or other.paired is True:
            paired = True
        elif self.paired is False or other.paired is False:
            paired = False
        else:
            paired = None
        ble_profile = self.ble_profile or other.ble_profile
        return DeviceInfo(
            name=name,
            address=self.address,
            paired=paired,
            transport=self.transport,
            ble_profile=ble_profile,
        )

    @staticmethod
    def dedupe(devices: list[DeviceInfo]) -> list[DeviceInfo]:
        by_addr: dict[tuple[str, DeviceTransport], DeviceInfo] = {}
        for device in devices:
            key = (device.address, device.transport)
            existing = by_addr.get(key)
            if existing is None:
                by_addr[key] = device
            else:
                by_addr[key] = existing.merge(device)
        results = list(by_addr.values())
        results.sort(
            key=lambda item: (item.name or "", item.address, item.transport.value)
        )
        return results


@dataclass(frozen=True)
class ScanFailure:
    transport: DeviceTransport
    error: Exception
