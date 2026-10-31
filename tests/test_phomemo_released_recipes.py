from __future__ import annotations

import unittest
from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import patch

from catlabel.core.resource_limits import MAX_DIMENSION
from catlabel.protocol.families import phomemo_esc_core as recipes
from catlabel.protocol.types import PaperMode
from catlabel.raster import PixelFormat, RasterBuffer

_SETUP_PREFIX = bytes.fromhex("1b40 1f1102")
_COEFFICIENT = bytes.fromhex("1f1137")
_MEDIA = bytes.fromhex("1f11")
_UNCOMPRESSED = bytes.fromhex("1f113500")
_COMPACT_FEED = bytes.fromhex("1b6402")
_DENSITY_LEVELS = ((1, 100), (2, 100), (4, 100), (4, 150))


@dataclass(frozen=True)
class _WireSpec:
    content_width: int
    top_padding: int
    paper_modes: tuple[PaperMode, ...]
    tag_total_width: int | None = None


_WIRE_SPECS = {
    "m02": _WireSpec(384, 4, (PaperMode.PLAIN, PaperMode.TAG)),
    "m02s": _WireSpec(
        576,
        4,
        (PaperMode.PLAIN, PaperMode.TAG),
        tag_total_width=588,
    ),
    "m02_pro": _WireSpec(
        576,
        4,
        (PaperMode.PLAIN, PaperMode.TAG),
        tag_total_width=583,
    ),
    "t02": _WireSpec(384, 4, (PaperMode.PLAIN, PaperMode.TAG)),
    "m02x": _WireSpec(384, 4, (PaperMode.PLAIN,)),
    "m110": _WireSpec(
        384,
        0,
        (PaperMode.TAG, PaperMode.PLAIN, PaperMode.BLACK_TAG),
    ),
    "m220": _WireSpec(
        576,
        0,
        (PaperMode.TAG, PaperMode.PLAIN, PaperMode.BLACK_TAG),
    ),
}


def _wire_setup(
    *,
    density: int | None,
    paper_mode: PaperMode,
) -> bytes:
    level = 2 if density is None else max(1, min(4, int(density)))
    density_value, coefficient = _DENSITY_LEVELS[level - 1]
    media_value = 0x26 if paper_mode is PaperMode.BLACK_TAG else 0x0B
    return (
        _SETUP_PREFIX
        + bytes((density_value,))
        + _COEFFICIENT
        + bytes((coefficient,))
        + _MEDIA
        + bytes((media_value,))
        + _UNCOMPRESSED
    )


def _expected_page(
    pixels: list[int],
    width: int,
    height: int,
    *,
    variant: str,
    paper_mode: PaperMode,
    density: int | None = None,
    is_first_page: bool = True,
    is_last_page: bool = True,
    ends_media_page: bool = True,
) -> bytes:
    """Encode a literal protocol expectation without using production helpers."""
    spec = _WIRE_SPECS[variant]
    output_width = width
    left_padding = 0
    if paper_mode is PaperMode.TAG and spec.tag_total_width is not None:
        output_width = spec.tag_total_width
        left_padding = output_width - width

    output_height = height + spec.top_padding
    bytes_per_row = (output_width + 7) // 8
    packed_rows = bytearray(bytes_per_row * output_height)
    for source_index, value in enumerate(pixels):
        if value:
            source_y, source_x = divmod(source_index, width)
            output_y = source_y + spec.top_padding
            output_x = source_x + left_padding
            offset = output_y * bytes_per_row + output_x // 8
            packed_rows[offset] |= 1 << (7 - output_x % 8)

    payload = bytearray()
    if is_first_page:
        payload += _wire_setup(density=density, paper_mode=paper_mode)

    for first_row in range(0, output_height, 0xFFFF):
        block_height = min(0xFFFF, output_height - first_row)
        payload += bytes.fromhex("1d763000")
        payload += bytes_per_row.to_bytes(2, "little")
        payload += block_height.to_bytes(2, "little")
        first_byte = first_row * bytes_per_row
        final_byte = (first_row + block_height) * bytes_per_row
        payload += packed_rows[first_byte:final_byte]

    if is_last_page:
        payload += _COMPACT_FEED * 2
    elif ends_media_page:
        payload += _COMPACT_FEED
    return bytes(payload)


def _pattern_pixels(width: int, pattern: str) -> list[int]:
    pixels = [0] * (width * 3)
    if pattern == "black":
        return [1] * len(pixels)
    if pattern == "asymmetric_edges":
        pixels[0] = 1
        pixels[width + width - 1] = 1
        pixels[2 * width + width // 2] = 1
    if pattern not in {"white", "black", "asymmetric_edges"}:
        raise AssertionError(f"Unknown raster pattern: {pattern}")
    return pixels


class PhomemoReleasedRecipeTests(unittest.TestCase):
    def test_m02_complete_page_matches_literal_current_wire_vector(self) -> None:
        pixels = [1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]
        raster = RasterBuffer(pixels, width=8)
        self.assertEqual(
            recipes.build_released_page(raster, variant="m02"),
            bytes.fromhex(
                "1b401f1102021f1137641f110b1f113500"
                "1d76300001000600000000008040"
                "1b64021b6402"
            ),
        )

    def test_compact_whole_payload_fixtures_cover_widths_modes_and_pixels(
        self,
    ) -> None:
        for variant, spec in _WIRE_SPECS.items():
            widths = (1, 7, 8, 9, spec.content_width)
            for width in widths:
                for mode in spec.paper_modes:
                    for pattern in ("white", "black", "asymmetric_edges"):
                        pixels = _pattern_pixels(width, pattern)
                        raster = RasterBuffer(pixels, width, PixelFormat.BW1)
                        with self.subTest(
                            variant=variant,
                            width=width,
                            mode=mode,
                            pattern=pattern,
                        ):
                            expected_width = (
                                spec.tag_total_width
                                if mode is PaperMode.TAG
                                and spec.tag_total_width is not None
                                else width
                            )
                            expected_height = 3 + spec.top_padding
                            self.assertEqual(
                                recipes.plan_released_raster_size(
                                    width,
                                    3,
                                    variant=variant,
                                    paper_mode=mode,
                                ),
                                (expected_width, expected_height),
                            )
                            self.assertEqual(
                                recipes.build_released_page(
                                    raster,
                                    variant=variant,
                                    paper_mode=mode,
                                ),
                                _expected_page(
                                    pixels,
                                    width,
                                    3,
                                    variant=variant,
                                    paper_mode=mode,
                                ),
                            )

    def test_first_intermediate_and_final_page_boundaries(self) -> None:
        pixels = _pattern_pixels(9, "asymmetric_edges")
        raster = RasterBuffer(pixels, 9)
        cases = (
            (True, False, True),
            (False, False, True),
            (False, True, False),
            (False, False, False),
        )
        for variant in ("m02", "m02x", "m02s"):
            for first, last, media_end in cases:
                with self.subTest(
                    variant=variant,
                    first=first,
                    last=last,
                    media_end=media_end,
                ):
                    self.assertEqual(
                        recipes.build_released_page(
                            raster,
                            variant=variant,
                            paper_mode=PaperMode.PLAIN,
                            is_first_page=first,
                            is_last_page=last,
                            ends_media_page=media_end,
                        ),
                        _expected_page(
                            pixels,
                            9,
                            3,
                            variant=variant,
                            paper_mode=PaperMode.PLAIN,
                            is_first_page=first,
                            is_last_page=last,
                            ends_media_page=media_end,
                        ),
                    )

    def test_density_media_and_reference_recipe_geometry(self) -> None:
        raster = RasterBuffer([0] * 8, width=8)
        for variant in _WIRE_SPECS:
            spec = _WIRE_SPECS[variant]
            modes = spec.paper_modes
            for mode in modes:
                for level in (None, -10, 1, 2, 3, 4, 9):
                    with self.subTest(variant=variant, mode=mode, density=level):
                        self.assertEqual(
                            recipes.build_released_page(
                                raster,
                                variant=variant,
                                paper_mode=mode,
                                density=level,
                            ),
                            _expected_page(
                                [0] * 8,
                                8,
                                1,
                                variant=variant,
                                paper_mode=mode,
                                density=level,
                            ),
                        )

        for variant in ("m110", "m220"):
            for mode in _WIRE_SPECS[variant].paper_modes:
                self.assertEqual(
                    recipes.plan_released_raster_size(
                        8,
                        1,
                        variant=variant,
                        paper_mode=mode,
                    ),
                    (8, 1),
                )

    def test_m02x_is_compact_plain_only_and_rejects_oversize_before_scanning(
        self,
    ) -> None:
        class UnscannablePixels(list[int]):
            def __iter__(self) -> Iterator[int]:
                raise AssertionError("invalid recipe must fail before pixel scan")

        for mode in (PaperMode.TAG, PaperMode.BLACK_TAG, PaperMode.A4_SHEET):
            raster = RasterBuffer(UnscannablePixels([0] * 8), width=8)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                recipes.build_released_page(
                    raster,
                    variant="m02x",
                    paper_mode=mode,
                )

        too_wide = RasterBuffer(UnscannablePixels([0] * 385), width=385)
        with self.assertRaisesRegex(ValueError, "content width"):
            recipes.build_released_page(too_wide, variant="m02x")

        pixels = _pattern_pixels(8, "asymmetric_edges")
        self.assertEqual(
            recipes.build_released_page(
                RasterBuffer(pixels, width=8),
                variant="m02x",
                density=None,
            ),
            _expected_page(
                pixels,
                8,
                3,
                variant="m02x",
                paper_mode=PaperMode.PLAIN,
                density=2,
            ),
        )

    def test_gsv0_row_stripes_respect_65535_row_limit(self) -> None:
        source_height = 0xFFFF - 4 + 1
        pixels = [0] * (8 * source_height)
        pixels[0] = 1
        pixels[-1] = 1
        raster = RasterBuffer(pixels, width=8)
        with patch.object(
            recipes, "validate_image_budget", side_effect=lambda w, h: w * h
        ):
            payload = recipes.build_released_page(raster, variant="m02")

        setup = _wire_setup(density=2, paper_mode=PaperMode.PLAIN)
        first_block_offset = len(setup)
        first_block_size = 8 + 0xFFFF
        self.assertEqual(
            payload[first_block_offset : first_block_offset + 8],
            bytes.fromhex("1d7630000100ffff"),
        )
        self.assertEqual(
            payload[first_block_offset + 8 : first_block_offset + 8 + 4],
            bytes(4),
        )
        self.assertEqual(payload[first_block_offset + 8 + 4], 0x80)
        second_block_offset = first_block_offset + first_block_size
        self.assertEqual(
            payload[second_block_offset : second_block_offset + 8],
            bytes.fromhex("1d76300001000100"),
        )
        self.assertEqual(payload[second_block_offset + 8], 0x01)
        self.assertTrue(payload.endswith(_COMPACT_FEED * 2))

    def test_invalid_rasters_variants_modes_and_content_width_reject(self) -> None:
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

        for variant in ("m02", "m02x"):
            with (
                self.subTest(variant=variant),
                self.assertRaisesRegex(ValueError, "content width"),
            ):
                recipes.build_released_page(
                    RasterBuffer([0] * 385, width=385), variant=variant
                )

    def test_size_planner_validates_input_and_padded_budgets_before_scanning(
        self,
    ) -> None:
        expected_sizes = (
            ("m02", PaperMode.PLAIN, (8, 6)),
            ("m02", PaperMode.TAG, (8, 6)),
            ("m02s", PaperMode.PLAIN, (8, 6)),
            ("m02s", PaperMode.TAG, (588, 6)),
            ("m02_pro", PaperMode.TAG, (583, 6)),
            ("t02", PaperMode.PLAIN, (8, 6)),
            ("m02x", PaperMode.PLAIN, (8, 6)),
            ("m110", PaperMode.TAG, (8, 2)),
            ("m220", PaperMode.BLACK_TAG, (8, 2)),
        )
        for variant, mode, expected in expected_sizes:
            with self.subTest(variant=variant, mode=mode):
                self.assertEqual(
                    recipes.plan_released_raster_size(
                        8,
                        2,
                        variant=variant,
                        paper_mode=mode,
                    ),
                    expected,
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

        if MAX_DIMENSION < 65_535:
            with self.assertRaises(ValueError):
                recipes.plan_released_raster_size(
                    8,
                    MAX_DIMENSION + 1,
                    variant="m02",
                )

        class UnscannablePixels(list[int]):
            def __iter__(self) -> Iterator[int]:
                raise AssertionError("pixels must not be scanned before preflight")

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
                recipes,
                "validate_image_budget",
                side_effect=reject_padded_size,
            ),
            patch.object(
                recipes,
                "_pad_raster",
                side_effect=AssertionError("padding allocated before budget check"),
            ),
            self.assertRaisesRegex(MemoryError, "padded budget"),
        ):
            recipes.build_released_page(raster, variant="m02")
        self.assertEqual(calls, [(8, 2), (8, 6)])

        pixels = [1, 0, 0, 0, 0, 0, 0, 0]
        original = pixels.copy()
        recipes.build_released_page(RasterBuffer(pixels, width=8), variant="m02")
        self.assertEqual(pixels, original)


if __name__ == "__main__":
    unittest.main()
