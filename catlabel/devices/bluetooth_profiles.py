from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class BleBulkWriteProfile:
    char_uuid: str
    chunk_cap: int = 20
    write_delay_ms: int = 50
    flow_controlled: bool = False


@dataclass(frozen=True)
class BleTransportProfile:
    """GATT endpoints and byte-transfer policy selected by the device layer."""

    standard_chunk_cap: int = 20
    standard_write_delay_ms: int = 50
    preferred_service_uuid: str = ""
    preferred_write_char_uuid: str = ""
    notify_char_uuid: str = ""
    prefer_generic_notify: bool = False
    flow_controlled_standard_write: bool = False
    bulk_write: BleBulkWriteProfile | None = None
    write_without_response_payload_reserve: int = 0
    flow_resume_timeout_s: float | None = None
    control_notify_char_uuid: str = ""


_FALLBACK = BleTransportProfile()
_TINY = BleTransportProfile(
    standard_chunk_cap=512,
    prefer_generic_notify=True,
    flow_controlled_standard_write=True,
    flow_resume_timeout_s=600.0,
)
_PROFILES = {
    "legacy": _TINY,
    "legacy_prefixed": _TINY,
    "luck_normal": BleTransportProfile(),
    "luck_normal_a4": BleTransportProfile(),
    "v5g": BleTransportProfile(
        prefer_generic_notify=True,
        standard_chunk_cap=56 * 8,
        standard_write_delay_ms=30,
        write_without_response_payload_reserve=5,
    ),
    "v5c": BleTransportProfile(
        prefer_generic_notify=True,
        flow_controlled_standard_write=True,
    ),
    "v5x": BleTransportProfile(
        preferred_service_uuid="0000ae30-0000-1000-8000-00805f9b34fb",
        notify_char_uuid="0000ae02-0000-1000-8000-00805f9b34fb",
        bulk_write=BleBulkWriteProfile(
            char_uuid="0000ae03-0000-1000-8000-00805f9b34fb",
            chunk_cap=180,
            write_delay_ms=30,
            flow_controlled=True,
        ),
        write_without_response_payload_reserve=5,
    ),
    "phomemo_esc": BleTransportProfile(
        preferred_service_uuid="0000ff00-0000-1000-8000-00805f9b34fb",
        preferred_write_char_uuid="0000ff02-0000-1000-8000-00805f9b34fb",
        prefer_generic_notify=True,
        standard_chunk_cap=128,
        standard_write_delay_ms=20,
    ),
    "niimbot": BleTransportProfile(
        preferred_service_uuid="e7810a71-73ae-499d-8c15-faa9aef0c3f2",
        prefer_generic_notify=True,
        standard_chunk_cap=20,
        standard_write_delay_ms=10,
    ),
    "eleph_hprt_esc": BleTransportProfile(
        standard_chunk_cap=180,
        standard_write_delay_ms=10,
    ),
    "eleph_tspl": BleTransportProfile(
        preferred_service_uuid="000018f0-0000-1000-8000-00805f9b34fb",
        preferred_write_char_uuid="00002af1-0000-1000-8000-00805f9b34fb",
        standard_chunk_cap=20,
        standard_write_delay_ms=30,
    ),
    "toprint_tspl": BleTransportProfile(
        standard_chunk_cap=180,
        standard_write_delay_ms=10,
    ),
    "toprint_hprt_esc": BleTransportProfile(
        standard_chunk_cap=180,
        standard_write_delay_ms=10,
    ),
    "instaprint_core": BleTransportProfile(
        standard_chunk_cap=180,
        standard_write_delay_ms=10,
    ),
    "funny_lx": BleTransportProfile(
        preferred_service_uuid="0000ffe6-0000-1000-8000-00805f9b34fb",
        preferred_write_char_uuid="0000ffe1-0000-1000-8000-00805f9b34fb",
        notify_char_uuid="0000ffe2-0000-1000-8000-00805f9b34fb",
        standard_chunk_cap=100,
        standard_write_delay_ms=0,
    ),
}


def get_ble_transport_profile(
    protocol_family: str | None,
) -> BleTransportProfile:
    if isinstance(protocol_family, Enum):
        key = protocol_family.value
    elif protocol_family is None:
        key = "legacy"
    else:
        key = str(protocol_family).strip().lower()
    return _PROFILES.get(key, _FALLBACK)
