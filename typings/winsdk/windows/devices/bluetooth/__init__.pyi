from __future__ import annotations

from collections.abc import Awaitable

from ..enumeration import DeviceInformation

class BluetoothDevice:
    bluetooth_address: int
    device_information: DeviceInformation | None
    name: str

    @staticmethod
    def from_bluetooth_address_async(address: int, /) -> Awaitable[BluetoothDevice]: ...
