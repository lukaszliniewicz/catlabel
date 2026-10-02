from __future__ import annotations

import unittest

from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.packet import (
    PrefixedPacketStreamDecoder,
    make_packet,
    prefixed_packet_length,
    prefixed_packet_payload,
)


class DeclaredPayloadTests(unittest.TestCase):
    def test_trailerless_accessor_does_not_make_a_complete_frame(self) -> None:
        packet = make_packet(0xAE, b"\x00\x01", ProtocolFamily.LEGACY)
        decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)
        for end in range(6, len(packet) - 2):
            self.assertIsNone(
                prefixed_packet_payload(packet[:end], ProtocolFamily.LEGACY)
            )
        trailerless = packet[:-2]
        self.assertEqual(
            prefixed_packet_payload(trailerless, ProtocolFamily.LEGACY), b"\x00\x01"
        )
        self.assertIsNone(prefixed_packet_length(trailerless, 0, ProtocolFamily.LEGACY))
        self.assertEqual(decoder.feed(trailerless), ())
        frames = decoder.feed(packet[-2:])
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].payload, b"\x00\x01")

    def test_zero_length_marker_and_wrong_prefix(self) -> None:
        marker = bytes.fromhex("2221a9000000")
        self.assertEqual(prefixed_packet_payload(marker, ProtocolFamily.V5X), b"")
        self.assertIsNone(prefixed_packet_length(marker, 0, ProtocolFamily.V5X))
        self.assertIsNone(prefixed_packet_payload(marker[:-1], ProtocolFamily.V5X))
        self.assertIsNone(prefixed_packet_payload(marker, ProtocolFamily.LEGACY))

    def test_accessor_ignores_trailer_but_decoder_rejects_corruption(self) -> None:
        packet = make_packet(0xAE, b"\x01", ProtocolFamily.LEGACY)
        corrupt = packet[:-2] + b"\x00\x00"
        self.assertEqual(
            prefixed_packet_payload(corrupt, ProtocolFamily.LEGACY), b"\x01"
        )
        decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)
        self.assertEqual(decoder.feed(corrupt), ())
        self.assertEqual(decoder.feed(packet)[0].raw, packet)


if __name__ == "__main__":
    unittest.main()
