"""Printer discovery, model metadata, and profile persistence services."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from ..core.models import PrinterProfile
from ..transport.bluetooth import SppBackend
from ..vendors import VendorRegistry


class ServiceError(Exception):
    """An application service failure with an HTTP-compatible status and detail."""

    def __init__(
        self, status_code: int, detail: Any, *, cause: Exception | None = None
    ):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.cause = cause


class PrinterProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speed: int | None = None
    energy: int | None = None
    feed_lines: int | None = None
    paper_mode: str | None = None


# This is the one process-local discovery cache used by direct service callers.
# REST routes pass their legacy module variable as the cache for monkeypatch
# compatibility, so the route and service never maintain parallel caches.
scanned_devices_cache: list[Any] = []


def get_supported_models() -> dict[str, Any]:
    vendor_registry: Any = VendorRegistry
    return {"models": cast(list[dict[str, Any]], vendor_registry.get_all_models())}


def get_printer_model_info(name: str) -> dict[str, Any]:
    vendor_registry: Any = VendorRegistry
    return cast(dict[str, Any], vendor_registry.identify_device(name))


def hardware_catalog_hash(*, vendor_registry: Any = VendorRegistry) -> str:
    """Hash the exact public model catalog using its canonical JSON form."""
    payload = json.dumps(
        vendor_registry.get_all_models(),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def recognized_scanned_devices(
    devices: list[Any], *, vendor_registry: Any = VendorRegistry
) -> list[Any]:
    recognized: list[Any] = []
    for device in devices:
        name = device.name or "Unknown Printer"
        hardware_info = vendor_registry.identify_device(name, device, device.address)

        if (
            hardware_info.get("vendor") == "generic"
            and hardware_info.get("model_id") == "generic"
        ):
            continue

        transport = getattr(device, "transport", None)
        transport_value = str(getattr(transport, "value", transport) or "").lower()
        if (
            hardware_info.get("vendor") in {"niimbot", "phomemo"}
            and transport_value != "ble"
        ):
            continue

        recognized.append(device)
    return recognized


def scan_result_payload(
    device: Any, *, vendor_registry: Any = VendorRegistry
) -> dict[str, Any]:
    name = device.name or "Unknown Printer"
    hardware_info = vendor_registry.identify_device(name, device, device.address)
    transport = getattr(device, "transport", None)
    transport_value = str(getattr(transport, "value", transport) or "").lower()

    return {
        **hardware_info,
        "name": name,
        "address": device.address,
        "display_address": getattr(device, "display_address", device.address),
        "paired": device.paired,
        "transport": transport_value or None,
    }


async def scan_recognized_devices(
    *,
    scanner: Any = SppBackend,
    cache: list[Any] | None = None,
    vendor_registry: Any = VendorRegistry,
) -> tuple[list[Any], list[Any]]:
    devices, failures = await scanner.scan_with_failures(
        include_classic=True,
        include_ble=True,
    )
    recognized = recognized_scanned_devices(devices, vendor_registry=vendor_registry)
    target_cache = scanned_devices_cache if cache is None else cache
    target_cache[:] = recognized
    return recognized, failures


async def scan_printers(
    *,
    scanner: Any = SppBackend,
    cache: list[Any] | None = None,
    vendor_registry: Any = VendorRegistry,
) -> dict[str, Any]:
    devices, failures = await scan_recognized_devices(
        scanner=scanner,
        cache=cache,
        vendor_registry=vendor_registry,
    )
    return {
        "devices": [
            scan_result_payload(device, vendor_registry=vendor_registry)
            for device in devices
        ],
        "failures": [str(failure.error) for failure in failures],
    }


def get_printer_profile(
    mac_address: str,
    *,
    db_engine: Engine,
    create_defaults: bool = False,
) -> PrinterProfile | None:
    with Session(db_engine) as session:
        profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()
        if profile is None:
            profile = PrinterProfile(mac_address=mac_address)
            if create_defaults:
                session.add(profile)
                session.commit()
                session.refresh(profile)
        return profile


def update_printer_profile(
    mac_address: str,
    update: PrinterProfileUpdate,
    *,
    db_engine: Engine,
) -> PrinterProfile:
    from ..protocol.types import PaperMode

    with Session(db_engine) as session:
        profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()
        if profile is None:
            profile = PrinterProfile(mac_address=mac_address)

        if update.speed is not None:
            profile.speed = update.speed
        if update.energy is not None:
            profile.energy = update.energy
        if update.feed_lines is not None:
            profile.feed_lines = update.feed_lines
        if update.paper_mode is not None:
            try:
                profile.paper_mode = (
                    None
                    if update.paper_mode == ""
                    else PaperMode(update.paper_mode).value
                )
            except ValueError as exc:
                raise ServiceError(400, "Unsupported paper mode", cause=exc) from exc

        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile
