from __future__ import annotations

import unittest
from unittest.mock import patch

from PIL import Image, ImageOps

from catlabel.protocol.encoding import pack_line
from catlabel.raster import PixelFormat, RasterBuffer
from catlabel.vendors.phomemo.client import PhomemoClient


def _expected_row_bytes(row: list[int]) -> bytes:
    packed = bytearray()
    for start in range(0, len(row), 8):
        value = 0
        for offset, pixel in enumerate(row[start : start + 8]):
            value |= pixel << (7 - offset)
        packed.append(value)
    return bytes(packed)


class PhomemoRasterTests(unittest.TestCase):
    def _client(self) -> PhomemoClient:
        return object.__new__(PhomemoClient)

    def test_partial_width_rows_are_packed_independently_msb_first(self) -> None:
        for width in (1, 7, 8, 9, 15, 16):
            with self.subTest(width=width):
                rows = [
                    [int(index % 2 == 0) for index in range(width)],
                    [int(index % 3 == 0) for index in range(width)],
                    [int(index % 2 == 1) for index in range(width)],
                ]
                pixels = [pixel for row in rows for pixel in row]
                raster = RasterBuffer(pixels=pixels, width=width)
                image = Image.new("L", (width, len(rows)))

                with patch(
                    "catlabel.vendors.phomemo.client.image_to_raster",
                    return_value=raster,
                ) as render:
                    result = self._client()._render_to_raster(image, dither=False)

                expected_width_bytes = (width + 7) // 8
                expected_data = b"".join(_expected_row_bytes(row) for row in rows)
                self.assertEqual(
                    result,
                    (expected_data, expected_width_bytes, len(rows)),
                )
                self.assertEqual(len(result[0]), expected_width_bytes * len(rows))
                render.assert_called_once()
                rendered_image, pixel_format = render.call_args.args
                self.assertIs(rendered_image, image)
                self.assertIs(pixel_format, PixelFormat.BW1)
                self.assertFalse(render.call_args.kwargs["dither"])

                remainder = width % 8
                if remainder:
                    padding_mask = (1 << (8 - remainder)) - 1
                    for row_index in range(len(rows)):
                        final_byte = result[0][
                            row_index * expected_width_bytes + expected_width_bytes - 1
                        ]
                        self.assertEqual(final_byte & padding_mask, 0)

    def test_divisible_widths_match_the_original_flat_pack(self) -> None:
        for width in (8, 16):
            with self.subTest(width=width):
                height = 3
                pixels = [
                    int((index * 7 + index // width) % 5 < 2)
                    for index in range(width * height)
                ]
                raster = RasterBuffer(pixels=pixels, width=width)
                image = Image.new("L", (width, height))

                with patch(
                    "catlabel.vendors.phomemo.client.image_to_raster",
                    return_value=raster,
                ):
                    packed, width_bytes, result_height = (
                        self._client()._render_to_raster(image)
                    )

                self.assertEqual(
                    packed, pack_line(list(raster.pixels), lsb_first=False)
                )
                self.assertEqual(width_bytes, width // 8)
                self.assertEqual(result_height, height)

    def test_clockwise_rotation_is_applied_before_raster_conversion(self) -> None:
        image = Image.new("L", (2, 3))
        image.putdata([0, 40, 80, 120, 160, 200])
        expected = image.rotate(-90, expand=True)
        received: list[tuple[Image.Image, PixelFormat, bool]] = []

        def rasterize(
            rendered_image: Image.Image,
            pixel_format: PixelFormat,
            *,
            dither: bool,
        ) -> RasterBuffer:
            received.append((rendered_image.copy(), pixel_format, dither))
            return RasterBuffer(
                pixels=[0] * (rendered_image.width * rendered_image.height),
                width=rendered_image.width,
                pixel_format=pixel_format,
            )

        with patch(
            "catlabel.vendors.phomemo.client.image_to_raster",
            side_effect=rasterize,
        ):
            result = self._client()._render_to_raster(
                image,
                rotate_cw=True,
                dither=False,
            )

        self.assertEqual(len(received), 1)
        received_image, pixel_format, dither = received[0]
        self.assertEqual(received_image.size, (3, 2))
        self.assertEqual(received_image.tobytes(), expected.tobytes())
        self.assertIs(pixel_format, PixelFormat.BW1)
        self.assertFalse(dither)
        self.assertEqual(result[1:], (1, 2))

    def test_inversion_and_dither_are_forwarded_to_raster_conversion(self) -> None:
        image = Image.new("RGB", (3, 2))
        image.putdata(
            [
                (0, 10, 20),
                (30, 40, 50),
                (60, 70, 80),
                (90, 100, 110),
                (120, 130, 140),
                (150, 160, 170),
            ]
        )
        expected = ImageOps.invert(image.convert("L"))
        received: list[tuple[Image.Image, PixelFormat, bool]] = []

        def rasterize(
            rendered_image: Image.Image,
            pixel_format: PixelFormat,
            *,
            dither: bool,
        ) -> RasterBuffer:
            received.append((rendered_image.copy(), pixel_format, dither))
            return RasterBuffer(
                pixels=[0] * (rendered_image.width * rendered_image.height),
                width=rendered_image.width,
                pixel_format=pixel_format,
            )

        with patch(
            "catlabel.vendors.phomemo.client.image_to_raster",
            side_effect=rasterize,
        ):
            result = self._client()._render_to_raster(
                image,
                invert=True,
                dither=False,
            )

        self.assertEqual(len(received), 1)
        received_image, pixel_format, dither = received[0]
        self.assertEqual(received_image.mode, "L")
        self.assertEqual(received_image.tobytes(), expected.tobytes())
        self.assertIs(pixel_format, PixelFormat.BW1)
        self.assertFalse(dither)
        self.assertEqual(result[1:], (1, 2))


if __name__ == "__main__":
    unittest.main()
