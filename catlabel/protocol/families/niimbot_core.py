"""Pure NIIMBOT packet and D-row encoding helpers.

Copyright 2026 Daniel Banecki (TiMini-Print).
Licensed under the Apache License, Version 2.0.

The NIIMBOT wire framing, row-count selection, and indexed-row convention are
derived from timiniprint 0.8.1, pinned at release commit
``f676917257b5d1f869e0f13beff03785258e2a2e``.  The source is licensed under
Apache License 2.0; see the repository LICENSE and NOTICE for its full terms and
upstream attribution.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...core.resource_limits import validate_image_budget
from ...raster import PixelFormat, RasterBuffer

_CONNECT_COMMAND = 0xC1
_EMPTY_ROW_COMMAND = 0x84
_INDEXED_ROW_COMMAND = 0x83
_BITMAP_ROW_COMMAND = 0x85
_INDEXED_ROW_THRESHOLD = 6
_BLACK_BIT_COUNTS = tuple(value.bit_count() for value in range(256))


def frame(command: int, data: bytes = b"\x01") -> bytes:
    """Build a NIIMBOT frame, including CONNECT's leading transport marker."""
    if isinstance(command, bool):
        raise ValueError("NIIMBOT command must be an integer in 0..255")
    if not 0 <= command <= 0xFF:
        raise ValueError("NIIMBOT command must be an integer in 0..255")
    if len(data) > 0xFF:
        raise ValueError("NIIMBOT frame data must be at most 255 bytes")

    checksum = command ^ len(data)
    for value in data:
        checksum ^= value
    packet = (
        b"\x55\x55"
        + bytes((command, len(data)))
        + data
        + bytes((checksum & 0xFF,))
        + b"\xaa\xaa"
    )
    if command == _CONNECT_COMMAND:
        return b"\x03" + packet
    return packet


def connect_result(payload: bytes) -> int | None:
    """Return the recognized CONNECT result from an already-decoded payload."""
    if payload and payload[0] in (1, 2, 3):
        return payload[0]
    return None


def model_id(payload: bytes) -> int | None:
    """Decode the model ID value from an already-decoded reply payload."""
    if len(payload) == 1:
        return payload[0] << 8
    if len(payload) == 2:
        return int.from_bytes(payload, byteorder="big", signed=True)
    return None


def protocol_version(payload: bytes) -> int:
    """Map status-data firmware bytes to the NIIMBOT protocol generation."""
    if len(payload) <= 12:
        return 0

    encoded = payload[11] * 100 + payload[12]
    if 204 <= encoded < 300:
        return 3
    if encoded in (300, 301):
        return 4
    if encoded >= 302:
        return 5
    return 0


def encode_d_rows(raster: RasterBuffer) -> tuple[bytes, ...]:
    """Encode BW1 raster rows as coalesced NIIMBOT empty, sparse, or dense frames."""
    if raster.pixel_format is not PixelFormat.BW1:
        raise ValueError("NIIMBOT requires BW1 raster data")

    width = raster.width
    if type(width) is not int or width <= 0:
        raise ValueError("NIIMBOT raster width must be a positive integer")
    if width > 0xFFFF:
        raise ValueError("NIIMBOT raster width must not exceed 65535 pixels")
    if width % 8 != 0:
        raise ValueError("NIIMBOT raster width must be divisible by 8")

    pixel_count = len(raster.pixels)
    if pixel_count % width != 0:
        raise ValueError("NIIMBOT raster pixels must form complete rows")
    height = pixel_count // width
    if not 1 <= height <= 0xFFFF:
        raise ValueError("NIIMBOT raster height must be in 1..65535 pixels")

    # Validate the resource ceiling before scanning, packing, or collecting rows.
    validate_image_budget(width, height)
    raster.validate()

    encoded_frames: list[bytes] = []
    run_start = 0
    run_repeat = 0
    run_black_count = 0
    run_data: bytes | None = None

    for row_number in range(height):
        start = row_number * width
        line = raster.pixels[start : start + width]
        black_count = sum(1 for pixel in line if pixel)
        row_data = _pack_row_msb(line) if black_count else None

        if run_repeat and row_data == run_data:
            run_repeat += 1
            continue

        if run_repeat:
            encoded_frames.extend(
                _encode_row_run(
                    run_start,
                    run_repeat,
                    run_black_count,
                    run_data,
                    width,
                )
            )
        run_start = row_number
        run_repeat = 1
        run_black_count = black_count
        run_data = row_data

    if run_repeat:
        encoded_frames.extend(
            _encode_row_run(
                run_start,
                run_repeat,
                run_black_count,
                run_data,
                width,
            )
        )
    return tuple(encoded_frames)


def _pack_row_msb(pixels: Sequence[int]) -> bytes:
    packed = bytearray(len(pixels) // 8)
    for index, pixel in enumerate(pixels):
        if pixel:
            packed[index // 8] |= 1 << (7 - index % 8)
    return bytes(packed)


def _encode_row_run(
    row_number: int,
    repeat: int,
    black_count: int,
    row_data: bytes | None,
    width: int,
) -> tuple[bytes, ...]:
    frames: list[bytes] = []
    offset = 0
    while offset < repeat:
        chunk_repeat = min(0xFF, repeat - offset)
        current_row = row_number + offset
        if row_data is None:
            payload = _u16be(current_row) + bytes((chunk_repeat,))
            command = _EMPTY_ROW_COMMAND
        else:
            counts = _count_pixels(row_data, width)
            header = _u16be(current_row) + bytes(counts) + bytes((chunk_repeat,))
            if black_count <= _INDEXED_ROW_THRESHOLD:
                payload = header + _index_pixels(row_data)
                command = _INDEXED_ROW_COMMAND
            else:
                payload = header + row_data
                command = _BITMAP_ROW_COMMAND
        frames.append(frame(command, payload))
        offset += chunk_repeat
    return tuple(frames)


def _count_pixels(row_data: bytes, width: int) -> tuple[int, int, int]:
    chunk_width = width // 8 // 3
    if chunk_width > 0 and len(row_data) <= chunk_width * 3:
        parts = [0, 0, 0]
        for byte_index, value in enumerate(row_data):
            chunk_index = byte_index // chunk_width
            if chunk_index < 3:
                parts[chunk_index] += _BLACK_BIT_COUNTS[value]
        return parts[0], parts[1], parts[2]

    total = sum(_BLACK_BIT_COUNTS[value] for value in row_data)
    return 0, total & 0xFF, (total >> 8) & 0xFF


def _index_pixels(row_data: bytes) -> bytes:
    indexes = bytearray()
    for byte_index, value in enumerate(row_data):
        for bit_index in range(8):
            if value & (1 << (7 - bit_index)):
                indexes.extend(_u16be(byte_index * 8 + bit_index))
    return bytes(indexes)


def _u16be(value: int) -> bytes:
    return value.to_bytes(2, byteorder="big", signed=False)
