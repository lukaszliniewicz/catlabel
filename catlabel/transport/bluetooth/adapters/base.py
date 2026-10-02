from __future__ import annotations

from .... import reporting
from ....devices import BleTransportProfile
from ..types import DeviceInfo, DeviceTransport, SocketLike


class _BaseBluetoothAdapter:
    transport: DeviceTransport

    def scan_blocking(self, timeout: float) -> list[DeviceInfo]:
        raise NotImplementedError

    def create_socket(
        self,
        pairing_hint: bool | None = None,
        ble_profile: BleTransportProfile | None = None,
        reporter: reporting.Reporter = reporting.DUMMY_REPORTER,
    ) -> SocketLike:
        raise NotImplementedError

    def resolve_rfcomm_channels(self, address: str) -> list[int]:
        return []

    def ensure_paired(self, address: str, pairing_hint: bool | None = None) -> None:
        return None


class _ClassicBluetoothAdapter(_BaseBluetoothAdapter):
    transport = DeviceTransport.CLASSIC


class _BleBluetoothAdapter(_BaseBluetoothAdapter):
    transport = DeviceTransport.BLE

    def resolve_rfcomm_channels(self, address: str) -> list[int]:
        return [1]
