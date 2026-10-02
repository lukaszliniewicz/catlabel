"""Pure Print Master M110/M120 page recipe.

Copyright 2026 Daniel Banecki (TiMini-Print).
Licensed under the Apache License, Version 2.0.

The wire order is derived from TiMini-Print commit
``fe603ca2ee1d21866f66f86d63ca2fc101916de8``. See the upstream LICENSE and
NOTICE for license terms and attribution.
"""

from __future__ import annotations

from ...core.resource_limits import validate_image_budget
from ...protocol.families.bitmap import build_gs_v0_blocks
from ...raster import PixelFormat, RasterBuffer

_DENSITY_PREFIX = b"\x1f\x11\x02"
_SPEED_PREFIX = b"\x1f\x11\x23"
_INIT = b"\x1b\x40"
_PRINT_MULTI = b"\x1f\x11\x21\x01"
_ROW_WIDTH = 384
_MAX_LINES_PER_BLOCK = 0xFFFF
_VARIANTS = frozenset(("printmaster_m110", "printmaster_m120"))


def build_printmaster_page(
    raster: RasterBuffer,
    *,
    variant: str,
    density: int | None = None,
    speed: int | None = None,
) -> bytes:
    """Build one Print Master M110/M120 raster page without performing I/O."""
    if variant not in _VARIANTS:
        raise ValueError(f"Unsupported Print Master protocol variant: {variant!r}")
    if raster.pixel_format is not PixelFormat.BW1:
        raise ValueError("Print Master M110/M120 jobs require a BW1 raster")
    if type(raster.width) is not int or raster.width != _ROW_WIDTH:
        raise ValueError(f"Print Master M110/M120 jobs require {_ROW_WIDTH}px width")

    pixel_count = len(raster.pixels)
    if pixel_count % _ROW_WIDTH:
        raise ValueError("Print Master raster pixels must form complete rows")
    height = pixel_count // _ROW_WIDTH
    if height < 1:
        raise ValueError("Print Master raster height must be positive")

    # Check dimensions and aggregate input budget before validation/packing can
    # allocate block copies or encoded output.
    _ = validate_image_budget(_ROW_WIDTH, height)
    raster.validate()

    payload = bytearray()
    if density is not None and density != 0:
        payload += _DENSITY_PREFIX + bytes((_clamp_byte(density, minimum=1),))
    if speed is not None:
        payload += _SPEED_PREFIX + bytes((_clamp_byte(speed, minimum=0),))
    payload += _INIT
    if variant == "printmaster_m120":
        payload += _PRINT_MULTI
    payload += build_gs_v0_blocks(
        raster,
        max_lines_per_block=_MAX_LINES_PER_BLOCK,
        lsb_first=False,
        mode=0,
    )
    return bytes(payload)


def _clamp_byte(value: int, *, minimum: int) -> int:
    return max(minimum, min(0xFF, int(value)))
