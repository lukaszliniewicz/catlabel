"""Funny Print LX BLE command dialect."""

from __future__ import annotations

from dataclasses import dataclass

from ...raster import PixelFormat
from ..plan import ProtocolPlan
from ..steps import ProtocolReplyExpectation, ProtocolReplyMatcher, ProtocolStep
from ..types import ImageEncoding, ImagePipelineConfig, PaperMode
from .base import PrintJobRequest, ProtocolBehavior
from .bitmap import pack_bw1_rows

_PRINTHEAD_WIDTH_PX = 384
_PACKET_DATA_BYTES = 96
_PACKET_HALF_BYTES = 48
_DIRECT_VARIANT = "lx_d_direct"
_REVERSED_VARIANT = "lx_d_reversed"
_SUPPORTED_VARIANTS = frozenset({_DIRECT_VARIANT, _REVERSED_VARIANT})
_FEED_PAPER_CMD = bytes.fromhex("5a 03 81 00 04 00 00 00 00 00 00 00")


@dataclass(frozen=True)
class FunnyLxCrc:
    low: bytes
    high: bytes


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = (
                ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
            )
    return crc


def challenge_crc(random_bytes: bytes, mac_bytes: bytes) -> FunnyLxCrc:
    if len(mac_bytes) != 6:
        raise ValueError("Funny LX MAC must contain 6 bytes")
    low = bytearray()
    high = bytearray()
    for random_byte in random_bytes:
        crc = crc16_xmodem(bytes([random_byte]) + mac_bytes)
        low.append(crc & 0xFF)
        high.append((crc >> 8) & 0xFF)
    return FunnyLxCrc(bytes(low), bytes(high))


def build_job(request: PrintJobRequest) -> ProtocolPlan:
    variant = request.protocol_variant or _DIRECT_VARIANT
    if variant not in _SUPPORTED_VARIANTS:
        raise ValueError(f"Unsupported Funny LX protocol variant: {variant!r}")
    raster = request.require_raster(PixelFormat.BW1)
    raster.validate()
    if raster.width != _PRINTHEAD_WIDTH_PX:
        raise ValueError("Funny LX jobs require 384px raster width")

    content = pack_bw1_rows(raster, lsb_first=False)
    packet_count = (len(content) + _PACKET_DATA_BYTES - 1) // _PACKET_DATA_BYTES
    total = _u16be(packet_count)
    steps: list[ProtocolStep] = []
    if request.is_first_page:
        darkness = max(1, min(5, int(request.blackening or 4))) - 1
        steps.append(ProtocolStep.send("darkness", bytes([0x5A, 0x0C, darkness])))
    steps.append(ProtocolStep.send("print header", b"\x5a\x04" + total + b"\x00\x00"))
    steps.extend(
        ProtocolStep.send(f"image packet {index}", packet)
        for index, packet in enumerate(_image_packets(content, variant), start=1)
    )
    steps.append(
        ProtocolStep.wait(
            "image transfer ready",
            reply_matcher=_image_transfer_ready_matcher(),
            timeout_sec=10.0,
        )
    )
    steps.append(
        ProtocolStep.query(
            "print footer",
            b"\x5a\x04" + total + b"\x01",
            expect=ProtocolReplyExpectation.NONE,
            timeout_sec=10.0,
            reply_matcher=_footer_matcher(total),
        )
    )
    return ProtocolPlan.sequence(tuple(steps))


def _image_packets(content: bytes, variant: str) -> tuple[bytes, ...]:
    command = bytes(reversed(content)) if variant == _REVERSED_VARIANT else content
    packets = []
    for index, offset in enumerate(range(0, len(command), _PACKET_DATA_BYTES)):
        block = command[offset : offset + _PACKET_DATA_BYTES]
        block += b"\x00" * (_PACKET_DATA_BYTES - len(block))
        if variant == _REVERSED_VARIANT:
            block = block[:_PACKET_HALF_BYTES][::-1] + block[_PACKET_HALF_BYTES:][::-1]
        packets.append(b"\x55" + _u16be(index) + block + b"\x00")
    return tuple(packets)


def _u16be(value: int) -> bytes:
    if value < 0 or value > 0xFFFF:
        raise ValueError("Funny LX value does not fit uint16")
    return value.to_bytes(2, "big")


def _image_transfer_ready_matcher() -> ProtocolReplyMatcher:
    def complete(raw: bytes) -> bool:
        return raw.startswith(b"\x5a\x06")

    return ProtocolReplyMatcher(
        complete=complete, matches=lambda raw: bool(raw and complete(raw))
    )


def _footer_matcher(total: bytes) -> ProtocolReplyMatcher:
    def complete(raw: bytes) -> bool:
        return (
            len(raw) >= 5
            and raw[:2] == b"\x5a\x04"
            and raw[2:4] == total
            and raw[4] == 1
        )

    return ProtocolReplyMatcher(
        complete=complete, matches=lambda raw: bool(raw and complete(raw))
    )


def advance_paper_cmd(_dpi: int, _family, _variant: str | None = None) -> bytes:
    return _FEED_PAPER_CMD


def retract_paper_cmd(_dpi: int, _family, _variant: str | None = None) -> bytes:
    return b""


BEHAVIOR = ProtocolBehavior(
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1,),
        encoding=ImageEncoding.FUNNY_LX_RASTER,
    ),
    image_encoding_support={ImageEncoding.FUNNY_LX_RASTER: (PixelFormat.BW1,)},
    supported_protocol_variants=tuple(sorted(_SUPPORTED_VARIANTS)),
    supported_paper_modes=(PaperMode.PLAIN,),
    advance_paper_builder=advance_paper_cmd,
    retract_paper_builder=retract_paper_cmd,
    job_builder=build_job,
)
