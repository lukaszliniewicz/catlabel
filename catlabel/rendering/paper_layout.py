"""Prepare label images for a selected generic-printer paper layout."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol, cast

from PIL import Image

from ..core.resource_limits import (
    MAX_PRINT_JOBS,
    ResourceLimitError,
    validate_image_budget,
)


class _ResizableImage(Protocol):
    def resize(self, size: tuple[int, int], resample: int) -> Image.Image: ...


def _resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    # Pillow's size annotation also includes an untyped NumPy array. This
    # boundary uses only its documented integer tuple and resampling arguments.
    return cast(_ResizableImage, image).resize(size, Image.Resampling.LANCZOS)


def _normalize_rotation(rotation_degrees: object) -> int:
    if isinstance(rotation_degrees, bool) or not isinstance(rotation_degrees, int):
        raise ValueError("rotation_degrees must be an integer multiple of 90")
    normalized_rotation = rotation_degrees % 360
    if normalized_rotation not in (0, 90, 180, 270):
        raise ValueError("rotation_degrees must be a multiple of 90")
    return normalized_rotation


@dataclass(frozen=True)
class PaperImageLayout:
    """Image-space dimensions and clockwise rotation for a paper preset."""

    render_width_px: int
    render_height_px: int | None = None
    rotation_degrees: int = 0

    def __post_init__(self) -> None:
        validate_image_budget(self.render_width_px, 1)
        if self.render_height_px is not None:
            validate_image_budget(1, self.render_height_px)
        object.__setattr__(
            self,
            "rotation_degrees",
            _normalize_rotation(self.rotation_degrees),
        )


@dataclass(frozen=True)
class _PlannedStrip:
    image_index: int
    crop_box: tuple[int, int, int, int]
    normalized_size: tuple[int, int]
    normalized_paste_xy: tuple[int, int]
    fitted_size: tuple[int, int]
    canvas_size: tuple[int, int]
    paste_xy: tuple[int, int]


def _rotated_size(width: int, height: int, rotation_degrees: int) -> tuple[int, int]:
    if rotation_degrees in (90, 270):
        return height, width
    return width, height


def _rotation_transpose(rotation_degrees: int) -> Image.Transpose | None:
    return {
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }.get(rotation_degrees)


def _build_image_plan(
    images: Sequence[Image.Image],
    layout: PaperImageLayout,
    *,
    split_mode: bool,
) -> tuple[_PlannedStrip, ...]:
    if len(images) > MAX_PRINT_JOBS:
        raise ResourceLimitError(f"At most {MAX_PRINT_JOBS} label images are allowed.")

    planned: list[_PlannedStrip] = []
    source_pixels = 0
    output_pixels = 0
    planned_jobs = 0

    for image_index, image in enumerate(images):
        source_pixels = validate_image_budget(
            image.width,
            image.height,
            source_pixels,
        )
        rotated_width, rotated_height = _rotated_size(
            image.width,
            image.height,
            layout.rotation_degrees,
        )
        validate_image_budget(rotated_width, rotated_height)

        is_split = split_mode and rotated_width > layout.render_width_px
        strip_count = (
            (rotated_width + layout.render_width_px - 1) // layout.render_width_px
            if is_split
            else 1
        )
        if strip_count > MAX_PRINT_JOBS - planned_jobs:
            raise ResourceLimitError(
                f"Print requires more than {MAX_PRINT_JOBS} label jobs."
            )
        planned_jobs += strip_count

        for strip_index in range(strip_count):
            if is_split:
                left = strip_index * layout.render_width_px
                right = min(left + layout.render_width_px, rotated_width)
                crop_box = (left, 0, right, rotated_height)
                segment_width = right - left
                segment_height = rotated_height
                validate_image_budget(segment_width, segment_height)
                # Generic split remainders are left-aligned on their paper.
                normalized_offset = 0
            else:
                crop_box = (0, 0, rotated_width, rotated_height)
                segment_width = rotated_width
                segment_height = rotated_height
                if segment_width < layout.render_width_px:
                    normalized_offset = (layout.render_width_px - segment_width) // 2
                else:
                    normalized_offset = 0

            if not is_split and segment_width > layout.render_width_px:
                normalized_height = max(
                    1,
                    int(segment_height * layout.render_width_px / float(segment_width)),
                )
            else:
                normalized_height = segment_height

            normalized_size = (layout.render_width_px, normalized_height)
            validate_image_budget(*normalized_size)
            normalized_paste_xy = (normalized_offset, 0)

            fitted_width = layout.render_width_px
            if (
                layout.render_height_px is not None
                and normalized_height > layout.render_height_px
            ):
                fitted_width = max(
                    1,
                    round(
                        layout.render_width_px
                        * layout.render_height_px
                        / normalized_height
                    ),
                )
                fitted_height = layout.render_height_px
                validate_image_budget(fitted_width, fitted_height)
                horizontal_offset = (layout.render_width_px - fitted_width) // 2
                vertical_offset = 0
            else:
                fitted_height = normalized_height
                horizontal_offset = 0
                vertical_offset = (
                    (layout.render_height_px - normalized_height) // 2
                    if layout.render_height_px is not None
                    else 0
                )

            fitted_size = (fitted_width, fitted_height)
            canvas_height = (
                layout.render_height_px
                if layout.render_height_px is not None
                else normalized_height
            )
            output_pixels = validate_image_budget(
                layout.render_width_px,
                canvas_height,
                output_pixels,
            )
            planned.append(
                _PlannedStrip(
                    image_index=image_index,
                    crop_box=crop_box,
                    normalized_size=normalized_size,
                    normalized_paste_xy=normalized_paste_xy,
                    fitted_size=fitted_size,
                    canvas_size=(layout.render_width_px, canvas_height),
                    paste_xy=(horizontal_offset, vertical_offset),
                )
            )

    return tuple(planned)


def plan_image_layout(
    images: Sequence[Image.Image],
    layout: PaperImageLayout,
    *,
    split_mode: bool = False,
) -> tuple[tuple[int, int], ...]:
    """Preflight source, intermediate, and output dimensions without PIL edits."""
    return tuple(
        strip.canvas_size
        for strip in _build_image_plan(images, layout, split_mode=split_mode)
    )


def _close_images(images: dict[int, Image.Image]) -> None:
    for image in tuple(images.values()):
        with suppress(Exception):
            image.close()
    images.clear()


def prepare_paper_images(
    images: Sequence[Image.Image],
    layout: PaperImageLayout,
    *,
    split_mode: bool = False,
) -> list[Image.Image]:
    """Return independently owned RGB images prepared for the paper layout.

    Every source and planned output is validated before the first transpose,
    conversion, crop, resize, or canvas allocation. The caller retains ownership
    of every input image and receives ownership of every returned image.
    """
    plan = _build_image_plan(images, layout, split_mode=split_mode)
    outputs: list[Image.Image] = []
    owned: dict[int, Image.Image] = {}

    def track(image: Image.Image) -> Image.Image:
        owned[id(image)] = image
        return image

    def discard(image: Image.Image) -> None:
        image.close()
        owned.pop(id(image), None)

    try:
        rotation = _rotation_transpose(layout.rotation_degrees)
        current_source_index: int | None = None
        working_rgb: Image.Image | None = None

        for strip in plan:
            if strip.image_index != current_source_index:
                if working_rgb is not None:
                    discard(working_rgb)
                    working_rgb = None
                current_source_index = strip.image_index
                source = images[current_source_index]
                rotated = (
                    track(source.transpose(rotation))
                    if rotation is not None
                    else source
                )
                converted = rotated.convert("RGB")
                if converted is source:
                    converted = source.copy()
                if converted is not rotated:
                    track(converted)
                elif rotated is source:
                    # A same-mode convert may return its input; the working image
                    # must still be independent of the caller's source.
                    converted = track(source.copy())
                else:
                    # The transposed image is already an internally owned RGB
                    # image, so it can serve as the working copy.
                    converted = rotated
                if rotated is not source and rotated is not converted:
                    discard(rotated)
                working_rgb = converted

            if working_rgb is None:
                raise RuntimeError("paper image plan lost its working source")

            is_whole_image = strip.crop_box == (
                0,
                0,
                working_rgb.width,
                working_rgb.height,
            )
            content = (
                working_rgb
                if is_whole_image
                else track(working_rgb.crop(strip.crop_box))
            )
            if content.size == strip.normalized_size:
                normalized = content
            elif content.width > layout.render_width_px:
                normalized = track(_resize(content, strip.normalized_size))
            else:
                normalized = track(Image.new("RGB", strip.normalized_size, "white"))
                normalized.paste(content, strip.normalized_paste_xy)

            fitted = (
                normalized
                if strip.fitted_size == strip.normalized_size
                else track(_resize(normalized, strip.fitted_size))
            )

            canvas = track(Image.new("RGB", strip.canvas_size, "white"))
            canvas.paste(fitted, strip.paste_xy)
            outputs.append(canvas)
            if fitted is not normalized:
                discard(fitted)
            if normalized is not content:
                discard(normalized)
            if content is not working_rgb:
                discard(content)

        if working_rgb is not None:
            discard(working_rgb)
        for output in outputs:
            owned.pop(id(output), None)
        _close_images(owned)
        return outputs
    except BaseException:
        _close_images(owned)
        raise
