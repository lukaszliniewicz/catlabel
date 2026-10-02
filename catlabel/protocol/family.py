from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum
from types import MappingProxyType


class ProtocolStrEnum(StrEnum):
    """String enum that preserves the former ``Enum.__str__`` behavior."""

    def __str__(self) -> str:
        return Enum.__str__(self)

    def __format__(self, format_spec: str) -> str:
        return Enum.__format__(self, format_spec)


class ProtocolCommandSet(ProtocolStrEnum):
    LEGACY = "legacy"
    LUCK_NORMAL = "luck_normal"
    V5G = "v5g"
    V5X = "v5x"
    V5C = "v5c"
    DCK = "dck"
    ELEPH_HPRT_ESC = "eleph_hprt_esc"
    ELEPH_TSPL = "eleph_tspl"
    TOPRINT_HPRT_ESC = "toprint_hprt_esc"
    TOPRINT_TSPL = "toprint_tspl"
    YK_ASTRA_P1 = "yk_astra_p1"
    INSTAPRINT_CORE = "instaprint_core"
    FUNNY_LX = "funny_lx"


@dataclass(frozen=True)
class ProtocolSpec:
    packet_prefix: bytes | None
    command_set: ProtocolCommandSet


class ProtocolFamily(ProtocolStrEnum):
    LEGACY = "legacy"
    LEGACY_PREFIXED = "legacy_prefixed"
    LUCK_NORMAL = "luck_normal"
    LUCK_NORMAL_A4 = "luck_normal_a4"
    V5G = "v5g"
    V5X = "v5x"
    V5C = "v5c"
    DCK = "dck"
    ELEPH_HPRT_ESC = "eleph_hprt_esc"
    ELEPH_TSPL = "eleph_tspl"
    TOPRINT_HPRT_ESC = "toprint_hprt_esc"
    TOPRINT_TSPL = "toprint_tspl"
    YK_ASTRA_P1 = "yk_astra_p1"
    INSTAPRINT_CORE = "instaprint_core"
    FUNNY_LX = "funny_lx"

    @classmethod
    def from_value(cls, value: ProtocolFamily | str | None) -> ProtocolFamily:
        if isinstance(value, cls):
            return value
        if not value:
            return cls.LEGACY
        return cls(str(value).strip().lower())

    @property
    def spec(self) -> ProtocolSpec:
        return PROTOCOL_SPECS[self]

    @property
    def packet_prefix(self) -> bytes | None:
        return self.spec.packet_prefix

    @property
    def uses_prefixed_packets(self) -> bool:
        return self.packet_prefix is not None

    def require_packet_prefix(self) -> bytes:
        prefix = self.packet_prefix
        if prefix is None:
            raise ValueError(f"{self.value} does not use prefixed command packets")
        return prefix

    @property
    def command_set(self) -> ProtocolCommandSet:
        return self.spec.command_set


PROTOCOL_SPECS: Mapping[ProtocolFamily, ProtocolSpec] = MappingProxyType(
    {
        ProtocolFamily.LEGACY: ProtocolSpec(
            bytes([0x51, 0x78]), ProtocolCommandSet.LEGACY
        ),
        ProtocolFamily.LEGACY_PREFIXED: ProtocolSpec(
            bytes([0x12, 0x51, 0x78]), ProtocolCommandSet.LEGACY
        ),
        ProtocolFamily.LUCK_NORMAL: ProtocolSpec(None, ProtocolCommandSet.LUCK_NORMAL),
        ProtocolFamily.LUCK_NORMAL_A4: ProtocolSpec(
            None, ProtocolCommandSet.LUCK_NORMAL
        ),
        ProtocolFamily.V5G: ProtocolSpec(bytes([0x51, 0x78]), ProtocolCommandSet.V5G),
        ProtocolFamily.V5X: ProtocolSpec(bytes([0x22, 0x21]), ProtocolCommandSet.V5X),
        ProtocolFamily.V5C: ProtocolSpec(bytes([0x56, 0x88]), ProtocolCommandSet.V5C),
        ProtocolFamily.DCK: ProtocolSpec(bytes([0x55, 0xAA]), ProtocolCommandSet.DCK),
        ProtocolFamily.ELEPH_HPRT_ESC: ProtocolSpec(
            None, ProtocolCommandSet.ELEPH_HPRT_ESC
        ),
        ProtocolFamily.ELEPH_TSPL: ProtocolSpec(None, ProtocolCommandSet.ELEPH_TSPL),
        ProtocolFamily.TOPRINT_HPRT_ESC: ProtocolSpec(
            None, ProtocolCommandSet.TOPRINT_HPRT_ESC
        ),
        ProtocolFamily.TOPRINT_TSPL: ProtocolSpec(
            None, ProtocolCommandSet.TOPRINT_TSPL
        ),
        ProtocolFamily.YK_ASTRA_P1: ProtocolSpec(None, ProtocolCommandSet.YK_ASTRA_P1),
        ProtocolFamily.INSTAPRINT_CORE: ProtocolSpec(
            None, ProtocolCommandSet.INSTAPRINT_CORE
        ),
        ProtocolFamily.FUNNY_LX: ProtocolSpec(None, ProtocolCommandSet.FUNNY_LX),
    }
)


__all__ = [
    "PROTOCOL_SPECS",
    "ProtocolCommandSet",
    "ProtocolFamily",
    "ProtocolStrEnum",
    "ProtocolSpec",
]
