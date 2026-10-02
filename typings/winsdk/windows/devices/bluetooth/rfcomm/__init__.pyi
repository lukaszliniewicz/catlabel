from __future__ import annotations

from collections.abc import Awaitable
from uuid import UUID

from ....networking import HostName
from .. import BluetoothDevice

class RfcommServiceId:
    @staticmethod
    def from_uuid(value: UUID, /) -> RfcommServiceId | None: ...

class RfcommDeviceService:
    connection_host_name: HostName | None
    connection_service_name: str
    device: BluetoothDevice | None

    @staticmethod
    def from_id_async(device_id: str, /) -> Awaitable[RfcommDeviceService]: ...
    @staticmethod
    def get_device_selector(service_id: RfcommServiceId | None, /) -> str: ...
