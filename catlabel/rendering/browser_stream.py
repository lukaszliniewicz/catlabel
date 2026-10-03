"""Collect bounded, one-at-a-time image frames from the headless browser."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Any, cast

from PIL import Image

from ..core.resource_limits import (
    MAX_IMAGE_BYTES,
    ResourceLimitError,
    validate_image_budget,
)
from .image_payload import decode_image_payloads
from .owned_decode import decode_owned

MAX_ENCODED_OUTPUT_CHARS = 64 * 1024 * 1024
_PNG_DATA_URL_PREFIX = "data:image/png;base64,"
MAX_ENCODED_IMAGE_CHARS = len(_PNG_DATA_URL_PREFIX) + 4 * ((MAX_IMAGE_BYTES + 2) // 3)

_FRAME_EVENT_SCRIPT = """() => {
  const frame = window.__CATLABEL_RENDER_FRAME__;
  return frame !== undefined && frame !== null
    || window.__RENDER_ERROR__ !== undefined && window.__RENDER_ERROR__ !== null
    || document.querySelector('#render-done') !== null;
}"""

_FRAME_METADATA_SCRIPT = """() => {
  const frame = window.__CATLABEL_RENDER_FRAME__;
  const hasFrame = frame !== undefined && frame !== null;
  const payload = hasFrame ? frame.payload : undefined;
  return {
    error: window.__RENDER_ERROR__ ?? null,
    done: document.querySelector('#render-done') !== null,
    hasFrame,
    index: hasFrame ? frame.index : null,
    total: hasFrame ? frame.total : null,
    payloadType: typeof payload,
    payloadLength: typeof payload === 'string' ? payload.length : null,
    payloadHeader: typeof payload === 'string' ? payload.slice(0, 22) : null,
  };
}"""

_FRAME_PAYLOAD_SCRIPT = "() => window.__CATLABEL_RENDER_FRAME__?.payload"
_ACK_FRAME_SCRIPT = "(index) => window.__CATLABEL_ACK_RENDER_FRAME__(index)"


def _close_images(images: list[Image.Image]) -> None:
    for image in images:
        with suppress(Exception):
            image.close()


def _resource_error(message: str) -> ResourceLimitError:
    return ResourceLimitError(message)


def _read_boolean(value: object, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise _resource_error(f"The renderer returned invalid {name} metadata.")
    return value


def _read_count(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _resource_error(f"The renderer returned invalid {name} metadata.")
    return value


def _valid_data_url(payload: str) -> bool:
    return payload.startswith(_PNG_DATA_URL_PREFIX) and bool(
        payload[len(_PNG_DATA_URL_PREFIX) :]
    )


async def collect_streamed_images(
    page: Any,
    *,
    expected_jobs: int,
    rotate: bool,
    check_active: Callable[[], None],
) -> list[Image.Image]:
    """Decode and acknowledge each validated image frame before requesting the next."""

    if type(expected_jobs) is not int or expected_jobs < 1:
        raise _resource_error("The expected streamed image count is invalid.")

    images: list[Image.Image] = []
    decoded_current: list[Image.Image] = []
    current_image: Image.Image | None = None
    encoded_chars = 0
    pixels = 0

    try:
        while True:
            check_active()
            await page.wait_for_function(_FRAME_EVENT_SCRIPT, polling=5)
            check_active()

            check_active()
            raw_metadata = await page.evaluate(_FRAME_METADATA_SCRIPT)
            check_active()
            if not isinstance(raw_metadata, dict):
                raise _resource_error("The renderer returned invalid frame metadata.")

            metadata = cast(dict[str, object], raw_metadata)
            error = metadata.get("error")
            if error is not None:
                raise RuntimeError(f"Frontend renderer failed: {error}")
            done = _read_boolean(metadata.get("done"), name="completion")
            has_frame = _read_boolean(metadata.get("hasFrame"), name="frame")

            if not has_frame:
                if not done:
                    continue
                if len(images) != expected_jobs:
                    raise _resource_error(
                        "The renderer completed with an unexpected label count."
                    )
                return images

            if done:
                raise _resource_error(
                    "The renderer completed with an unexpected image frame."
                )
            if len(images) >= expected_jobs:
                raise _resource_error(
                    "The renderer returned more image frames than expected."
                )

            index = _read_count(metadata.get("index"), name="frame index")
            total = _read_count(metadata.get("total"), name="frame count")
            if total != expected_jobs:
                raise _resource_error(
                    "The renderer returned an unexpected label count."
                )
            if index >= expected_jobs or index != len(images):
                raise _resource_error(
                    "The renderer returned duplicate or out-of-order image frames."
                )

            if metadata.get("payloadType") != "string":
                raise _resource_error("The renderer returned an invalid image payload.")
            if metadata.get("payloadHeader") != _PNG_DATA_URL_PREFIX:
                raise _resource_error("The renderer returned an invalid image payload.")
            payload_length = _read_count(
                metadata.get("payloadLength"), name="payload length"
            )
            if (
                payload_length <= len(_PNG_DATA_URL_PREFIX)
                or payload_length > MAX_ENCODED_IMAGE_CHARS
            ):
                raise _resource_error(
                    "The renderer image exceeds the per-image encoded size limit."
                )
            if (
                payload_length > MAX_ENCODED_OUTPUT_CHARS
                or encoded_chars + payload_length > MAX_ENCODED_OUTPUT_CHARS
            ):
                raise _resource_error(
                    "The renderer output exceeds the encoded size limit."
                )

            check_active()
            payload = await page.evaluate(_FRAME_PAYLOAD_SCRIPT)
            check_active()
            if (
                not isinstance(payload, str)
                or len(payload) != payload_length
                or len(payload) > MAX_ENCODED_IMAGE_CHARS
                or len(payload) > MAX_ENCODED_OUTPUT_CHARS
                or not _valid_data_url(payload)
            ):
                raise _resource_error("The renderer returned an invalid image payload.")
            encoded_chars += payload_length

            check_active()
            decoded_current = await decode_owned(
                lambda payload=payload: decode_image_payloads([payload], rotate=rotate)
            )
            del payload
            check_active()
            if len(decoded_current) != 1:
                raise _resource_error(
                    "The renderer returned an unexpected decoded image count."
                )
            current_image = decoded_current.pop()
            pixels = validate_image_budget(
                current_image.width, current_image.height, pixels
            )

            check_active()
            acknowledged = await page.evaluate(_ACK_FRAME_SCRIPT, index)
            check_active()
            if acknowledged is not True:
                raise _resource_error(
                    "The renderer did not acknowledge the image frame."
                )

            images.append(current_image)
            current_image = None
    except BaseException:
        _close_images(decoded_current)
        if current_image is not None:
            _close_images([current_image])
        _close_images(images)
        raise
