"""Bounded decoding shared by browser and API print inputs."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from io import BytesIO

from PIL import Image

from ..core.resource_limits import (
    MAX_IMAGE_BYTES,
    MAX_PRINT_JOBS,
    ResourceLimitError,
    validate_image_budget,
)


def decode_image_payloads(
    payloads: Sequence[object], *, rotate: bool = False
) -> list[Image.Image]:
    if len(payloads) > MAX_PRINT_JOBS:
        raise ResourceLimitError(f"At most {MAX_PRINT_JOBS} label images are allowed.")
    images: list[Image.Image] = []
    pixels = 0
    try:
        for payload in payloads:
            if not isinstance(payload, str):
                raise ValueError("Image payload must be a base64 string.")
            encoded = payload.split(",", 1)[1] if "," in payload else payload
            if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
                raise ResourceLimitError("An encoded image exceeds the byte limit.")
            decoded = base64.b64decode(encoded, validate=True)
            if len(decoded) > MAX_IMAGE_BYTES:
                raise ResourceLimitError("An image exceeds the byte limit.")
            with Image.open(BytesIO(decoded)) as source:
                pixels = validate_image_budget(source.width, source.height, pixels)
                rendered = source.convert("RGB")
            images.append(rendered)
            if rotate:
                rotated = rendered.rotate(90, expand=True)
                rendered.close()
                images[-1] = rotated
        return images
    except BaseException:
        for image in images:
            image.close()
        raise
