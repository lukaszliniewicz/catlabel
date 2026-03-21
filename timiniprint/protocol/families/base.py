from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from ..family import ProtocolFamily
from ..packet import prefixed_packet_length

ManualMotionBuilder = Callable[[int, ProtocolFamily], bytes]
FamilyJobBuilder = Callable[["PrintJobRequest"], bytes]


@dataclass(frozen=True)
class FlowControlProfile:
    pause_packets: frozenset[bytes] = frozenset()
    resume_packets: frozenset[bytes] = frozenset()


@dataclass(frozen=True)
class BleTransportProfile:
    # Transport settings drive endpoint selection and write routing.
    split_bulk_writes: bool = False
    preferred_service_uuid: str = ""
    bulk_char_uuid: str = ""
    notify_char_uuid: str = ""
    prefer_generic_notify: bool = False
    flow_control: FlowControlProfile | None = None
    wait_for_flow_on_standard_write: bool = False
    bulk_chunk_size: int = 180
    split_tail_packets: tuple[bytes, ...] = ()


@dataclass(frozen=True)
class ProtocolBehavior:
    transport: BleTransportProfile = field(default_factory=BleTransportProfile)
    advance_paper_builder: ManualMotionBuilder | None = None
    retract_paper_builder: ManualMotionBuilder | None = None
    job_builder: FamilyJobBuilder | None = None


@dataclass(frozen=True)
class PrintJobRequest:
    pixels: Sequence[int]
    width: int
    is_text: bool
    speed: int
    energy: int
    blackening: int
    compress: bool
    lsb_first: bool
    protocol_family: ProtocolFamily
    feed_padding: int
    dev_dpi: int


@dataclass(frozen=True)
class SplitWritePlan:
    commands: tuple[bytes, ...]
    bulk_payload: bytes
    trailing_commands: tuple[bytes, ...]


@dataclass(frozen=True)
class ProtocolDefinition:
    spec: "ProtocolSpec"
    behavior: ProtocolBehavior


def split_prefixed_bulk_stream(
    data: bytes,
    protocol_family: ProtocolFamily | str,
    trailing_packets: tuple[bytes, ...] = (),
) -> SplitWritePlan:
    family = ProtocolFamily.from_value(protocol_family)
    commands = []
    trailing_commands = []
    offset = 0

    while True:
        packet_len = prefixed_packet_length(data, offset, family)
        if packet_len is None:
            break
        commands.append(data[offset : offset + packet_len])
        offset += packet_len

    if offset == len(data):
        return SplitWritePlan(tuple(commands), b"", tuple(trailing_commands))

    tail = len(data)
    for packet in trailing_packets:
        if data.endswith(packet) and tail - len(packet) >= offset:
            trailing_commands.insert(0, packet)
            tail -= len(packet)

    bulk_payload = data[offset:tail]
    if not commands and not trailing_commands:
        return SplitWritePlan((data,), b"", ())
    return SplitWritePlan(tuple(commands), bulk_payload, tuple(trailing_commands))
