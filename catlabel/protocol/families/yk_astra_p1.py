# TiMini-Print
# Copyright 2026 Daniel Banecki
# Licensed under the Apache License, Version 2.0. See LICENSE for the full terms.
# Ported from Dejniel/TiMini-Print at f676917257b5d1f869e0f13beff03785258e2a2e:
# timiniprint/protocol/families/yk_astra_p1/core.py
# Local adaptation: this encoder implements only the released S001 variant.

from __future__ import annotations

from ...raster import PixelFormat, RasterBuffer
from ..plan import ProtocolPlan
from ..types import ImageEncoding, ImagePipelineConfig, PaperMode
from .base import PrintJobRequest, ProtocolBehavior
from .yk_common import SEQUENCE_MODULUS, pack_yk_frame

_HEAD_WIDTH = 96
_ROWS_PER_FRAME = 4
_ROW_BYTES = _HEAD_WIDTH // 8
_RASTER_FRAME_BYTES = _ROW_BYTES * _ROWS_PER_FRAME
_RASTER_LEFT_PADDING = 6

_RASTER = 0x00
_FEED_FORWARD = 0x02
_FEED_SPECIAL = 0x03
_FEED_BACKWARD = 0x04
_DENSITY = 0x09
_SPEED = 0x0A
_PAPER_TYPE = 0x28

_PAPER_CODES = {
    PaperMode.PLAIN: 0,
    PaperMode.TAG: 1,
    PaperMode.BLACK_TAG: 2,
}


def build_job(request: PrintJobRequest) -> ProtocolPlan:
    if request.image_pipeline.encoding is not ImageEncoding.YK_ASTRA_P1_RAW:
        raise ValueError(
            "Unsupported YK Astra P1 image encoding: "
            f"{request.image_pipeline.encoding.value}"
        )
    if not request.protocol_variant:
        raise ValueError("YK Astra P1 requires an explicit protocol variant")
    if request.protocol_variant != "s001":
        raise ValueError(
            f"Unsupported YK Astra P1 protocol variant: {request.protocol_variant}"
        )

    raster = request.require_raster(PixelFormat.BW1)
    raster.validate()
    speed = _uint8(request.speed, "speed")
    density = _uint8(9 if request.density is None else request.density, "density")
    paper_code = _paper_code(request.paper_mode)
    raster_bytes = _pack_raster(raster, request.left_padding_pixels)

    packets: list[bytes] = []
    sequence = 0

    def add(command: int, payload: bytes = b"") -> None:
        nonlocal sequence
        packets.append(pack_yk_frame(command, payload, sequence=sequence))
        sequence = (sequence + 1) % SEQUENCE_MODULUS

    if request.is_first_page:
        add(_SPEED, bytes((speed,)))
        add(_DENSITY, bytes((density,)))
        add(_PAPER_TYPE, bytes((0x01, paper_code)))

        if paper_code == 0:
            add(_FEED_BACKWARD, (12).to_bytes(2, "little"))
        else:
            add(_FEED_SPECIAL, b"\x02" + (800).to_bytes(2, "little"))

    if paper_code != 0:
        add(_FEED_FORWARD, (2).to_bytes(2, "little"))

    for offset in range(0, len(raster_bytes), _RASTER_FRAME_BYTES):
        add(_RASTER, raster_bytes[offset : offset + _RASTER_FRAME_BYTES])

    if paper_code == 0:
        add(_FEED_FORWARD, (52).to_bytes(2, "little"))
        if request.is_last_page:
            add(_FEED_FORWARD, (12).to_bytes(2, "little"))
    else:
        final_mode = 0x01 if request.is_last_page else 0x00
        add(_FEED_SPECIAL, bytes((final_mode,)) + (800).to_bytes(2, "little"))

    return ProtocolPlan.stream(b"".join(packets))


def _paper_code(paper_mode: PaperMode | None) -> int:
    mode = PaperMode.TAG if paper_mode is None else paper_mode
    try:
        return _PAPER_CODES[mode]
    except KeyError as exc:
        raise ValueError(
            f"YK Astra P1 does not support paper mode: {mode.value}"
        ) from exc


def _pack_raster(raster: RasterBuffer, left_padding_pixels: int) -> bytes:
    padding = _RASTER_LEFT_PADDING + max(0, left_padding_pixels)
    if padding + raster.width > _HEAD_WIDTH:
        raise ValueError(
            f"YK Astra P1 raster width {raster.width}px plus {padding}px padding "
            f"exceeds {_HEAD_WIDTH}px head"
        )

    pixels = list(raster.pixels)
    packed = bytearray()
    for row in range(raster.height):
        row_bits = bytearray(_ROW_BYTES)
        source_offset = row * raster.width
        for column in range(raster.width):
            if pixels[source_offset + column]:
                bit = padding + column
                row_bits[bit >> 3] |= 0x80 >> (bit & 0x07)
        packed.extend(row_bits)
    return bytes(packed)


def _uint8(value: int, label: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"YK Astra P1 {label} must fit in uint8")
    return value


BEHAVIOR = ProtocolBehavior(
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1,),
        encoding=ImageEncoding.YK_ASTRA_P1_RAW,
    ),
    image_encoding_support={
        ImageEncoding.YK_ASTRA_P1_RAW: (PixelFormat.BW1,),
    },
    supported_protocol_variants=("s001",),
    supported_paper_modes=(PaperMode.PLAIN, PaperMode.TAG, PaperMode.BLACK_TAG),
    job_builder=build_job,
)
