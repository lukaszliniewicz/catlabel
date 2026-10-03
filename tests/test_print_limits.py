from __future__ import annotations

import asyncio
import base64
import unittest
from contextlib import suppress
from io import BytesIO
from threading import Event
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from catlabel.api import routes_print
from catlabel.core.resource_limits import ResourceLimitError
from catlabel.rendering.image_payload import decode_image_payloads
from catlabel.rendering.template import (
    BrowserRenderer,
    RenderBusyError,
    RendererStoppedError,
    render_via_browser,
)


def _error_detail(failure: HTTPException) -> dict[str, object]:
    if not isinstance(failure.detail, dict):
        raise AssertionError("expected structured HTTP error details")
    return failure.detail


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
            patch.object(
                routes_print, "render_via_browser_async", new=AsyncMock()
            ) as render,
            patch.object(
                routes_print, "_execute_claimed_print_jobs", new=AsyncMock()
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
            patch.object(
                routes_print, "render_via_browser_async", new=AsyncMock()
            ) as render,
            self.assertRaises(HTTPException) as raised,
        ):
            await routes_print.print_direct(request)
        self.assertEqual(raised.exception.status_code, 422)
        render.assert_not_called()

    async def test_renderer_failures_map_to_render_http_errors_without_printing(
        self,
    ) -> None:
        direct = routes_print.DirectPrintRequest(
            mac_address="AA:BB:CC:DD:EE:FF", canvas_state={}
        )
        batch = routes_print.BatchPrintRequest(
            mac_address="AA:BB:CC:DD:EE:FF", canvas_state={}, variables_list=[{}]
        )
        error_cases = (
            (RenderBusyError, "renderer busy", 503),
            (RendererStoppedError, "renderer stopped", 503),
            (TimeoutError, "render deadline", 504),
            (ResourceLimitError, "render output limit", 422),
            (RuntimeError, "browser failed", 500),
        )
        for request in (direct, batch):
            for error_type, message, status_code in error_cases:
                with self.subTest(route=type(request).__name__, error=error_type):
                    error = error_type(message)
                    with (
                        patch.object(
                            routes_print,
                            "render_via_browser_async",
                            new=AsyncMock(side_effect=error),
                        ) as render,
                        patch.object(
                            routes_print,
                            "_execute_claimed_print_jobs",
                            new=AsyncMock(),
                        ) as execute,
                        self.assertRaises(HTTPException) as raised,
                    ):
                        if isinstance(request, routes_print.DirectPrintRequest):
                            await routes_print.print_direct(request)
                        else:
                            await routes_print.print_batch(request)
                    self.assertEqual(raised.exception.status_code, status_code)
                    self.assertEqual(
                        raised.exception.detail,
                        {
                            "message": message,
                            "stage": "render",
                            "delivery_uncertain": False,
                        },
                    )
                    render.assert_awaited_once()
                    execute.assert_not_awaited()

    def test_copies_are_strict_and_bounded(self) -> None:
        for copies in (0, 101, True, "2", 1.5):
            with self.subTest(copies=copies), self.assertRaises(ValidationError):
                routes_print.BatchPrintRequest.model_validate(
                    {"mac_address": "fixture", "canvas_state": {}, "copies": copies}
                )

    async def test_decoded_image_pixel_limit_precedes_conversion(self) -> None:
        request = routes_print.ImagePrintRequest(
            mac_address="AA:BB:CC:DD:EE:FF", images=[_png()]
        )
        with (
            patch(
                "catlabel.rendering.image_payload.validate_image_budget",
                side_effect=ResourceLimitError("too many pixels"),
            ),
            patch.object(Image.Image, "convert") as convert,
            patch.object(
                routes_print, "_execute_claimed_print_jobs", new=AsyncMock()
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
                mac_address="AA:BB:CC:DD:EE:FF", images=[_png()]
            )
            with (
                patch.object(
                    routes_print, "decode_image_payloads", return_value=images
                ),
                patch.object(
                    routes_print,
                    "_execute_claimed_print_jobs",
                    new=AsyncMock(side_effect=error),
                ),
                self.assertRaises(type(error)),
            ):
                await routes_print.print_images_direct(request)
            with self.assertRaises(ValueError):
                images[0].getpixel((0, 0))

    async def test_invalid_blank_address_precedes_all_route_preparation(self) -> None:
        direct = routes_print.DirectPrintRequest(mac_address="", canvas_state={})
        batch = routes_print.BatchPrintRequest(mac_address="", canvas_state={})
        image_request = routes_print.ImagePrintRequest(mac_address="", images=[_png()])
        with (
            patch.object(
                routes_print, "render_via_browser_async", new=AsyncMock()
            ) as render,
            patch.object(routes_print, "decode_image_payloads") as decode,
            patch.object(
                routes_print, "_execute_claimed_print_jobs", new=AsyncMock()
            ) as execute,
        ):
            with (
                self.subTest(route="direct"),
                self.assertRaises(HTTPException) as direct_error,
            ):
                await routes_print.print_direct(direct)
            with (
                self.subTest(route="batch"),
                self.assertRaises(HTTPException) as batch_error,
            ):
                await routes_print.print_batch(batch)
            with (
                self.subTest(route="images"),
                self.assertRaises(HTTPException) as image_error,
            ):
                await routes_print.print_images_direct(image_request)
            for raised in (direct_error, batch_error, image_error):
                self.assertEqual(raised.exception.status_code, 400)
                self.assertEqual(_error_detail(raised.exception)["stage"], "admission")

            render.assert_not_awaited()
            decode.assert_not_called()
            execute.assert_not_awaited()

    async def test_direct_only_adds_mac_address_and_empty_images_bypass_admission(
        self,
    ) -> None:
        mac_address = "AA:BB:CC:DD:EE:FF"
        receipt = {
            "status": "submitted",
            "submitted": 1,
            "physical_completion": "unverified",
            "job_id": "fixture-job",
            "message": "fixture receipt",
        }
        prepared_images = [
            Image.new("RGB", (2, 2), (1, 1, 1)),
            Image.new("RGB", (2, 2), (2, 2, 2)),
            Image.new("RGB", (2, 2), (3, 3, 3)),
        ]
        with (
            patch.object(
                routes_print,
                "render_via_browser_async",
                new=AsyncMock(side_effect=[[prepared_images[0]], [prepared_images[1]]]),
            ),
            patch.object(
                routes_print,
                "decode_image_payloads",
                return_value=[prepared_images[2]],
            ),
            patch.object(
                routes_print,
                "_execute_claimed_print_jobs",
                new=AsyncMock(return_value=receipt),
            ) as execute,
        ):
            direct_receipt = await routes_print.print_direct(
                routes_print.DirectPrintRequest(
                    mac_address=mac_address, canvas_state={}
                )
            )
            batch_receipt = await routes_print.print_batch(
                routes_print.BatchPrintRequest(mac_address=mac_address, canvas_state={})
            )
            image_receipt = await routes_print.print_images_direct(
                routes_print.ImagePrintRequest(mac_address=mac_address, images=[_png()])
            )

            self.assertEqual(direct_receipt, {**receipt, "mac_address": mac_address})
            self.assertEqual(batch_receipt, receipt)
            self.assertEqual(image_receipt, receipt)
            execute.assert_awaited()

        for image in prepared_images:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))

        with patch.object(routes_print, "canonical_device_address") as validate:
            empty_receipt = await routes_print.print_images_direct(
                routes_print.ImagePrintRequest(mac_address="", images=[])
            )
        self.assertEqual(
            empty_receipt,
            {"status": "empty", "submitted": 0, "physical_completion": "unverified"},
        )
        validate.assert_not_called()

    async def test_cancel_during_decode_waits_for_and_closes_late_result(self) -> None:
        started = Event()
        release = Event()
        images: list[Image.Image] = []
        decode_calls = 0

        def blocked_decode(_payloads, *, rotate: bool = False) -> list[Image.Image]:
            nonlocal decode_calls
            decode_calls += 1
            started.set()
            if not release.wait(2):
                raise TimeoutError("test decoder was not released")
            image = Image.new("RGB", (2, 2), (9, 8, 7))
            images.append(image)
            return [image]

        request = routes_print.ImagePrintRequest(
            mac_address="AA:BB:CC:DD:EE:FF", images=[_png()]
        )
        with (
            patch.object(routes_print, "decode_image_payloads", blocked_decode),
            patch.object(
                routes_print, "_execute_claimed_print_jobs", new=AsyncMock()
            ) as execute,
        ):
            task = asyncio.create_task(routes_print.print_images_direct(request))
            try:
                started_in_time = await asyncio.wait_for(
                    asyncio.to_thread(started.wait, 2), timeout=2
                )
                self.assertTrue(started_in_time)
                task.cancel("caller-stop")
                done, _ = await asyncio.wait({task}, timeout=0.05)
                self.assertFalse(done)

                with self.assertRaises(HTTPException) as busy:
                    await routes_print.print_images_direct(request)
                self.assertEqual(busy.exception.status_code, 409)
                self.assertEqual(_error_detail(busy.exception)["stage"], "admission")
                self.assertEqual(decode_calls, 1)

                release.set()
                with self.assertRaises(asyncio.CancelledError) as raised:
                    await asyncio.wait_for(task, timeout=2)
                self.assertEqual(raised.exception.args, ("caller-stop",))
                self.assertEqual(len(images), 1)
                with self.assertRaises(ValueError):
                    images[0].getpixel((0, 0))
                execute.assert_not_awaited()
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                    with suppress(BaseException):
                        await task


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
            patch.object(
                BrowserRenderer, "_ensure_browser", new=AsyncMock()
            ) as ensure_browser,
            self.assertRaises(ResourceLimitError),
        ):
            render_via_browser({"width": 10000, "height": 10000}, [{}])
        ensure_browser.assert_not_awaited()
