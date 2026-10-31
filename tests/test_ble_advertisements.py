from __future__ import annotations

import asyncio
import json
import sys
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import patch

from catlabel.services.printers import scan_result_payload
from catlabel.transport.bluetooth.adapters.bleak_adapter import _BleakBleAdapter
from catlabel.transport.bluetooth.types import DeviceInfo, DeviceTransport
from catlabel.vendors.generic.manifest import GenericManifest


class BleAdvertisementTests(unittest.TestCase):
    def test_detection_receives_advertisement_bytes_and_api_serializes_hex(
        self,
    ) -> None:
        device = DeviceInfo(
            "Evidence",
            "opaque-id",
            transport=DeviceTransport.BLE,
            manufacturer_data={0x1234: b"\x00\xff\x59"},
        )
        with patch(
            "catlabel.vendors.generic.manifest.PrinterModelRegistry.load"
        ) as load:
            load.return_value.detect_with_origin.return_value = None
            self.assertIsNone(
                GenericManifest().identify_device(device.name, device, device.address)
            )
            load.return_value.detect_with_origin.assert_called_once_with(
                "Evidence", "opaque-id", manufacturer_data={0x1234: b"\x00\xff\x59"}
            )
        registry = SimpleNamespace(
            identify_device=lambda *_args: {"vendor": "generic", "model_id": "known"}
        )
        result = scan_result_payload(device, vendor_registry=registry)
        self.assertEqual(result["manufacturer_data"], {"4660": "00ff59"})
        self.assertEqual(
            json.loads(json.dumps(result))["manufacturer_data"], {"4660": "00ff59"}
        )

    def scan(
        self, result: Any
    ) -> tuple[_BleakBleAdapter, list[DeviceInfo], list[tuple[float, bool]]]:
        calls: list[tuple[float, bool]] = []

        class Scanner:
            @staticmethod
            async def discover(*, timeout: float, return_adv: bool):
                calls.append((timeout, return_adv))
                return result

        module = ModuleType("bleak")
        module.__dict__["BleakScanner"] = Scanner
        adapter = _BleakBleAdapter()
        with asyncio.Runner(), patch.dict(sys.modules, {"bleak": module}):
            devices = adapter.scan_blocking(0.025)
        return adapter, devices, calls

    def test_scan_retains_advertised_name_manufacturer_bytes_and_actual_device_cache(
        self,
    ) -> None:
        device = SimpleNamespace(name="Cached name", address="AA:BB:CC:DD:EE:FF")
        payload = bytearray(b"\x00\xff\x01")
        data = {0x1234: payload}
        advertisement = SimpleNamespace(
            local_name="Advertised name", manufacturer_data=data
        )
        adapter, devices, calls = self.scan({device.address: (device, advertisement)})
        self.assertEqual(calls, [(0.025, True)])
        self.assertIs(adapter._device_cache[device.address], device)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].name, "Advertised name")
        self.assertEqual(devices[0].manufacturer_data, {0x1234: b"\x00\xff\x01"})
        manufacturer_data = devices[0].manufacturer_data
        assert manufacturer_data is not None
        self.assertIsInstance(manufacturer_data[0x1234], bytes)
        payload[0] = 9
        data.clear()
        self.assertEqual(devices[0].manufacturer_data, {0x1234: b"\x00\xff\x01"})

    def test_empty_observed_manufacturer_data_is_distinct_from_unavailable(
        self,
    ) -> None:
        device = SimpleNamespace(name="Fallback name", address="opaque-device-id")
        _, devices, _ = self.scan(
            {"key": (device, SimpleNamespace(local_name=None, manufacturer_data={}))}
        )
        self.assertEqual(devices[0].name, "Fallback name")
        self.assertEqual(devices[0].manufacturer_data, {})
        _, unavailable, _ = self.scan([device])
        self.assertIsNone(unavailable[0].manufacturer_data)
        self.assertEqual(unavailable[0].address, "opaque-device-id")
        self.assertEqual(unavailable[0].transport, DeviceTransport.BLE)

    def test_legacy_list_scan_preserves_device_objects_and_names_without_advertisement_evidence(
        self,
    ) -> None:
        device = SimpleNamespace(name="Legacy scanner", address="lower-case-address")
        adapter, devices, calls = self.scan([device])
        self.assertEqual(calls, [(0.025, True)])
        self.assertIs(adapter._device_cache[device.address.upper()], device)
        self.assertEqual(devices[0].name, device.name)
        self.assertIsNone(devices[0].manufacturer_data)

    def test_merge_retains_latest_observed_map_including_empty_map(self) -> None:
        original = DeviceInfo(
            "Device", "id", transport=DeviceTransport.BLE, manufacturer_data={1: b"old"}
        )
        latest = DeviceInfo(
            "Device", "id", transport=DeviceTransport.BLE, manufacturer_data={2: b"new"}
        )
        unavailable = DeviceInfo("Device", "id", transport=DeviceTransport.BLE)
        empty = DeviceInfo(
            "Device", "id", transport=DeviceTransport.BLE, manufacturer_data={}
        )
        self.assertEqual(original.merge(latest).manufacturer_data, {2: b"new"})
        self.assertEqual(original.merge(unavailable).manufacturer_data, {1: b"old"})
        self.assertEqual(original.merge(empty).manufacturer_data, {})
        self.assertEqual(
            DeviceInfo.dedupe([original, latest, unavailable])[0].manufacturer_data,
            {2: b"new"},
        )
        self.assertIsNone(DeviceInfo("Classic", "id").manufacturer_data)


if __name__ == "__main__":
    unittest.main()
