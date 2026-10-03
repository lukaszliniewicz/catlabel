from __future__ import annotations

import copy
import unittest
from collections.abc import Callable
from types import SimpleNamespace

from PIL import Image

from catlabel.transport.bluetooth import SppBackend
from catlabel.vendors.generic.client import GenericClient
from catlabel.vendors.generic.manifest import GenericManifest


class _A41Backend(SppBackend):
    def __init__(self, firmware: bytes = b"1.26", *, bad_speed_ack: bool = False):
        super().__init__()
        self.firmware = firmware
        self.bad_speed_ack = bad_speed_ack
        self.queries: list[bytes] = []
        self.writes: list[bytes] = []

    def can_query_control_packet(self) -> bool:
        return True

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float = 1.0,
        reply_complete: Callable[[bytes], bool] | None = None,
    ) -> bytes | None:
        self.queries.append(packet)
        if packet == b"\x10\xff\x20\xf1":
            return self.firmware
        if packet[:3] == b"\x10\xff\xc0" and self.bad_speed_ack:
            return b"NO"
        return b"\x00" if packet == b"\x10\xff\x40" else b"OK"

    async def write(
        self,
        data: bytes,
        chunk_size: int,
        delay_ms: int = 0,
        interval_ms: int | None = None,
    ) -> None:
        self.writes.append(data)

    async def attach_runtime_controller(
        self, runtime_controller: object, *, timeout: float = 1.0
    ) -> None:
        pass


def _client(
    *,
    name: str = "LuckP_A41_1234",
    density: int | None = None,
    speed: int | None = None,
) -> GenericClient:
    hardware = GenericManifest().identify_device(name)
    assert hardware is not None
    return GenericClient(
        SimpleNamespace(name=name, address="00:11:22:33:44:55"),
        hardware,
        SimpleNamespace(paper_mode=None, speed=speed, energy=density, feed_lines=0),
        SimpleNamespace(speed=99, energy=5000, feed_lines=50),
    )


class A41PublicClientTests(unittest.IsolatedAsyncioTestCase):
    async def _print(self, client: GenericClient, backend: _A41Backend) -> None:
        client.backend = backend
        with Image.new("RGB", (8, 1), "white") as source:
            await client.print_images([source], dither=False)
            self.assertEqual(source.getpixel((0, 0)), (255, 255, 255))

    async def test_defaults_and_overrides_use_live_range_without_catalog_mutation(self):
        for firmware, density, speed, expected_density, expected_speed in (
            (b"1.25", None, None, 1, None),
            (b"1.26", None, None, 8, 4),
            (b"1.26", 14, 9, 14, 8),
            (b"1.26", 99, -3, 15, 0),
            (b"1.26", 0, 0, 1, 4),
            (b"1.25", 0, 9, 0, None),
            (b"1.25", 14, None, 2, None),
            (b"garbage", None, None, 1, None),
        ):
            with self.subTest(firmware=firmware, density=density, speed=speed):
                client = _client(density=density, speed=speed)
                before = copy.deepcopy(client.hardware_info)
                before_profile = vars(client.printer_profile).copy()
                before_settings = vars(client.settings).copy()
                backend = _A41Backend(firmware)
                await self._print(client, backend)
                self.assertEqual(backend.queries[0], b"\x10\xff\x20\xf1")
                self.assertIn(
                    b"\x10\xff\x10\x00" + bytes((expected_density,)),
                    backend.queries,
                )
                speed_packets = [p for p in backend.queries if p[:3] == b"\x10\xff\xc0"]
                self.assertEqual(
                    speed_packets,
                    []
                    if expected_speed is None
                    else [b"\x10\xff\xc0" + bytes((expected_speed,))],
                )
                self.assertTrue(backend.writes)
                self.assertEqual(client.hardware_info, before)
                self.assertEqual(vars(client.printer_profile), before_profile)
                self.assertEqual(vars(client.settings), before_settings)

    async def test_repeated_print_does_not_reuse_modern_firmware_range(self):
        client = _client()
        backend = _A41Backend()
        await self._print(client, backend)
        backend.firmware = b"1.25"
        backend.queries.clear()
        await self._print(client, backend)
        self.assertIn(b"\x10\xff\x10\x00\x01", backend.queries)
        self.assertFalse(any(p[:3] == b"\x10\xff\xc0" for p in backend.queries))

    async def test_bad_speed_ack_stops_before_raster_and_never_retries(self):
        client = _client()
        backend = _A41Backend(bad_speed_ack=True)
        with self.assertRaises(RuntimeError):
            await self._print(client, backend)
        self.assertFalse(backend.writes)
        self.assertEqual(backend.queries.count(b"\x10\xff\xc0\x04"), 1)
        self.assertNotIn(b"\x10\xff\x40", backend.queries)

    async def test_similar_names_do_not_get_firmware_policy(self):
        for name in ("APA41_123", "LuckP_A42_1234"):
            with self.subTest(name=name):
                client = _client(name=name)
                backend = _A41Backend()
                await self._print(client, backend)
                self.assertNotIn(b"\x10\xff\x20\xf1", backend.queries)
                self.assertFalse(any(p[:3] == b"\x10\xff\xc0" for p in backend.queries))
