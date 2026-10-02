from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from catlabel.transport.bluetooth.adapters import windows_winrt
from catlabel.transport.bluetooth.types import DeviceTransport


class _FakeRfcommServiceId:
    @staticmethod
    def from_uuid(value: object) -> object:
        return ("service-id", value)


class _FakeRfcommDeviceService:
    selector_service_id: object
    services_by_id: dict[str, object]

    @staticmethod
    def get_device_selector(service_id: object) -> str:
        _FakeRfcommDeviceService.selector_service_id = service_id
        return "fake-rfcomm-selector"

    @staticmethod
    async def from_id_async(device_id: str) -> object:
        return _FakeRfcommDeviceService.services_by_id[device_id]


class _FakeDeviceInformation:
    selector_call: tuple[str, list[str]] | None = None
    infos: list[object] = []

    @staticmethod
    async def find_all_async(
        selector: str,
        additional_properties: list[str],
    ) -> list[object]:
        _FakeDeviceInformation.selector_call = (selector, additional_properties)
        return _FakeDeviceInformation.infos


class WindowsSdkContractTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(sys.platform == "win32", "requires the native Windows SDK")
    async def test_native_sdk_imports_are_available(self) -> None:
        sdk_classes = windows_winrt._winrt_imports()
        self.assertEqual(len(sdk_classes), 6)
        self.assertTrue(all(isinstance(value, type) for value in sdk_classes))

    async def test_scan_uses_documented_filter_and_empty_properties_overload(
        self,
    ) -> None:
        info = SimpleNamespace(
            id="device-id",
            name="Fallback name",
            pairing=SimpleNamespace(is_paired=True),
        )
        _FakeDeviceInformation.infos = [info]
        _FakeRfcommDeviceService.services_by_id = {
            "device-id": SimpleNamespace(
                device=SimpleNamespace(
                    name="Device name",
                    bluetooth_address=0xAABBCCDDEEFF,
                )
            )
        }
        fake_sdk = (
            _FakeDeviceInformation,
            object,
            _FakeRfcommDeviceService,
            _FakeRfcommServiceId,
            object,
            object,
        )

        with patch.object(windows_winrt, "_winrt_imports", return_value=fake_sdk):
            devices, service_ids = await windows_winrt._scan_winrt_async(timeout=0)

        self.assertEqual(
            _FakeDeviceInformation.selector_call,
            ("fake-rfcomm-selector", []),
        )
        self.assertEqual(
            _FakeRfcommDeviceService.selector_service_id,
            ("service-id", windows_winrt.SPP_UUID),
        )
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].name, "Device name")
        self.assertEqual(devices[0].address, "AA:BB:CC:DD:EE:FF")
        self.assertIs(devices[0].transport, DeviceTransport.CLASSIC)
        self.assertEqual(service_ids, {"AA:BB:CC:DD:EE:FF": "device-id"})

    async def test_null_service_device_is_skipped_without_hiding_valid_device(
        self,
    ) -> None:
        _FakeDeviceInformation.infos = [
            SimpleNamespace(
                id="no-device",
                name="Unavailable device",
                pairing=None,
            ),
            SimpleNamespace(
                id="valid-device",
                name="Fallback name",
                pairing=SimpleNamespace(is_paired=False),
            ),
        ]
        _FakeRfcommDeviceService.services_by_id = {
            "no-device": SimpleNamespace(device=None),
            "valid-device": SimpleNamespace(
                device=SimpleNamespace(name="Valid device", bluetooth_address=1)
            ),
        }
        fake_sdk = (
            _FakeDeviceInformation,
            object,
            _FakeRfcommDeviceService,
            _FakeRfcommServiceId,
            object,
            object,
        )

        with patch.object(windows_winrt, "_winrt_imports", return_value=fake_sdk):
            devices, service_ids = await windows_winrt._scan_winrt_async(timeout=0)

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].name, "Valid device")
        self.assertEqual(devices[0].address, "00:00:00:00:00:01")
        self.assertEqual(service_ids, {"00:00:00:00:00:01": "valid-device"})


if __name__ == "__main__":
    unittest.main()
