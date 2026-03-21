from __future__ import annotations

from ..encoding import pack_line
from ..packet import make_packet
from ..family import ProtocolFamily
from .base import BleTransportProfile, FlowControlProfile, PrintJobRequest, ProtocolBehavior

_AE30_SERVICE_UUID = "0000ae30-0000-1000-8000-00805f9b34fb"
_AE03_DATA_UUID = "0000ae03-0000-1000-8000-00805f9b34fb"
_AE02_NOTIFY_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"

_GET_SERIAL_PACKET = bytes.fromhex("2221A70000000000")
_FINALIZE_PACKET = bytes.fromhex("2221AD000100000000")
_MANUAL_MOTION_PAYLOAD = bytes([0x05, 0x00])

_FLOW_CONTROL = FlowControlProfile(
    pause_packets=frozenset(
        {
            bytes.fromhex("AA01"),
            bytes.fromhex("5178AE0101001070FF"),
            bytes.fromhex("2221A800010020E0FF"),
            bytes.fromhex("2221AE0101001070FF"),
            bytes.fromhex("2221AE0001000000"),
        }
    ),
    resume_packets=frozenset(
        {
            bytes.fromhex("AA00"),
            bytes.fromhex("5178AE0101000000FF"),
            bytes.fromhex("2221A80001003090FF"),
            bytes.fromhex("2221AE0101000000FF"),
            bytes.fromhex("2221AE0001001000"),
        }
    ),
)


TRANSPORT = BleTransportProfile(
    split_bulk_writes=True,
    preferred_service_uuid=_AE30_SERVICE_UUID,
    bulk_char_uuid=_AE03_DATA_UUID,
    notify_char_uuid=_AE02_NOTIFY_UUID,
    flow_control=_FLOW_CONTROL,
    bulk_chunk_size=180,
    split_tail_packets=(_FINALIZE_PACKET,),
)


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


def advance_paper_cmd(_dpi: int, protocol_family: ProtocolFamily) -> bytes:
    return make_packet(0xA3, _MANUAL_MOTION_PAYLOAD, protocol_family)


def retract_paper_cmd(_dpi: int, protocol_family: ProtocolFamily) -> bytes:
    return make_packet(0xA4, _MANUAL_MOTION_PAYLOAD, protocol_family)


def build_job(request: PrintJobRequest) -> bytes:
    if request.width <= 0 or len(request.pixels) % request.width != 0:
        raise ValueError("Pixel count must be a multiple of width")

    height = len(request.pixels) // request.width
    job = bytearray()
    job += _GET_SERIAL_PACKET
    job += make_packet(0xA9, height.to_bytes(2, "little"), request.protocol_family)
    job += _raw_lsb_payload(list(request.pixels), request.width)
    job += _FINALIZE_PACKET
    return bytes(job)


BEHAVIOR = ProtocolBehavior(
    transport=TRANSPORT,
    advance_paper_builder=advance_paper_cmd,
    retract_paper_builder=retract_paper_cmd,
    job_builder=build_job,
)
