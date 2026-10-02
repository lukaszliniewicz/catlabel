from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from typing import cast

from catlabel.protocol.families.yk_astra_session import (
    COMPLETION_STATUS_COMMANDS,
    PAPER_QUERY_COMMAND,
    PAPER_REPLY_COMMAND,
    STATUS_QUERY_COMMAND,
    STATUS_REPLY_COMMANDS,
    AstraP1PaperDetails,
    first_paper_details,
    first_status,
    pack_paper_query,
    pack_status_query,
    paper_details_from_frame,
    status_from_frame,
)
from catlabel.protocol.families.yk_common import (
    FRAME_END,
    FRAME_START,
    SEQUENCE_MODULUS,
    YkFrame,
    YkFrameStreamDecoder,
    iter_yk_frames,
    pack_yk_frame,
    resequence_yk_frame,
)

# Fixed wire vectors are written independently of the encoder under test.
STATUS_QUERY = bytes.fromhex("6410000000000000009b")
PAPER_QUERY = bytes.fromhex("647200010001000000009b")
INTEGRITY_QUERY = bytes.fromhex("6410000000875734129b")
# 0x12345678 + (100 + 18 + 63 + 3 + 0 + 0 + 100 + 155) + 155.
EMBEDDED_MARKERS = bytes.fromhex("64123f030000649bca5834129b")
STATUS_REPLY = bytes.fromhex("6480000800feff08af02030463000000009b")
PAPER_REPLY = bytes.fromhex("6473000400010f282a000000009b")


def _frame(command: int, payload: bytes) -> YkFrame:
    return YkFrame(command, 0, payload, 0, len(payload) + 10)


def _attempt_mutation(value: object, attribute: str, replacement: int) -> None:
    setattr(value, attribute, replacement)


class YkFrameContracts(unittest.TestCase):
    def test_fixed_wire_layout_and_integrity_vectors(self) -> None:
        self.assertEqual((FRAME_START, FRAME_END, SEQUENCE_MODULUS), (100, 155, 64))
        self.assertEqual(pack_yk_frame(0x10), STATUS_QUERY)
        self.assertEqual(
            pack_yk_frame(0x10, calculated_integrity=True), INTEGRITY_QUERY
        )
        self.assertEqual(
            pack_yk_frame(
                0x12, b"\x00\x64\x9b", sequence=63, calculated_integrity=True
            ),
            EMBEDDED_MARKERS,
        )
        self.assertEqual(
            tuple(iter_yk_frames(EMBEDDED_MARKERS)),
            (YkFrame(0x12, 63, b"\x00\x64\x9b", 0x123458CA, 13),),
        )

    def test_byte_ranges_sequence_wrap_and_u16_payload_limit(self) -> None:
        for command in (-1, 256):
            with self.subTest(command=command), self.assertRaises(ValueError):
                pack_yk_frame(command)
        for command in (1.5, "16", None):
            with self.subTest(command=command), self.assertRaises(TypeError):
                pack_yk_frame(cast(int, command))
        self.assertEqual(pack_yk_frame(0)[:2], b"\x64\x00")
        self.assertEqual(pack_yk_frame(255)[:2], b"\x64\xff")
        for sequence, encoded in ((-1, 63), (64, 0), (129, 1)):
            self.assertEqual(pack_yk_frame(0x10, sequence=sequence)[2], encoded)
        payload = b"\xff" * 65535
        packet = pack_yk_frame(0x10, payload)
        self.assertEqual(packet[:5], bytes.fromhex("641000ffff"))
        self.assertEqual(packet[-5:], bytes.fromhex("000000009b"))
        self.assertEqual(len(packet), 65545)
        self.assertEqual(tuple(iter_yk_frames(packet))[0].payload, payload)
        with self.assertRaisesRegex(ValueError, "uint16"):
            pack_yk_frame(0x10, payload + b"\xff")

    def test_resequence_preserves_payload_and_integrity_mode(self) -> None:
        self.assertEqual(
            resequence_yk_frame(STATUS_QUERY, sequence=65),
            bytes.fromhex("6410010000000000009b"),
        )
        self.assertEqual(
            resequence_yk_frame(EMBEDDED_MARKERS, sequence=64),
            bytes.fromhex("641200030000649b8b5834129b"),
        )
        for invalid in (
            b"",
            STATUS_QUERY[:-1],
            b"\x00" + STATUS_QUERY,
            STATUS_QUERY + b"\x00",
            STATUS_QUERY + PAPER_QUERY,
            INTEGRITY_QUERY[:-2] + b"\x00\x9b",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                resequence_yk_frame(invalid, sequence=1)

    def test_frame_is_frozen_and_preserves_all_fields(self) -> None:
        frame = tuple(iter_yk_frames(INTEGRITY_QUERY))[0]
        self.assertEqual(frame, YkFrame(0x10, 0, b"", 0x12345787, 10))
        with self.assertRaises(FrozenInstanceError):
            _attempt_mutation(frame, "command", 0)

    def test_every_split_and_bytewise_fragmentation(self) -> None:
        expected = (YkFrame(0x12, 63, b"\x00\x64\x9b", 0x123458CA, 13),)
        for split in range(1, len(EMBEDDED_MARKERS)):
            with self.subTest(split=split):
                decoder = YkFrameStreamDecoder()
                self.assertEqual(decoder.feed(EMBEDDED_MARKERS[:split]), ())
                self.assertEqual(decoder.pending, EMBEDDED_MARKERS[:split])
                self.assertEqual(decoder.feed(EMBEDDED_MARKERS[split:]), expected)
                self.assertEqual(decoder.pending, b"")
        decoder = YkFrameStreamDecoder()
        frames: list[YkFrame] = []
        for value in EMBEDDED_MARKERS:
            frames.extend(decoder.feed(bytes((value,))))
        self.assertEqual(tuple(frames), expected)

    def test_coalesced_frames_noise_and_incomplete_tail(self) -> None:
        decoder = YkFrameStreamDecoder()
        frames = decoder.feed(
            b"noise" + STATUS_QUERY + b"garbage" + PAPER_QUERY + STATUS_REPLY[:4]
        )
        self.assertEqual([frame.command for frame in frames], [0x10, 0x72])
        self.assertEqual(decoder.pending, STATUS_REPLY[:4])
        self.assertEqual(decoder.feed(STATUS_REPLY[4:])[0].command, 0x80)
        self.assertEqual(decoder.feed(b"garbage" * 10000), ())
        self.assertEqual(decoder.pending, b"")

    def test_incomplete_payload_is_opaque_even_with_a_complete_inner_frame(
        self,
    ) -> None:
        # A valid-looking frame inside an outer payload cannot trigger resync.
        prefix = bytes.fromhex("642a001400")
        payload_start = STATUS_QUERY + b"\x00" * 9
        decoder = YkFrameStreamDecoder()
        self.assertEqual(decoder.feed(prefix + payload_start), ())
        self.assertEqual(decoder.feed(b""), ())
        self.assertEqual(decoder.pending, prefix + payload_start)
        frames = decoder.feed(bytes.fromhex("00000000009b"))
        self.assertEqual(frames, (_frame(0x2A, payload_start + b"\x00"),))
        self.assertEqual(decoder.pending, b"")

    def test_pending_never_exceeds_one_max_u16_frame(self) -> None:
        decoder = YkFrameStreamDecoder()
        prefix = bytes.fromhex("642a00ffff")
        # Largest incomplete frame is 65,544 bytes, including a nested frame.
        body = STATUS_QUERY + b"\x00" * (65535 - len(STATUS_QUERY))
        partial = prefix + body + b"\x00" * 4
        self.assertEqual(decoder.feed(partial), ())
        self.assertEqual(len(decoder.pending), 65544)
        self.assertEqual(decoder.pending, partial)
        frames = decoder.feed(b"\x9b" + b"noise" * 20000 + STATUS_QUERY)
        self.assertEqual([frame.command for frame in frames], [0x2A, 0x10])
        self.assertEqual(frames[0].payload, body)
        self.assertEqual(decoder.pending, b"")

    def test_bad_footer_and_nonzero_integrity_resynchronize(self) -> None:
        failures = (
            STATUS_QUERY[:-1] + b"\x00",
            INTEGRITY_QUERY[:5] + bytes.fromhex("885734129b"),
            INTEGRITY_QUERY[:1] + b"\x11" + INTEGRITY_QUERY[2:],
        )
        for corrupt in failures:
            with self.subTest(corrupt=corrupt):
                decoder = YkFrameStreamDecoder()
                self.assertEqual(
                    decoder.feed(corrupt + PAPER_QUERY), (_frame(0x72, b"\x01"),)
                )
                self.assertEqual(decoder.pending, b"")
        # Zero integrity is a valid released protocol mode.
        self.assertEqual(tuple(iter_yk_frames(STATUS_QUERY)), (_frame(0x10, b""),))


class AstraStatusContracts(unittest.TestCase):
    def test_queries_match_literal_wire_and_constants(self) -> None:
        self.assertEqual(pack_status_query(), STATUS_QUERY)
        self.assertEqual(pack_paper_query(), PAPER_QUERY)
        self.assertEqual(
            pack_status_query(sequence=65), bytes.fromhex("6410010000000000009b")
        )
        self.assertEqual(
            pack_paper_query(sequence=-1), bytes.fromhex("64723f010001000000009b")
        )
        self.assertEqual(
            (STATUS_QUERY_COMMAND, PAPER_QUERY_COMMAND, PAPER_REPLY_COMMAND),
            (0x10, 0x72, 0x73),
        )
        self.assertEqual(STATUS_REPLY_COMMANDS, (0x80, 0x81, 0xFF))
        self.assertEqual(COMPLETION_STATUS_COMMANDS, (0x81, 0xFF))

    def test_literal_status_fields_signed_voltage_and_errors(self) -> None:
        status = first_status(STATUS_REPLY)
        assert status is not None
        self.assertEqual(
            (status.command, status.voltage_raw, status.status_bits), (0x80, -2, 0xAF08)
        )
        self.assertEqual(
            (
                status.density,
                status.auto_off_time,
                status.speed,
                status.battery_percent,
            ),
            (2, 3, 4, 99),
        )
        self.assertTrue(status.is_printing)
        self.assertTrue(status.valid_paper)
        self.assertTrue(status.paper_loaded)
        self.assertFalse(status.completion_status)
        self.assertEqual(
            status.errors, ("cover open", "low battery", "overheating", "out of paper")
        )
        with self.assertRaises(FrozenInstanceError):
            _attempt_mutation(status, "density", 0)

    def test_all_status_shapes_and_rejected_lengths(self) -> None:
        for command in (0x80, 0x81, 0xFF):
            valid_lengths = (7, 8, 12) if command == 0xFF else (8,)
            for length in range(14):
                with self.subTest(command=command, length=length):
                    payload = bytes.fromhex("feff000002030463") + b"\xaa" * 6
                    status = status_from_frame(_frame(command, payload[:length]))
                    if length not in valid_lengths:
                        self.assertIsNone(status)
                        continue
                    assert status is not None
                    self.assertEqual(status.voltage_raw, -2)
                    self.assertEqual(
                        status.battery_percent, None if length == 7 else 99
                    )
                    self.assertEqual(status.completion_status, command in (0x81, 0xFF))

    def test_every_status_bit_has_only_its_released_meaning(self) -> None:
        properties = {
            "is_printing": 3,
            "cover_open": 8,
            "low_battery": 9,
            "overheating": 10,
            "paper_out": 11,
            "valid_paper": 13,
            "paper_loaded": 15,
        }
        errors = {
            8: "cover open",
            9: "low battery",
            10: "overheating",
            11: "out of paper",
        }
        for command in (0x80, 0x81, 0xFF):
            for bit in range(16):
                with self.subTest(command=command, bit=bit):
                    payload = (
                        b"\x00\x00"
                        + (1 << bit).to_bytes(2, "little")
                        + b"\x02\x03\x04\x63"
                    )
                    status = status_from_frame(_frame(command, payload))
                    assert status is not None
                    for name, expected_bit in properties.items():
                        expected = bit == expected_bit and not (
                            command == 0xFF and name == "paper_loaded"
                        )
                        self.assertEqual(getattr(status, name), expected, name)
                    self.assertEqual(
                        status.errors, (errors[bit],) if bit in errors else ()
                    )

    def test_ff_paper_loaded_uses_voltage_bit_two_including_signed_voltage(
        self,
    ) -> None:
        for voltage in (0, 4, 0x8000, 0x8004, 0xFFFF):
            for status_bits in (0, 0x8000):
                with self.subTest(voltage=voltage, status_bits=status_bits):
                    payload = (
                        voltage.to_bytes(2, "little")
                        + status_bits.to_bytes(2, "little")
                        + b"\x02\x03\x04"
                    )
                    status = status_from_frame(_frame(0xFF, payload))
                    assert status is not None
                    self.assertEqual(status.paper_loaded, bool(voltage & 4))

    def test_paper_shape_unknown_commands_and_optional_first_helpers(self) -> None:
        self.assertEqual(
            first_paper_details(PAPER_REPLY), AstraP1PaperDetails(1, 15, 40, 42)
        )
        for length in (0, 1, 2, 3, 5, 8):
            self.assertIsNone(paper_details_from_frame(_frame(0x73, b"\x00" * length)))
        for command in range(256):
            if command not in STATUS_REPLY_COMMANDS:
                self.assertIsNone(status_from_frame(_frame(command, b"\x00" * 8)))
            if command != 0x73:
                self.assertIsNone(
                    paper_details_from_frame(_frame(command, b"\x00" * 4))
                )
        for data in (None, b"", b"noise", STATUS_REPLY[:-1]):
            self.assertIsNone(first_status(data))
            self.assertIsNone(first_paper_details(data))
        self.assertEqual(
            first_status(PAPER_REPLY + STATUS_REPLY), first_status(STATUS_REPLY)
        )
        self.assertEqual(
            first_paper_details(STATUS_REPLY + PAPER_REPLY),
            first_paper_details(PAPER_REPLY),
        )
        self.assertIsNone(first_status(STATUS_QUERY + PAPER_QUERY))
        self.assertIsNone(first_paper_details(STATUS_QUERY + PAPER_QUERY))


if __name__ == "__main__":
    unittest.main()
