from __future__ import annotations

from ..encoding import pack_line
from ..packet import make_packet
from .base import BleTransportProfile, FlowControlProfile, PrintJobRequest, ProtocolBehavior

_FLOW_CONTROL = FlowControlProfile(
    pause_packets=frozenset({bytes.fromhex("5688A70101000107FF")}),
    resume_packets=frozenset({bytes.fromhex("5688A70101000000FF")}),
)


TRANSPORT = BleTransportProfile(
    prefer_generic_notify=True,
    flow_control=_FLOW_CONTROL,
    wait_for_flow_on_standard_write=True,
)


def _settings_payload(blackening: int, is_text: bool) -> bytes:
    level = max(1, min(5, blackening))
    if level <= 2:
        density = 0x01
    elif level >= 4:
        density = 0x03
    else:
        density = 0x02
    mode = 0x01 if is_text else 0x02
    return bytes([density, mode])


def build_job(request: PrintJobRequest) -> bytes:
    if request.width % 8 != 0:
        raise ValueError("Width must be divisible by 8")
    if len(request.pixels) % request.width != 0:
        raise ValueError("Pixel count must be a multiple of width")

    job = bytearray()
    job += make_packet(
        0xA2,
        _settings_payload(request.blackening, request.is_text),
        request.protocol_family,
    )
    job += make_packet(0xA3, bytes([0x01]), request.protocol_family)

    height = len(request.pixels) // request.width
    for row in range(height):
        line = request.pixels[row * request.width : (row + 1) * request.width]
        job += make_packet(0xA4, pack_line(line, lsb_first=True), request.protocol_family)

    job += make_packet(0xA6, bytes([0x30, 0x00]), request.protocol_family)
    job += make_packet(0xA1, bytes([0x00]), request.protocol_family)
    return bytes(job)


BEHAVIOR = ProtocolBehavior(transport=TRANSPORT, job_builder=build_job)
