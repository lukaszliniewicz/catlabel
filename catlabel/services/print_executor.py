"""Printer admission and execution, independent of REST and MCP adapters."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from types import SimpleNamespace
from typing import Any

from PIL import Image
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from ..core.database import engine as default_engine
from ..core.models import PrinterProfile, Settings
from ..core.resource_limits import ResourceLimitError
from ..printing.admission import (
    DeviceAdmission,
    DeviceBusyError,
    canonical_device_address,
    printer_admission,
)
from ..transport.bluetooth import SppBackend
from ..vendors import VendorRegistry
from .printers import (
    ServiceError,
    hardware_catalog_hash,
    scan_recognized_devices,
    scanned_devices_cache,
)

logger = logging.getLogger(__name__)

DeliveryStartHook = Callable[[], Awaitable[None]]
ClaimedExecutor = Callable[[str, list[Any], bool, bool, str], Awaitable[dict[str, Any]]]


def _exception_text(exc: BaseException | None) -> str | None:
    if exc is None:
        return None
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _print_service_error(
    *,
    job_id: str,
    stage: str,
    message: str,
    status_code: int,
    exc: BaseException | None = None,
    suggestion: str | None = None,
    delivery_uncertain: bool = False,
    code: str | None = None,
) -> ServiceError:
    detail: dict[str, Any] = {
        "message": message,
        "stage": stage,
        "error_id": job_id,
        "delivery_uncertain": delivery_uncertain,
    }
    cause = _exception_text(exc)
    if cause:
        detail["error"] = cause
    if suggestion:
        detail["suggestion"] = suggestion
    if code:
        detail["code"] = code
    return ServiceError(
        status_code,
        detail,
        cause=exc if isinstance(exc, Exception) else None,
    )


async def with_print_admission(
    mac_address: str,
    action: Callable[[str], Awaitable[dict[str, Any]]],
    *,
    admission: DeviceAdmission = printer_admission,
) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:8]
    try:
        canonical_device_address(mac_address)
    except ValueError as exc:
        raise _print_service_error(
            job_id=job_id,
            stage="admission",
            status_code=400,
            message="Select a printer with a valid device address.",
            exc=exc,
        ) from exc
    try:
        async with admission.claim(mac_address):
            return await action(job_id)
    except DeviceBusyError as exc:
        raise _print_service_error(
            job_id=job_id,
            stage="admission",
            status_code=409,
            message="Another print job is already using this printer.",
            exc=exc,
            suggestion="Wait for the current job to finish before submitting another.",
        ) from exc


def _db_settings_and_profile(
    db_engine: Engine, mac_address: str
) -> tuple[Settings, PrinterProfile | None]:
    with Session(db_engine) as session:
        settings = session.get(Settings, 1) or Settings()
        profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()
        return settings, profile


def _snapshot_object(values: Mapping[str, Any]) -> SimpleNamespace:
    # Printer clients consume these values through attributes. Copying the
    # mapping keeps a caller's frozen plan untouched while preserving that API.
    return SimpleNamespace(**dict(values))


def _expected_hardware_matches(
    expected_hardware: Mapping[str, Any] | None,
    hardware_info: Mapping[str, Any],
    *,
    vendor_registry: Any,
) -> bool:
    if expected_hardware is None:
        return True

    checks = {
        key: expected_value
        for key, expected_value in expected_hardware.items()
        if expected_value is not None
    }
    if not checks:
        return True
    actual: dict[str, Any] = {
        "vendor": hardware_info.get("vendor"),
        "model_id": hardware_info.get("model_id"),
    }
    if "catalog_sha256" in checks:
        actual["catalog_sha256"] = hardware_catalog_hash(
            vendor_registry=vendor_registry
        )
    return all(actual[key] == expected_value for key, expected_value in checks.items())


async def execute_claimed_print_jobs(
    mac_address: str,
    images: list[Any],
    split_mode: bool,
    dither: bool,
    job_id: str,
    *,
    db_engine: Engine | None = None,
    devices_cache: list[Any] | None = None,
    scanner: Any = SppBackend,
    vendor_registry: Any = VendorRegistry,
    frozen_settings: dict[str, Any] | None = None,
    frozen_profile: dict[str, Any] | None = None,
    expected_hardware: dict[str, Any] | None = None,
    on_delivery_start: DeliveryStartHook | None = None,
) -> dict[str, Any]:
    """Execute a job while its caller holds the per-printer admission claim."""
    engine = default_engine if db_engine is None else db_engine
    target_cache = scanned_devices_cache if devices_cache is None else devices_cache

    settings: Any
    printer_profile: Any
    if frozen_settings is None or frozen_profile is None:
        stored_settings, stored_profile = await asyncio.to_thread(
            _db_settings_and_profile, engine, mac_address
        )
        settings = (
            stored_settings
            if frozen_settings is None
            else _snapshot_object(frozen_settings)
        )
        printer_profile = (
            stored_profile
            if frozen_profile is None
            else _snapshot_object(frozen_profile)
        )
    else:
        settings = _snapshot_object(frozen_settings)
        printer_profile = _snapshot_object(frozen_profile)

    target_device = next(
        (
            device
            for device in target_cache
            if _same_device_address(device.address, mac_address)
        ),
        None,
    )
    scan_failures: list[Any] = []

    if target_device is None:
        try:
            recognized, scan_failures = await scan_recognized_devices(
                scanner=scanner,
                cache=target_cache,
                vendor_registry=vendor_registry,
            )
        except Exception as exc:
            raise _print_service_error(
                job_id=job_id,
                stage="scan",
                message="CatLabel could not scan the computer's Bluetooth adapters.",
                status_code=503,
                exc=exc,
                suggestion="Check that Bluetooth is enabled, then scan for the printer again.",
            ) from exc
        target_device = next(
            (
                device
                for device in recognized
                if _same_device_address(device.address, mac_address)
            ),
            None,
        )

    if target_device is None:
        scan_detail = "; ".join(str(failure.error) for failure in scan_failures) or None
        raise _print_service_error(
            job_id=job_id,
            stage="scan",
            message=f"Printer {mac_address} was not found during a fresh Bluetooth scan.",
            status_code=404,
            exc=RuntimeError(scan_detail) if scan_detail else None,
            suggestion="Make sure the printer is on and in range, then scan and select it again.",
        )

    try:
        hardware_info = vendor_registry.identify_device(
            getattr(target_device, "name", ""),
            target_device,
            target_device.address,
        )
        if hardware_info.get("model_id") == "generic":
            raise ServiceError(
                422,
                "This device has no unambiguous supported printer profile.",
            )
        unknown_expected_fields = set(expected_hardware or {}) - {
            "vendor",
            "model_id",
            "catalog_sha256",
        }
        if unknown_expected_fields:
            raise ServiceError(
                422,
                "Unsupported expected hardware fields: "
                + ", ".join(sorted(str(key) for key in unknown_expected_fields)),
            )
        matches_expected = _expected_hardware_matches(
            expected_hardware,
            hardware_info,
            vendor_registry=vendor_registry,
        )
        if not matches_expected:
            raise _print_service_error(
                job_id=job_id,
                stage="prepare",
                message="The selected printer or supported model catalog changed after this job was prepared.",
                status_code=409,
                code="printer_capabilities_changed",
            )
        manifest = vendor_registry.get_manifest(hardware_info["vendor"])
        client = manifest.get_client(
            target_device,
            hardware_info,
            printer_profile,
            settings,
        )
    except ServiceError:
        raise
    except Exception as exc:
        raise _print_service_error(
            job_id=job_id,
            stage="prepare",
            message="CatLabel could not prepare the selected printer driver.",
            status_code=500,
            exc=exc,
        ) from exc

    try:
        submitted_labels = client.validate_images(images, split_mode)
    except ResourceLimitError as exc:
        raise _print_service_error(
            job_id=job_id,
            stage="validation",
            message=str(exc),
            status_code=422,
            exc=exc,
            delivery_uncertain=False,
        ) from exc

    if on_delivery_start is not None:
        try:
            await on_delivery_start()
        except ServiceError:
            raise
        except Exception as exc:
            raise _print_service_error(
                job_id=job_id,
                stage="delivery_start",
                message="CatLabel could not record that printer delivery is starting.",
                status_code=503,
                exc=exc,
                suggestion="No printer controls were sent; retry after the print service is available.",
                delivery_uncertain=False,
            ) from exc

    pending_cancellation: asyncio.CancelledError | None = None
    try:
        try:
            connected = await client.connect()
        except Exception as exc:
            status_code = getattr(exc, "status_code", 503)
            detail = getattr(exc, "detail", None)
            message = (
                str(detail)
                if detail is not None
                else f"CatLabel could not connect using the {hardware_info['vendor']} printer driver."
            )
            raise _print_service_error(
                job_id=job_id,
                stage="connect",
                status_code=status_code if isinstance(status_code, int) else 503,
                exc=exc,
                message=message,
                suggestion="Check that the printer is on, in range, and paired when using Classic Bluetooth.",
            ) from exc
        if not connected:
            raise _print_service_error(
                job_id=job_id,
                stage="connect",
                status_code=503,
                exc=getattr(client, "last_error", None),
                message=f"CatLabel could not connect using the {hardware_info['vendor']} printer driver.",
                suggestion="Check that the printer is on, in range, and paired when using Classic Bluetooth.",
            )

        try:
            await client.print_images(images, split_mode, dither=dither)
        except Exception as exc:
            uncertain = bool(getattr(exc, "delivery_uncertain", True))
            message = (
                "The print job stopped. Some labels may already have printed."
                if uncertain
                else "The printer rejected the job before label data was sent."
            )
            raw_status = getattr(exc, "status_code", 500)
            raise _print_service_error(
                job_id=job_id,
                stage=str(getattr(exc, "stage", "print")),
                message=message,
                status_code=raw_status if isinstance(raw_status, int) else 500,
                exc=exc,
                delivery_uncertain=uncertain,
                suggestion=(
                    "Check the physical output before resubmitting; retrying can produce duplicate labels."
                    if uncertain
                    else "Check the printer and media settings before submitting again."
                ),
            ) from exc
    except asyncio.CancelledError as exc:
        pending_cancellation = exc
        raise
    finally:
        try:
            await _disconnect_owned(client, job_id)
        except asyncio.CancelledError as cleanup_cancellation:
            if pending_cancellation is not None:
                raise pending_cancellation from cleanup_cancellation
            raise

    return {
        "status": "submitted",
        "submitted": submitted_labels,
        "physical_completion": "unverified",
        "job_id": job_id,
        "message": "Label data sent. Check the printer for the physical output.",
    }


def _same_device_address(left: str, right: str) -> bool:
    try:
        return canonical_device_address(left) == canonical_device_address(right)
    except ValueError:
        return False


async def _disconnect_owned(client: Any, job_id: str) -> None:
    """Drain a disconnect task without losing the first cancellation."""
    task = asyncio.create_task(client.disconnect())
    cancellation: asyncio.CancelledError | None = None

    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            caller_task = asyncio.current_task()
            if caller_task is not None and caller_task.cancelling() > 0:
                if cancellation is None:
                    cancellation = exc
                if task.done():
                    break
            elif cancellation is None:
                cancellation = exc
                break
        except Exception:
            break

    try:
        task.result()
    except asyncio.CancelledError as exc:
        if cancellation is None:
            cancellation = exc
    except Exception:
        logger.exception("Print job %s failed while disconnecting", job_id)

    if cancellation is not None:
        raise cancellation


async def execute_print_jobs(
    mac_address: str,
    images: list[Any],
    split_mode: bool = False,
    dither: bool = True,
    *,
    admission: DeviceAdmission = printer_admission,
    db_engine: Engine | None = None,
    devices_cache: list[Any] | None = None,
    scanner: Any = SppBackend,
    vendor_registry: Any = VendorRegistry,
    frozen_settings: dict[str, Any] | None = None,
    frozen_profile: dict[str, Any] | None = None,
    expected_hardware: dict[str, Any] | None = None,
    on_delivery_start: DeliveryStartHook | None = None,
    claimed_executor: ClaimedExecutor | None = None,
) -> dict[str, Any]:
    """Print borrowed images without taking ownership of or closing them."""

    async def execute(job_id: str) -> dict[str, Any]:
        if (
            claimed_executor is not None
            and frozen_settings is None
            and frozen_profile is None
            and expected_hardware is None
            and on_delivery_start is None
        ):
            return await claimed_executor(
                mac_address, images, split_mode, dither, job_id
            )
        return await execute_claimed_print_jobs(
            mac_address,
            images,
            split_mode,
            dither,
            job_id,
            db_engine=db_engine,
            devices_cache=devices_cache,
            scanner=scanner,
            vendor_registry=vendor_registry,
            frozen_settings=frozen_settings,
            frozen_profile=frozen_profile,
            expected_hardware=expected_hardware,
            on_delivery_start=on_delivery_start,
        )

    return await with_print_admission(mac_address, execute, admission=admission)


async def execute_owned_print_jobs(
    mac_address: str,
    prepare: Callable[[], Awaitable[list[Image.Image]]],
    split_mode: bool = False,
    dither: bool = True,
    *,
    admission: DeviceAdmission = printer_admission,
    db_engine: Engine | None = None,
    devices_cache: list[Any] | None = None,
    scanner: Any = SppBackend,
    vendor_registry: Any = VendorRegistry,
    frozen_settings: dict[str, Any] | None = None,
    frozen_profile: dict[str, Any] | None = None,
    expected_hardware: dict[str, Any] | None = None,
    on_delivery_start: DeliveryStartHook | None = None,
    claimed_executor: ClaimedExecutor | None = None,
) -> dict[str, Any]:
    async def execute(job_id: str) -> dict[str, Any]:
        images = await prepare()
        try:
            if (
                claimed_executor is not None
                and frozen_settings is None
                and frozen_profile is None
                and expected_hardware is None
                and on_delivery_start is None
            ):
                return await claimed_executor(
                    mac_address, images, split_mode, dither, job_id
                )
            return await execute_claimed_print_jobs(
                mac_address,
                images,
                split_mode,
                dither,
                job_id,
                db_engine=db_engine,
                devices_cache=devices_cache,
                scanner=scanner,
                vendor_registry=vendor_registry,
                frozen_settings=frozen_settings,
                frozen_profile=frozen_profile,
                expected_hardware=expected_hardware,
                on_delivery_start=on_delivery_start,
            )
        finally:
            for image in images:
                try:
                    image.close()
                except Exception:
                    logger.exception(
                        "Print job %s failed while closing an owned image", job_id
                    )

    return await with_print_admission(mac_address, execute, admission=admission)


async def execute_print_job(
    mac_address: str,
    image: Any,
    split_mode: bool = False,
    dither: bool = True,
) -> dict[str, Any]:
    return await execute_print_jobs(mac_address, [image], split_mode, dither=dither)
