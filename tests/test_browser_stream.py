from __future__ import annotations

import asyncio
import base64
import binascii
import threading
import unittest
from collections.abc import Callable
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from catlabel.core.resource_limits import ResourceLimitError
from catlabel.rendering import browser_stream


def _png_data_url(size: tuple[int, int] = (3, 2)) -> str:
    with Image.new("RGB", size, "white") as image, BytesIO() as output:
        image.save(output, format="PNG")
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class FakeStreamPage:
    def __init__(
        self,
        frames: list[dict[str, object]],
        *,
        error: object = None,
        payload_on_transfer: Callable[[int, object], object] | None = None,
    ) -> None:
        self.frames = frames
        self.error = error
        self.payload_on_transfer = payload_on_transfer
        self.position = 0
        self.payload_transfers = 0
        self.acknowledged: list[object] = []
        self.outstanding_payloads = 0
        self.max_outstanding_payloads = 0
        self.metadata_reads = 0
        self.polling_values: list[int] = []

    async def wait_for_function(self, expression: str, *, polling: int) -> object:
        if expression != browser_stream._FRAME_EVENT_SCRIPT:
            raise AssertionError("collector waited for an unexpected browser event")
        self.polling_values.append(polling)
        if polling != 5:
            raise AssertionError("collector must poll stream state every 5 ms")
        return object()

    async def evaluate(self, expression: str, argument: object = None) -> object:
        if expression == browser_stream._FRAME_METADATA_SCRIPT:
            self.metadata_reads += 1
            has_frame = self.position < len(self.frames)
            frame = self.frames[self.position] if has_frame else None
            payload = frame.get("payload") if frame is not None else None
            metadata = {
                "error": self.error,
                "done": not has_frame,
                "hasFrame": has_frame,
                "index": frame.get("index") if frame is not None else None,
                "total": frame.get("total") if frame is not None else None,
                "payloadType": (
                    frame.get("payloadType", "string")
                    if frame is not None
                    else "undefined"
                ),
                "payloadLength": (
                    frame.get(
                        "payloadLength",
                        len(payload) if isinstance(payload, str) else None,
                    )
                    if frame is not None
                    else None
                ),
                "payloadHeader": (
                    frame.get(
                        "payloadHeader",
                        payload[:22] if isinstance(payload, str) else None,
                    )
                    if frame is not None
                    else None
                ),
            }
            metadata.update(
                {
                    key: value
                    for key, value in (frame or {}).items()
                    if key
                    in {
                        "done",
                        "hasFrame",
                        "index",
                        "total",
                        "payloadType",
                        "payloadLength",
                        "payloadHeader",
                    }
                }
            )
            return metadata

        if expression == browser_stream._FRAME_PAYLOAD_SCRIPT:
            if self.outstanding_payloads != 0:
                raise AssertionError("a second payload was read before acknowledgement")
            frame = self.frames[self.position]
            self.payload_transfers += 1
            self.outstanding_payloads += 1
            self.max_outstanding_payloads = max(
                self.max_outstanding_payloads, self.outstanding_payloads
            )
            payload = frame.get("payload")
            if self.payload_on_transfer is not None:
                return self.payload_on_transfer(self.position, payload)
            return payload

        if expression == browser_stream._ACK_FRAME_SCRIPT:
            self.acknowledged.append(argument)
            if self.outstanding_payloads != 1:
                raise AssertionError("frame acknowledgement had no outstanding payload")
            self.outstanding_payloads -= 1
            self.position += 1
            return argument == self.position - 1

        raise AssertionError(f"Unexpected page.evaluate expression: {expression}")


def _frame(
    index: object,
    payload: object,
    *,
    total: object = 1,
    **metadata: object,
) -> dict[str, object]:
    frame: dict[str, object] = {"index": index, "total": total, "payload": payload}
    frame.update(metadata)
    return frame


class BrowserStreamTests(unittest.IsolatedAsyncioTestCase):
    async def _collect(
        self,
        page: FakeStreamPage,
        *,
        expected_jobs: int = 1,
        rotate: bool = False,
        check_active: Callable[[], None] = lambda: None,
    ) -> list[Image.Image]:
        return await browser_stream.collect_streamed_images(
            page,
            expected_jobs=expected_jobs,
            rotate=rotate,
            check_active=check_active,
        )

    async def test_collects_each_payload_before_acknowledging_and_waiting_again(
        self,
    ) -> None:
        payload = _png_data_url()
        page = FakeStreamPage(
            [_frame(0, payload, total=2), _frame(1, payload, total=2)]
        )
        images = await self._collect(page, expected_jobs=2, rotate=True)
        try:
            self.assertEqual([image.size for image in images], [(2, 3), (2, 3)])
            self.assertEqual(page.acknowledged, [0, 1])
            self.assertEqual(page.payload_transfers, 2)
            self.assertEqual(page.max_outstanding_payloads, 1)
            self.assertEqual(page.metadata_reads, 3)
            self.assertEqual(page.polling_values, [5, 5, 5])
        finally:
            for image in images:
                image.close()

    async def test_type_and_size_limits_are_checked_before_payload_transfer(
        self,
    ) -> None:
        payload = _png_data_url()
        invalid_type = FakeStreamPage([_frame(0, payload, payloadType="object")])
        with self.assertRaises(ResourceLimitError):
            await self._collect(invalid_type)
        self.assertEqual(invalid_type.payload_transfers, 0)

        oversized = FakeStreamPage(
            [
                _frame(
                    0,
                    payload,
                    payloadLength=browser_stream.MAX_ENCODED_IMAGE_CHARS + 1,
                )
            ]
        )
        self.assertLess(
            browser_stream.MAX_ENCODED_IMAGE_CHARS,
            browser_stream.MAX_ENCODED_OUTPUT_CHARS,
        )
        with self.assertRaisesRegex(ResourceLimitError, "per-image encoded size"):
            await self._collect(oversized)
        self.assertEqual(oversized.payload_transfers, 0)

        aggregate_oversized = FakeStreamPage(
            [
                _frame(
                    0,
                    payload,
                    payloadLength=browser_stream.MAX_ENCODED_OUTPUT_CHARS + 1,
                )
            ]
        )
        with self.assertRaisesRegex(ResourceLimitError, "per-image encoded size"):
            await self._collect(aggregate_oversized)
        self.assertEqual(aggregate_oversized.payload_transfers, 0)

        per_frame_limit = FakeStreamPage([_frame(0, payload)])
        with (
            patch.object(browser_stream, "MAX_ENCODED_OUTPUT_CHARS", len(payload) - 1),
            self.assertRaisesRegex(ResourceLimitError, "encoded size"),
        ):
            await self._collect(per_frame_limit)
        self.assertEqual(per_frame_limit.payload_transfers, 0)

    async def test_aggregate_limit_rejects_next_frame_before_transfer(self) -> None:
        payload = _png_data_url()
        page = FakeStreamPage(
            [_frame(0, payload, total=2), _frame(1, payload, total=2)]
        )
        with (
            patch.object(
                browser_stream,
                "MAX_ENCODED_OUTPUT_CHARS",
                len(payload) * 2 - 1,
            ),
            self.assertRaisesRegex(ResourceLimitError, "output exceeds"),
        ):
            await self._collect(page, expected_jobs=2)
        self.assertEqual(page.payload_transfers, 1)
        self.assertEqual(page.acknowledged, [0])

    async def test_indices_counts_and_payload_contents_are_validated(self) -> None:
        payload = _png_data_url()
        cases = (
            (_frame(True, payload), "index"),
            (_frame(0, payload, total=True), "count"),
            (_frame(1, payload), "duplicate or out-of-order"),
            (_frame(0, "not-a-data-url"), "invalid image payload"),
        )
        for frame, expected_message in cases:
            with self.subTest(frame=frame):
                page = FakeStreamPage([frame])
                with self.assertRaisesRegex(ResourceLimitError, expected_message):
                    await self._collect(page)
                self.assertEqual(page.acknowledged, [])

        mismatched = FakeStreamPage(
            [_frame(0, payload)],
            payload_on_transfer=lambda _position, value: (
                f"{value}extra" if isinstance(value, str) else value
            ),
        )
        with self.assertRaisesRegex(ResourceLimitError, "invalid image payload"):
            await self._collect(mismatched)
        self.assertEqual(mismatched.payload_transfers, 1)
        self.assertEqual(mismatched.acknowledged, [])

    async def test_render_error_aborts_before_payload_transfer_or_ack(self) -> None:
        for error in ("canvas failed", ""):
            with self.subTest(error=error):
                page = FakeStreamPage([_frame(0, _png_data_url())], error=error)
                with self.assertRaisesRegex(RuntimeError, "Frontend renderer failed"):
                    await self._collect(page)
                self.assertEqual(page.payload_transfers, 0)
                self.assertEqual(page.acknowledged, [])

    async def test_decoded_pixel_budget_is_cumulative_across_frames(self) -> None:
        payload = _png_data_url()
        page = FakeStreamPage(
            [_frame(0, payload, total=2), _frame(1, payload, total=2)]
        )
        validate_calls: list[int] = []
        decoded_images: list[Image.Image] = []
        real_validate = browser_stream.validate_image_budget
        real_decode = browser_stream.decode_image_payloads

        def bounded_validate(width: object, height: object, pixels: object = 0) -> int:
            if (
                isinstance(width, bool)
                or not isinstance(width, int)
                or isinstance(height, bool)
                or not isinstance(height, int)
            ):
                raise ResourceLimitError("test image dimensions are invalid")
            prior = pixels if isinstance(pixels, int) else -1
            validate_calls.append(prior)
            if prior + width * height > 8:
                raise ResourceLimitError("test cumulative pixel limit")
            return real_validate(width, height, pixels)

        def collect_decode(
            payloads: object, *, rotate: bool = False
        ) -> list[Image.Image]:
            result = real_decode(payloads, rotate=rotate)  # type: ignore[arg-type]
            decoded_images.extend(result)
            return result

        with (
            patch.object(browser_stream, "validate_image_budget", bounded_validate),
            patch.object(browser_stream, "decode_image_payloads", collect_decode),
            self.assertRaisesRegex(ResourceLimitError, "cumulative pixel"),
        ):
            await self._collect(page, expected_jobs=2)

        self.assertEqual(validate_calls, [0, 6])
        self.assertEqual(page.acknowledged, [0])
        self.assertEqual(len(decoded_images), 2)
        for image in decoded_images:
            with self.assertRaises(ValueError):
                _ = image.getpixel((0, 0))

    async def test_decode_failure_closes_prior_images_and_does_not_ack_bad_frame(
        self,
    ) -> None:
        good_payload = _png_data_url()
        bad_payload = "data:image/png;base64,not-valid-base64!"
        page = FakeStreamPage(
            [
                _frame(0, good_payload, total=2),
                _frame(1, bad_payload, total=2),
            ]
        )
        decoded_images: list[Image.Image] = []
        real_decode = browser_stream.decode_image_payloads

        def collect_decode(
            payloads: object, *, rotate: bool = False
        ) -> list[Image.Image]:
            result = real_decode(payloads, rotate=rotate)  # type: ignore[arg-type]
            decoded_images.extend(result)
            return result

        with (
            patch.object(browser_stream, "decode_image_payloads", collect_decode),
            self.assertRaises((ValueError, binascii.Error)),
        ):
            await self._collect(page, expected_jobs=2)

        self.assertEqual(page.acknowledged, [0])
        self.assertEqual(len(decoded_images), 1)
        with self.assertRaises(ValueError):
            _ = decoded_images[0].getpixel((0, 0))

    async def test_cancel_during_decode_closes_late_image_and_never_acknowledges(
        self,
    ) -> None:
        page = FakeStreamPage([_frame(0, _png_data_url())])
        decode_started = threading.Event()
        release_decode = threading.Event()
        decoded_images: list[Image.Image] = []
        real_decode = browser_stream.decode_image_payloads

        def blocking_decode(
            payloads: object, *, rotate: bool = False
        ) -> list[Image.Image]:
            decode_started.set()
            if not release_decode.wait(timeout=2):
                raise TimeoutError("test decoder gate timed out")
            result = real_decode(payloads, rotate=rotate)  # type: ignore[arg-type]
            decoded_images.extend(result)
            return result

        with patch.object(browser_stream, "decode_image_payloads", blocking_decode):
            collection = asyncio.create_task(self._collect(page))
            self.assertTrue(await asyncio.to_thread(decode_started.wait, 1))
            collection.cancel()
            await asyncio.sleep(0.01)
            release_decode.set()
            with self.assertRaises(asyncio.CancelledError):
                await collection

        self.assertEqual(page.acknowledged, [])
        self.assertEqual(len(decoded_images), 1)
        with self.assertRaises(ValueError):
            _ = decoded_images[0].getpixel((0, 0))

    async def test_unexpected_frame_after_expected_final_ack_is_rejected(self) -> None:
        payload = _png_data_url()
        page = FakeStreamPage(
            [_frame(0, payload, total=1), _frame(1, payload, total=1)]
        )
        with self.assertRaisesRegex(ResourceLimitError, "more image frames"):
            await self._collect(page)
        self.assertEqual(page.acknowledged, [0])
        self.assertEqual(page.payload_transfers, 1)


if __name__ == "__main__":
    unittest.main()
