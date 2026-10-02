"""Pure Phomemo page recipes pinned to the TiMini-Print 0.8.1 release.

Copyright 2026 Daniel Banecki (TiMini-Print).
Licensed under the Apache License, Version 2.0.

The wire layouts and raster placement are derived from upstream commit
``f676917257b5d1f869e0f13beff03785258e2a2e``. See the repository LICENSE and
NOTICE for license terms and attribution.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.resource_limits import validate_image_budget
from ...protocol.families.bitmap import build_gs_v0_blocks
from ...protocol.types import PaperMode
from ...raster import PixelFormat, RasterBuffer

_INIT = b"\x1b\x40"
_JUSTIFY = b"\x1b\x61"
_DENSITY = b"\x1f\x11\x02"
_DENSITY_COEFFICIENT = b"\x1f\x11\x37"
_MEDIA = b"\x1f\x11"
_UNCOMPRESSED = b"\x1f\x11\x35\x00"
_PRINT_AND_FEED_LINES = b"\x1b\x64"
_COMPACT_FEED = b"\x1b\x64\x02"
_COMPACT_DENSITY_LEVELS = ((1, 100), (2, 100), (4, 100), (4, 150))
_PAPER_MEDIA = {
    PaperMode.PLAIN: 0x0B,
    PaperMode.TAG: 0x0B,
    PaperMode.BLACK_TAG: 0x26,
}
_LABEL_MODES = (PaperMode.TAG, PaperMode.PLAIN, PaperMode.BLACK_TAG)
_M02X_VARIANT = "m02x"


@dataclass(frozen=True)
class _CompactRecipe:
    content_width: int
    left_padding: int
    paper_modes: tuple[PaperMode, ...]
    tag_right_extra: int = 0


_COMPACT_RECIPES: dict[str, _CompactRecipe] = {
    "m02": _CompactRecipe(384, 4, (PaperMode.PLAIN, PaperMode.TAG)),
    "m02s": _CompactRecipe(
        576,
        4,
        (PaperMode.PLAIN, PaperMode.TAG),
        tag_right_extra=12,
    ),
    "m02_pro": _CompactRecipe(
        576,
        4,
        (PaperMode.PLAIN, PaperMode.TAG),
        tag_right_extra=7,
    ),
    "t02": _CompactRecipe(384, 4, (PaperMode.PLAIN, PaperMode.TAG)),
    "m110": _CompactRecipe(384, 0, _LABEL_MODES),
    "m220": _CompactRecipe(576, 0, _LABEL_MODES),
}


def plan_released_raster_size(
    width: int,
    height: int,
    *,
    variant: str,
    paper_mode: PaperMode | None = None,
) -> tuple[int, int]:
    """Validate recipe geometry and return the logical padded raster size."""
    if type(width) is not int or width < 1:
        raise ValueError("Phomemo raster width must be a positive integer")
    if type(height) is not int or height < 1:
        raise ValueError("Phomemo raster height must be a positive integer")

    recipe, selected_mode = _resolve_recipe(variant, paper_mode)
    validate_image_budget(width, height)

    if recipe is None:
        return width, height
    if width > recipe.content_width:
        raise ValueError(
            f"Phomemo content width must not exceed {recipe.content_width}px"
        )

    right_padding = 0
    if selected_mode is PaperMode.TAG and recipe.tag_right_extra:
        right_padding = recipe.content_width + recipe.tag_right_extra - width

    padded_width = recipe.left_padding + width + right_padding
    validate_image_budget(padded_width, height)
    return padded_width, height


def build_released_page(
    raster: RasterBuffer,
    *,
    variant: str,
    density: int | None = None,
    paper_mode: PaperMode | None = None,
    is_first_page: bool = True,
    is_last_page: bool = True,
    ends_media_page: bool = True,
    post_print_feed_count: int = 0,
) -> bytes:
    """Build one released ordinary Phomemo page without performing live I/O."""
    if raster.pixel_format is not PixelFormat.BW1:
        raise ValueError("Phomemo recipes require a BW1 raster")
    width = raster.width
    if type(width) is not int or width < 1:
        raise ValueError("Phomemo raster width must be a positive integer")
    pixel_count = len(raster.pixels)
    if pixel_count % width:
        raise ValueError("Phomemo raster pixels must form complete rows")
    height = pixel_count // width

    padded_width, _ = plan_released_raster_size(
        width,
        height,
        variant=variant,
        paper_mode=paper_mode,
    )
    recipe, selected_mode = _resolve_recipe(variant, paper_mode)
    raster.validate()

    if recipe is None:
        payload = bytearray(_INIT)
        payload += _JUSTIFY + b"\x01"
        payload += _DENSITY + bytes((_clamp_byte(density, default=4),))
        payload += build_gs_v0_blocks(
            raster,
            max_lines_per_block=0xFF,
            lsb_first=False,
            mode=0,
        )
        if ends_media_page and post_print_feed_count > 0:
            payload += _PRINT_AND_FEED_LINES + bytes(
                (_clamp_byte(post_print_feed_count, default=0),)
            )
        return bytes(payload)

    assert selected_mode is not None
    right_padding = 0
    if selected_mode is PaperMode.TAG and recipe.tag_right_extra:
        right_padding = recipe.content_width + recipe.tag_right_extra - width
    placed_raster = _pad_raster(
        raster,
        left=recipe.left_padding,
        right=right_padding,
        final_width=padded_width,
        height=height,
    )

    payload = bytearray()
    if is_first_page:
        level = 2 if density is None else int(density)
        density_value, coefficient = _COMPACT_DENSITY_LEVELS[max(1, min(4, level)) - 1]
        payload += _INIT
        payload += _DENSITY + bytes((density_value,))
        payload += _DENSITY_COEFFICIENT + bytes((coefficient,))
        payload += _MEDIA + bytes((_PAPER_MEDIA[selected_mode],))
        payload += _UNCOMPRESSED

    payload += build_gs_v0_blocks(
        placed_raster,
        max_lines_per_block=0xFFFF,
        lsb_first=False,
        mode=0,
    )
    if is_last_page:
        payload += _COMPACT_FEED * 2
    elif ends_media_page:
        payload += _COMPACT_FEED
    return bytes(payload)


def _resolve_recipe(
    variant: str,
    paper_mode: PaperMode | None,
) -> tuple[_CompactRecipe | None, PaperMode | None]:
    if variant == _M02X_VARIANT:
        modes = (PaperMode.PLAIN,)
        recipe = None
    else:
        recipe = _COMPACT_RECIPES.get(variant)
        if recipe is None:
            raise ValueError(f"Unsupported Phomemo recipe variant: {variant}")
        modes = recipe.paper_modes

    selected_mode = modes[0] if paper_mode is None else paper_mode
    if not any(selected_mode is mode for mode in modes):
        raise ValueError(f"Unsupported Phomemo paper mode: {paper_mode!r}")
    return recipe, selected_mode


def _pad_raster(
    raster: RasterBuffer,
    *,
    left: int,
    right: int,
    final_width: int,
    height: int,
) -> RasterBuffer:
    if left == 0 and right == 0:
        return raster

    pixels = [0] * (final_width * height)
    for row in range(height):
        source_start = row * raster.width
        destination_start = row * final_width + left
        for column in range(raster.width):
            pixels[destination_start + column] = raster.pixels[source_start + column]
    return RasterBuffer(pixels, final_width, PixelFormat.BW1)


def _clamp_byte(value: int | None, *, default: int) -> int:
    if value is None:
        value = default
    return max(0, min(0xFF, int(value)))
