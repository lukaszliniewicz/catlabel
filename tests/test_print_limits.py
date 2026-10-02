from __future__ import annotations

import asyncio
import base64
import unittest
from io import BytesIO
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from catlabel.api import routes_print
from catlabel.core.resource_limits import ResourceLimitError
from catlabel.rendering.image_payload import decode_image_payloads
from catlabel.rendering.template import render_via_browser


def _png(width: int = 8, height: int = 4) -> str:
    with Image.new("RGB", (width, height), "white") as image, BytesIO() as output:
        image.save(output, format="PNG")
        return base64.b64encode(output.getvalue()).decode("ascii")


class PrintInputLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_huge_matrix_rejected_before_expansion_render_or_device(self) -> None:
        request = routes_print.BatchPrintRequest(
            mac_address="fixture",
            canvas_state={},
            variables_matrix={str(i): ["a", "b"] for i in range(100)},
        )
        with (
            patch.object(routes_print, "render_via_browser") as render,
            patch.object(
                routes_print, "execute_print_jobs", new=AsyncMock()
            ) as execute,
            self.assertRaises(HTTPException) as raised,
        ):
            await routes_print.print_batch(request)
        self.assertEqual(raised.exception.status_code, 422)
        render.assert_not_called()
        execute.assert_not_awaited()

    async def test_oversized_dimensions_rejected_before_render(self) -> None:
        request = routes_print.DirectPrintRequest(
            mac_address="fixture", canvas_state={"width": 20001, "height": 1}
        )
        with (
            patch.object(routes_print, "render_via_browser") as render,
            self.assertRaises(HTTPException) as raised,
        ):
            await routes_print.print_direct(request)
        self.assertEqual(raised.exception.status_code, 422)
        render.assert_not_called()

    def test_copies_are_strict_and_bounded(self) -> None:
        for copies in (0, 101, True, "2", 1.5):
            with self.subTest(copies=copies), self.assertRaises(ValidationError):
                routes_print.BatchPrintRequest.model_validate(
                    {"mac_address": "fixture", "canvas_state": {}, "copies": copies}
                )

    async def test_decoded_image_pixel_limit_precedes_conversion(self) -> None:
        request = routes_print.ImagePrintRequest(mac_address="fixture", images=[_png()])
        with (
            patch(
                "catlabel.rendering.image_payload.validate_image_budget",
                side_effect=ResourceLimitError("too many pixels"),
            ),
            patch.object(Image.Image, "convert") as convert,
            patch.object(
                routes_print, "execute_print_jobs", new=AsyncMock()
            ) as execute,
            self.assertRaises(HTTPException) as raised,
        ):
            await routes_print.print_images_direct(request)
        self.assertEqual(raised.exception.status_code, 422)
        convert.assert_not_called()
        execute.assert_not_awaited()

    async def test_processed_images_close_after_failure_or_cancellation(self) -> None:
        for error in (RuntimeError("fixture failure"), asyncio.CancelledError()):
            images = decode_image_payloads([_png()])
            request = routes_print.ImagePrintRequest(
                mac_address="fixture", images=[_png()]
            )
            with (
                patch.object(
                    routes_print, "decode_image_payloads", return_value=images
                ),
                patch.object(
                    routes_print, "execute_print_jobs", new=AsyncMock(side_effect=error)
                ),
                self.assertRaises(type(error)),
            ):
                await routes_print.print_images_direct(request)
            with self.assertRaises(ValueError):
                images[0].getpixel((0, 0))


class ImagePayloadTests(unittest.TestCase):
    def test_rejects_invalid_base64_and_closes_partial_results(self) -> None:
        closed = []
        original_close = Image.Image.close

        def close(image: Image.Image) -> None:
            closed.append(image)
            original_close(image)

        with (
            patch.object(Image.Image, "close", new=close),
            self.assertRaises(ValueError),
        ):
            decode_image_payloads([_png(), "@@not-base64@@"])
        self.assertEqual(len(closed), 1)
        with self.assertRaises(ValueError):
            closed[0].getpixel((0, 0))

    def test_rotation_preserves_geometry(self) -> None:
        images = decode_image_payloads([f"data:image/png;base64,{_png()}"], rotate=True)
        try:
            self.assertEqual(images[0].size, (4, 8))
        finally:
            images[0].close()

    def test_encoded_byte_limit_rejects_before_decoding(self) -> None:
        with (
            patch("catlabel.rendering.image_payload.MAX_IMAGE_BYTES", 3),
            patch("catlabel.rendering.image_payload.base64.b64decode") as decode,
            self.assertRaises(ResourceLimitError),
        ):
            decode_image_payloads(["AAAAA"])
        decode.assert_not_called()

    def test_backend_render_limit_rejects_before_browser_creation(self) -> None:
        with (
            patch("catlabel.rendering.template._get_browser") as browser,
            self.assertRaises(ResourceLimitError),
        ):
            render_via_browser({"width": 10000, "height": 10000}, [{}])
        browser.assert_not_called()
