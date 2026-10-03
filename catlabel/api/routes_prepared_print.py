"""API for staging rendered PNG pages before an explicit print commit."""

from __future__ import annotations

from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from PIL import Image
from pydantic import BaseModel, Field

from ..core.resource_limits import (
    MAX_IMAGE_BYTES,
    MAX_PRINT_JOBS,
    ResourceLimitError,
    validate_image_budget,
)
from ..rendering.owned_decode import decode_owned
from ..services.prepared_prints import (
    PreparedPrintCapacityError,
    PreparedPrintConflict,
    PreparedPrintInvalidImage,
    PreparedPrintLease,
    PreparedPrintNotFound,
    PreparedPrintProgress,
    PreparedPrintStore,
    PreparedPrintStoreStopped,
    PreparedPrintTooLarge,
)
from .routes_print import execute_owned_print_jobs

router = APIRouter(tags=["Print"])


class PreparedPrintStartRequest(BaseModel):
    expected_jobs: int = Field(strict=True, ge=1, le=MAX_PRINT_JOBS)


class PreparedPrintCommitRequest(BaseModel):
    mac_address: str
    split_mode: bool = Field(default=False, strict=True)
    is_rotated: bool = Field(default=False, strict=True)
    dither: bool = Field(default=True, strict=True)


def _store(request: Request) -> PreparedPrintStore:
    store = getattr(request.app.state, "prepared_print_store", None)
    if not isinstance(store, PreparedPrintStore):
        raise HTTPException(
            status_code=503, detail="Prepared print storage is unavailable."
        )
    return store


def _progress_payload(progress: PreparedPrintProgress) -> dict[str, str | int]:
    return {
        "prepared_id": progress.prepared_id,
        "total": progress.total,
        "next_index": progress.next_index,
    }


def _store_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PreparedPrintNotFound):
        status_code = 404
    elif isinstance(exc, PreparedPrintConflict):
        status_code = 409
    elif isinstance(exc, PreparedPrintTooLarge):
        status_code = 413
    elif isinstance(exc, (PreparedPrintCapacityError, PreparedPrintStoreStopped)):
        status_code = 503
    elif isinstance(exc, (PreparedPrintInvalidImage, ResourceLimitError)):
        status_code = 422
    elif isinstance(exc, OSError):
        status_code = 503
    else:
        status_code = 500
    return HTTPException(status_code=status_code, detail=str(exc))


def _decode_prepared_png(
    png_bytes: bytes, *, rotate: bool, pixels_so_far: int
) -> list[Image.Image]:
    image: Image.Image | None = None
    try:
        with Image.open(BytesIO(png_bytes)) as source:
            if source.format != "PNG":
                raise PreparedPrintInvalidImage("Prepared page must be a PNG.")
            validate_image_budget(source.width, source.height, pixels_so_far)
            image = source.convert("RGB")
        if rotate:
            rotated = image.rotate(90, expand=True)
            image.close()
            image = rotated
        return [image]
    except (PreparedPrintInvalidImage, ResourceLimitError):
        if image is not None:
            with suppress(Exception):
                image.close()
        raise
    except BaseException as exc:
        if image is not None:
            with suppress(Exception):
                image.close()
        if isinstance(exc, Exception):
            raise PreparedPrintInvalidImage(
                "Prepared page is not a valid PNG."
            ) from exc
        raise


async def _decode_lease_pages(
    lease: PreparedPrintLease, *, rotate: bool
) -> list[Image.Image]:
    images: list[Image.Image] = []
    pixels = 0
    try:
        for path in lease.page_paths:
            # Read and close each file before handing immutable bytes to the worker.
            png_bytes = Path(path).read_bytes()
            if len(png_bytes) > MAX_IMAGE_BYTES:
                raise ResourceLimitError("A prepared page exceeds the byte limit.")
            decoded = await decode_owned(
                lambda payload=png_bytes, prior_pixels=pixels: _decode_prepared_png(
                    payload, rotate=rotate, pixels_so_far=prior_pixels
                )
            )
            if len(decoded) != 1:
                for image in decoded:
                    with suppress(Exception):
                        image.close()
                raise PreparedPrintInvalidImage("Prepared page did not decode once.")
            image = decoded[0]
            images.append(image)
            pixels += image.width * image.height
        return images
    except BaseException:
        for image in images:
            with suppress(Exception):
                image.close()
        raise


@router.post("/api/print/prepared", status_code=201)
async def start_prepared_print(
    request: Request, body: PreparedPrintStartRequest
) -> dict[str, str | int]:
    try:
        progress = _store(request).start(body.expected_jobs)
    except HTTPException:
        raise
    except Exception as exc:
        raise _store_error(exc) from exc
    return _progress_payload(progress)


@router.post("/api/print/prepared/{prepared_id}/pages/{index}")
async def append_prepared_print_page(
    request: Request,
    prepared_id: str,
    index: int,
    file: Annotated[UploadFile, File()],
) -> dict[str, str | int]:
    try:
        try:
            png_bytes = await file.read(MAX_IMAGE_BYTES + 1)
        finally:
            await file.close()
        if len(png_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413, detail="Prepared page exceeds the byte limit."
            )
        progress = _store(request).append(prepared_id, index, png_bytes)
    except HTTPException:
        raise
    except Exception as exc:
        raise _store_error(exc) from exc
    return _progress_payload(progress)


@router.delete("/api/print/prepared/{prepared_id}")
async def discard_prepared_print(request: Request, prepared_id: str) -> dict[str, str]:
    try:
        _store(request).cancel(prepared_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _store_error(exc) from exc
    return {"status": "discarded"}


@router.post("/api/print/prepared/{prepared_id}/commit")
async def commit_prepared_print(
    request: Request,
    prepared_id: str,
    body: PreparedPrintCommitRequest,
) -> dict[str, Any]:
    store = _store(request)
    try:
        lease = store.take_for_commit(prepared_id)
    except Exception as exc:
        raise _store_error(exc) from exc

    async def prepare() -> list[Image.Image]:
        try:
            return await _decode_lease_pages(lease, rotate=body.is_rotated)
        except ResourceLimitError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PreparedPrintInvalidImage as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=422, detail="Prepared page is not a valid PNG."
            ) from exc

    try:
        return await execute_owned_print_jobs(
            body.mac_address,
            prepare,
            body.split_mode,
            dither=body.dither,
        )
    finally:
        store.finish(lease)
