from __future__ import annotations

import unittest
from collections.abc import Iterator
from unittest.mock import patch

from catlabel.protocol.families import phomemo_esc_core as recipes
from catlabel.protocol.types import PaperMode
from catlabel.raster import PixelFormat, RasterBuffer

_COMPACT_SETUP = bytes.fromhex("1b40 1f110202 1f113764 1f110b 1f113500")
_COMPACT_FEED = bytes.fromhex("1b6402")


def _edge_raster(width: int, height: int = 2) -> RasterBuffer:
    pixels = [0] * (width * height)
    pixels[0] = 1
    pixels[-1] = 1
    return RasterBuffer(pixels, width, PixelFormat.BW1)


def _expected_raster_block(
    width: int,
    height: int,
    *,
    wire_width: int,
    left_padding: int,
) -> bytes:
    row_bytes = (wire_width + 7) // 8
    rows = bytearray(row_bytes * height)
    rows[left_padding // 8] |= 1 << (7 - left_padding % 8)
    last_pixel = left_padding + width - 1
    rows[(height - 1) * row_bytes + last_pixel // 8] |= 1 << (7 - last_pixel % 8)
    return (
        bytes.fromhex("1d763000")
        + row_bytes.to_bytes(2, "little")
        + height.to_bytes(2, "little")
        + rows
    )


class PhomemoReleasedRecipeTests(unittest.TestCase):
    def test_m02_complete_page_matches_literal_wire_vector(self) -> None:
        raster = RasterBuffer(
            [1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0],
            width=8,
        )
        self.assertEqual(
            recipes.build_released_page(raster, variant="m02"),
            bytes.fromhex(
                "1b401f1102021f1137641f110b1f1135001d76300002000200080004001b64021b6402"
            ),
        )

    def test_compact_placement_preserves_odd_width_rows_and_tag_padding(self) -> None:
        fixtures = {
            "m02": (384, 4, 0, (PaperMode.PLAIN, PaperMode.TAG)),
            "m02s": (576, 4, 12, (PaperMode.PLAIN, PaperMode.TAG)),
            "m02_pro": (576, 4, 7, (PaperMode.PLAIN, PaperMode.TAG)),
            "t02": (384, 4, 0, (PaperMode.PLAIN, PaperMode.TAG)),
            "m110": (384, 0, 0, (PaperMode.TAG, PaperMode.PLAIN, PaperMode.BLACK_TAG)),
            "m220": (576, 0, 0, (PaperMode.TAG, PaperMode.PLAIN, PaperMode.BLACK_TAG)),
        }
        widths = (1, 7, 17, 383, 384, 575, 576)
        for variant, (maximum, left, tag_extra, modes) in fixtures.items():
            for width in widths:
                if width > maximum:
                    continue
                for mode in modes:
                    with self.subTest(variant=variant, width=width, mode=mode):
                        right = (
                            maximum + tag_extra - width
                            if mode is PaperMode.TAG and tag_extra
                            else 0
                        )
                        wire_width = left + width + right
                        media = 0x26 if mode is PaperMode.BLACK_TAG else 0x0B
                        setup = _COMPACT_SETUP.replace(
                            bytes.fromhex("1f110b"), bytes((0x1F, 0x11, media))
                        )
                        page = recipes.build_released_page(
                            _edge_raster(width),
                            variant=variant,
                            paper_mode=mode,
                        )
                        block = _expected_raster_block(
                            width,
                            2,
                            wire_width=wire_width,
                            left_padding=left,
                        )
                        self.assertEqual(page, setup + block + _COMPACT_FEED * 2)

    def test_size_planner_returns_logical_geometry_and_checks_resource_limits(
        self,
    ) -> None:
        self.assertEqual(
            recipes.plan_released_raster_size(8, 2, variant="m02"),
            (12, 2),
        )
        self.assertEqual(
            recipes.plan_released_raster_size(8, 2, variant="m02s"),
            (12, 2),
        )
        self.assertEqual(
            recipes.plan_released_raster_size(
                8,
                2,
                variant="m02s",
                paper_mode=PaperMode.TAG,
            ),
            (592, 2),
        )
        self.assertEqual(
            recipes.plan_released_raster_size(
                8,
                2,
                variant="m02_pro",
                paper_mode=PaperMode.TAG,
            ),
            (587, 2),
        )
        self.assertEqual(
            recipes.plan_released_raster_size(
                1000,
                2,
                variant="m02x",
                paper_mode=PaperMode.PLAIN,
            ),
            (1000, 2),
        )

        for width, height in ((0, 2), (8, 0), (True, 2), (8, -1)):
            with (
                self.subTest(width=width, height=height),
                self.assertRaises(ValueError),
            ):
                recipes.plan_released_raster_size(
                    width,
                    height,
                    variant="m02",  # type: ignore[arg-type]
                )

    def test_density_media_channels_and_page_feed_precedence(self) -> None:
        density_wire = (
            (None, 2, 100),
            (-10, 1, 100),
            (1, 1, 100),
            (2, 2, 100),
            (3, 4, 100),
            (4, 4, 150),
            (9, 4, 150),
        )
        raster = RasterBuffer([0] * 8, width=8)
        for variant in ("m02", "m02s", "m02_pro", "t02", "m110", "m220"):
            for level, density, coefficient in density_wire:
                with self.subTest(variant=variant, density=level):
                    page = recipes.build_released_page(
                        raster,
                        variant=variant,
                        density=level,
                        paper_mode=PaperMode.BLACK_TAG
                        if variant in ("m110", "m220")
                        else PaperMode.PLAIN,
                    )
                    expected_density = bytes((density,))
                    expected_coefficient = bytes((coefficient,))
                    self.assertIn(
                        b"\x1f\x11\x02"
                        + expected_density
                        + b"\x1f\x117"
                        + expected_coefficient,
                        page,
                    )

        black_tag = recipes.build_released_page(
            raster, variant="m110", paper_mode=PaperMode.BLACK_TAG
        )
        plain = recipes.build_released_page(
            raster, variant="m110", paper_mode=PaperMode.PLAIN
        )
        tag = recipes.build_released_page(
            raster, variant="m110", paper_mode=PaperMode.TAG
        )
        default_mode = recipes.build_released_page(raster, variant="m110")
        for page, media in ((black_tag, 0x26), (plain, 0x0B), (tag, 0x0B)):
            self.assertIn(bytes((0x1F, 0x11, media)), page)
        self.assertIn(bytes.fromhex("1f110b"), default_mode)

        intermediate = recipes.build_released_page(
            raster,
            variant="m02",
            is_first_page=False,
            is_last_page=False,
            ends_media_page=True,
        )
        self.assertEqual(intermediate, bytes.fromhex("1d763000020001000000 1b6402"))
        final_without_media_end = recipes.build_released_page(
            raster,
            variant="m02",
            is_first_page=False,
            is_last_page=True,
            ends_media_page=False,
        )
        self.assertEqual(
            final_without_media_end,
            bytes.fromhex("1d763000020001000000 1b6402 1b6402"),
        )
        neither = recipes.build_released_page(
            raster,
            variant="m02",
            is_first_page=False,
            is_last_page=False,
            ends_media_page=False,
        )
        self.assertEqual(neither, bytes.fromhex("1d763000020001000000"))

    def test_m02x_uses_esc_setup_each_page_raw_density_and_one_feed_command(
        self,
    ) -> None:
        raster = RasterBuffer([1] + [0] * 7, width=8)
        page = recipes.build_released_page(
            raster,
            variant="m02x",
            density=17,
            is_first_page=False,
            is_last_page=True,
            ends_media_page=True,
            post_print_feed_count=3,
        )
        self.assertEqual(
            page,
            bytes.fromhex("1b401b61011f110211 1d7630000100010080 1b6403"),
        )

        no_feed = recipes.build_released_page(
            raster,
            variant="m02x",
            is_last_page=True,
            ends_media_page=False,
        )
        self.assertEqual(
            no_feed,
            bytes.fromhex("1b401b61011f110204 1d7630000100010080"),
        )
        clamped = recipes.build_released_page(
            raster,
            variant="m02x",
            density=300,
            ends_media_page=True,
            post_print_feed_count=300,
        )
        self.assertEqual(clamped[:9], bytes.fromhex("1b401b61011f1102ff"))
        self.assertTrue(clamped.endswith(b"\x1b\x64\xff"))

    def test_compact_page_splits_256_rows_once_and_m02x_splits_them_twice(self) -> None:
        raster = RasterBuffer([0] * (8 * 256), width=8)
        compact = recipes.build_released_page(raster, variant="m02")
        self.assertEqual(
            compact,
            _COMPACT_SETUP
            + bytes.fromhex("1d76300002000001")
            + bytes(512)
            + _COMPACT_FEED * 2,
        )

        m02x = recipes.build_released_page(raster, variant="m02x")
        self.assertEqual(
            m02x,
            bytes.fromhex("1b401b61011f110204")
            + bytes.fromhex("1d7630000100ff00")
            + bytes(255)
            + bytes.fromhex("1d76300001000100")
            + b"\x00",
        )

    def test_invalid_rasters_variants_modes_and_printmaster_variants_reject(
        self,
    ) -> None:
        invalid_rasters = (
            RasterBuffer([], width=8),
            RasterBuffer([0] * 7, width=8),
            RasterBuffer([0, 2, 0, 0, 0, 0, 0, 0], width=8),
            RasterBuffer([0] * 8, width=8, pixel_format=PixelFormat.GRAY8),
            RasterBuffer([0] * 385, width=385),
        )
        for raster in invalid_rasters:
            with self.subTest(raster=raster), self.assertRaises(ValueError):
                recipes.build_released_page(raster, variant="m02")

        for variant in ("unknown", "printmaster_m110", "printmaster_m120"):
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                recipes.build_released_page(
                    RasterBuffer([0] * 8, width=8), variant=variant
                )

        for variant, mode in (
            ("m02", PaperMode.BLACK_TAG),
            ("m02s", PaperMode.BLACK_TAG),
            ("m02_pro", PaperMode.BLACK_TAG),
            ("t02", PaperMode.BLACK_TAG),
            ("m02x", PaperMode.TAG),
            ("m110", PaperMode.A4_SHEET),
        ):
            with (
                self.subTest(variant=variant, mode=mode),
                self.assertRaises(ValueError),
            ):
                recipes.build_released_page(
                    RasterBuffer([0] * 8, width=8),
                    variant=variant,
                    paper_mode=mode,
                )

        with self.assertRaisesRegex(ValueError, "content width"):
            recipes.build_released_page(
                RasterBuffer([0] * 385, width=385), variant="m02"
            )

    def test_input_pixels_remain_unchanged_and_budget_preflight_precedes_scanning(
        self,
    ) -> None:
        class UnscannablePixels(list[int]):
            def __iter__(self) -> Iterator[int]:
                raise AssertionError(
                    "pixels must not be scanned before budget preflight"
                )

        raster = RasterBuffer(UnscannablePixels([0] * 16), width=8)
        with (
            patch.object(
                recipes,
                "validate_image_budget",
                side_effect=MemoryError("input budget"),
            ),
            self.assertRaisesRegex(MemoryError, "input budget"),
        ):
            recipes.build_released_page(raster, variant="m02")

        calls: list[tuple[int, int]] = []

        def reject_padded_size(width: int, height: int) -> int:
            calls.append((width, height))
            if len(calls) == 2:
                raise MemoryError("padded budget")
            return width * height

        with (
            patch.object(
                recipes, "validate_image_budget", side_effect=reject_padded_size
            ),
            self.assertRaisesRegex(MemoryError, "padded budget"),
        ):
            recipes.build_released_page(raster, variant="m02")
        self.assertEqual(calls, [(8, 2), (12, 2)])

        pixels = [1, 0, 0, 0, 0, 0, 0, 0]
        before = pixels.copy()
        recipes.build_released_page(RasterBuffer(pixels, width=8), variant="m02")
        self.assertEqual(pixels, before)


if __name__ == "__main__":
    unittest.main()
