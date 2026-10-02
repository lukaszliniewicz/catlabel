from __future__ import annotations

import unittest
import zlib

from catlabel.protocol.families.luck_normal_core import LuckNormalBitmapEncoder
from catlabel.raster import PixelFormat, RasterBuffer


class LuckOddWidthTests(unittest.TestCase):
    def test_physical_dot_widths_pack_rows_separately_in_raw_and_compressed_jobs(
        self,
    ) -> None:
        # Independent edge-dot and filled-row vectors. The header counts bytes;
        # the unused low bits in each final byte stay white, never spill rows.
        for width, edge_row, filled_row in (
            (1, b"\x80", b"\x80"),
            (7, b"\x82", b"\xfe"),
            (8, b"\x81", b"\xff"),
            (9, b"\x80\x80", b"\xff\x80"),
            (15, b"\x80\x02", b"\xff\xfe"),
            (16, b"\x80\x01", b"\xff\xff"),
            (591, b"\x80" + bytes(72) + b"\x02", b"\xff" * 73 + b"\xfe"),
            (830, b"\x80" + bytes(102) + b"\x04", b"\xff" * 103 + b"\xfc"),
        ):
            with self.subTest(width=width):
                first = [0] * width
                first[0] = first[-1] = 1
                raster = RasterBuffer(first + [1] * width, width, PixelFormat.BW1)
                encoder = LuckNormalBitmapEncoder()
                raw = encoder._encode_raw(raster)
                compressed = encoder._encode_compressed(raster)
                width_bytes = len(edge_row)
                self.assertEqual(
                    raw[:8],
                    b"\x1d\x76\x30\x00"
                    + width_bytes.to_bytes(2, "little")
                    + b"\x02\x00",
                )
                self.assertEqual(raw[8:], edge_row + filled_row)
                self.assertEqual(
                    compressed[:6],
                    b"\x1f\x10" + width_bytes.to_bytes(2, "big") + b"\x00\x02",
                )
                self.assertEqual(
                    int.from_bytes(compressed[6:10], "big"), len(compressed[10:])
                )
                self.assertEqual(
                    zlib.decompress(compressed[10:]), edge_row + filled_row
                )


if __name__ == "__main__":
    unittest.main()
