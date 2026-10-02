"""Shared resource ceilings and validation for untrusted render inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from math import ceil, isfinite
from typing import Any, cast


class ResourceLimitError(ValueError):
    """Raised when an input exceeds or violates a resource limit."""


_LIMIT_KEYS = frozenset(
    {
        "schema_version",
        "max_batch_records",
        "max_print_copies",
        "max_print_jobs",
        "max_render_pixels",
        "max_dimension",
        "max_canvas_entries",
        "max_request_bytes",
        "max_upload_bytes",
        "max_image_bytes",
    }
)


def _load_resource_limits() -> dict[str, int]:
    try:
        raw_data: object = json.loads(
            files("catlabel")
            .joinpath("data/resource_limits.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResourceLimitError(
            "Unable to load resource limit configuration."
        ) from exc

    if not isinstance(raw_data, dict):
        raise ResourceLimitError("Resource limit configuration has an invalid schema.")
    data = cast(dict[str, object], raw_data)
    if set(data) != set(_LIMIT_KEYS):
        raise ResourceLimitError("Resource limit configuration has an invalid schema.")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ResourceLimitError("Resource limit configuration version must be 1.")

    limits: dict[str, int] = {}
    for key in _LIMIT_KEYS - {"schema_version"}:
        value = data[key]
        if type(value) is not int or value <= 0:
            raise ResourceLimitError(
                f"Resource limit {key!r} must be a positive integer."
            )
        limits[key] = value
    return limits


_RESOURCE_LIMITS = _load_resource_limits()

MAX_BATCH_RECORDS: int = _RESOURCE_LIMITS["max_batch_records"]
MAX_PRINT_COPIES: int = _RESOURCE_LIMITS["max_print_copies"]
MAX_PRINT_JOBS: int = _RESOURCE_LIMITS["max_print_jobs"]
MAX_RENDER_PIXELS: int = _RESOURCE_LIMITS["max_render_pixels"]
MAX_DIMENSION: int = _RESOURCE_LIMITS["max_dimension"]
MAX_CANVAS_ENTRIES: int = _RESOURCE_LIMITS["max_canvas_entries"]
MAX_REQUEST_BYTES: int = _RESOURCE_LIMITS["max_request_bytes"]
MAX_UPLOAD_BYTES: int = _RESOURCE_LIMITS["max_upload_bytes"]
MAX_IMAGE_BYTES: int = _RESOURCE_LIMITS["max_image_bytes"]

_MAX_PAGE_INDEX = MAX_PRINT_JOBS - 1
_DEFAULT_DIMENSION = 384


def require_count(value: object, *, name: str, maximum: int) -> int:
    """Return a positive integer count no greater than ``maximum``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResourceLimitError(f"{name} must be an integer.")
    if value < 1 or value > maximum:
        raise ResourceLimitError(f"{name} must be between 1 and {maximum}.")
    return value


def _require_sequence(value: object, *, name: str) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ResourceLimitError(f"{name} must be a sequence.")


def _require_mapping(value: object, *, name: str) -> None:
    if not isinstance(value, Mapping):
        raise ResourceLimitError(f"{name} must be a mapping.")


def batch_record_count(
    variables_list: Sequence[Mapping[str, str]],
    variables_matrix: Mapping[str, Sequence[str]] | None,
) -> int:
    """Count explicit and Cartesian batch records without building combinations."""
    _require_sequence(variables_list, name="variables_list")

    list_count = len(variables_list)
    if list_count > MAX_BATCH_RECORDS:
        raise ResourceLimitError(f"variables_list exceeds {MAX_BATCH_RECORDS} records.")

    matrix_count = 0
    if variables_matrix is not None:
        _require_mapping(variables_matrix, name="variables_matrix")
        if variables_matrix:
            matrix_count = 1
            for axis in variables_matrix.values():
                _require_sequence(axis, name="Each variables_matrix axis")
                axis_count = len(axis)
                if axis_count == 0:
                    raise ResourceLimitError(
                        "Each variables_matrix axis must be nonempty."
                    )
                if axis_count > MAX_BATCH_RECORDS:
                    raise ResourceLimitError(
                        f"Each variables_matrix axis is limited to {MAX_BATCH_RECORDS} values."
                    )
                matrix_count *= axis_count
                if matrix_count > MAX_BATCH_RECORDS:
                    raise ResourceLimitError(
                        f"variables_matrix exceeds {MAX_BATCH_RECORDS} records."
                    )

    total_count = list_count + matrix_count
    if total_count > MAX_BATCH_RECORDS:
        raise ResourceLimitError(f"Combined batch exceeds {MAX_BATCH_RECORDS} records.")
    if total_count == 0:
        return 1
    return total_count


def _dimension_pixels(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResourceLimitError(f"{name} must be a finite positive number.")
    if value <= 0 or value > MAX_DIMENSION or not isfinite(value):
        raise ResourceLimitError(
            f"{name} must be finite, positive, and no greater than {MAX_DIMENSION}."
        )
    return ceil(value)


def _page_index(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ResourceLimitError("pageIndex must be a nonnegative integer.")
    if isinstance(value, int):
        index = value
    elif isinstance(value, float):
        if not isfinite(value) or not value.is_integer():
            raise ResourceLimitError("pageIndex must be a finite integer.")
        index = int(value)
    elif isinstance(value, str):
        try:
            numeric_index = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ResourceLimitError("pageIndex must be a numeric string.") from exc
        if not numeric_index.is_finite():
            raise ResourceLimitError("pageIndex must be a finite integer.")
        if numeric_index < 0 or numeric_index > _MAX_PAGE_INDEX:
            raise ResourceLimitError(
                f"pageIndex must be between 0 and {_MAX_PAGE_INDEX}."
            )
        if numeric_index != numeric_index.to_integral_value():
            raise ResourceLimitError("pageIndex must be a finite integer.")
        index = int(numeric_index)
    else:
        raise ResourceLimitError("pageIndex must be a nonnegative integer.")

    if index < 0 or index > _MAX_PAGE_INDEX:
        raise ResourceLimitError(f"pageIndex must be between 0 and {_MAX_PAGE_INDEX}.")
    return index


def validate_render_budget(
    canvas: Mapping[str, Any], *, records: int, copies: int
) -> tuple[int, int]:
    """Validate a canvas and return its total print-job and pixel counts."""
    _require_mapping(canvas, name="canvas")
    record_count = require_count(records, name="records", maximum=MAX_BATCH_RECORDS)
    copy_count = require_count(copies, name="copies", maximum=MAX_PRINT_COPIES)

    width = _dimension_pixels(canvas.get("width", _DEFAULT_DIMENSION), name="width")
    height = _dimension_pixels(canvas.get("height", _DEFAULT_DIMENSION), name="height")

    page_ids = {0}
    for field in ("items", "pageLayouts"):
        raw_entries: object = canvas.get(field)
        if raw_entries is None:
            continue
        if not isinstance(raw_entries, list):
            raise ResourceLimitError(f"{field} must be a list or null.")
        entries = cast(list[object], raw_entries)
        if len(entries) > MAX_CANVAS_ENTRIES:
            raise ResourceLimitError(f"{field} exceeds {MAX_CANVAS_ENTRIES} entries.")
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ResourceLimitError(f"Each {field} entry must be a mapping.")
            entry_mapping = cast(Mapping[str, object], entry)
            page_ids.add(_page_index(entry_mapping.get("pageIndex")))

    jobs = record_count * copy_count * len(page_ids)
    if jobs > MAX_PRINT_JOBS:
        raise ResourceLimitError(f"Render requires more than {MAX_PRINT_JOBS} jobs.")

    pixels = width * height * jobs
    if pixels > MAX_RENDER_PIXELS:
        raise ResourceLimitError(
            f"Render requires more than {MAX_RENDER_PIXELS} pixels."
        )
    return jobs, pixels


def validate_image_budget(
    width: object, height: object, pixels_so_far: object = 0
) -> int:
    """Return cumulative image pixels after validating dimensions and budget."""
    width_pixels = require_count(width, name="width", maximum=MAX_DIMENSION)
    height_pixels = require_count(height, name="height", maximum=MAX_DIMENSION)
    prior_pixels = _require_nonnegative_count(pixels_so_far, name="pixels_so_far")

    total_pixels = prior_pixels + width_pixels * height_pixels
    if total_pixels > MAX_RENDER_PIXELS:
        raise ResourceLimitError(
            f"Image allocation exceeds {MAX_RENDER_PIXELS} cumulative pixels."
        )
    return total_pixels


def _require_nonnegative_count(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResourceLimitError(f"{name} must be a nonnegative integer.")
    return value
