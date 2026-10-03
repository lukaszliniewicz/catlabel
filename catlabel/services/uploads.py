"""Bounded font and PDF upload processing."""

from __future__ import annotations

import asyncio
import base64
import math
import os
import tempfile
import threading
from contextlib import ExitStack, suppress
from io import BytesIO
from pathlib import Path, PureWindowsPath
from typing import cast

import pypdfium2 as pdfium
from fastapi import HTTPException, UploadFile
from PIL import ImageFont
from sqlalchemy import Engine
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, select

from ..core.models import Font
from ..core.paths import FONTS_DIRECTORY
from ..core.resource_limits import (
    MAX_IMAGE_BYTES,
    MAX_PRINT_JOBS,
    MAX_REQUEST_BYTES,
    MAX_UPLOAD_BYTES,
    ResourceLimitError,
    validate_image_budget,
)

_FONT_DIRECTORY = FONTS_DIRECTORY
_FONT_PROMOTION_LOCK = threading.Lock()
_PDF_SCALE = 203 / 72
_PDF_RESPONSE_OVERHEAD_BYTES = 1024
_PDF_DATA_URL_JSON_OVERHEAD_BYTES = 3
_PDF_DATA_URL_PREFIX = "data:image/png;base64,"


async def store_uploaded_font(file: UploadFile, engine: Engine) -> Font:
    """Validate and store one uploaded TTF or OTF font."""
    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ResourceLimitError("Uploaded file exceeds the size limit.")
        return await asyncio.to_thread(
            _store_uploaded_font_sync, file.filename, data, engine
        )
    except HTTPException:
        raise
    except ResourceLimitError as exc:
        raise HTTPException(
            status_code=413, detail="Uploaded file exceeds the size limit."
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to store font.") from exc
    finally:
        await file.close()


def _store_uploaded_font_sync(
    filename: str | None, data: bytes, engine: Engine
) -> Font:
    safe_filename = _safe_font_filename(filename)
    _validate_font_data(data)

    target = _FONT_DIRECTORY / safe_filename
    with _FONT_PROMOTION_LOCK:
        if target.exists() or target.is_symlink():
            raise HTTPException(
                status_code=409, detail="A font with this filename already exists."
            )

        temporary_path: Path | None = None
        promoted = False
        with Session(engine, expire_on_commit=False) as session:
            try:
                name_clause = cast(ColumnElement[bool], Font.name == safe_filename)
                existing = session.exec(select(Font).where(name_clause)).first()
                if existing is not None:
                    raise HTTPException(
                        status_code=409,
                        detail="A font with this filename already exists.",
                    )

                os.makedirs(_FONT_DIRECTORY, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=".catlabel-font-",
                    suffix=".tmp",
                    dir=_FONT_DIRECTORY,
                    delete=False,
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                    temporary_file.write(data)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())

                os.replace(temporary_path, target)
                promoted = True
                font = Font(
                    name=safe_filename,
                    file_path=f"fonts/{safe_filename}",
                )
                session.add(font)
                session.commit()
                return font
            except HTTPException:
                _rollback_quietly(session)
                if promoted:
                    _remove_own_file(target)
                raise
            except Exception as exc:
                _rollback_quietly(session)
                if promoted:
                    _remove_own_file(target)
                raise HTTPException(
                    status_code=500, detail="Unable to store font."
                ) from exc
            finally:
                if temporary_path is not None:
                    _remove_own_file(temporary_path)


def _safe_font_filename(filename: str | None) -> str:
    if filename is None or not 1 <= len(filename) <= 200:
        raise HTTPException(status_code=400, detail="Invalid font filename.")
    windows_path = PureWindowsPath(filename)
    if (
        filename in {".", ".."}
        or "\x00" in filename
        or "/" in filename
        or "\\" in filename
        or bool(windows_path.drive)
        or windows_path.is_absolute()
        or Path(filename).is_absolute()
        or any(ord(character) < 32 or character in '<>:"|?*' for character in filename)
        or filename.endswith((".", " "))
        or filename.split(".", 1)[0].rstrip(" ").upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    ):
        raise HTTPException(status_code=400, detail="Invalid font filename.")
    if Path(filename).suffix.lower() not in {".ttf", ".otf"}:
        raise HTTPException(
            status_code=400, detail="Only TTF and OTF font files are supported."
        )
    return filename


def _validate_font_data(data: bytes) -> None:
    font_stream = BytesIO(data)
    try:
        ImageFont.truetype(font_stream, 12)
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid font file.") from exc
    finally:
        font_stream.close()


def _rollback_quietly(session: Session) -> None:
    with suppress(Exception):
        session.rollback()


def _remove_own_file(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)


async def convert_uploaded_pdf(file: UploadFile) -> list[str]:
    """Render a bounded PDF upload into PNG data URLs.

    Caller cancellation requests that the synchronous worker stop and drains
    its task before returning. Independent cancellation of that task, or event
    loop shutdown, can end the asyncio wrapper while the worker thread is still
    running; task completion alone does not prove the thread has finished.
    """
    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ResourceLimitError("Uploaded file exceeds the size limit.")

        stop_event = threading.Event()
        conversion_task = asyncio.create_task(
            asyncio.to_thread(_convert_uploaded_pdf_sync, data, stop_event=stop_event)
        )
        try:
            return await asyncio.shield(conversion_task)
        except asyncio.CancelledError as cancellation:
            stop_event.set()
            caller_task = asyncio.current_task()
            if caller_task is not None and caller_task.cancelling() > 0:
                while not conversion_task.done():
                    try:
                        await asyncio.shield(conversion_task)
                    except asyncio.CancelledError:
                        if conversion_task.done():
                            break
                    except BaseException:
                        break

            with suppress(BaseException):
                conversion_task.result()
            raise cancellation
    except ResourceLimitError as exc:
        raise HTTPException(
            status_code=413, detail="Uploaded PDF exceeds a processing limit."
        ) from exc
    except _InvalidUploadedPDF as exc:
        raise HTTPException(status_code=400, detail="Invalid PDF file.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to convert PDF.") from exc
    finally:
        await file.close()


class _InvalidUploadedPDF(ValueError):
    """Raised when uploaded bytes or page geometry cannot represent a PDF."""


class _PdfConversionAborted(Exception):
    """Raised when an asynchronous caller asks the worker to stop."""


def _raise_if_pdf_conversion_stopped(stop_event: threading.Event | None) -> None:
    if stop_event is not None and stop_event.is_set():
        raise _PdfConversionAborted


def _convert_uploaded_pdf_sync(
    data: bytes, *, stop_event: threading.Event | None = None
) -> list[str]:
    _raise_if_pdf_conversion_stopped(stop_event)
    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise _InvalidUploadedPDF from exc

    images: list[str] = []
    with ExitStack() as document_stack:
        document_stack.callback(document.close)
        try:
            page_count = len(document)
        except Exception as exc:
            raise _InvalidUploadedPDF from exc
        if page_count < 1:
            raise _InvalidUploadedPDF
        if page_count > MAX_PRINT_JOBS:
            raise ResourceLimitError("PDF contains too many pages.")

        pixels_so_far = 0
        for page_index in range(page_count):
            _raise_if_pdf_conversion_stopped(stop_event)
            try:
                page = document[page_index]
            except Exception as exc:
                raise _InvalidUploadedPDF from exc

            with ExitStack() as page_stack:
                page_stack.callback(page.close)
                try:
                    raw_width, raw_height = page.get_size()
                except Exception as exc:
                    raise _InvalidUploadedPDF from exc
                width = _pdf_dimension(raw_width)
                height = _pdf_dimension(raw_height)

                scaled_width = width * _PDF_SCALE
                scaled_height = height * _PDF_SCALE
                if not math.isfinite(scaled_width) or not math.isfinite(scaled_height):
                    raise _InvalidUploadedPDF
                try:
                    pixel_width = math.ceil(scaled_width)
                    pixel_height = math.ceil(scaled_height)
                except (OverflowError, ValueError) as exc:
                    raise _InvalidUploadedPDF from exc

                pixels_so_far = validate_image_budget(
                    pixel_width, pixel_height, pixels_so_far
                )

        response_bytes = 0
        response_byte_limit = MAX_REQUEST_BYTES - _PDF_RESPONSE_OVERHEAD_BYTES
        for page_index in range(page_count):
            _raise_if_pdf_conversion_stopped(stop_event)
            try:
                page = document[page_index]
            except Exception as exc:
                raise _InvalidUploadedPDF from exc

            with ExitStack() as page_stack:
                page_stack.callback(page.close)

                try:
                    bitmap = page.render(_PDF_SCALE)
                    page_stack.callback(bitmap.close)
                    source_image = bitmap.to_pil()
                    page_stack.callback(source_image.close)
                    image = source_image.copy()
                    page_stack.callback(image.close)
                    with BytesIO() as encoded_image:
                        image.save(encoded_image, format="PNG")
                        png_bytes = encoded_image.getvalue()
                except ResourceLimitError:
                    raise
                except Exception as exc:
                    raise _InvalidUploadedPDF from exc

                _raise_if_pdf_conversion_stopped(stop_event)
                if len(png_bytes) > MAX_IMAGE_BYTES:
                    raise ResourceLimitError(
                        "Rendered PDF page exceeds the image limit."
                    )
                base64_length = 4 * ((len(png_bytes) + 2) // 3)
                data_url_length = len(_PDF_DATA_URL_PREFIX) + base64_length
                next_response_bytes = (
                    response_bytes + data_url_length + _PDF_DATA_URL_JSON_OVERHEAD_BYTES
                )
                if next_response_bytes > response_byte_limit:
                    raise ResourceLimitError(
                        "Converted PDF response exceeds the request size limit."
                    )

                encoded_png = base64.b64encode(png_bytes).decode("ascii")
                _raise_if_pdf_conversion_stopped(stop_event)
                images.append(f"{_PDF_DATA_URL_PREFIX}{encoded_png}")
                response_bytes = next_response_bytes

    return images


def _pdf_dimension(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _InvalidUploadedPDF
    try:
        dimension = float(value)
    except (OverflowError, ValueError) as exc:
        raise _InvalidUploadedPDF from exc
    if not math.isfinite(dimension) or dimension <= 0:
        raise _InvalidUploadedPDF
    return dimension
