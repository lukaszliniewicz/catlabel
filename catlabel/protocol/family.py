from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProtocolCommandSet(str, Enum):
    LEGACY = "legacy"
    V5X = "v5x"
    V5C = "v5c"
    DCK = "dck"


class ProtocolTransportStyle(str, Enum):
    STANDARD = "standard"
    SPLIT_BULK = "split_bulk"
    FLOW_CONTROLLED = "flow_controlled"


@dataclass(frozen=True)
class ProtocolSpec:
    packet_prefix: bytes
    command_set: ProtocolCommandSet
    transport_style: ProtocolTransportStyle


class ProtocolFamily(str, Enum):
    LEGACY = "legacy"
    LEGACY_PREFIXED = "legacy_prefixed"
    V5X = "v5x"
    V5C = "v5c"
    DCK = "dck"

    @classmethod
    def from_value(cls, value: "ProtocolFamily | str | None") -> "ProtocolFamily":
        if isinstance(value, cls):
            return value
        if not value:
            return cls.LEGACY
        return cls(str(value).strip().lower())

    @property
    def spec(self) -> ProtocolSpec:
        from .families import get_protocol_definition

        return get_protocol_definition(self).spec

    @property
    def packet_prefix(self) -> bytes:
        return self.spec.packet_prefix

    @property
    def command_set(self) -> ProtocolCommandSet:
        return self.spec.command_set

    @property
    def transport_style(self) -> ProtocolTransportStyle:
        return self.spec.transport_style
