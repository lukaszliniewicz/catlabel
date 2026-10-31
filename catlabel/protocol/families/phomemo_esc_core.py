"""Pure Phomemo page recipes adapted from TiMini-Print's compact protocol.

Copyright 2026 Daniel Banecki (TiMini-Print).
Licensed under the Apache License, Version 2.0.

The wire layouts are derived from upstream commit
``6a71ecf7742e36be05bed7f4e52c4822cccced68``. This module adapts those recipes
to CatLabel's bounded ``RasterBuffer`` and page-building interfaces. See the
repository LICENSE and NOTICE for license terms and attribution.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.resource_limits import validate_image_budget
from ...protocol.families.bitmap import build_gs_v0_blocks
from ...protocol.types import PaperMode
from ...raster import PixelFormat, RasterBuffer

_INIT = b"\x1b\x40"
_DENSITY = b"\x1f\x11\x02"
_DENSITY_COEFFICIENT = b"\x1f\x11\x37"
_MEDIA = b"\x1f\x11"
_UNCOMPRESSED = b"\x1f\x11\x35\x00"
_COMPACT_FEED = b"\x1b\x64\x02"
_COMPACT_DENSITY_LEVELS = ((1, 100), (2, 100), (4, 100), (4, 150))
_PAPER_MEDIA = {
    PaperMode.PLAIN: 0x0B,
    PaperMode.TAG: 0x0B,
    PaperMode.BLACK_TAG: 0x26,
}
_LABEL_MODES = (PaperMode.TAG, PaperMode.PLAIN, PaperMode.BLACK_TAG)


@dataclass(frozen=True)
class _CompactRecipe:
    content_width: int
    paper_modes: tuple[PaperMode, ...]
    top_padding: int = 0
    tag_total_width: int | None = None


_COMPACT_RECIPES: dict[str, _CompactRecipe] = {
    "m02": _CompactRecipe(
        384,
        (PaperMode.PLAIN, PaperMode.TAG),
        top_padding=4,
    ),
    "m02s": _CompactRecipe(
        576,
        (PaperMode.PLAIN, PaperMode.TAG),
        top_padding=4,
        tag_total_width=588,
    ),
    "m02_pro": _CompactRecipe(
        576,
        (PaperMode.PLAIN, PaperMode.TAG),
        top_padding=4,
        tag_total_width=583,
    ),
    "t02": _CompactRecipe(
        384,
        (PaperMode.PLAIN, PaperMode.TAG),
        top_padding=4,
    ),
    "m02x": _CompactRecipe(
        384,
        (PaperMode.PLAIN,),
        top_padding=4,
    ),
    "m110": _CompactRecipe(384, _LABEL_MODES),
    "m220": _CompactRecipe(576, _LABEL_MODES),
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

    if width > recipe.content_width:
        raise ValueError(
            f"Phomemo content width must not exceed {recipe.content_width}px"
        )

    padded_width = width
    if selected_mode is PaperMode.TAG and recipe.tag_total_width is not None:
        padded_width = recipe.tag_total_width
    padded_height = height + recipe.top_padding
    validate_image_budget(padded_width, padded_height)
    return padded_width, padded_height


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

    padded_width, padded_height = plan_released_raster_size(
        width,
        height,
        variant=variant,
        paper_mode=paper_mode,
    )
    recipe, selected_mode = _resolve_recipe(variant, paper_mode)
    raster.validate()

    left_padding = 0
    if selected_mode is PaperMode.TAG and recipe.tag_total_width is not None:
        left_padding = recipe.tag_total_width - width
    placed_raster = _pad_raster(
        raster,
        left=left_padding,
        top=recipe.top_padding,
        final_width=padded_width,
        final_height=padded_height,
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
) -> tuple[_CompactRecipe, PaperMode]:
    recipe = _COMPACT_RECIPES.get(variant)
    if recipe is None:
        raise ValueError(f"Unsupported Phomemo recipe variant: {variant}")

    selected_mode = recipe.paper_modes[0] if paper_mode is None else paper_mode
    if not any(selected_mode is mode for mode in recipe.paper_modes):
        raise ValueError(f"Unsupported Phomemo paper mode: {paper_mode!r}")
    return recipe, selected_mode


def _pad_raster(
    raster: RasterBuffer,
    *,
    left: int,
    top: int,
    final_width: int,
    final_height: int,
    height: int,
) -> RasterBuffer:
    if left == 0 and top == 0:
        return raster

    pixels = [0] * (final_width * final_height)
    for row in range(height):
        source_start = row * raster.width
        destination_start = (row + top) * final_width + left
        for column in range(raster.width):
            pixels[destination_start + column] = raster.pixels[source_start + column]
    return RasterBuffer(pixels, final_width, PixelFormat.BW1)
