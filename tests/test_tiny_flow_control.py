from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import cast

from catlabel.printing.runtime.base import RuntimeController, RuntimeSessionApi
from catlabel.printing.runtime.factory import runtime_controller_for_device
from catlabel.printing.runtime.tiny import TinyRuntimeController
from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.packet import (
    PrefixedPacket,
    PrefixedPacketStreamDecoder,
    crc8_value,
    make_packet,
)

PAUSE_FRAME = bytes.fromhex("5178AE0101001070FF")
RESUME_FRAME = bytes.fromhex("5178AE0101000000FF")
LEGACY_PREFIX = bytes.fromhex("5178")


def _frame(opcode: int, flags: int, payload: bytes) -> bytes:
    return (
        LEGACY_PREFIX
        + bytes([opcode, flags])
        + len(payload).to_bytes(2, "little")
        + payload
        + bytes([crc8_value(payload), 0xFF])
    )


class FlowRecordingSession:
    def __init__(self) -> None:
        self.flow_updates: list[tuple[bool, bytes]] = []

    def set_flow_paused(self, paused: bool, *, payload: bytes = b"") -> None:
        self.flow_updates.append((paused, payload))


class PrefixedPacketStreamDecoderTests(unittest.TestCase):
    def test_pause_and_resume_decode_at_every_split_point(self) -> None:
        for frame, payload in (
            (PAUSE_FRAME, b"\x10"),
            (RESUME_FRAME, b"\x00"),
        ):
            for split in range(len(frame) + 1):
                with self.subTest(frame=frame.hex(), split=split):
                    decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)
                    first = decoder.feed(frame[:split])
                    if split < len(frame):
                        self.assertEqual(first, ())
                        packets = decoder.feed(frame[split:])
                    else:
                        packets = first

                    self.assertEqual(
                        packets,
                        (
                            PrefixedPacket(
                                raw=frame,
                                opcode=0xAE,
                                flags=0x01,
                                payload=payload,
                            ),
                        ),
                    )
                    self.assertEqual(decoder.pending, b"")

    def test_bytewise_coalesced_and_garbage_with_split_prefix(self) -> None:
        decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)
        self.assertEqual(decoder.feed(b"\x99\x51"), ())
        self.assertEqual(decoder.pending, b"\x51")
        self.assertEqual(
            decoder.feed(PAUSE_FRAME[1:] + RESUME_FRAME),
            (
                PrefixedPacket(PAUSE_FRAME, 0xAE, 0x01, b"\x10"),
                PrefixedPacket(RESUME_FRAME, 0xAE, 0x01, b"\x00"),
            ),
        )
        self.assertEqual(decoder.pending, b"")

        bytewise_decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)
        packets: list[PrefixedPacket] = []
        for value in PAUSE_FRAME:
            packets.extend(bytewise_decoder.feed(bytes([value])))

        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].raw, PAUSE_FRAME)
        self.assertEqual(packets[0].payload, b"\x10")
        self.assertEqual(bytewise_decoder.pending, b"")

        coalesced_decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)
        self.assertEqual(
            tuple(coalesced_decoder.feed(PAUSE_FRAME + RESUME_FRAME)),
            (
                PrefixedPacket(PAUSE_FRAME, 0xAE, 0x01, b"\x10"),
                PrefixedPacket(RESUME_FRAME, 0xAE, 0x01, b"\x00"),
            ),
        )
        self.assertEqual(coalesced_decoder.pending, b"")

    def test_bad_crc_and_footer_are_rejected_and_stream_resynchronizes(self) -> None:
        bad_crc = bytearray(PAUSE_FRAME)
        bad_crc[-2] ^= 0x01
        bad_footer = bytearray(PAUSE_FRAME)
        bad_footer[-1] ^= 0x01

        for invalid in (bytes(bad_crc), bytes(bad_footer)):
            with self.subTest(invalid=invalid.hex()):
                decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)
                packets = decoder.feed(invalid + RESUME_FRAME)
                self.assertEqual(
                    packets,
                    (PrefixedPacket(RESUME_FRAME, 0xAE, 0x01, b"\x00"),),
                )
                self.assertEqual(decoder.pending, b"")

    def test_incomplete_max_length_candidate_is_not_skipped_for_inner_prefix(
        self,
    ) -> None:
        decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)
        header = LEGACY_PREFIX + bytes([0x99, 0x01]) + b"\xff\xff"
        partial_packet = header + PAUSE_FRAME

        self.assertEqual(decoder.feed(partial_packet), ())
        self.assertEqual(decoder.pending, partial_packet)

    def test_maximum_u16_packet_stays_bounded_and_decodes_when_complete(self) -> None:
        payload = bytes(0xFFFF)
        header = (
            LEGACY_PREFIX + bytes([0x99, 0x00]) + len(payload).to_bytes(2, "little")
        )
        frame = header + payload + bytes([crc8_value(payload), 0xFF])
        maximum_frame_length = len(LEGACY_PREFIX) + 4 + 0xFFFF + 2
        decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)

        self.assertEqual(len(frame), maximum_frame_length)
        self.assertEqual(decoder.feed(frame[:-1]), ())
        self.assertEqual(decoder.pending, frame[:-1])
        self.assertLessEqual(len(decoder.pending), maximum_frame_length)
        self.assertEqual(
            decoder.feed(frame[-1:]),
            (PrefixedPacket(frame, 0x99, 0x00, payload),),
        )
        self.assertEqual(decoder.pending, b"")

    def test_existing_packet_builder_keeps_both_outbound_prefix_variants(self) -> None:
        self.assertEqual(
            make_packet(0xAE, b"\x10", ProtocolFamily.LEGACY),
            bytes.fromhex("5178AE0001001070FF"),
        )
        self.assertEqual(
            make_packet(0xAE, b"\x10", ProtocolFamily.LEGACY_PREFIXED),
            bytes.fromhex("125178AE0001001070FF"),
        )


class TinyRuntimeControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_exact_pause_and_resume_notifications_change_flow(self) -> None:
        session = FlowRecordingSession()
        runtime_session = cast(RuntimeSessionApi, session)
        controller = TinyRuntimeController()
        notifications = b"".join(
            (
                _frame(0xAF, 0x01, b"\x10"),
                _frame(0xAE, 0x00, b"\x10"),
                _frame(0xAE, 0x02, b"\x10"),
                _frame(0xAE, 0x01, b"\x10\x00"),
                _frame(0xAE, 0x01, b"\x01"),
                PAUSE_FRAME,
                RESUME_FRAME,
            )
        )

        controller.handle_notification(runtime_session, notifications)

        self.assertEqual(
            session.flow_updates,
            [(True, PAUSE_FRAME), (False, RESUME_FRAME)],
        )

    async def test_pending_packet_state_moves_only_from_tiny_controller(self) -> None:
        session = FlowRecordingSession()
        runtime_session = cast(RuntimeSessionApi, session)
        previous = TinyRuntimeController()
        previous.handle_notification(runtime_session, PAUSE_FRAME[:5])
        current = TinyRuntimeController()

        current.adopt_previous(previous)
        self.assertEqual(previous._decoder.pending, b"")
        current.handle_notification(runtime_session, PAUSE_FRAME[5:])

        self.assertEqual(session.flow_updates, [(True, PAUSE_FRAME)])

        unrelated = RuntimeController()
        fresh = TinyRuntimeController()
        fresh.adopt_previous(unrelated)
        fresh.handle_notification(runtime_session, PAUSE_FRAME[5:])
        self.assertEqual(session.flow_updates, [(True, PAUSE_FRAME)])

    async def test_stop_resets_decoder_and_unpauses(self) -> None:
        session = FlowRecordingSession()
        runtime_session = cast(RuntimeSessionApi, session)
        controller = TinyRuntimeController()
        controller.handle_notification(runtime_session, PAUSE_FRAME)
        controller.handle_notification(runtime_session, RESUME_FRAME[:5])

        await controller.stop(runtime_session)

        self.assertEqual(
            session.flow_updates,
            [(True, PAUSE_FRAME), (False, b"")],
        )
        self.assertEqual(controller._decoder.pending, b"")
        controller.handle_notification(runtime_session, RESUME_FRAME[5:])
        self.assertEqual(len(session.flow_updates), 2)
        controller.handle_notification(runtime_session, RESUME_FRAME)
        self.assertEqual(
            session.flow_updates[-1],
            (False, RESUME_FRAME),
        )

    async def test_factory_selects_tiny_for_both_legacy_families(self) -> None:
        for family in (ProtocolFamily.LEGACY, ProtocolFamily.LEGACY_PREFIXED):
            with self.subTest(family=family.value):
                controller = runtime_controller_for_device(
                    SimpleNamespace(protocol_family=family)
                )
                self.assertIsInstance(controller, TinyRuntimeController)
                assert isinstance(controller, TinyRuntimeController)
                session = FlowRecordingSession()
                controller.handle_notification(
                    cast(RuntimeSessionApi, session), PAUSE_FRAME
                )
                self.assertEqual(session.flow_updates, [(True, PAUSE_FRAME)])


if __name__ == "__main__":
    unittest.main()
