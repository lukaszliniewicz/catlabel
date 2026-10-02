from __future__ import annotations

from .... import reporting
from ....devices import BleTransportProfile
from ..types import DeviceInfo, SocketLike
from .base import _ClassicBluetoothAdapter
from .macos_iobluetooth import _MacClassicBackend


class _MacClassicAdapter(_ClassicBluetoothAdapter):
    def __init__(self) -> None:
        self._backend = _MacClassicBackend()

    def scan_blocking(self, timeout: float) -> list[DeviceInfo]:
        return DeviceInfo.dedupe(self._backend.scan_inquiry(timeout))

    def create_socket(
        self,
        pairing_hint: bool | None = None,
        ble_profile: BleTransportProfile | None = None,
        reporter: reporting.Reporter = reporting.DUMMY_REPORTER,
    ) -> SocketLike:
        _ = ble_profile
        return self._backend.create_socket()

    def resolve_rfcomm_channels(self, address: str) -> list[int]:
        return self._backend.resolve_rfcomm_channels(address)

    def ensure_paired(self, address: str, pairing_hint: bool | None = None) -> None:
        self._backend.pair_device(address)
