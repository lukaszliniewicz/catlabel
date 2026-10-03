from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from PIL import Image

from catlabel.rendering import renderer


class GrayPreprocessingTests(unittest.TestCase):
    def test_recorded_gradients_keep_exact_pixels_with_one_alpha_scan(self) -> None:
        cases = (
            (
                384,
                384,
                True,
                "4372e40c907193132f3b79cc01e7b816511c5273b52946c2052e52a145037d7e",
            ),
            (
                384,
                384,
                False,
                "7b479bdc3e4b73aee2d3def14e2d43213d475b5a359eb94251ccb10fcf39107e",
            ),
            (
                816,
                1218,
                True,
                "9f4fa8f11499c3969577cfcfbbb1256681225fc241624c994683ec743e9447ea",
            ),
            (
                816,
                1218,
                False,
                "221cd8e110a23f4459f686f7019987fa0bb306e9a61537b89a469055fbd5391e",
            ),
        )
        for width, height, horizontal, expected in cases:
            with self.subTest(width=width, height=height, horizontal=horizontal):
                pixels = bytes(
                    (x * 255 // (width - 1))
                    if horizontal
                    else (y * 255 // (height - 1))
                    for y in range(height)
                    for x in range(width)
                    for _channel in range(3)
                )
                with Image.frombytes("RGB", (width, height), pixels) as image:
                    with (
                        patch.object(
                            renderer,
                            "_gray_enhance_alpha",
                            wraps=renderer._gray_enhance_alpha,
                        ) as alpha,
                        renderer._preprocess_gray_image(image) as output,
                    ):
                        self.assertEqual(output.mode, "L")
                        self.assertEqual(output.size, (width, height))
                        self.assertEqual(
                            hashlib.sha256(output.tobytes()).hexdigest(), expected
                        )
                    alpha.assert_called_once()
