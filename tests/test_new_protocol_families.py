from __future__ import annotations

import unittest
from collections.abc import Callable
from unittest.mock import patch

from catlabel.printing import build_raster_job, send_prepared_job
from catlabel.printing.runtime.base import PreparedRuntimeContext
from catlabel.printing.runtime.funny_lx import FunnyLxRuntimeController
from catlabel.printing.runtime.luck_normal import (
    LUCK_MODEL_QUERY_PACKET,
    LUCK_VERSION_QUERY_PACKET,
    LuckNormalRuntimeController,
)
from catlabel.protocol import (
    ProtocolJob,
    ProtocolReplyExpectation,
    ProtocolStepOperation,
)
from catlabel.protocol.families.funny_lx import challenge_crc
from catlabel.protocol.types import PaperMode
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet
from catlabel.transport.bluetooth.adapters.windows_winrt import (
    _WinRtClassicBackend,
    _WinRtSocket,
)
from catlabel.transport.bluetooth.backend import _query_control_packet
from catlabel.vendors.generic.models import PrinterModelRegistry
from tests.runtime_session_fake import RuntimeSessionFake


def _job(
    model_key: str,
    pixels: list[int],
    width: int,
    *,
    density: int | None = None,
    blackening: int = 3,
    paper_mode: PaperMode | None = None,
) -> ProtocolJob:
    model = PrinterModelRegistry.load().get(model_key)
    assert model is not None
    raster = RasterBuffer(pixels, width=width, pixel_format=PixelFormat.BW1)
    return build_raster_job(
        model=model,
        raster_set=RasterSet.from_single(raster),
        image_pipeline=model.image_pipeline,
        is_text=False,
        speed=model.img_print_speed,
        energy=model.moderation_energy,
        density=density,
        blackening=blackening,
        feed_padding=0,
        paper_mode=paper_mode,
        protocol_family=model.protocol_family,
        protocol_variant=model.protocol_variant,
    )


class StatelessProtocolFamilyTests(unittest.TestCase):
    def test_eleph_hprt_zl1_job_and_media_step(self) -> None:
        job = _job(
            "toprint_hprt_esc_zl1",
            [1, 0, 0, 0, 0, 0, 0, 0, 1],
            9,
            density=2,
            paper_mode=PaperMode.TAG,
        )
        self.assertEqual(len(job.steps), 2)
        self.assertEqual(job.steps[0].data, b"\x10\xff\x10\x03\x02")
        self.assertIn(b"\x1d\x76\x30\x00\x02\x00\x01\x00\x80\x80", job.payload)
        self.assertTrue(job.payload.endswith(b"\x10\xff\x10\x00\x02"))

    def test_eleph_tspl_p1_source_command_order(self) -> None:
        job = _job(
            "eleph_tspl_p1",
            [1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0],
            8,
            density=9,
            paper_mode=PaperMode.TAG,
        )
        markers = (
            b"\x10\xff\x10\x03\x02",
            b"SIZE 1 mm,0.25 mm\r\n",
            b"DIRECTION 0,0\r\n",
            b"GAP 3 mm,0 mm\r\n",
            b"SET RIBBON OFF\r\n",
            b"DENSITY 9\r\n",
            b"REFERENCE 0,0\r\n",
            b"BITMAP 0,0,1,2,0,\x80@\r\n",
            b"PRINT 1,1\r\n",
        )
        positions = [job.payload.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))

    def test_instaprint_core_job_is_byte_exact(self) -> None:
        job = _job(
            "instaprint_ctp500_coreprint",
            [1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0],
            8,
            density=15,
            paper_mode=PaperMode.PLAIN,
        )
        self.assertEqual(
            job.payload,
            b"\x1b\x40\x1d\x49\xf0\x0f"
            b"\x1d\x76\x30\x00\x01\x00\x02\x00\x80\x40"
            b"\x0a\x0a\x0a\x0a",
        )


class _InteractiveConnection:
    def __init__(self, replies: list[bytes]) -> None:
        self.replies = list(replies)
        self.queries: list[bytes] = []
        self.sent: list[bytes] = []

    async def attach_runtime_controller(self, controller, *, timeout: float) -> None:
        _ = controller, timeout

    def can_send_control_packet(self) -> bool:
        return True

    def can_query_control_packet(self) -> bool:
        return True

    def can_send_bulk_payload(self) -> bool:
        return False

    def can_wait_for_notification(self) -> bool:
        return False

    def can_send_control_packet_wait_notification(self) -> bool:
        return False

    async def query_control_packet(self, packet: bytes, **_kwargs) -> bytes | None:
        self.queries.append(bytes(packet))
        return self.replies.pop(0) if self.replies else None

    async def send_standard_payload(self, data: bytes) -> None:
        self.sent.append(bytes(data))

    async def send(self, job: ProtocolJob) -> None:
        raise AssertionError(f"interactive job was flattened: {job.payload.hex()}")


class LuckPpa2Tests(unittest.IsolatedAsyncioTestCase):
    async def test_ppa2_executes_queries_interleaved_with_sends(self) -> None:
        model = PrinterModelRegistry.load().get("luck_ppa2l")
        assert model is not None
        job = _job(
            "luck_ppa2l",
            [0] * 8,
            8,
            density=1,
            paper_mode=PaperMode.TAG,
        )
        self.assertEqual(job.steps[0].operation, ProtocolStepOperation.QUERY)
        self.assertEqual(job.steps[1].label, "status")
        self.assertFalse(job.steps[1].include_in_payload)
        self.assertEqual(job.steps[-1].expect, ProtocolReplyExpectation.OK_OR_AA)

        connection = _InteractiveConnection([b"OK", b"\x00", b"OK", b"\xaa"])
        controller = LuckNormalRuntimeController(protocol_variant="lujiang_normal")
        await send_prepared_job(
            model,
            connection,
            job,
            runtime_context=PreparedRuntimeContext(runtime_controller=controller),
        )
        self.assertEqual(len(connection.queries), 4)
        self.assertIn(b"\x1d\x76\x30", b"".join(connection.sent))

    async def test_capability_probe_enables_gray_only_for_gy_model(self) -> None:
        connection = _InteractiveConnection(["PPA2L_GY".encode("gb2312"), b"1.26"])
        controller = LuckNormalRuntimeController(protocol_variant="lujiang_normal")
        from catlabel import reporting
        from catlabel.printing.runtime.session import RuntimeConnectionSession

        session = RuntimeConnectionSession(
            connection, reporter=reporting.DUMMY_REPORTER
        )
        await controller.probe_capabilities(session, timeout=0.1)
        self.assertEqual(
            connection.queries, [LUCK_MODEL_QUERY_PACKET, LUCK_VERSION_QUERY_PACKET]
        )
        capabilities = controller.runtime_capabilities()
        self.assertIsNotNone(capabilities)
        if capabilities is None:
            self.fail("runtime capabilities should have been established")
        self.assertTrue(capabilities.supports_gray)


class _FunnySession(RuntimeSessionFake):
    def __init__(
        self, control_replies: list[bytes], wait_replies: list[bytes] | None = None
    ) -> None:
        self.control_replies = list(control_replies)
        self.wait_replies = [] if wait_replies is None else list(wait_replies)
        self.control: list[bytes] = []
        self.standard: list[bytes] = []
        self.warnings: list[tuple[str, str]] = []
        self.on_standard: Callable[[bytes], None] | None = None

    def can_send_control_packet(self) -> bool:
        return True

    def can_query_control_packet(self) -> bool:
        return False

    def can_send_standard_payload(self) -> bool:
        return True

    def can_send_bulk_payload(self) -> bool:
        return False

    def can_wait_for_notification(self) -> bool:
        return True

    def can_send_control_packet_wait_notification(self) -> bool:
        return True

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        self.control.append(bytes(packet))
        return True

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        self.control.append(bytes(packet))
        return self.control_replies.pop(0)

    async def send_standard_payload(self, data: bytes) -> object:
        self.standard.append(bytes(data))
        if self.on_standard:
            self.on_standard(bytes(data))

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        return self.wait_replies.pop(0) if self.wait_replies else None

    def report_debug(self, message: str) -> None:
        pass

    def report_warning(self, *, short: str, detail: str) -> None:
        self.warnings.append((short, detail))


class FunnyLxTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_and_retry_aware_job(self) -> None:
        random_bytes = bytes.fromhex("f7 cf 01 02 03 04 05 06 07 08")
        mac = bytes.fromhex("c00000000460")
        crc = challenge_crc(random_bytes, mac)
        session = _FunnySession(
            [
                b"\x5a\x01\x00",
                b"\x5a\x0a" + crc.low,
                b"\x5a\x0b\x01",
                b"\x5a\x04\x00\x02\x01",
            ],
            [b"\x5a\x06\x00"],
        )
        controller = FunnyLxRuntimeController(
            bluetooth_address="C0:00:00:00:04:60",
            random_bytes_factory=lambda: random_bytes,
            sleep=lambda _delay: _completed(),
        )
        await controller.initialize_connection(session, mtu_size=100, timeout=0.1)
        job = _job("funny_lx_d", [0] * (384 * 4), 384, blackening=4)
        requested = False

        def retry_after_first(payload: bytes) -> None:
            nonlocal requested
            if not requested and payload.startswith(b"\x55\x00\x00"):
                requested = True
                controller.handle_notification(session, b"\x5a\x05\x00\x01")

        session.on_standard = retry_after_first
        self.assertTrue(
            await controller.send_protocol_steps(session, job.steps, timeout=0.1)
        )
        indexes = [
            packet[1:3] for packet in session.standard if packet.startswith(b"\x55")
        ]
        self.assertEqual(indexes, [b"\x00\x00", b"\x00\x00", b"\x00\x01"])
        self.assertEqual(session.warnings, [])


async def _completed() -> None:
    return None


class _PartialSocket:
    def __init__(self) -> None:
        self.replies = [b"O", b"K\x00"]
        self.sent = b""
        self.timeout = None

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, _size: int) -> bytes:
        return self.replies.pop(0)

    def settimeout(self, value) -> None:
        self.timeout = value

    def gettimeout(self):
        return self.timeout


class SppQueryTests(unittest.TestCase):
    def test_classic_query_collects_partial_reply_until_match(self) -> None:
        sock = _PartialSocket()
        reply = _query_control_packet(
            sock,
            b"QUERY",
            timeout=0.1,
            reply_complete=lambda data: data.startswith(b"OK"),
        )
        self.assertEqual(sock.sent, b"QUERY")
        self.assertEqual(reply, b"OK\x00")

    def test_windows_winrt_socket_exposes_received_spp_bytes(self) -> None:
        class Reader:
            async def _load(self, size: int) -> int:
                return min(size, 2)

            def load_async(self, size: int):
                return self._load(size)

            def read_bytes(self, target: bytearray) -> None:
                target[:] = b"OK"

        sock = _WinRtSocket(_WinRtClassicBackend())
        sock.settimeout(0.1)
        try:
            with patch.object(sock, "_reader", Reader()):
                self.assertEqual(sock.recv(4096), b"OK")
                self.assertEqual(sock.gettimeout(), 0.1)
        finally:
            if sock._loop is not None:
                sock._loop.close()
                sock._loop = None


if __name__ == "__main__":
    unittest.main()
