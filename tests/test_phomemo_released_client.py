from __future__ import annotations

import asyncio
import hashlib
import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

import catlabel.vendors.phomemo.client as phomemo_client_module
from catlabel.core.resource_limits import (
    MAX_DIMENSION,
    MAX_PRINT_JOBS,
    ResourceLimitError,
)
from catlabel.devices import get_ble_transport_profile
from catlabel.printing.job_spool import ProtocolJobSpool
from catlabel.protocol.job import ProtocolJob
from catlabel.protocol.types import PaperMode
from catlabel.transport.bluetooth import DeviceInfo, DeviceTransport, SppBackend
from catlabel.vendors.phomemo.client import PhomemoClient


class _SizeOnlyImage:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.copy = Mock(side_effect=AssertionError("unexpected image copy"))
        self.crop = Mock(side_effect=AssertionError("unexpected image crop"))
        self.resize = Mock(side_effect=AssertionError("unexpected image resize"))


class _CapturingConnectTransport(SppBackend):
    def __init__(self, failures: tuple[Exception, ...] = ()) -> None:
        super().__init__()
        self.failures = list(failures)
        self.attempt_batches: list[tuple[DeviceInfo, ...]] = []
        self.disconnect_count = 0

    async def connect_attempts(
        self,
        attempts: list[DeviceInfo],
        pairing_hint: bool | None = None,
    ) -> None:
        self.attempt_batches.append(tuple(attempts))
        if self.failures:
            raise self.failures.pop(0)

    async def disconnect(self) -> None:
        self.disconnect_count += 1


def _dimensions_only(width: int, height: int) -> tuple[Image.Image, _SizeOnlyImage]:
    image = _SizeOnlyImage(width, height)
    return cast(Image.Image, image), image


def _client(
    variant: str | None,
    *,
    width_px: int = 384,
    dpi: int = 203,
    paper_mode: str | None = None,
    energy: int | None = None,
    feed_lines: int | None = None,
    hardware: dict[str, object] | None = None,
    settings_energy: int = 5000,
    settings_feed: int | None = 41,
) -> PhomemoClient:
    hardware_info: dict[str, object] = {
        "protocol_family": "phomemo_m02",
        "width_px": width_px,
        "dpi": dpi,
    }
    if variant is not None:
        hardware_info["protocol_variant"] = variant
    if hardware is not None:
        hardware_info.update(hardware)
    return PhomemoClient(
        SimpleNamespace(address="AA:BB:CC:DD:EE:FF"),
        hardware_info,
        SimpleNamespace(
            paper_mode=paper_mode,
            energy=energy,
            feed_lines=feed_lines,
        ),
        SimpleNamespace(energy=settings_energy, feed_lines=settings_feed),
    )


def _black_dot_image(
    width: int, height: int, dots: tuple[tuple[int, int], ...]
) -> Image.Image:
    image = Image.new("L", (width, height), 255)
    for x, y in dots:
        image.putpixel((x, y), 0)
    return image


class PhomemoReleasedClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_released_connect_prefers_classic_then_ble_endpoint(self) -> None:
        device = SimpleNamespace(
            name="Phomemo M02",
            address="device-address",
            paired=True,
            classic_endpoint=SimpleNamespace(address="classic-address"),
            ble_endpoint=SimpleNamespace(address="ble-address"),
        )
        client = PhomemoClient(
            device,
            {"protocol_variant": "m02"},
            SimpleNamespace(paper_mode=None, energy=None, feed_lines=None),
            SimpleNamespace(energy=5000, feed_lines=41),
        )
        transport = _CapturingConnectTransport()
        client.transport = transport

        self.assertTrue(await client.connect())

        self.assertEqual(len(transport.attempt_batches), 1)
        classic, ble = transport.attempt_batches[0]
        self.assertEqual(
            (classic.transport, classic.address, classic.name, classic.paired),
            (
                DeviceTransport.CLASSIC,
                "classic-address",
                "Phomemo M02",
                True,
            ),
        )
        self.assertEqual(
            (ble.transport, ble.address, ble.name, ble.paired),
            (DeviceTransport.BLE, "ble-address", "Phomemo M02", True),
        )
        self.assertIsNone(classic.ble_profile)
        self.assertEqual(ble.ble_profile, get_ble_transport_profile("phomemo_esc"))

    async def test_released_connect_falls_back_to_device_address_for_both(self) -> None:
        device = SimpleNamespace(
            name="Phomemo M02S",
            address="shared-address",
            paired=False,
        )
        client = PhomemoClient(
            device,
            {"protocol_variant": "m02s"},
            SimpleNamespace(paper_mode=None, energy=None, feed_lines=None),
            SimpleNamespace(energy=0, feed_lines=None),
        )
        transport = _CapturingConnectTransport()
        client.transport = transport

        self.assertTrue(await client.connect())

        attempts = transport.attempt_batches[0]
        self.assertEqual(
            [(attempt.transport, attempt.address) for attempt in attempts],
            [
                (DeviceTransport.CLASSIC, "shared-address"),
                (DeviceTransport.BLE, "shared-address"),
            ],
        )

    async def test_legacy_connect_remains_ble_only(self) -> None:
        device = SimpleNamespace(
            name="Legacy Phomemo",
            address="device-address",
            paired=True,
            ble_endpoint=SimpleNamespace(address="ble-endpoint"),
        )
        client = PhomemoClient(
            device,
            {"protocol_family": "phomemo_m02"},
            SimpleNamespace(paper_mode=None, energy=None, feed_lines=None),
            SimpleNamespace(energy=0, feed_lines=None),
        )
        transport = _CapturingConnectTransport()
        client.transport = transport

        self.assertTrue(await client.connect())

        attempts = transport.attempt_batches[0]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].transport, DeviceTransport.BLE)
        self.assertEqual(attempts[0].address, "ble-endpoint")
        self.assertEqual(attempts[0].paired, True)
        self.assertEqual(
            attempts[0].ble_profile,
            get_ble_transport_profile("phomemo_esc"),
        )

    async def test_unknown_connect_variant_fails_before_transport_attempt(self) -> None:
        client = PhomemoClient(
            SimpleNamespace(address="device-address"),
            {"protocol_variant": "printmaster-only"},
            SimpleNamespace(paper_mode=None, energy=None, feed_lines=None),
            SimpleNamespace(energy=0, feed_lines=None),
        )
        transport = _CapturingConnectTransport()
        client.transport = transport

        with self.assertRaisesRegex(ValueError, "Unsupported Phomemo recipe variant"):
            await client.connect()

        self.assertEqual(transport.attempt_batches, [])
        self.assertEqual(transport.disconnect_count, 0)

    async def test_released_connect_retry_disconnects_then_succeeds(self) -> None:
        device = SimpleNamespace(
            name="Phomemo M02X",
            address="device-address",
            paired=None,
            classic_endpoint=SimpleNamespace(address="classic-address"),
            ble_endpoint=SimpleNamespace(address="ble-address"),
        )
        client = PhomemoClient(
            device,
            {"protocol_variant": "m02x"},
            SimpleNamespace(paper_mode=None, energy=None, feed_lines=None),
            SimpleNamespace(energy=0, feed_lines=None),
        )
        failure = OSError("first connection attempt failed")
        transport = _CapturingConnectTransport((failure,))
        client.transport = transport
        sleep = AsyncMock()

        with patch.object(phomemo_client_module.asyncio, "sleep", new=sleep):
            self.assertTrue(await client.connect())

        self.assertEqual(len(transport.attempt_batches), 2)
        self.assertEqual(transport.disconnect_count, 1)
        self.assertIs(client.last_error, failure)
        sleep.assert_awaited_once_with(1.5)
        self.assertEqual(
            [
                [(attempt.transport, attempt.address) for attempt in batch]
                for batch in transport.attempt_batches
            ],
            [
                [
                    (DeviceTransport.CLASSIC, "classic-address"),
                    (DeviceTransport.BLE, "ble-address"),
                ],
                [
                    (DeviceTransport.CLASSIC, "classic-address"),
                    (DeviceTransport.BLE, "ble-address"),
                ],
            ],
        )

    async def test_m02_public_print_emits_literal_released_page(self) -> None:
        client = _client("m02", hardware={"default_energy": 2})
        image = _black_dot_image(8, 2, ((0, 0), (1, 1)))
        send = AsyncMock()
        client._send = send

        try:
            await client.print_images([image], dither=False)
        finally:
            image.close()

        expected = bytes.fromhex(
            "1b401f1102021f1137641f110b1f1135001d76300002000200080004001b64021b6402"
        )
        send.assert_awaited_once_with(expected)

    async def test_m02s_tag_uses_native_pixels_and_released_padding(self) -> None:
        client = _client(
            "m02s",
            width_px=576,
            dpi=300,
            paper_mode="tag",
            hardware={"default_energy": 2},
        )
        image = _black_dot_image(8, 2, ((0, 0), (1, 1)))
        send = AsyncMock()
        client._send = send

        try:
            await client.print_images([image], dither=False)
        finally:
            image.close()

        call_args = send.await_args
        if call_args is None:
            self.fail("released page was not sent")
        payload = call_args.args[0]
        setup = bytes.fromhex("1b401f1102021f1137641f110b1f113500")
        self.assertEqual(payload[: len(setup)], setup)
        self.assertEqual(
            payload[len(setup) : len(setup) + 8], b"\x1dv0\x00J\x00\x02\x00"
        )
        row_width = 74
        first_row = b"\x08" + bytes(row_width - 1)
        second_row = b"\x04" + bytes(row_width - 1)
        self.assertEqual(
            payload,
            setup
            + bytes.fromhex("1d7630004a000200")
            + first_row
            + second_row
            + bytes.fromhex("1b64021b6402"),
        )

    async def test_split_mode_crops_left_aligned_strips_and_preserves_pixels(
        self,
    ) -> None:
        client = _client("m02", width_px=8)
        image = _black_dot_image(10, 1, ((0, 0), (7, 0), (8, 0), (9, 0)))
        send = AsyncMock()
        client._send = send

        original_copy = Image.Image.copy
        owned_images: list[Image.Image] = []
        segments: list[Image.Image] = []
        original_builder = PhomemoClient._build_released_job

        def track_copy(source: Image.Image) -> Image.Image:
            result = original_copy(source)
            if source.size == image.size:
                owned_images.append(result)
            return result

        def track_build(
            rendered_image: Image.Image,
            *,
            variant: str,
            paper_mode: PaperMode | None,
            density: int,
            feed_count: int,
            is_first_page: bool,
            is_last_page: bool,
            dither: bool,
        ) -> bytes:
            segments.append(rendered_image)
            return original_builder(
                rendered_image,
                variant=variant,
                paper_mode=paper_mode,
                density=density,
                feed_count=feed_count,
                is_first_page=is_first_page,
                is_last_page=is_last_page,
                dither=dither,
            )

        try:
            with (
                patch.object(Image.Image, "copy", new=track_copy),
                patch.object(client, "_build_released_job", side_effect=track_build),
            ):
                await client.print_images([image], split_mode=True, dither=False)
                self.assertEqual(image.getpixel((0, 0)), 0)
        finally:
            image.close()

        expected = bytes.fromhex(
            "1b401f1102021f1137641f110b1f113500"
            "1d7630000200010008101b6402"
            "1d763000010001000c1b64021b6402"
        )
        send.assert_awaited_once_with(expected)
        self.assertEqual(len(owned_images), 1)
        self.assertEqual(len(segments), 2)
        for owned in [*owned_images, *segments]:
            with self.assertRaises(ValueError):
                owned.getpixel((0, 0))

    async def test_released_large_pages_are_spooled_then_sent_in_bounded_chunks(
        self,
    ) -> None:
        client = _client("m02", width_px=4, feed_lines=41)
        image = _black_dot_image(10, 1, ((0, 0), (9, 0)))
        payloads = (
            b"A" * (64 * 1024 + 17),
            b"B" * (64 * 1024 + 31),
            b"C" * (64 * 1024 + 5),
        )
        build_flags: list[tuple[bool, bool]] = []
        sent_chunks: list[bytes] = []
        captured_spools: list[ProtocolJobSpool] = []
        real_spool = ProtocolJobSpool
        payload_index = 0

        def capture_spool() -> ProtocolJobSpool:
            spool = real_spool()
            captured_spools.append(spool)
            return spool

        def build_page(
            _segment: Image.Image,
            *,
            variant: str,
            paper_mode: PaperMode | None,
            density: int,
            feed_count: int,
            is_first_page: bool,
            is_last_page: bool,
            dither: bool,
        ) -> bytes:
            nonlocal payload_index
            self.assertEqual(variant, "m02")
            self.assertIsNone(paper_mode)
            self.assertEqual(density, 2)
            self.assertEqual(feed_count, 41)
            self.assertFalse(dither)
            build_flags.append((is_first_page, is_last_page))
            payload = payloads[payload_index]
            payload_index += 1
            return payload

        async def capture_send(data: bytes) -> None:
            self.assertEqual(len(build_flags), len(payloads))
            self.assertTrue(captured_spools)
            self.assertFalse(captured_spools[0]._file.closed)
            sent_chunks.append(data)

        client._send = capture_send
        try:
            with (
                patch.object(
                    phomemo_client_module,
                    "ProtocolJobSpool",
                    side_effect=capture_spool,
                ),
                patch.object(client, "_build_released_job", side_effect=build_page),
            ):
                await client.print_images([image], split_mode=True, dither=False)
        finally:
            image.close()

        expected = b"".join(payloads)
        self.assertEqual(build_flags, [(True, False), (False, False), (False, True)])
        self.assertEqual(
            [len(chunk) for chunk in sent_chunks], [65536, 65536, 65536, 53]
        )
        self.assertEqual(sent_chunks[0], payloads[0][:65536])
        self.assertEqual(sent_chunks[1], payloads[0][65536:] + payloads[1][:65519])
        self.assertEqual(sent_chunks[2], payloads[1][65519:] + payloads[2][:65488])
        self.assertEqual(sent_chunks[3], payloads[2][65488:])
        self.assertEqual(sum(map(len, sent_chunks)), len(expected))
        self.assertEqual(
            hashlib.sha256(b"".join(sent_chunks)).digest(),
            hashlib.sha256(expected).digest(),
        )
        self.assertEqual(len(captured_spools), 1)
        self.assertTrue(captured_spools[0]._file.closed)

    async def test_released_builder_failure_closes_spool_without_sending(self) -> None:
        client = _client("m02", width_px=8)
        image = _black_dot_image(10, 1, ((0, 0),))
        send = AsyncMock()
        client._send = send
        captured_spools: list[ProtocolJobSpool] = []
        real_spool = ProtocolJobSpool
        build_count = 0

        def capture_spool() -> ProtocolJobSpool:
            spool = real_spool()
            captured_spools.append(spool)
            return spool

        def fail_second_page(
            _segment: Image.Image,
            **_kwargs: object,
        ) -> bytes:
            nonlocal build_count
            build_count += 1
            if build_count == 2:
                raise RuntimeError("second page build failed")
            return b"first page"

        try:
            with (
                patch.object(
                    phomemo_client_module,
                    "ProtocolJobSpool",
                    side_effect=capture_spool,
                ),
                patch.object(
                    client,
                    "_build_released_job",
                    side_effect=fail_second_page,
                ),
                self.assertRaisesRegex(RuntimeError, "second page build failed"),
            ):
                await client.print_images([image], split_mode=True, dither=False)

            self.assertEqual(image.getpixel((0, 0)), 0)
        finally:
            image.close()

        send.assert_not_awaited()
        self.assertEqual(build_count, 2)
        self.assertEqual(len(captured_spools), 1)
        self.assertTrue(captured_spools[0]._file.closed)

    async def test_released_spool_append_failure_closes_spool_without_sending(
        self,
    ) -> None:
        client = _client("m02", width_px=8)
        image = _black_dot_image(10, 1, ((0, 0),))
        send = AsyncMock()
        client._send = send
        captured_spools: list[ProtocolJobSpool] = []
        real_spool = ProtocolJobSpool
        real_append = ProtocolJobSpool.append
        append_count = 0

        def capture_spool() -> ProtocolJobSpool:
            spool = real_spool()
            captured_spools.append(spool)
            return spool

        def fail_second_append(spool: ProtocolJobSpool, job: ProtocolJob) -> None:
            nonlocal append_count
            append_count += 1
            if append_count == 2:
                raise OSError("second page append failed")
            real_append(spool, job)

        try:
            with (
                patch.object(
                    phomemo_client_module,
                    "ProtocolJobSpool",
                    side_effect=capture_spool,
                ),
                patch.object(ProtocolJobSpool, "append", new=fail_second_append),
                self.assertRaisesRegex(OSError, "second page append failed"),
            ):
                await client.print_images([image], split_mode=True, dither=False)

            self.assertEqual(image.getpixel((0, 0)), 0)
        finally:
            image.close()

        send.assert_not_awaited()
        self.assertEqual(append_count, 2)
        self.assertEqual(len(captured_spools), 1)
        self.assertTrue(captured_spools[0]._file.closed)

    async def test_released_send_cancellation_closes_spool_and_preserves_source(
        self,
    ) -> None:
        client = _client("m02")
        image = _black_dot_image(8, 1, ((0, 0),))
        send_started = asyncio.Event()
        captured_spools: list[ProtocolJobSpool] = []
        real_spool = ProtocolJobSpool

        def capture_spool() -> ProtocolJobSpool:
            spool = real_spool()
            captured_spools.append(spool)
            return spool

        async def block_first_send(data: bytes) -> None:
            self.assertTrue(data)
            send_started.set()
            await asyncio.Event().wait()

        client._send = block_first_send
        task: asyncio.Task[None] | None = None
        try:
            with patch.object(
                phomemo_client_module,
                "ProtocolJobSpool",
                side_effect=capture_spool,
            ):
                task = asyncio.create_task(client.print_images([image], dither=False))
                await asyncio.wait_for(send_started.wait(), timeout=2)
                self.assertEqual(len(captured_spools), 1)
                self.assertFalse(captured_spools[0]._file.closed)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            self.assertTrue(captured_spools[0]._file.closed)
            self.assertEqual(image.getpixel((0, 0)), 0)
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            image.close()

    async def test_physical_job_limit_rejects_before_copy_or_send(self) -> None:
        client = _client("m02", width_px=1)
        image, dimensions_only = _dimensions_only(MAX_PRINT_JOBS + 1, 1)
        send = AsyncMock()
        client._send = send

        with (
            patch.object(
                phomemo_client_module,
                "image_to_raster",
                side_effect=AssertionError("unexpected raster conversion"),
            ),
            self.assertRaises(ResourceLimitError),
        ):
            await client.print_images([image], split_mode=True)

        dimensions_only.copy.assert_not_called()
        dimensions_only.crop.assert_not_called()
        dimensions_only.resize.assert_not_called()
        send.assert_not_awaited()

    async def test_cumulative_tag_padding_rejects_before_copy_or_send(self) -> None:
        client = _client("m02s", width_px=576, paper_mode="tag")
        images = [_dimensions_only(8, MAX_DIMENSION)[0] for _ in range(5)]
        dimensions_only = [cast(_SizeOnlyImage, image) for image in images]
        send = AsyncMock()
        client._send = send

        with (
            patch.object(
                phomemo_client_module,
                "image_to_raster",
                side_effect=AssertionError("unexpected raster conversion"),
            ),
            self.assertRaises(ResourceLimitError),
        ):
            await client.print_images(images)

        for image in dimensions_only:
            image.copy.assert_not_called()
            image.crop.assert_not_called()
            image.resize.assert_not_called()
        send.assert_not_awaited()

    async def test_m02x_profile_feed_zero_overrides_hardware_and_global_feed(
        self,
    ) -> None:
        client = _client(
            "m02x",
            paper_mode="plain",
            feed_lines=0,
            hardware={"default_energy": 4, "default_feed": 23},
            settings_feed=17,
        )
        image = _black_dot_image(8, 1, ((0, 0),))
        send = AsyncMock()
        client._send = send

        try:
            await client.print_images([image], dither=False)
        finally:
            image.close()

        send.assert_awaited_once_with(
            bytes.fromhex("1b401b61011f1102041d7630000100010080")
        )

    async def test_owned_images_close_when_recipe_fails_and_caller_stays_open(
        self,
    ) -> None:
        client = _client("m02", width_px=8)
        image = _black_dot_image(10, 1, ((0, 0),))
        send = AsyncMock()
        client._send = send

        original_copy = Image.Image.copy
        owned_images: list[Image.Image] = []
        segments: list[Image.Image] = []
        original_builder = PhomemoClient._build_released_job

        def track_copy(source: Image.Image) -> Image.Image:
            result = original_copy(source)
            if source.size == image.size:
                owned_images.append(result)
            return result

        def track_failed_build(
            rendered_image: Image.Image,
            *,
            variant: str,
            paper_mode: PaperMode | None,
            density: int,
            feed_count: int,
            is_first_page: bool,
            is_last_page: bool,
            dither: bool,
        ) -> bytes:
            segments.append(rendered_image)
            return original_builder(
                rendered_image,
                variant=variant,
                paper_mode=paper_mode,
                density=density,
                feed_count=feed_count,
                is_first_page=is_first_page,
                is_last_page=is_last_page,
                dither=dither,
            )

        try:
            with (
                patch.object(Image.Image, "copy", new=track_copy),
                patch.object(
                    client,
                    "_build_released_job",
                    side_effect=track_failed_build,
                ),
                patch.object(
                    phomemo_client_module,
                    "build_released_page",
                    side_effect=RuntimeError("simulated recipe failure"),
                ),
                self.assertRaisesRegex(RuntimeError, "simulated recipe failure"),
            ):
                await client.print_images([image], split_mode=True, dither=False)

            self.assertEqual(image.getpixel((0, 0)), 0)
        finally:
            image.close()

        self.assertEqual(len(owned_images), 1)
        self.assertEqual(len(segments), 1)
        for owned in [*owned_images, *segments]:
            with self.assertRaises(ValueError):
                owned.getpixel((0, 0))
        send.assert_not_awaited()

    async def test_head_scaled_copy_and_resize_close_after_success(self) -> None:
        client = _client("m02", width_px=8)
        image = _black_dot_image(10, 2, ((0, 0), (9, 1)))
        send = AsyncMock()
        client._send = send

        original_copy = Image.Image.copy
        original_resize = Image.Image.resize
        copied_images: list[Image.Image] = []
        resized_images: list[Image.Image] = []
        rendered_images: list[Image.Image] = []
        original_builder = PhomemoClient._build_released_job

        def track_copy(source: Image.Image) -> Image.Image:
            result = original_copy(source)
            if source.size == image.size:
                copied_images.append(result)
            return result

        def track_resize(
            source: Image.Image,
            size: tuple[int, int],
            resample: int = Image.Resampling.BICUBIC,
            box: tuple[float, float, float, float] | None = None,
            reducing_gap: float | None = None,
        ) -> Image.Image:
            result = original_resize(
                source,
                size,
                resample=resample,
                box=box,
                reducing_gap=reducing_gap,
            )
            if source.size == image.size:
                resized_images.append(result)
            return result

        def track_build(
            rendered_image: Image.Image,
            *,
            variant: str,
            paper_mode: PaperMode | None,
            density: int,
            feed_count: int,
            is_first_page: bool,
            is_last_page: bool,
            dither: bool,
        ) -> bytes:
            rendered_images.append(rendered_image)
            return original_builder(
                rendered_image,
                variant=variant,
                paper_mode=paper_mode,
                density=density,
                feed_count=feed_count,
                is_first_page=is_first_page,
                is_last_page=is_last_page,
                dither=dither,
            )

        try:
            with (
                patch.object(Image.Image, "copy", new=track_copy),
                patch.object(Image.Image, "resize", new=track_resize),
                patch.object(client, "_build_released_job", side_effect=track_build),
            ):
                await client.print_images([image], split_mode=False, dither=False)
                self.assertEqual(image.getpixel((0, 0)), 0)
        finally:
            image.close()

        send.assert_awaited_once()
        self.assertEqual(len(copied_images), 1)
        self.assertEqual(len(resized_images), 1)
        self.assertEqual(len(rendered_images), 1)
        self.assertEqual(rendered_images[0].size, (8, 2))
        for owned in [*copied_images, *resized_images, *rendered_images]:
            with self.assertRaises(ValueError):
                owned.getpixel((0, 0))

    async def test_unknown_variant_fails_before_copy_or_raster_conversion(self) -> None:
        client = _client("printmaster_variant")
        image, dimensions_only = _dimensions_only(8, 1)
        send = AsyncMock()
        client._send = send

        with (
            patch.object(
                phomemo_client_module,
                "image_to_raster",
                side_effect=AssertionError("unexpected raster conversion"),
            ),
            self.assertRaisesRegex(ValueError, "Unsupported Phomemo recipe variant"),
        ):
            await client.print_images([image])

        dimensions_only.copy.assert_not_called()
        send.assert_not_awaited()

    async def test_m02_pro_without_variant_retains_legacy_dpi_route(self) -> None:
        client = _client(None, width_px=624, dpi=300)
        image = _black_dot_image(100, 10, ())
        legacy_print = AsyncMock()
        client._print_m02 = legacy_print

        try:
            await client.print_images([image], dither=False)
        finally:
            image.close()

        legacy_print.assert_awaited_once()
        call_args = legacy_print.await_args
        if call_args is None:
            self.fail("legacy M02 print route was not called")
        working_image = call_args.args[0]
        self.assertEqual(working_image.size, (148, 15))
        working_image.close()


if __name__ == "__main__":
    unittest.main()
