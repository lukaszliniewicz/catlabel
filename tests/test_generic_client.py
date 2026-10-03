from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from catlabel.printing.job_spool import ProtocolJobSpool
from catlabel.printing.runtime.v5g import V5GRuntimeController
from catlabel.protocol.families.yk_common import iter_yk_frames
from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.job import ProtocolJob
from catlabel.protocol.packet import (
    prefixed_packet_opcode,
    prefixed_packet_payload,
    split_prefixed_packets,
)
from catlabel.rendering.paper_layout import PaperImageLayout, iter_prepared_paper_images
from catlabel.transport.bluetooth import SppBackend
from catlabel.transport.bluetooth.types import DeviceInfo, DeviceTransport
from catlabel.vendors.generic import client as generic_client_module
from catlabel.vendors.generic.client import GenericClient
from catlabel.vendors.generic.manifest import GenericManifest


def _hardware_width(hardware: Mapping[str, object]) -> int:
    width = hardware.get("width_px")
    if not isinstance(width, int) or isinstance(width, bool):
        raise AssertionError("generic fixture must provide an integer width_px")
    return width


class _TrackingSpool(ProtocolJobSpool):
    def __init__(self) -> None:
        super().__init__()
        self.append_calls = 0
        self.close_calls = 0

    def append(self, job: ProtocolJob) -> None:
        self.append_calls += 1
        super().append(job)

    def close(self) -> None:
        self.close_calls += 1
        super().close()

    @property
    def is_closed(self) -> bool:
        return self._file.closed


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


class _LuckBackend(_Backend):
    def __init__(self) -> None:
        super().__init__()
        self.queries: list[bytes] = []

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
        return b"\x00" if packet == b"\x10\xff\x40" else b"OK"


class _PrintMasterFallbackBackend(_Backend):
    def __init__(self) -> None:
        super().__init__()
        self.disconnects = 0

    def can_wait_for_notification(self) -> bool:
        return (
            bool(self.attempts)
            and self.attempts[-1][0].transport is DeviceTransport.BLE
        )

    async def disconnect(self) -> None:
        self.disconnects += 1


class GenericClientTests(unittest.IsolatedAsyncioTestCase):
    def _new_generic_client(
        self,
        *,
        profile_feed_lines: int | None = None,
        settings_feed_lines: int = 0,
    ) -> GenericClient:
        device = SimpleNamespace(name="GT01", address="00:11:22:33:44:55")
        hardware = GenericManifest().identify_device(
            device.name, device, device.address
        )
        self.assertIsNotNone(hardware)
        if hardware is None:
            self.fail("GT01 should resolve to generic hardware")
        return GenericClient(
            device,
            hardware,
            SimpleNamespace(
                paper_mode=None,
                speed=None,
                energy=None,
                feed_lines=profile_feed_lines,
            ),
            SimpleNamespace(speed=0, energy=0, feed_lines=settings_feed_lines),
        )

    def _observe_paper_iterator(
        self,
        images: Sequence[Image.Image],
        layout: PaperImageLayout,
        yielded: list[Image.Image],
        closed: list[bool],
        *,
        split_mode: bool = False,
    ) -> Generator[Image.Image, None, None]:
        iterator = iter_prepared_paper_images(images, layout, split_mode=split_mode)
        try:
            for image in iterator:
                yielded.append(image)
                yield image
        finally:
            iterator.close()
            closed.append(True)

    async def test_printmaster_falls_back_from_unobservable_classic_to_ble(
        self,
    ) -> None:
        device = SimpleNamespace(name="M110", address="00:11:22:33:44:55")
        hardware = GenericManifest().identify_device(device.name)
        assert hardware is not None
        client = GenericClient(
            device,
            hardware,
            SimpleNamespace(speed=None, energy=None, feed_lines=0, paper_mode=None),
            SimpleNamespace(speed=0, energy=0, feed_lines=0),
        )
        backend = _PrintMasterFallbackBackend()
        client.backend = backend
        with patch(
            "catlabel.vendors.generic.client.asyncio.sleep", new=AsyncMock()
        ) as sleep:
            self.assertTrue(await client.connect())
        self.assertEqual(
            [attempt[0].transport for attempt in backend.attempts],
            [DeviceTransport.CLASSIC, DeviceTransport.BLE],
        )
        self.assertTrue(all(len(attempt) == 1 for attempt in backend.attempts))
        self.assertEqual(backend.disconnects, 1)
        sleep.assert_not_awaited()

    async def test_luck_model_defaults_and_explicit_zero_reach_wire(self) -> None:
        for name, override, expected in (
            ("APA41_123", None, 2),
            ("APA49_123", None, 3),
            ("APA41_123", 0, 0),
        ):
            with self.subTest(name=name, override=override):
                device = SimpleNamespace(name=name, address="00:11:22:33:44:55")
                hardware = GenericManifest().identify_device(name)
                assert hardware is not None
                self.assertEqual(hardware["capabilities"]["density"]["min"], 0)
                self.assertEqual(
                    hardware["capabilities"]["density"]["default"],
                    2 if "APA41" in name else 3,
                )
                client = GenericClient(
                    device,
                    hardware,
                    SimpleNamespace(
                        paper_mode=None, speed=None, energy=override, feed_lines=0
                    ),
                    SimpleNamespace(speed=10, energy=5000, feed_lines=50),
                )
                backend = _LuckBackend()
                client.backend = backend
                source = Image.new("RGB", (8, 1), "white")
                try:
                    await client.print_images([source], dither=False)
                    self.assertEqual(
                        backend.queries[0], b"\x10\xff\x10\x00" + bytes([expected])
                    )
                    self.assertEqual(backend.queries[-1], b"\x10\xff\xf1E")
                    self.assertEqual(source.getpixel((0, 0)), (255, 255, 255))
                finally:
                    await client.disconnect()
                    source.close()

    async def test_released_s001_preset_and_density_reach_public_client(self) -> None:
        device = SimpleNamespace(name="S001", address="00:11:22:33:44:55")
        hardware = GenericManifest().identify_device(
            device.name, device, device.address
        )
        assert hardware is not None
        client = GenericClient(
            device,
            hardware,
            SimpleNamespace(paper_mode=None, speed=None, energy=None, feed_lines=0),
            SimpleNamespace(speed=0, energy=0, feed_lines=0),
        )
        backend = _Backend()
        client.backend = backend
        source = Image.new("RGB", (280, 88), "white")
        try:
            self.assertEqual(client.validate_images([source]), 1)
            await client.print_images([source], dither=False)
            self.assertEqual(len(backend.writes), 1)
            frames = tuple(iter_yk_frames(backend.writes[0][0]))
            self.assertEqual(
                [(frame.command, frame.payload) for frame in frames[:3]],
                [
                    (0x0A, bytes([25])),
                    (0x09, bytes([9])),
                    (0x28, bytes([1, 1])),
                ],
            )
            rasters = [frame for frame in frames if frame.command == 0x00]
            self.assertEqual(len(rasters), 70)
            self.assertTrue(all(len(frame.payload) == 48 for frame in rasters))
            self.assertEqual(source.size, (280, 88))
        finally:
            await client.disconnect()
            source.close()

    async def test_prepared_images_close_on_failure_without_closing_input(self) -> None:
        client = self._new_generic_client()
        source = Image.new("RGB", (2, 3), "white")
        prepared: list[Image.Image] = []
        iterator_closed: list[bool] = []
        spools: list[_TrackingSpool] = []

        def stream(
            images: Sequence[Image.Image],
            layout: PaperImageLayout,
            *,
            split_mode: bool = False,
        ) -> Generator[Image.Image, None, None]:
            return self._observe_paper_iterator(
                images,
                layout,
                prepared,
                iterator_closed,
                split_mode=split_mode,
            )

        def create_spool() -> _TrackingSpool:
            spool = _TrackingSpool()
            spools.append(spool)
            return spool

        try:
            with (
                patch(
                    "catlabel.vendors.generic.client.iter_prepared_paper_images",
                    stream,
                ),
                patch(
                    "catlabel.vendors.generic.client.ProtocolJobSpool",
                    side_effect=create_spool,
                ),
                patch(
                    "catlabel.vendors.generic.client.image_to_raster",
                    side_effect=RuntimeError("encode failed"),
                ),
                patch(
                    "catlabel.vendors.generic.client.send_prepared_job",
                    new=AsyncMock(),
                ),
                self.assertRaisesRegex(RuntimeError, "encode failed"),
            ):
                await client.print_images([source])
            self.assertEqual(len(prepared), 1)
            with self.assertRaises(ValueError):
                prepared[0].getpixel((0, 0))
            self.assertEqual(iterator_closed, [True])
            self.assertEqual(len(spools), 1)
            self.assertEqual(spools[0].close_calls, 1)
            self.assertTrue(spools[0]._file.closed)
            self.assertEqual(source.getpixel((0, 0)), (255, 255, 255))
        finally:
            source.close()

    async def test_second_page_build_failure_sends_nothing_and_closes_stream_and_spool(
        self,
    ) -> None:
        client = self._new_generic_client()
        sources = [Image.new("RGB", (2, 3), "white") for _ in range(2)]
        prepared: list[Image.Image] = []
        iterator_closed: list[bool] = []
        spools: list[_TrackingSpool] = []
        build_calls: list[dict[str, object]] = []

        def stream(
            images: Sequence[Image.Image],
            layout: PaperImageLayout,
            *,
            split_mode: bool = False,
        ) -> Generator[Image.Image, None, None]:
            return self._observe_paper_iterator(
                images,
                layout,
                prepared,
                iterator_closed,
                split_mode=split_mode,
            )

        def create_spool() -> _TrackingSpool:
            spool = _TrackingSpool()
            spools.append(spool)
            return spool

        def fail_second_build(**kwargs: object) -> ProtocolJob:
            build_calls.append(kwargs)
            if len(build_calls) == 2:
                raise RuntimeError("second build failed")
            return ProtocolJob(payload=b"first page")

        send_job = AsyncMock()
        try:
            with (
                patch(
                    "catlabel.vendors.generic.client.iter_prepared_paper_images",
                    stream,
                ),
                patch(
                    "catlabel.vendors.generic.client.ProtocolJobSpool",
                    side_effect=create_spool,
                ),
                patch(
                    "catlabel.vendors.generic.client.build_raster_job",
                    side_effect=fail_second_build,
                ),
                patch(
                    "catlabel.vendors.generic.client.send_prepared_job",
                    new=send_job,
                ),
                self.assertRaisesRegex(RuntimeError, "second build failed"),
            ):
                await client.print_images(sources)

            self.assertEqual(len(prepared), 2)
            for image in prepared:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))
            self.assertEqual(iterator_closed, [True])
            self.assertEqual(len(spools), 1)
            self.assertEqual(spools[0].append_calls, 1)
            self.assertEqual(spools[0].close_calls, 1)
            self.assertTrue(spools[0]._file.closed)
            send_job.assert_not_awaited()
            self.assertEqual(len(build_calls), 2)
            self.assertTrue(
                all(source.getpixel((0, 0)) == (255, 255, 255) for source in sources)
            )
        finally:
            for source in sources:
                source.close()

    async def test_spools_all_jobs_before_send_and_preserves_page_fields_and_bytes(
        self,
    ) -> None:
        client = self._new_generic_client(settings_feed_lines=23)
        sources = [Image.new("RGB", (2, 3), "white") for _ in range(2)]
        for source in sources:
            self.addCleanup(source.close)
        prepared: list[Image.Image] = []
        iterator_closed: list[bool] = []
        spools: list[_TrackingSpool] = []
        build_calls: list[dict[str, object]] = []
        sent_jobs: list[ProtocolJob] = []
        expected_jobs = [
            ProtocolJob(payload=b"first protocol page", wait_for_completion=True),
            ProtocolJob(payload=b"second protocol page", wait_for_completion=True),
        ]

        def stream(
            images: Sequence[Image.Image],
            layout: PaperImageLayout,
            *,
            split_mode: bool = False,
        ) -> Generator[Image.Image, None, None]:
            return self._observe_paper_iterator(
                images,
                layout,
                prepared,
                iterator_closed,
                split_mode=split_mode,
            )

        def create_spool() -> _TrackingSpool:
            spool = _TrackingSpool()
            spools.append(spool)
            return spool

        def build_job(**kwargs: object) -> ProtocolJob:
            build_calls.append(kwargs)
            return expected_jobs[len(build_calls) - 1]

        async def send_job(
            model: object,
            connection: object,
            job: ProtocolJob,
            **kwargs: object,
        ) -> None:
            self.assertIs(model, client.model)
            self.assertIs(connection, client._runtime_connection)
            self.assertEqual(len(build_calls), 2)
            self.assertEqual(len(spools[0]), 2)
            self.assertFalse(spools[0].is_closed)
            self.assertEqual(iterator_closed, [True])
            self.assertEqual(len(prepared), 2)
            for image in prepared:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))
            self.assertEqual(kwargs["timeout"], 1.0)
            self.assertIs(
                kwargs["reporter"], generic_client_module.reporting.DUMMY_REPORTER
            )
            self.assertIs(kwargs["runtime_context"], client._runtime_context)
            sent_jobs.append(job)

        sleep = AsyncMock()
        with (
            patch(
                "catlabel.vendors.generic.client.iter_prepared_paper_images",
                stream,
            ),
            patch(
                "catlabel.vendors.generic.client.ProtocolJobSpool",
                side_effect=create_spool,
            ),
            patch.object(
                client,
                "_effective_protocol_family",
                return_value=ProtocolFamily.LEGACY,
            ),
            patch(
                "catlabel.vendors.generic.client.runtime_controller_for_device",
                return_value=None,
            ),
            patch(
                "catlabel.vendors.generic.client.build_raster_job",
                side_effect=build_job,
            ),
            patch(
                "catlabel.vendors.generic.client.send_prepared_job",
                side_effect=send_job,
            ),
            patch("catlabel.vendors.generic.client.asyncio.sleep", new=sleep),
        ):
            await client.print_images(sources, dither=False)

        self.assertEqual(
            [
                (
                    call["page_index"],
                    call["page_count"],
                    call["feed_padding"],
                )
                for call in build_calls
            ],
            [(1, 2, 0), (2, 2, 23)],
        )
        self.assertEqual(
            [job.payload for job in sent_jobs],
            [b"first protocol page", b"second protocol page"],
        )
        self.assertEqual([job.wait_for_completion for job in sent_jobs], [False, True])
        self.assertEqual(spools[0].append_calls, 2)
        self.assertEqual(spools[0].close_calls, 1)
        self.assertTrue(spools[0].is_closed)
        sleep.assert_awaited_once_with(1.5)
        self.assertTrue(
            all(source.getpixel((0, 0)) == (255, 255, 255) for source in sources)
        )

    async def test_phomemo_keeps_intermediate_completion_and_skips_page_delay(
        self,
    ) -> None:
        client = self._new_generic_client()
        sources = [Image.new("RGB", (2, 3), "white") for _ in range(2)]
        build_calls = 0
        sent_jobs: list[ProtocolJob] = []
        expected_jobs = [
            ProtocolJob(payload=b"phomemo first", wait_for_completion=True),
            ProtocolJob(payload=b"phomemo second", wait_for_completion=True),
        ]

        def build_job(**kwargs: object) -> ProtocolJob:
            nonlocal build_calls
            build_calls += 1
            self.assertIs(kwargs["protocol_family"], ProtocolFamily.PHOMEMO_ESC)
            return expected_jobs[build_calls - 1]

        async def send_job(
            _model: object,
            _connection: object,
            job: ProtocolJob,
            **_kwargs: object,
        ) -> None:
            sent_jobs.append(job)

        sleep = AsyncMock()
        try:
            with (
                patch.object(
                    client,
                    "_effective_protocol_family",
                    return_value=ProtocolFamily.PHOMEMO_ESC,
                ),
                patch(
                    "catlabel.vendors.generic.client.runtime_controller_for_device",
                    return_value=None,
                ),
                patch(
                    "catlabel.vendors.generic.client.build_raster_job",
                    side_effect=build_job,
                ),
                patch(
                    "catlabel.vendors.generic.client.send_prepared_job",
                    side_effect=send_job,
                ),
                patch("catlabel.vendors.generic.client.asyncio.sleep", new=sleep),
            ):
                await client.print_images(sources, dither=False)

            self.assertEqual(
                [job.wait_for_completion for job in sent_jobs], [True, True]
            )
            self.assertEqual(
                [job.payload for job in sent_jobs],
                [b"phomemo first", b"phomemo second"],
            )
            sleep.assert_not_awaited()
            self.assertTrue(
                all(source.getpixel((0, 0)) == (255, 255, 255) for source in sources)
            )
        finally:
            for source in sources:
                source.close()

    async def test_send_cancellation_closes_spool_and_iterator_not_borrowed_images(
        self,
    ) -> None:
        client = self._new_generic_client()
        sources = [Image.new("RGB", (2, 3), "white") for _ in range(2)]
        prepared: list[Image.Image] = []
        iterator_closed: list[bool] = []
        spools: list[_TrackingSpool] = []
        entered_send = asyncio.Event()
        never_release = asyncio.Event()
        build_calls = 0
        expected_jobs = [
            ProtocolJob(payload=b"first cancellation page"),
            ProtocolJob(payload=b"second cancellation page"),
        ]

        def stream(
            images: Sequence[Image.Image],
            layout: PaperImageLayout,
            *,
            split_mode: bool = False,
        ) -> Generator[Image.Image, None, None]:
            return self._observe_paper_iterator(
                images,
                layout,
                prepared,
                iterator_closed,
                split_mode=split_mode,
            )

        def create_spool() -> _TrackingSpool:
            spool = _TrackingSpool()
            spools.append(spool)
            return spool

        def build_job(**_kwargs: object) -> ProtocolJob:
            nonlocal build_calls
            build_calls += 1
            return expected_jobs[build_calls - 1]

        async def blocked_send(
            _model: object,
            _connection: object,
            job: ProtocolJob,
            **_kwargs: object,
        ) -> None:
            self.assertEqual(job.payload, b"first cancellation page")
            self.assertEqual(len(spools[0]), 2)
            self.assertEqual(iterator_closed, [True])
            for image in prepared:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))
            entered_send.set()
            await never_release.wait()

        task: asyncio.Task[None] | None = None
        try:
            with (
                patch(
                    "catlabel.vendors.generic.client.iter_prepared_paper_images",
                    stream,
                ),
                patch(
                    "catlabel.vendors.generic.client.ProtocolJobSpool",
                    side_effect=create_spool,
                ),
                patch(
                    "catlabel.vendors.generic.client.build_raster_job",
                    side_effect=build_job,
                ),
                patch(
                    "catlabel.vendors.generic.client.send_prepared_job",
                    side_effect=blocked_send,
                ),
            ):
                task = asyncio.create_task(client.print_images(sources, dither=False))
                await asyncio.wait_for(entered_send.wait(), timeout=2)
                task.cancel("cancel while sending")
                with self.assertRaises(asyncio.CancelledError):
                    await task

            self.assertEqual(iterator_closed, [True])
            self.assertEqual(spools[0].append_calls, 2)
            self.assertEqual(spools[0].close_calls, 1)
            self.assertTrue(spools[0].is_closed)
            self.assertTrue(
                all(source.getpixel((0, 0)) == (255, 255, 255) for source in sources)
            )
        finally:
            never_release.set()
            if task is not None and not task.done():
                task.cancel("test cleanup")
                with suppress(asyncio.CancelledError):
                    await task
            for source in sources:
                source.close()

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
