from __future__ import annotations

from .commands import (
    blackening_cmd,
    dev_state_cmd,
    energy_cmd,
    feed_paper_cmd,
    paper_cmd,
    print_mode_cmd,
)
from .encoding import build_line_packets
from .families import PrintJobRequest, get_protocol_behavior
from .family import ProtocolFamily
from .types import Raster


def _build_family_job(request: PrintJobRequest) -> bytes | None:
    behavior = get_protocol_behavior(request.protocol_family)
    if behavior.job_builder is None:
        return None
    return behavior.job_builder(request)


def build_print_payload(
    pixels: list[int],
    width: int,
    is_text: bool,
    speed: int,
    energy: int,
    compress: bool,
    lsb_first: bool,
    protocol_family: ProtocolFamily | str,
) -> bytes:
    """Build the main payload for a print job (no final feed/state)."""
    family = ProtocolFamily.from_value(protocol_family)
    request = PrintJobRequest(
        pixels=pixels,
        width=width,
        is_text=is_text,
        speed=speed,
        energy=energy,
        blackening=3,
        compress=compress,
        lsb_first=lsb_first,
        protocol_family=family,
        feed_padding=0,
        dev_dpi=203,
    )
    family_payload = _build_family_job(request)
    if family_payload is not None:
        return family_payload

    payload = bytearray()
    payload += energy_cmd(energy, family)
    payload += print_mode_cmd(is_text, family)
    payload += feed_paper_cmd(speed, family)
    payload += build_line_packets(
        pixels,
        width,
        speed,
        compress,
        lsb_first,
        family,
        line_feed_every=200,
    )
    return bytes(payload)


def build_print_payload_from_raster(
    raster: Raster,
    is_text: bool,
    speed: int,
    energy: int,
    compress: bool,
    lsb_first: bool,
    protocol_family: ProtocolFamily | str,
) -> bytes:
    """Build the main payload from a Raster helper object."""
    raster.validate()
    return build_print_payload(
        raster.pixels,
        raster.width,
        is_text,
        speed,
        energy,
        compress,
        lsb_first,
        protocol_family,
    )


def build_job(
    pixels: list[int],
    width: int,
    is_text: bool,
    speed: int,
    energy: int,
    blackening: int,
    compress: bool,
    lsb_first: bool,
    protocol_family: ProtocolFamily | str,
    feed_padding: int,
    dev_dpi: int,
) -> bytes:
    """Build a full job payload ready to send to the printer."""
    family = ProtocolFamily.from_value(protocol_family)
    request = PrintJobRequest(
        pixels=pixels,
        width=width,
        is_text=is_text,
        speed=speed,
        energy=energy,
        blackening=blackening,
        compress=compress,
        lsb_first=lsb_first,
        protocol_family=family,
        feed_padding=feed_padding,
        dev_dpi=dev_dpi,
    )
    family_job = _build_family_job(request)
    if family_job is not None:
        return family_job

    job = bytearray()
    job += blackening_cmd(blackening, family)
    job += build_print_payload(
        pixels,
        width,
        is_text,
        speed,
        energy,
        compress,
        lsb_first,
        family,
    )
    job += feed_paper_cmd(feed_padding, family)
    job += paper_cmd(dev_dpi, family)
    job += paper_cmd(dev_dpi, family)
    job += feed_paper_cmd(feed_padding, family)
    job += dev_state_cmd(family)
    return bytes(job)


def build_job_from_raster(
    raster: Raster,
    is_text: bool,
    speed: int,
    energy: int,
    blackening: int,
    compress: bool,
    lsb_first: bool,
    protocol_family: ProtocolFamily | str,
    feed_padding: int,
    dev_dpi: int,
) -> bytes:
    """Build a full job payload from a Raster helper object."""
    raster.validate()
    return build_job(
        raster.pixels,
        raster.width,
        is_text,
        speed,
        energy,
        blackening,
        compress,
        lsb_first,
        protocol_family,
        feed_padding,
        dev_dpi,
    )
