from __future__ import annotations

import unittest

from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.packet import PrefixedPacketStreamDecoder, make_packet


class PrefixedPacketOffsetTests(unittest.TestCase):
    def test_fragmented_packet_offset_includes_preceding_noise(self) -> None:
        decoder = PrefixedPacketStreamDecoder(ProtocolFamily.V5C)
        packet = make_packet(0xA1, b"\x00", ProtocolFamily.V5C)

        self.assertEqual(decoder.feed(b"junk" + packet[:1]), ())
        decoded = decoder.feed(packet[1:])

        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0].raw, packet)
        self.assertEqual(decoded[0].start_offset, 4)
        self.assertEqual(decoder.received_byte_count, 4 + len(packet))

    def test_coalesced_frames_have_absolute_start_offsets(self) -> None:
        decoder = PrefixedPacketStreamDecoder(ProtocolFamily.V5C)
        first = make_packet(0xA1, b"\x80", ProtocolFamily.V5C)
        second = make_packet(0xA1, b"\x00", ProtocolFamily.V5C)

        decoded = decoder.feed(b"xyz" + first + second)

        self.assertEqual([packet.raw for packet in decoded], [first, second])
        self.assertEqual(
            [packet.start_offset for packet in decoded],
            [3, 3 + len(first)],
        )
        self.assertEqual(decoder.received_byte_count, 3 + len(first) + len(second))

    def test_invalid_crc_frame_is_skipped_without_shifting_next_offset(self) -> None:
        decoder = PrefixedPacketStreamDecoder(ProtocolFamily.V5C)
        invalid = bytearray(make_packet(0xA1, b"\x01", ProtocolFamily.V5C))
        invalid[-2] ^= 0x01
        valid = make_packet(0xA1, b"\x00", ProtocolFamily.V5C)

        decoded = decoder.feed(bytes(invalid) + valid)

        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0].raw, valid)
        self.assertEqual(decoded[0].start_offset, len(invalid))
        self.assertEqual(decoder.received_byte_count, len(invalid) + len(valid))

    def test_partial_prefix_and_junk_are_counted_before_later_frame(self) -> None:
        decoder = PrefixedPacketStreamDecoder(ProtocolFamily.V5C)
        packet = make_packet(0xA1, b"\x00", ProtocolFamily.V5C)

        self.assertEqual(decoder.feed(b"junk\x56"), ())
        decoded = decoder.feed(packet[1:])

        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0].start_offset, 4)
        self.assertEqual(decoder.pending, b"")


if __name__ == "__main__":
    unittest.main()
