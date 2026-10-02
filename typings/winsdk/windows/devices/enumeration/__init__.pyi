from __future__ import annotations

from collections.abc import Awaitable, Iterable, Sequence
from enum import IntEnum
from typing import overload

class DeviceClass(IntEnum):
    ALL = 0
    AUDIO_CAPTURE = 1
    AUDIO_RENDER = 2
    PORTABLE_STORAGE_DEVICE = 3
    VIDEO_CAPTURE = 4
    IMAGE_SCANNER = 5
    LOCATION = 6

class DeviceInformationKind(IntEnum):
    UNKNOWN = 0
    DEVICE_INTERFACE = 1
    DEVICE_CONTAINER = 2
    DEVICE = 3
    DEVICE_INTERFACE_CLASS = 4
    ASSOCIATION_ENDPOINT = 5
    ASSOCIATION_ENDPOINT_CONTAINER = 6
    ASSOCIATION_ENDPOINT_SERVICE = 7
    DEVICE_PANEL = 8

class DevicePairingResultStatus(IntEnum):
    PAIRED = 0
    ALREADY_PAIRED = 3

class DevicePairingResult:
    status: DevicePairingResultStatus

class DeviceInformationPairing:
    is_paired: bool

    def pair_async(self) -> Awaitable[DevicePairingResult]: ...

class DeviceInformation:
    id: str
    name: str
    pairing: DeviceInformationPairing | None

    @staticmethod
    def create_from_id_async(device_id: str, /) -> Awaitable[DeviceInformation]: ...
    @overload
    @staticmethod
    def find_all_async() -> Awaitable[Sequence[DeviceInformation]]: ...
    @overload
    @staticmethod
    def find_all_async(
        device_class: DeviceClass, /
    ) -> Awaitable[Sequence[DeviceInformation]]: ...
    @overload
    @staticmethod
    def find_all_async(
        aqs_filter: str,
        additional_properties: Iterable[str],
        /,
    ) -> Awaitable[Sequence[DeviceInformation]]: ...
    @overload
    @staticmethod
    def find_all_async(
        aqs_filter: str,
        additional_properties: Iterable[str],
        kind: DeviceInformationKind,
        /,
    ) -> Awaitable[Sequence[DeviceInformation]]: ...
