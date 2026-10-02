from __future__ import annotations

import hashlib
import hmac

from ...raster import PixelFormat
from ..encoding import pack_line
from ..family import ProtocolFamily
from ..packet import make_packet, prefixed_packet_length, prefixed_packet_opcode
from ..plan import ProtocolPlan
from ..steps import ProtocolStep, ProtocolWriteChannel
from ..types import ImageEncoding, ImagePipelineConfig, PaperMode
from .base import PrintJobRequest, ProtocolBehavior, SplitWritePlan


def _hex_bytes(value: str) -> bytes:
    return bytes.fromhex(value)


V5X_SERVICE_UUID = "0000ae30-0000-1000-8000-00805f9b34fb"
V5X_BULK_DATA_UUID = "0000ae03-0000-1000-8000-00805f9b34fb"
V5X_NOTIFY_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"

# Fixed packets and notify markers used by the V5X BLE workflow.
V5X_GET_SERIAL_PACKET = _hex_bytes("2221A70000000000")
V5X_CONNECT_INIT_PACKET = _hex_bytes("2221B10001000000FF")
V5X_STATUS_POLL_PACKET = _hex_bytes("2221A300020000000000")
V5X_FINALIZE_PACKET = _hex_bytes("2221AD000100000000")
V5X_NOTIFY_GET_SERIAL_ACK = _hex_bytes("2221A7000000")
V5X_NOTIFY_START_READY = _hex_bytes("2221AA0000")
V5X_NOTIFY_START_PRINT_OK = _hex_bytes("2221A9000000")
V5X_NOTIFY_TRIGGER_STATUS_POLL = _hex_bytes("2221B20000")
V5X_NOTIFY_IDLE_GET_SERIAL = _hex_bytes("2221A60000")

_MANUAL_MOTION_PAYLOAD = bytes([0x05, 0x00])
V5X_LABEL_MODE_SUFFIX = _hex_bytes("30010000")
V5X_GRAY_MODE_SUFFIX = _hex_bytes("30020000")
V5X_STANDARD_MODE_SUFFIX = _hex_bytes("30000000")
V5X_GRAY_MODE = 0x02
# Firmware blackening 1-5 maps to different density bytes for dot and gray
# jobs; the values are not linear.
_DOT_DENSITY_BY_LEVEL = (0x58, 0x5A, 0x5D, 0x5F, 0x62)
_GRAY_DENSITY_BY_LEVEL = (0x4B, 0x50, 0x55, 0x5A, 0x62)
# Pause/resume packets were captured as a finite set of flow-control markers
# across the known V5X-compatible firmwares.
_FLOW_PAUSE_HEX = (
    "AA01",
    "5178AE0101001070FF",
    "2221A800010020E0FF",
    "2221AE0101001070FF",
    "2221AE0001000000",
)
_FLOW_RESUME_HEX = (
    "AA00",
    "5178AE0101000000FF",
    "2221A80001003090FF",
    "2221AE0101000000FF",
    "2221AE0001001000",
)
V5X_NOTIFY_PAUSE_PACKETS = frozenset(_hex_bytes(value) for value in _FLOW_PAUSE_HEX)
V5X_NOTIFY_RESUME_PACKETS = frozenset(_hex_bytes(value) for value in _FLOW_RESUME_HEX)


def _raw_lsb_payload(pixels: list[int] | tuple[int, ...], width: int) -> bytes:
    if width % 8 != 0:
        raise ValueError("Width must be divisible by 8")
    if len(pixels) % width != 0:
        raise ValueError("Pixel count must be a multiple of width")
    payload = bytearray()
    height = len(pixels) // width
    for row in range(height):
        line = pixels[row * width : (row + 1) * width]
        payload += pack_line(line, lsb_first=True)
    return bytes(payload)


def _gray_payload(raster) -> bytes:
    if raster.pixel_format == PixelFormat.GRAY8:
        return bytes(raster.pixels)
    if raster.pixel_format == PixelFormat.GRAY4:
        return raster.packed_bytes()
    raise ValueError("V5X gray jobs require GRAY4 or GRAY8 raster data")


def advance_paper_cmd(
    _dpi: int,
    protocol_family: ProtocolFamily,
    _protocol_variant: str | None = None,
) -> bytes:
    return make_packet(0xA3, _MANUAL_MOTION_PAYLOAD, protocol_family)


def retract_paper_cmd(
    _dpi: int,
    protocol_family: ProtocolFamily,
    _protocol_variant: str | None = None,
) -> bytes:
    return make_packet(0xA4, _MANUAL_MOTION_PAYLOAD, protocol_family)


def _density_payload(request: PrintJobRequest) -> bytes:
    level = max(1, min(5, request.blackening))
    table = (
        _GRAY_DENSITY_BY_LEVEL
        if request.image_pipeline.encoding == ImageEncoding.V5X_GRAY
        else _DOT_DENSITY_BY_LEVEL
    )
    return bytes([table[level - 1]])


def _start_print_mode(request: PrintJobRequest) -> int:
    if request.image_pipeline.encoding == ImageEncoding.V5X_GRAY:
        return V5X_GRAY_MODE
    if request.paper_mode is PaperMode.TAG:
        return 0x01
    return 0x00


def _start_print_packet(height: int, request: PrintJobRequest) -> bytes:
    # Release v0.8.1 uses a literal four-byte payload and a zero footer for A9.
    header = _hex_bytes("2221A9000400")
    return (
        header
        + height.to_bytes(2, "little")
        + bytes([0x30, _start_print_mode(request), 0x00, 0x00])
    )


def split_print_stream(data: bytes) -> SplitWritePlan:
    """Split framed V5X controls from an opaque post-A9 raster stream."""

    commands: list[bytes] = []
    offset = 0
    while offset < len(data):
        packet_length = prefixed_packet_length(data, offset, ProtocolFamily.V5X)
        if packet_length is None:
            raise ValueError("Incomplete V5X command before raster")
        packet = data[offset : offset + packet_length]
        commands.append(packet)
        offset += packet_length
        if prefixed_packet_opcode(packet, ProtocolFamily.V5X) == 0xA9:
            if not data[offset:].endswith(V5X_FINALIZE_PACKET):
                raise ValueError("V5X raster is missing its finalizer")
            return SplitWritePlan(
                commands=tuple(commands),
                bulk_payload=data[offset : -len(V5X_FINALIZE_PACKET)],
                trailing_commands=(V5X_FINALIZE_PACKET,),
            )
    return SplitWritePlan(
        commands=tuple(commands), bulk_payload=b"", trailing_commands=()
    )


def build_sign_response(challenge: bytes, *, timestamp_ms: int) -> bytes:
    """Build the release-compatible response to a ten-byte V5X B3 challenge."""

    if len(challenge) != 10:
        raise ValueError("V5X signing challenge must contain ten bytes")
    clock_tail = timestamp_ms % 10000
    t0, t1 = divmod(clock_tail, 100)
    mask = bytes([0xA9, t1, 0xD3, 0x03, 0x78, 0xB6, 0x15, t0, 0xEA, 0x82])
    message = (
        bytes(value ^ salt for value, salt in zip(challenge, mask, strict=True))
        .hex()
        .upper()
        .encode("ascii")
    )
    key = f"93{t0:02x}e8ae5e93d79683dcaf9e{t1:02x}3ede35".encode("ascii")
    digest = hmac.new(key, message, hashlib.sha256).digest()
    return (
        bytes.fromhex("2221B3002200")
        + digest[:1]
        + bytes([t1])
        + digest[1:29]
        + bytes([t0])
        + digest[29:]
        + bytes.fromhex("00FF")
    )


def build_job(request: PrintJobRequest) -> ProtocolPlan:
    is_gray = request.image_pipeline.encoding == ImageEncoding.V5X_GRAY
    raster = (
        request.default_raster if is_gray else request.require_raster(PixelFormat.BW1)
    )
    height = raster.height
    density_packet = make_packet(
        0xA2, _density_payload(request), request.protocol_family
    )
    start_packet = _start_print_packet(height, request)
    raster_payload = (
        _gray_payload(raster)
        if is_gray
        else _raw_lsb_payload(list(raster.pixels), raster.width)
    )
    return ProtocolPlan.sequence(
        (
            ProtocolStep.send(
                "set density",
                density_packet,
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
            ProtocolStep.send(
                "start print",
                start_packet,
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
            ProtocolStep.send(
                "raster",
                raster_payload,
                write_channel=ProtocolWriteChannel.BULK,
            ),
            ProtocolStep.send(
                "finalize",
                V5X_FINALIZE_PACKET,
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
        )
    )


BEHAVIOR = ProtocolBehavior(
    supported_paper_modes=(PaperMode.PLAIN, PaperMode.TAG),
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1, PixelFormat.GRAY4, PixelFormat.GRAY8),
        encoding=ImageEncoding.V5X_DOT,
    ),
    image_encoding_support={
        ImageEncoding.V5X_DOT: (PixelFormat.BW1,),
        ImageEncoding.V5X_GRAY: (PixelFormat.GRAY4, PixelFormat.GRAY8),
    },
    advance_paper_builder=advance_paper_cmd,
    retract_paper_builder=retract_paper_cmd,
    job_builder=build_job,
)
