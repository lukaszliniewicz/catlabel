from __future__ import annotations

from ...raster import PixelFormat
from ..encoding import pack_line, rle_encode_line
from ..family import ProtocolFamily
from ..packet import make_packet
from ..types import ImageEncoding, ImagePipelineConfig, PaperMode
from .base import PrintJobRequest, ProtocolBehavior

VARIANT_LINE_EIGHT = "line_eight"
VARIANT_ESC_STAR = "esc_star"
VARIANT_ESC_STAR_EIGHT = "esc_star_eight"
VARIANT_PROFESSIONAL = "professional"
EIGHT_PAPER_MODES = (PaperMode.PLAIN, PaperMode.A4_SHEET)


def _blackening_cmd(level: int, family: ProtocolFamily | str) -> bytes:
    return make_packet(0xA4, bytes([0x30 + max(1, min(5, level))]), family)


def _energy_cmd(energy: int, family: ProtocolFamily | str) -> bytes:
    if energy <= 0:
        return b""
    return make_packet(0xAF, energy.to_bytes(2, "little"), family)


def _mode_cmd(is_text: bool, family: ProtocolFamily | str) -> bytes:
    return make_packet(0xBE, bytes([1 if is_text else 0]), family)


def _speed_cmd(speed: int, family: ProtocolFamily | str) -> bytes:
    return make_packet(0xBD, bytes([speed & 0xFF]), family)


def _state_cmd(family: ProtocolFamily | str) -> bytes:
    return make_packet(0xA3, b"\x00", family)


def _paper_feed_check_black_cmd(amount: int, family: ProtocolFamily | str) -> bytes:
    opcode = 0xA0 if amount < 0 else 0xA1
    return make_packet(opcode, abs(amount).to_bytes(2, "little") + b"\x11", family)


def _supported_paper_modes(protocol_variant: str | None) -> tuple[PaperMode, ...]:
    if protocol_variant in {
        VARIANT_LINE_EIGHT,
        VARIANT_ESC_STAR_EIGHT,
        VARIANT_PROFESSIONAL,
    }:
        return EIGHT_PAPER_MODES
    return ()


def _left_padded_pixels(request: PrintJobRequest) -> tuple[list[int], int]:
    raster = request.require_raster(PixelFormat.BW1)
    padding = max(0, request.left_padding_pixels)
    if padding == 0:
        return list(raster.pixels), raster.width
    pixels: list[int] = []
    for row in range(raster.height):
        start = row * raster.width
        pixels.extend([0] * padding)
        pixels.extend(raster.pixels[start : start + raster.width])
    return pixels, raster.width + padding


def _line_packets(
    pixels: list[int],
    width: int,
    request: PrintJobRequest,
    *,
    periodic_speed: bool = True,
) -> bytes:
    height = len(pixels) // width
    width_bytes = (width + 7) // 8
    output = bytearray()
    for row in range(height):
        line = pixels[row * width : (row + 1) * width]
        if request.image_pipeline.encoding == ImageEncoding.LEGACY_RLE:
            encoded = bytes(rle_encode_line(line))
            if len(encoded) <= width_bytes:
                output += make_packet(0xBF, encoded, request.protocol_family)
            else:
                output += make_packet(
                    0xA2,
                    pack_line(line, request.lsb_first),
                    request.protocol_family,
                )
        elif request.image_pipeline.encoding == ImageEncoding.LEGACY_RAW:
            output += make_packet(
                0xA2,
                pack_line(line, request.lsb_first),
                request.protocol_family,
            )
        else:
            raise ValueError(
                f"Unsupported legacy image encoding: {request.image_pipeline.encoding.value}"
            )
        if periodic_speed and (row + 1) % 200 == 0:
            output += _speed_cmd(request.speed, request.protocol_family)
    return bytes(output)


def _line_eight_tail_feed(request: PrintJobRequest) -> int:
    if request.paper_mode == PaperMode.A4_SHEET:
        if request.a4xii:
            return 500
        max_height = request.a4_sheet_max_height
        if max_height is None or max_height <= 0:
            max_height = 3800 if request.dev_dpi == 300 else 2400
        return max(0, max_height - request.require_raster(PixelFormat.BW1).height)
    if request.a4xii or not request.lsb_first:
        return 100
    dots_per_paper = 72 if request.dev_dpi == 300 else 48
    return max(0, request.post_print_feed_count + 1) * dots_per_paper


def _build_line_eight_job(
    request: PrintJobRequest, *, professional: bool = False
) -> bytes:
    pixels, width = _left_padded_pixels(request)
    output = bytearray()
    if professional:
        output += make_packet(0xA6, b"\x05", request.protocol_family)
    output += _blackening_cmd(request.blackening, request.protocol_family)
    output += _energy_cmd(request.energy, request.protocol_family)
    output += _mode_cmd(request.is_text, request.protocol_family)
    output += _speed_cmd(request.speed, request.protocol_family)
    output += _line_packets(pixels, width, request, periodic_speed=not professional)
    output += _paper_feed_check_black_cmd(
        _line_eight_tail_feed(request),
        request.protocol_family,
    )
    output += _state_cmd(request.protocol_family)
    return bytes(output)


def _esc_star_energy_byte(energy: int) -> int:
    if energy <= 0:
        return 0
    return energy.to_bytes(max(1, (energy.bit_length() + 7) // 8), "big")[0]


def _esc_star_24dot_payload(request: PrintJobRequest) -> bytes:
    raster = request.require_raster(PixelFormat.BW1)
    output = bytearray()
    for band in range((raster.height + 23) // 24):
        output += bytes(
            [0x1B, 0x2A, 0x21, raster.width & 0xFF, (raster.width >> 8) & 0xFF]
        )
        for x in range(raster.width):
            for stripe in range(3):
                value = 0
                for bit in range(8):
                    y = band * 24 + stripe * 8 + bit
                    if y < raster.height and raster.pixels[y * raster.width + x]:
                        value |= 1 << (7 - bit)
                output.append(value)
        output += b"\x1bJ\x00\x0a"
    return bytes(output)


def _build_esc_star_job(request: PrintJobRequest, *, eight: bool) -> bytes:
    if eight and request.paper_mode == PaperMode.A4_SHEET:
        max_height = request.a4_sheet_max_height
        if max_height is None or max_height <= 0:
            max_height = 3800 if request.dev_dpi == 300 else 2400
        final_feed = (
            max(
                0,
                max_height - request.require_raster(PixelFormat.BW1).height,
            )
            // 24
        )
    elif eight and request.one_length > 0:
        final_feed = request.one_length
    elif eight and request.feed_padding > 0:
        final_feed = request.feed_padding
    else:
        final_feed = 4 if request.dev_dpi == 300 else 3
    return bytes(
        b"\x1b@\x12#"
        + bytes([_esc_star_energy_byte(request.energy)])
        + _mode_cmd(request.is_text, request.protocol_family)
        + _esc_star_24dot_payload(request)
        + b"\x1bd"
        + bytes([final_feed & 0xFF])
        + _state_cmd(request.protocol_family)
    )


def _build_variant_job(request: PrintJobRequest) -> bytes | None:
    if request.protocol_variant == VARIANT_LINE_EIGHT:
        return _build_line_eight_job(request)
    if request.protocol_variant == VARIANT_PROFESSIONAL:
        return _build_line_eight_job(request, professional=True)
    if request.protocol_variant == VARIANT_ESC_STAR:
        return _build_esc_star_job(request, eight=False)
    if request.protocol_variant == VARIANT_ESC_STAR_EIGHT:
        return _build_esc_star_job(request, eight=True)
    return None


BEHAVIOR = ProtocolBehavior(
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1,),
        encoding=ImageEncoding.LEGACY_RAW,
    ),
    image_encoding_support={
        ImageEncoding.LEGACY_RAW: (PixelFormat.BW1,),
        ImageEncoding.LEGACY_RLE: (PixelFormat.BW1,),
    },
    supported_protocol_variants=(
        VARIANT_LINE_EIGHT,
        VARIANT_ESC_STAR,
        VARIANT_ESC_STAR_EIGHT,
        VARIANT_PROFESSIONAL,
    ),
    supported_paper_modes_resolver=_supported_paper_modes,
    job_builder=_build_variant_job,
)
