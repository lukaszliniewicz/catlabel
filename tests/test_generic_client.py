from __future__ import annotations

import unittest
from collections.abc import Mapping
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from catlabel.printing.runtime.v5g import V5GRuntimeController
from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.packet import (
    prefixed_packet_opcode,
    prefixed_packet_payload,
    split_prefixed_packets,
)
from catlabel.transport.bluetooth import SppBackend
from catlabel.transport.bluetooth.types import DeviceInfo, DeviceTransport
from catlabel.vendors.generic.client import GenericClient
from catlabel.vendors.generic.manifest import GenericManifest


def _hardware_width(hardware: Mapping[str, object]) -> int:
    width = hardware.get("width_px")
    if not isinstance(width, int) or isinstance(width, bool):
        raise AssertionError("generic fixture must provide an integer width_px")
    return width


class _Backend(SppBackend):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[tuple[bytes, object | None]] = []
        self.attached: list[object] = []
        self.attempts: list[tuple[DeviceInfo, ...]] = []

    async def connect_attempts(
        self, attempts: list[DeviceInfo], pairing_hint: bool | None = None
    ) -> None:
        self.attempts.append(tuple(attempts))

    async def write(
        self,
        data: bytes,
        chunk_size: int,
        delay_ms: int = 0,
        interval_ms: int | None = None,
    ) -> None:
        self.writes.append((data, None))

    async def attach_runtime_controller(
        self, runtime_controller: object, *, timeout: float = 1.0
    ) -> None:
        self.attached.append(runtime_controller)


class GenericClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_interactive_families_only_attempt_capable_transport(self) -> None:
        profile = SimpleNamespace(
            speed=None, energy=None, feed_lines=0, paper_mode=None
        )
        settings = SimpleNamespace(speed=0, energy=0, feed_lines=0)
        cases = (
            ("LX-D01", (DeviceTransport.BLE,)),
            ("PPA2L_1234", (DeviceTransport.CLASSIC,)),
        )
        for name, expected in cases:
            with self.subTest(name=name):
                device = SimpleNamespace(name=name, address="00:11:22:33:44:55")
                hardware = GenericManifest().identify_device(
                    name, device, device.address
                )
                self.assertIsNotNone(hardware)
                if hardware is None:
                    self.fail(f"{name} should resolve to generic hardware")
                client = GenericClient(device, hardware, profile, settings)
                backend = _Backend()
                client.backend = backend
                self.assertTrue(await client.connect())
                self.assertEqual(
                    tuple(attempt.transport for attempt in backend.attempts[0]),
                    expected,
                )

    async def test_client_prepares_one_runtime_and_sends_both_pages(self) -> None:
        device = SimpleNamespace(name="MX10", address="00:11:22:33:44:55")
        hardware = GenericManifest().identify_device(
            device.name, device, device.address
        )
        self.assertIsNotNone(hardware)
        if hardware is None:
            self.fail("MX10 should resolve to generic hardware")
        profile = SimpleNamespace(
            speed=None, energy=None, feed_lines=0, paper_mode=None
        )
        settings = SimpleNamespace(speed=0, energy=0, feed_lines=0)
        client = GenericClient(device, hardware, profile, settings)
        backend = _Backend()
        client.backend = backend
        image = Image.new("RGB", (_hardware_width(hardware), 1), "white")

        with patch(
            "catlabel.vendors.generic.client.asyncio.sleep",
            new=AsyncMock(),
        ):
            await client.print_images([image, image.copy()], dither=False)

        self.assertEqual(len(backend.writes), 2)
        self.assertTrue(all(runtime is None for _, runtime in backend.writes))
        self.assertIsInstance(
            client._runtime_context.runtime_controller, V5GRuntimeController
        )
        self.assertGreaterEqual(len(backend.attached), 1)
        self.assertTrue(
            all(
                controller is client._runtime_context.runtime_controller
                for controller in backend.attached
            )
        )

    async def test_v5g_raw_density_uses_high_energy_and_quality_together(self) -> None:
        device = SimpleNamespace(name="MX11", address="00:11:22:33:44:55")
        hardware = GenericManifest().identify_device(
            device.name, device, device.address
        )
        self.assertIsNotNone(hardware)
        if hardware is None:
            self.fail("MX11 should resolve to generic hardware")
        profile = SimpleNamespace(speed=None, energy=200, feed_lines=0, paper_mode=None)
        settings = SimpleNamespace(speed=0, energy=0, feed_lines=0)
        client = GenericClient(device, hardware, profile, settings)
        backend = _Backend()
        client.backend = backend
        image = Image.new("RGB", (_hardware_width(hardware), 1), "white")

        await client.print_images([image], dither=False)

        packets = split_prefixed_packets(backend.writes[0][0], ProtocolFamily.V5G)
        self.assertIsNotNone(packets)
        if packets is None:
            self.fail("V5G job should contain valid prefixed packets")
        by_opcode = {
            prefixed_packet_opcode(packet, ProtocolFamily.V5G): packet
            for packet in packets
        }
        self.assertEqual(
            prefixed_packet_payload(by_opcode[0xF2], ProtocolFamily.V5G),
            b"\x01\xc8",
        )
        self.assertEqual(
            prefixed_packet_payload(by_opcode[0xAF], ProtocolFamily.V5G),
            (15000).to_bytes(2, "little"),
        )
        self.assertEqual(
            prefixed_packet_payload(by_opcode[0xA4], ProtocolFamily.V5G),
            b"\x35",
        )

    async def test_v5g_auto_omits_density_when_model_has_no_profile(self) -> None:
        device = SimpleNamespace(name="MX02", address="00:11:22:33:44:55")
        hardware = GenericManifest().identify_device(
            device.name, device, device.address
        )
        self.assertIsNotNone(hardware)
        if hardware is None:
            self.fail("MX02 should resolve to generic hardware")
        profile = SimpleNamespace(speed=None, energy=0, feed_lines=0, paper_mode=None)
        settings = SimpleNamespace(speed=0, energy=0, feed_lines=0)
        client = GenericClient(device, hardware, profile, settings)
        backend = _Backend()
        client.backend = backend
        image = Image.new("RGB", (_hardware_width(hardware), 1), "white")

        await client.print_images([image], dither=False)

        packets = split_prefixed_packets(backend.writes[0][0], ProtocolFamily.V5G)
        self.assertIsNotNone(packets)
        if packets is None:
            self.fail("V5G job should contain valid prefixed packets")
        self.assertNotIn(
            0xF2,
            [prefixed_packet_opcode(packet, ProtocolFamily.V5G) for packet in packets],
        )


if __name__ == "__main__":
    unittest.main()
