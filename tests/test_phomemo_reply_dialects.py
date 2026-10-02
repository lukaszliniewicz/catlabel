from __future__ import annotations

import unittest

from catlabel.protocol.families import (
    phomemo_replies,
)

DecodedReply = phomemo_replies.DecodedReply
PhomemoReplyDecoder = phomemo_replies.PhomemoReplyDecoder
PrintMasterReplyDecoder = phomemo_replies.PrintMasterReplyDecoder

_PHOMEMO_FRAMES = (
    bytes.fromhex("03a8"),
    bytes.fromhex("040f"),
    bytes.fromhex("0598"),
    bytes.fromhex("0600"),
    bytes.fromhex("071a0f0c"),
    b"\x08Q194" + bytes.fromhex("1a0f0c1b05991a06880000"),
    bytes.fromhex("0901"),
    bytes.fromhex("0bb8"),
    bytes.fromhex("0e02"),
    bytes.fromhex("0f0c"),
    bytes.fromhex("1601"),
    bytes.fromhex("1703"),
    bytes.fromhex("1d02"),
    bytes.fromhex("2001"),
    bytes.fromhex("3500"),
    bytes.fromhex("3b00041a0f0c"),
)

_PRINTMASTER_FRAMES = (
    bytes.fromhex("03a8"),
    bytes.fromhex("040f"),
    bytes.fromhex("0598"),
    bytes.fromhex("0600"),
    bytes.fromhex("071a0f0c"),
    b"\x08Q194" + bytes.fromhex("1a0f0c1b05881a06990000"),
    bytes.fromhex("0bb8"),
    bytes.fromhex("0c26"),
    bytes.fromhex("0f0c"),
    bytes.fromhex("15020f0c"),
    bytes.fromhex("1703"),
    bytes.fromhex("31021a0f"),
    bytes.fromhex("3b1a0f0c"),
    bytes.fromhex("3e00"),
    bytes.fromhex("3f02"),
    bytes.fromhex("4012340200070903021a0f0c00301e"),
)


class PhomemoReplyDialectTests(unittest.TestCase):
    def _assert_every_split_and_bytewise(
        self,
        decoder_type: type[PhomemoReplyDecoder] | type[PrintMasterReplyDecoder],
        frames: tuple[bytes, ...],
        prefixes: tuple[bytes, ...],
    ) -> None:
        for frame in frames:
            for prefix in prefixes:
                wire = prefix + frame
                expected = [DecodedReply(frame, 0)]
                for split in range(len(wire) + 1):
                    with self.subTest(
                        frame=frame.hex(), prefix=prefix.hex(), split=split
                    ):
                        decoder = decoder_type()
                        replies = decoder.feed_with_offsets(
                            wire[:split]
                        ) + decoder.feed_with_offsets(wire[split:])
                        self.assertEqual(replies, expected)
                        self.assertEqual(decoder.received_byte_count, len(wire))
                        self.assertFalse(decoder.has_pending_frame)
                        self.assertEqual(decoder.pending_byte_count, 0)

                decoder = decoder_type()
                bytewise = [
                    reply
                    for value in wire
                    for reply in decoder.feed_with_offsets(bytes((value,)))
                ]
                self.assertEqual(bytewise, expected)
                self.assertEqual(decoder.feed(b""), [])
                self.assertEqual(decoder.received_byte_count, len(wire))

    def test_every_phomemo_frame_length_survives_all_splits(self) -> None:
        self._assert_every_split_and_bytewise(
            PhomemoReplyDecoder,
            _PHOMEMO_FRAMES,
            (b"\x1a",),
        )

    def test_every_printmaster_frame_length_survives_all_prefixes_and_splits(
        self,
    ) -> None:
        self._assert_every_split_and_bytewise(
            PrintMasterReplyDecoder,
            _PRINTMASTER_FRAMES,
            (b"", b"\x1a", b"\x1b"),
        )

    def test_dialects_do_not_accept_each_others_prefix_policy(self) -> None:
        phomemo = PhomemoReplyDecoder()
        self.assertEqual(phomemo.feed(bytes.fromhex("05991b0599")), [])
        self.assertFalse(phomemo.has_pending_frame)

        printmaster = PrintMasterReplyDecoder()
        replies = printmaster.feed_with_offsets(bytes.fromhex("1b05990599"))
        self.assertEqual(
            replies,
            [
                DecodedReply(bytes.fromhex("0599"), 0),
                DecodedReply(bytes.fromhex("0599"), 3),
            ],
        )

    def test_unknown_bytes_resynchronize_and_offsets_include_wire_prefixes(
        self,
    ) -> None:
        phomemo = PhomemoReplyDecoder()
        self.assertEqual(
            phomemo.feed_with_offsets(bytes.fromhex("fffe1b05991a")),
            [],
        )
        self.assertEqual(phomemo.pending_byte_count, 1)
        self.assertEqual(
            phomemo.feed_with_offsets(bytes.fromhex("050077")),
            [DecodedReply(bytes.fromhex("0500"), 5)],
        )
        self.assertEqual(phomemo.received_byte_count, 9)
        self.assertEqual(
            phomemo.feed(bytes.fromhex("ff1a05aa")), [bytes.fromhex("05aa")]
        )
        self.assertEqual(phomemo.received_byte_count, 13)

        printmaster = PrintMasterReplyDecoder()
        self.assertEqual(printmaster.feed_with_offsets(bytes.fromhex("ff1b071a")), [])
        self.assertEqual(printmaster.pending_byte_count, 3)
        self.assertEqual(
            printmaster.feed_with_offsets(bytes.fromhex("0f0c0599")),
            [
                DecodedReply(bytes.fromhex("071a0f0c"), 1),
                DecodedReply(bytes.fromhex("0599"), 6),
            ],
        )
        self.assertEqual(printmaster.received_byte_count, 8)

    def test_opaque_frames_keep_embedded_completion_and_fault_bytes(self) -> None:
        vectors = (
            (
                PhomemoReplyDecoder,
                b"\x08Q194" + bytes.fromhex("1a0f0c1b05991a06880000"),
                b"\x1a",
            ),
            (
                PrintMasterReplyDecoder,
                bytes.fromhex("4012340200070903021a0f0c00301e"),
                b"\x1b",
            ),
            (
                PrintMasterReplyDecoder,
                bytes.fromhex("071a0f0c"),
                b"",
            ),
        )
        for decoder_type, frame, prefix in vectors:
            with self.subTest(frame=frame.hex(), prefix=prefix.hex()):
                decoder = decoder_type()
                wire = prefix + frame
                self.assertEqual(decoder.feed(wire), [frame])
                self.assertEqual(decoder.pending_byte_count, 0)

    def test_incomplete_recognized_frame_survives_empty_feed_and_is_bounded(
        self,
    ) -> None:
        frame = b"\x08Q194" + bytes.fromhex("1a0f0c1b05991a06880000")
        decoder = PhomemoReplyDecoder()
        prefix = b"\xff" * 100 + b"\x1a" + frame[:-1]
        self.assertEqual(decoder.feed(prefix), [])
        self.assertTrue(decoder.has_pending_frame)
        self.assertEqual(decoder.pending_byte_count, 1 + len(frame) - 1)
        self.assertLessEqual(decoder.pending_byte_count, 17)
        self.assertEqual(decoder.feed(b""), [])
        self.assertTrue(decoder.has_pending_frame)
        self.assertEqual(decoder.feed(frame[-1:]), [frame])
        self.assertFalse(decoder.has_pending_frame)
        self.assertEqual(decoder.pending_byte_count, 0)


if __name__ == "__main__":
    _ = unittest.main()
