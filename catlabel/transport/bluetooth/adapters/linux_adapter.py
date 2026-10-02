from __future__ import annotations

import socket

from .... import reporting
from ....devices import BleTransportProfile
from ..types import DeviceInfo, SocketLike
from .base import _ClassicBluetoothAdapter
from .linux_cmd import LinuxCommandTools


class _LinuxClassicAdapter(_ClassicBluetoothAdapter):
    def __init__(self) -> None:
        self._commands = LinuxCommandTools()

    def scan_blocking(self, timeout: float) -> list[DeviceInfo]:
        devices, _ = self._commands.scan_devices(timeout)
        return DeviceInfo.dedupe(devices)

    def create_socket(
        self,
        pairing_hint: bool | None = None,
        ble_profile: BleTransportProfile | None = None,
        reporter: reporting.Reporter = reporting.DUMMY_REPORTER,
    ) -> SocketLike:
        if not hasattr(socket, "AF_BLUETOOTH") or not hasattr(socket, "BTPROTO_RFCOMM"):
            raise RuntimeError(
                "RFCOMM sockets are not supported on this system. Use --serial or run on Linux."
            )
        _ = ble_profile
        return socket.socket(
            socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
        )

    def resolve_rfcomm_channels(self, address: str) -> list[int]:
        return self._commands.resolve_rfcomm_channels(address)

    def ensure_paired(self, address: str, pairing_hint: bool | None = None) -> None:
        self._commands.ensure_paired(address)
