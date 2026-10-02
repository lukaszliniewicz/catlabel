import asyncio
import base64
import logging
import uuid
from io import BytesIO
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..core.database import engine
from ..core.models import PrinterProfile, Settings
from ..printing.admission import (
    DeviceBusyError,
    canonical_device_address,
    printer_admission,
)
from ..rendering.template import render_via_browser
from ..transport.bluetooth import SppBackend

router = APIRouter(tags=["Print"])
logger = logging.getLogger(__name__)


def _exception_text(exc: BaseException | None) -> str | None:
    if exc is None:
        return None
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _print_http_error(
    *,
    job_id: str,
    stage: str,
    message: str,
    status_code: int,
    exc: BaseException | None = None,
    suggestion: str | None = None,
    delivery_uncertain: bool = False,
) -> HTTPException:
    cause = _exception_text(exc)
    detail = {
        "message": message,
        "stage": stage,
        "error_id": job_id,
        "delivery_uncertain": delivery_uncertain,
    }
    if cause:
        detail["error"] = cause
    if suggestion:
        detail["suggestion"] = suggestion

    exc_info = None
    if exc is not None:
        exc_info = (type(exc), exc, exc.__traceback__)
    logger.error(
        "Print job %s failed during %s: %s%s",
        job_id,
        stage,
        message,
        f" ({cause})" if cause else "",
        exc_info=exc_info,
    )
    return HTTPException(status_code=status_code, detail=detail)


def _same_device_address(left: str, right: str) -> bool:
    try:
        return canonical_device_address(left) == canonical_device_address(right)
    except ValueError:
        return False


class PrintRequest(BaseModel):
    mac_address: str
    variables: dict[str, str] = {}


class DirectPrintRequest(BaseModel):
    mac_address: str
    canvas_state: dict[str, Any]
    variables: dict[str, str] = {}
    dither: bool = True


class BatchPrintRequest(BaseModel):
    mac_address: str
    canvas_state: dict[str, Any]
    copies: int = 1
    variables_list: list[dict[str, str]] = []
    variables_matrix: dict[str, list[str]] | None = None
    dither: bool = True


class ImagePrintRequest(BaseModel):
    mac_address: str
    images: list[str]
    split_mode: bool = False
    is_rotated: bool = False
    dither: bool = True


class PrinterProfileUpdate(BaseModel):
    speed: int | None = None
    energy: int | None = None
    feed_lines: int | None = None
    paper_mode: str | None = None


# SppBackend uses a cache for scanned devices
_scanned_devices_cache: list[Any] = []


def _recognized_scanned_devices(devices: list[Any]) -> list[Any]:
    from ..vendors import VendorRegistry

    recognized = []
    for device in devices:
        name = device.name or "Unknown Printer"
        hardware_info = VendorRegistry.identify_device(name, device, device.address)

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


def _scan_result_payload(device: Any) -> dict[str, Any]:
    from ..vendors import VendorRegistry

    name = device.name or "Unknown Printer"
    hardware_info = VendorRegistry.identify_device(name, device, device.address)
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


@router.get("/api/printers/supported_models")
def get_supported_models():
    from ..vendors import VendorRegistry

    return {"models": VendorRegistry.get_all_models()}


@router.get("/api/printers/model/{name}")
def get_printer_model_info(name: str):
    from ..vendors import VendorRegistry

    return VendorRegistry.identify_device(name)


@router.get("/api/printers/scan")
async def scan_printers():
    global _scanned_devices_cache
    devices, failures = await SppBackend.scan_with_failures(
        include_classic=True,
        include_ble=True,
    )
    _scanned_devices_cache = _recognized_scanned_devices(devices)

    results = [_scan_result_payload(device) for device in _scanned_devices_cache]
    return {"devices": results, "failures": [str(f.error) for f in failures]}


@router.get("/api/printers/{mac_address}/profile")
def get_printer_profile(mac_address: str):
    with Session(engine) as session:
        profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()
        if not profile:
            profile = PrinterProfile(mac_address=mac_address)
            session.add(profile)
            session.commit()
            session.refresh(profile)
        return profile


@router.put("/api/printers/{mac_address}/profile")
def update_printer_profile(mac_address: str, update: PrinterProfileUpdate):
    from ..protocol.types import PaperMode

    with Session(engine) as session:
        profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()
        if not profile:
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
                raise HTTPException(
                    status_code=400, detail="Unsupported paper mode"
                ) from exc

        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile


async def execute_print_jobs(
    mac_address: str, images: list[Any], split_mode: bool = False, dither: bool = True
):
    job_id = uuid.uuid4().hex[:8]
    try:
        canonical_device_address(mac_address)
    except ValueError as exc:
        raise _print_http_error(
            job_id=job_id,
            stage="admission",
            status_code=400,
            message="Select a printer with a valid device address.",
            exc=exc,
        ) from exc
    try:
        async with printer_admission.claim(mac_address):
            return await _execute_claimed_print_jobs(
                mac_address, images, split_mode, dither, job_id
            )
    except DeviceBusyError as exc:
        raise _print_http_error(
            job_id=job_id,
            stage="admission",
            status_code=409,
            message="Another print job is already using this printer.",
            exc=exc,
            suggestion="Wait for the current job to finish before submitting another.",
        ) from exc


async def _execute_claimed_print_jobs(
    mac_address: str, images: list[Any], split_mode: bool, dither: bool, job_id: str
):
    global _scanned_devices_cache

    def _get_db_settings(mac):
        with Session(engine) as session:
            settings = session.get(Settings, 1) or Settings()
            printer_profile = session.exec(
                select(PrinterProfile).where(PrinterProfile.mac_address == mac)
            ).first()
            return {
                "settings": settings,
                "profile": printer_profile,
            }

    db_data = await asyncio.to_thread(_get_db_settings, mac_address)
    settings = db_data["settings"]
    printer_profile = db_data["profile"]

    target_device = next(
        (
            d
            for d in _scanned_devices_cache
            if _same_device_address(d.address, mac_address)
        ),
        None,
    )
    scan_failures = []

    if not target_device:
        try:
            devices, scan_failures = await SppBackend.scan_with_failures(
                include_classic=True,
                include_ble=True,
            )
        except Exception as exc:
            raise _print_http_error(
                job_id=job_id,
                stage="scan",
                message="CatLabel could not scan the computer's Bluetooth adapters.",
                status_code=503,
                exc=exc,
                suggestion="Check that Bluetooth is enabled, then scan for the printer again.",
            ) from exc
        _scanned_devices_cache = _recognized_scanned_devices(devices)
        target_device = next(
            (
                d
                for d in _scanned_devices_cache
                if _same_device_address(d.address, mac_address)
            ),
            None,
        )

    if not target_device:
        scan_detail = "; ".join(str(f.error) for f in scan_failures) or None
        raise _print_http_error(
            job_id=job_id,
            stage="scan",
            message=f"Printer {mac_address} was not found during a fresh Bluetooth scan.",
            status_code=404,
            exc=RuntimeError(scan_detail) if scan_detail else None,
            suggestion="Make sure the printer is on and in range, then scan and select it again.",
        )

    from ..vendors import VendorRegistry

    try:
        hardware_info = VendorRegistry.identify_device(
            getattr(target_device, "name", ""),
            target_device,
            target_device.address,
        )
        if hardware_info.get("model_id") == "generic":
            raise HTTPException(
                status_code=422,
                detail="This device has no unambiguous supported printer profile.",
            )
        manifest = VendorRegistry.get_manifest(hardware_info["vendor"])
        client = manifest.get_client(
            target_device, hardware_info, printer_profile, settings
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _print_http_error(
            job_id=job_id,
            stage="prepare",
            message="CatLabel could not prepare the selected printer driver.",
            status_code=500,
            exc=exc,
        ) from exc

    try:
        try:
            connected = await client.connect()
        except HTTPException as exc:
            raise _print_http_error(
                job_id=job_id,
                stage="connect",
                message=str(exc.detail),
                status_code=exc.status_code,
                exc=exc,
                suggestion="Check that the printer is on, in range, and paired when using Classic Bluetooth.",
            ) from exc
        except Exception as exc:
            raise _print_http_error(
                job_id=job_id,
                stage="connect",
                status_code=503,
                exc=exc,
                message=f"CatLabel could not connect using the {hardware_info['vendor']} printer driver.",
                suggestion="Check that the printer is on, in range, and paired when using Classic Bluetooth.",
            ) from exc
        if not connected:
            raise _print_http_error(
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
            raise _print_http_error(
                job_id=job_id,
                stage=str(getattr(exc, "stage", "print")),
                message=message,
                status_code=exc.status_code if isinstance(exc, HTTPException) else 500,
                exc=exc,
                delivery_uncertain=uncertain,
                suggestion=(
                    "Check the physical output before resubmitting; retrying can produce duplicate labels."
                    if uncertain
                    else "Check the printer and media settings before submitting again."
                ),
            ) from exc
    finally:
        try:
            await client.disconnect()
        except Exception:
            # Cleanup must not hide the original failure or retain admission.
            logger.exception("Print job %s failed while disconnecting", job_id)
    return {
        "status": "submitted",
        "submitted": len(images),
        "physical_completion": "unverified",
        "job_id": job_id,
        "message": "Label data sent. Check the printer for the physical output.",
    }


async def execute_print_job(
    mac_address: str, img: Any, split_mode: bool = False, dither: bool = True
):
    return await execute_print_jobs(mac_address, [img], split_mode, dither=dither)


@router.post("/api/print/direct")
async def print_direct(request: DirectPrintRequest):
    split_mode = request.canvas_state.get("splitMode", False)
    images = await asyncio.to_thread(
        render_via_browser,
        request.canvas_state,
        [request.variables or {}],
        1,
    )
    receipt = await execute_print_jobs(
        request.mac_address, images, split_mode, dither=request.dither
    )
    return {**receipt, "mac_address": request.mac_address}


@router.post("/api/print/batch")
async def print_batch(request: BatchPrintRequest):
    split_mode = request.canvas_state.get("splitMode", False)

    variables_collection = []
    if request.variables_list:
        variables_collection.extend(request.variables_list)

    if request.variables_matrix:
        import itertools

        keys = list(request.variables_matrix.keys())
        values = list(request.variables_matrix.values())
        for combination in itertools.product(*values):
            variables_collection.append(dict(zip(keys, combination, strict=True)))

    if not variables_collection:
        variables_collection = [{}]

    images = await asyncio.to_thread(
        render_via_browser,
        request.canvas_state,
        variables_collection,
        request.copies,
    )

    return await execute_print_jobs(
        request.mac_address, images, split_mode, dither=request.dither
    )


@router.post("/api/print/images")
async def print_images_direct(request: ImagePrintRequest):
    from PIL import Image

    if not request.images:
        return {"status": "empty", "submitted": 0, "physical_completion": "unverified"}

    def _process_images(images_b64, is_rotated):
        pil_images = []
        for b64_image in images_b64:
            image_data = b64_image.split(",", 1)[1] if "," in b64_image else b64_image
            decoded = base64.b64decode(image_data)
            with Image.open(BytesIO(decoded)) as image:
                rendered = image.convert("RGB")
                if is_rotated:
                    rendered = rendered.rotate(90, expand=True)
                pil_images.append(rendered)
        return pil_images

    try:
        pil_images = await asyncio.to_thread(
            _process_images, request.images, request.is_rotated
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Invalid image payload supplied."
        ) from exc

    return await execute_print_jobs(
        request.mac_address, pil_images, request.split_mode, dither=request.dither
    )
