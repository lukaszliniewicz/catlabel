from __future__ import annotations

import unittest
import warnings
from unittest.mock import patch

from PIL import Image, ImageFont

from catlabel.rendering.converters.base import RasterConverter
from catlabel.rendering.converters.pdf import PdfConverter
from catlabel.rendering.converters.text import TextConverter
from catlabel.rendering.renderer import _flattened_data


class RenderingContractTests(unittest.TestCase):
    def test_flattened_data_matches_scalar_pixels_for_l_and_1(self) -> None:
        for mode, pixels in (("L", [0, 41, 128, 255]), ("1", [0, 255, 0, 255])):
            with self.subTest(mode=mode):
                image = Image.new(mode, (2, 2))
                image.putdata(pixels)

                self.assertEqual(list(_flattened_data(image)), pixels)

                with (
                    patch.object(
                        Image.Image,
                        "get_flattened_data",
                        None,
                        create=True,
                    ),
                    warnings.catch_warnings(),
                ):
                    warnings.simplefilter("ignore", DeprecationWarning)
                    self.assertEqual(list(_flattened_data(image)), pixels)

    def test_flattened_data_rejects_rgb_images(self) -> None:
        with self.assertRaisesRegex(ValueError, "mode 'L' or '1'"):
            _flattened_data(Image.new("RGB", (1, 1)))

    def test_default_font_renders_text_and_uses_its_metrics(self) -> None:
        converter = TextConverter()
        with patch(
            "catlabel.rendering.converters.text.find_monospace_bold_font",
            return_value=None,
        ):
            image = converter._render_text_image("Default font", 96)

        font = ImageFont.load_default()
        if isinstance(font, ImageFont.FreeTypeFont):
            expected_line_height = sum(font.getmetrics())
        else:
            bbox = font.getbbox("Ag")
            expected_line_height = int(bbox[3] - bbox[1])
        lines = converter._wrap_text_lines("Default font", 96, font)

        self.assertEqual(image.mode, "1")
        self.assertEqual(image.width, 96)
        self.assertEqual(image.height, expected_line_height * len(lines))
        self.assertEqual(
            TextConverter._text_width(font, "Ag"), int(font.getlength("Ag"))
        )
        self.assertEqual(TextConverter._font_line_height(font), expected_line_height)

    def test_margin_threshold_remains_strictly_less_than(self) -> None:
        image = Image.new("L", (6, 5), 255)
        image.putpixel((2, 2), 244)
        image.putpixel((3, 2), 244)
        image.putpixel((4, 2), 245)
        converter = RasterConverter(
            trim_side_margins=True,
            trim_top_bottom_margins=False,
        )

        self.assertEqual(converter._trim_margins_image(image).size, (2, 5))

    def test_pdf_bitmap_to_pil_must_return_an_image(self) -> None:
        class MalformedBitmap:
            def to_pil(self) -> object:
                return object()

        class PdfPage:
            def render(self, *, scale: float) -> MalformedBitmap:
                del scale
                return MalformedBitmap()

        with self.assertRaisesRegex(
            RuntimeError,
            "pypdfium2 render did not return a PIL image",
        ):
            PdfConverter._render_page_to_pil(PdfPage(), 1.0)


if __name__ == "__main__":
    unittest.main()
