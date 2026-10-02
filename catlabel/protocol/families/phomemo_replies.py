"""Reply framing for Phomemo and Print Master Quin dialects.

Copyright 2026 Daniel Banecki (TiMini-Print).
Licensed under the Apache License, Version 2.0.

The recognized frame lengths and prefix rules are derived from TiMini-Print
commit ``43b3203e229c271b75e86703e3a8f2ce428a8c45``. See the upstream LICENSE
and NOTICE for license terms and attribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class DecodedReply:
    """A decoded reply and the absolute offset of its first wire byte."""

    frame: bytes
    start_offset: int


class _ReplyDecoder:
    """Reassemble one reply dialect without scanning inside known frames."""

    _sizes: ClassVar[dict[int, int]] = {}
    _prefixes: ClassVar[tuple[int, ...]] = (0x1A,)
    _allow_bare: ClassVar[bool] = False

    def __init__(self) -> None:
        self._pending: bytearray = bytearray()
        self._pending_offset: int = 0
        self._received_byte_count: int = 0

    @property
    def has_pending_frame(self) -> bool:
        return bool(self._pending)

    @property
    def pending_byte_count(self) -> int:
        return len(self._pending)

    @property
    def received_byte_count(self) -> int:
        """Total wire bytes passed to feed, including bytes discarded as noise."""
        return self._received_byte_count

    def feed(self, payload: bytes) -> list[bytes]:
        return [reply.frame for reply in self.feed_with_offsets(payload)]

    def feed_with_offsets(self, payload: bytes) -> list[DecodedReply]:
        data = bytes(payload)
        self._pending.extend(data)
        self._received_byte_count += len(data)

        replies: list[DecodedReply] = []
        cursor = 0
        pending_length = len(self._pending)
        while cursor < pending_length:
            first_byte = self._pending[cursor]
            prefix_length = 1 if first_byte in self._prefixes else 0
            if prefix_length == 0 and not self._allow_bare:
                cursor += 1
                continue

            opcode_offset = cursor + prefix_length
            if opcode_offset >= pending_length:
                break

            frame_size = self._sizes.get(self._pending[opcode_offset])
            if frame_size is None:
                # Match the source framing policy: discard an unrecognized
                # prefix/opcode pair, or a single unknown bare byte.
                cursor += prefix_length + 1
                continue

            wire_size = prefix_length + frame_size
            if pending_length - cursor < wire_size:
                break

            start_offset = self._pending_offset + cursor
            frame_start = cursor + prefix_length
            frame_end = cursor + wire_size
            replies.append(
                DecodedReply(
                    bytes(self._pending[frame_start:frame_end]),
                    start_offset,
                )
            )
            cursor = frame_end

        if cursor:
            del self._pending[:cursor]
            self._pending_offset += cursor
        return replies


class PhomemoReplyDecoder(_ReplyDecoder):
    """Decode only 1A-prefixed Phomemo replies."""

    _sizes: ClassVar[dict[int, int]] = {
        0x03: 2,
        0x04: 2,
        0x05: 2,
        0x06: 2,
        0x07: 4,
        0x08: 16,
        0x09: 2,
        0x0B: 2,
        0x0E: 2,
        0x0F: 2,
        0x16: 2,
        0x17: 2,
        0x1D: 2,
        0x20: 2,
        0x35: 2,
        0x3B: 6,
    }


class PrintMasterReplyDecoder(_ReplyDecoder):
    """Decode bare or 1A/1B-prefixed Print Master replies."""

    _prefixes: ClassVar[tuple[int, ...]] = (0x1A, 0x1B)
    _allow_bare: ClassVar[bool] = True
    _sizes: ClassVar[dict[int, int]] = {
        0x03: 2,
        0x04: 2,
        0x05: 2,
        0x06: 2,
        0x07: 4,
        0x08: 16,
        0x0B: 2,
        0x0C: 2,
        0x0F: 2,
        0x15: 4,
        0x17: 2,
        0x31: 4,
        0x3B: 4,
        0x3E: 2,
        0x3F: 2,
        0x40: 15,
    }
