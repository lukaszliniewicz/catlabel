import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from PIL import Image
from pydantic import BaseModel, Field

from ..core.database import engine
from ..core.resource_limits import (
    MAX_BATCH_RECORDS,
    MAX_PRINT_COPIES,
    MAX_PRINT_JOBS,
    ResourceLimitError,
    batch_record_count,
    validate_render_budget,
)
from ..printing.admission import canonical_device_address, printer_admission
from ..rendering.image_payload import decode_image_payloads
from ..rendering.owned_decode import decode_owned
from ..rendering.template import (
    RenderBusyError,
    RendererStoppedError,
    render_via_browser_async,
)
from ..services import print_executor
from ..services import printers as printer_service
from ..services.harness import HarnessServices
from ..services.print_jobs import JobError
from ..services.printers import PrinterProfileUpdate, ServiceError
from ..transport.bluetooth import SppBackend
from ..vendors import VendorRegistry

router = APIRouter(tags=["Print"])
logger = logging.getLogger(__name__)

_harness: HarnessServices | None = None


def configure_harness(service: HarnessServices | None) -> None:
    global _harness
    _harness = service


@router.get("/api/print/jobs/{job_id}")
def get_print_job(job_id: str):
    if _harness is None:
        raise HTTPException(503, "Print job service is not ready.")
    try:
        return _harness.jobs.job_get(job_id, "local-editor")
    except JobError as exc:
        raise HTTPException(404, exc.code) from exc


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


def _render_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (RenderBusyError, RendererStoppedError)):
        status_code = 503
    elif isinstance(exc, TimeoutError):
        status_code = 504
    elif isinstance(exc, ResourceLimitError):
        status_code = 422
    else:
        status_code = 500
    return HTTPException(
        status_code=status_code,
        detail={
            "message": str(exc),
            "stage": "render",
            "delivery_uncertain": False,
        },
    )


def _same_device_address(left: str, right: str) -> bool:
    try:
        return canonical_device_address(left) == canonical_device_address(right)
    except ValueError:
        return False


class PrintRequest(BaseModel):
    mac_address: str
    variables: dict[str, str] = Field(default_factory=dict)


class DirectPrintRequest(BaseModel):
    mac_address: str
    canvas_state: dict[str, Any]
    variables: dict[str, str] = Field(default_factory=dict)
    dither: bool = True


class BatchPrintRequest(BaseModel):
    mac_address: str
    canvas_state: dict[str, Any]
    copies: int = Field(default=1, strict=True, ge=1, le=MAX_PRINT_COPIES)
    variables_list: list[dict[str, str]] = Field(
        default_factory=list, max_length=MAX_BATCH_RECORDS
    )
    variables_matrix: dict[str, list[str]] | None = None
    dither: bool = True


class ImagePrintRequest(BaseModel):
    mac_address: str
    images: list[str] = Field(max_length=MAX_PRINT_JOBS)
    split_mode: bool = False
    is_rotated: bool = False
    dither: bool = True


# SppBackend uses a cache for scanned devices
_scanned_devices_cache: list[Any] = printer_service.scanned_devices_cache


def _recognized_scanned_devices(devices: list[Any]) -> list[Any]:
    return printer_service.recognized_scanned_devices(
        devices,
        vendor_registry=VendorRegistry,
    )


def _scan_result_payload(device: Any) -> dict[str, Any]:
    return printer_service.scan_result_payload(
        device,
        vendor_registry=VendorRegistry,
    )


@router.get("/api/printers/supported_models")
def get_supported_models():
    return printer_service.get_supported_models()


@router.get("/api/printers/model/{name}")
def get_printer_model_info(name: str):
    return printer_service.get_printer_model_info(name)


@router.get("/api/printers/scan")
async def scan_printers():
    return await printer_service.scan_printers(
        scanner=SppBackend,
        cache=_scanned_devices_cache,
        vendor_registry=VendorRegistry,
    )


@router.get("/api/printers/{mac_address}/profile")
def get_printer_profile(mac_address: str):
    return printer_service.get_printer_profile(
        mac_address,
        db_engine=engine,
        create_defaults=True,
    )


@router.put("/api/printers/{mac_address}/profile")
def update_printer_profile(mac_address: str, update: PrinterProfileUpdate):
    try:
        return printer_service.update_printer_profile(
            mac_address,
            update,
            db_engine=engine,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _service_http_error(exc: ServiceError) -> HTTPException:
    detail = exc.detail
    if isinstance(detail, dict) and detail.get("error_id"):
        cause = exc.cause
        exc_info = (
            (type(cause), cause, cause.__traceback__) if cause is not None else None
        )
        logger.error(
            "Print job %s failed during %s: %s%s",
            detail.get("error_id"),
            detail.get("stage", "print"),
            detail.get("message", str(exc)),
            f" ({detail['error']})" if detail.get("error") else "",
            exc_info=exc_info,
        )
    return HTTPException(status_code=exc.status_code, detail=detail)


async def _with_print_admission(
    mac_address: str,
    action: Callable[[str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    try:
        return await print_executor.with_print_admission(
            mac_address,
            action,
            admission=printer_admission,
        )
    except ServiceError as exc:
        raise _service_http_error(exc) from exc


async def _execute_claimed_print_jobs(
    mac_address: str,
    images: list[Any],
    split_mode: bool,
    dither: bool,
    job_id: str,
) -> dict[str, Any]:
    return await print_executor.execute_claimed_print_jobs(
        mac_address,
        images,
        split_mode,
        dither,
        job_id,
        db_engine=engine,
        devices_cache=_scanned_devices_cache,
        scanner=SppBackend,
        vendor_registry=VendorRegistry,
    )


async def execute_print_jobs(
    mac_address: str,
    images: list[Any],
    split_mode: bool = False,
    dither: bool = True,
) -> dict[str, Any]:
    """Print borrowed images without taking ownership of or closing them."""
    try:
        return await print_executor.execute_print_jobs(
            mac_address,
            images,
            split_mode,
            dither=dither,
            admission=printer_admission,
            db_engine=engine,
            devices_cache=_scanned_devices_cache,
            scanner=SppBackend,
            vendor_registry=VendorRegistry,
            claimed_executor=_execute_claimed_print_jobs,
        )
    except ServiceError as exc:
        raise _service_http_error(exc) from exc


async def execute_owned_print_jobs(
    mac_address: str,
    prepare: Callable[[], Awaitable[list[Image.Image]]],
    split_mode: bool = False,
    dither: bool = True,
    *,
    frozen_settings: dict[str, Any] | None = None,
    frozen_profile: dict[str, Any] | None = None,
    expected_hardware: dict[str, Any] | None = None,
    on_delivery_start: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    if _harness is not None and frozen_settings is None and frozen_profile is None:
        try:
            return await _harness.submit_legacy(
                mac_address, prepare, split_mode, dither
            )
        except ServiceError as exc:
            raise _service_http_error(exc) from exc
    try:
        return await print_executor.execute_owned_print_jobs(
            mac_address,
            prepare,
            split_mode,
            dither=dither,
            admission=printer_admission,
            db_engine=engine,
            devices_cache=_scanned_devices_cache,
            scanner=SppBackend,
            vendor_registry=VendorRegistry,
            frozen_settings=frozen_settings,
            frozen_profile=frozen_profile,
            expected_hardware=expected_hardware,
            on_delivery_start=on_delivery_start,
            claimed_executor=_execute_claimed_print_jobs,
        )
    except ServiceError as exc:
        raise _service_http_error(exc) from exc


async def execute_print_job(
    mac_address: str, img: Any, split_mode: bool = False, dither: bool = True
):
    return await execute_print_jobs(mac_address, [img], split_mode, dither=dither)


@router.post("/api/print/direct")
async def print_direct(request: DirectPrintRequest):
    try:
        validate_render_budget(request.canvas_state, records=1, copies=1)
    except ResourceLimitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    split_mode = request.canvas_state.get("splitMode", False)

    async def prepare() -> list[Image.Image]:
        try:
            return await render_via_browser_async(
                request.canvas_state,
                [request.variables or {}],
                1,
            )
        except Exception as exc:
            raise _render_http_error(exc) from exc

    receipt = await execute_owned_print_jobs(
        request.mac_address, prepare, split_mode, dither=request.dither
    )
    return {**receipt, "mac_address": request.mac_address}


@router.post("/api/print/batch")
async def print_batch(request: BatchPrintRequest):
    try:
        records = batch_record_count(request.variables_list, request.variables_matrix)
        validate_render_budget(
            request.canvas_state, records=records, copies=request.copies
        )
    except ResourceLimitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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

    async def prepare() -> list[Image.Image]:
        try:
            return await render_via_browser_async(
                request.canvas_state,
                variables_collection,
                request.copies,
            )
        except Exception as exc:
            raise _render_http_error(exc) from exc

    return await execute_owned_print_jobs(
        request.mac_address, prepare, split_mode, dither=request.dither
    )


@router.post("/api/print/images")
async def print_images_direct(request: ImagePrintRequest):
    if not request.images:
        return {"status": "empty", "submitted": 0, "physical_completion": "unverified"}

    async def prepare() -> list[Image.Image]:
        try:
            return await decode_owned(
                lambda: decode_image_payloads(request.images, rotate=request.is_rotated)
            )
        except ResourceLimitError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail="Invalid image payload supplied."
            ) from exc

    return await execute_owned_print_jobs(
        request.mac_address,
        prepare,
        request.split_mode,
        dither=request.dither,
    )
