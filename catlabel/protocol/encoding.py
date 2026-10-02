from __future__ import annotations

from collections.abc import Sequence

from .family import ProtocolFamily
from .packet import make_packet
from .types import ImageEncoding


def encode_run(color: int, count: int) -> list[int]:
    """Encode a single RLE run for 1-bit data."""
    out: list[int] = []
    while count > 127:
        out.append((color << 7) | 127)
        count -= 127
    if count > 0:
        out.append((color << 7) | count)
    return out


def rle_encode_line(line: list[int]) -> list[int]:
    """RLE-encode a 1-bit pixel line (0/1 values)."""
    if not line:
        return []
    runs: list[int] = []
    prev = line[0]
    count = 1
    has_black = 1 if prev else 0
    for pix in line[1:]:
        if pix:
            has_black = 1
        if pix == prev:
            count += 1
        else:
            runs.extend(encode_run(prev, count))
            prev = pix
            count = 1
    if has_black:
        runs.extend(encode_run(prev, count))
    if not runs:
        runs.extend(encode_run(prev, count))
    return runs


def pack_line(line: Sequence[int], lsb_first: bool) -> bytes:
    """Pack a 1-bit line into bytes, with selectable bit order."""
    out = bytearray()
    for i in range(0, len(line), 8):
        chunk = list(line[i : i + 8])
        if len(chunk) < 8:
            chunk.extend([0] * (8 - len(chunk)))
        value = 0
        if lsb_first:
            for bit, pix in enumerate(chunk):
                if pix:
                    value |= 1 << bit
        else:
            for bit, pix in enumerate(chunk):
                if pix:
                    value |= 1 << (7 - bit)
        out.append(value)
    return bytes(out)


def build_line_packets(
    pixels: list[int],
    width: int,
    speed: int,
    image_encoding: ImageEncoding,
    lsb_first: bool,
    protocol_family: ProtocolFamily | str,
    line_feed_every: int,
) -> bytes:
    """Build data packets for all lines of a raster image."""
    if width % 8 != 0:
        raise ValueError("Width must be divisible by 8")
    height = len(pixels) // width
    width_bytes = width // 8
    out = bytearray()
    for row in range(height):
        line = pixels[row * width : (row + 1) * width]
        if image_encoding == ImageEncoding.LEGACY_RLE:
            rle = rle_encode_line(line)
            if len(rle) <= width_bytes:
                out += make_packet(0xBF, bytes(rle), protocol_family)
            else:
                raw = pack_line(line, lsb_first)
                out += make_packet(0xA2, raw, protocol_family)
        elif image_encoding == ImageEncoding.LEGACY_RAW:
            raw = pack_line(line, lsb_first)
            out += make_packet(0xA2, raw, protocol_family)
        else:
            raise ValueError(
                f"Unsupported legacy image encoding: {image_encoding.value}"
            )
        if line_feed_every and (row + 1) % line_feed_every == 0:
            out += make_packet(0xBD, bytes([speed & 0xFF]), protocol_family)
    return bytes(out)
