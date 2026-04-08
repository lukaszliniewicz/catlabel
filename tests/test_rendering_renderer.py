from __future__ import annotations

import unittest

from PIL import Image

from timiniprint.protocol.types import PixelFormat
from timiniprint.rendering.renderer import image_to_bw_pixels, image_to_raster_set


class RenderingRendererTests(unittest.TestCase):
    def test_dither_mode_black_white_mapping(self) -> None:
        img = Image.new("1", (2, 1), 1)
        img.putpixel((0, 0), 0)
        out = image_to_bw_pixels(img, dither=True)
        self.assertEqual(out, [1, 0])

    def test_non_dither_threshold_from_average(self) -> None:
        img = Image.new("L", (4, 1))
        img.putdata([0, 100, 220, 255])
        out = image_to_bw_pixels(img, dither=False)
        self.assertEqual(len(out), 4)
        self.assertEqual(out[0], 1)
        self.assertEqual(out[-1], 0)

    def test_image_to_raster_set_builds_requested_formats_with_matching_dimensions(self) -> None:
        img = Image.new("L", (4, 2))
        img.putdata([0, 32, 128, 255, 16, 64, 192, 240])
        raster_set = image_to_raster_set(
            img,
            (PixelFormat.GRAY4, PixelFormat.GRAY8, PixelFormat.BW1),
            dither=False,
            gamma_handle=False,
        )

        self.assertEqual(raster_set.width, 4)
        self.assertEqual(raster_set.height, 2)
        self.assertEqual(raster_set.require(PixelFormat.GRAY4).pixel_format, PixelFormat.GRAY4)
        self.assertEqual(raster_set.require(PixelFormat.GRAY8).pixel_format, PixelFormat.GRAY8)
        self.assertEqual(raster_set.require(PixelFormat.BW1).pixel_format, PixelFormat.BW1)


if __name__ == "__main__":
    unittest.main()
