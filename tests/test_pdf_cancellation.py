from __future__ import annotations

import asyncio
import threading
import unittest
from collections.abc import Coroutine
from io import BytesIO
from typing import Any
from unittest.mock import patch

from fastapi import UploadFile
from PIL import Image as PILImage

from catlabel.services import uploads


class _TrackingUploadFile(UploadFile):
    def __init__(self) -> None:
        self.close_calls = 0
        super().__init__(filename="fixture.pdf", file=BytesIO(b"fixture PDF"))

    async def close(self) -> None:
        self.close_calls += 1
        await super().close()


class _Bitmap:
    def __init__(self) -> None:
        self.image = PILImage.new("RGB", (3, 3), (255, 255, 255))
        self.close_calls = 0

    def to_pil(self) -> PILImage.Image:
        return self.image

    def close(self) -> None:
        self.close_calls += 1


class _Page:
    def __init__(
        self,
        render_started: threading.Event | None = None,
        render_release: threading.Event | None = None,
    ) -> None:
        self.render_started = render_started
        self.render_release = render_release
        self.render_calls = 0
        self.close_calls = 0
        self.bitmap: _Bitmap | None = None

    def get_size(self) -> tuple[float, float]:
        return (1.0, 1.0)

    def render(self, scale: float = 1) -> _Bitmap:
        del scale
        self.render_calls += 1
        if self.render_started is not None:
            self.render_started.set()
        if self.render_release is not None and not self.render_release.wait(2):
            raise RuntimeError("fixture render gate was not released")
        self.bitmap = _Bitmap()
        return self.bitmap

    def close(self) -> None:
        self.close_calls += 1


class _Document:
    def __init__(self, pages: list[_Page]) -> None:
        self.pages = pages
        self.close_calls = 0
        self.closed = threading.Event()

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, index: int) -> _Page:
        return self.pages[index]

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


class PdfCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def _wait_for_thread_event(self, event: threading.Event) -> bool:
        return await asyncio.to_thread(event.wait, 2)

    async def _assert_conversion_resources_closed(
        self,
        upload: _TrackingUploadFile,
        document: _Document,
        pages: list[_Page],
        closed_images: list[PILImage.Image],
    ) -> None:
        self.assertEqual(upload.close_calls, 1)
        self.assertTrue(upload.file.closed)
        self.assertEqual(document.close_calls, 1)
        self.assertTrue(
            all(
                page.close_calls == (2 if page.bitmap is not None else 1)
                for page in pages
            )
        )
        rendered_bitmaps = [page.bitmap for page in pages if page.bitmap is not None]
        self.assertEqual(len(rendered_bitmaps), 1)
        assert rendered_bitmaps[0] is not None
        self.assertEqual(rendered_bitmaps[0].close_calls, 1)
        self.assertEqual(len(closed_images), 2)

    async def test_caller_cancellation_drains_worker_and_preserves_first_reason(
        self,
    ) -> None:
        render_started = threading.Event()
        render_release = threading.Event()
        first_page = _Page(render_started, render_release)
        second_page = _Page()
        pages = [first_page, second_page]
        document = _Document(pages)
        upload = _TrackingUploadFile()
        closed_images: list[PILImage.Image] = []
        original_close = PILImage.Image.close

        def track_close(image: PILImage.Image) -> None:
            closed_images.append(image)
            original_close(image)

        with (
            patch(
                "catlabel.services.uploads.pdfium.PdfDocument",
                return_value=document,
            ),
            patch.object(PILImage.Image, "close", track_close),
        ):
            conversion = asyncio.create_task(uploads.convert_uploaded_pdf(upload))
            started = await self._wait_for_thread_event(render_started)
            conversion.cancel("first cancellation")
            await asyncio.sleep(0)
            pending_after_first_cancel = not conversion.done()
            conversion.cancel("repeated cancellation")
            await asyncio.sleep(0)
            pending_after_repeated_cancel = not conversion.done()
            render_release.set()

            with self.assertRaises(asyncio.CancelledError) as raised:
                await conversion

        self.assertTrue(started)
        self.assertTrue(pending_after_first_cancel)
        self.assertTrue(pending_after_repeated_cancel)
        self.assertEqual(raised.exception.args, ("first cancellation",))
        self.assertEqual(first_page.render_calls, 1)
        self.assertEqual(second_page.render_calls, 0)
        await self._assert_conversion_resources_closed(
            upload, document, pages, closed_images
        )

    async def test_independent_conversion_task_cancellation_does_not_spin_or_claim_thread_done(
        self,
    ) -> None:
        render_started = threading.Event()
        render_release = threading.Event()
        first_page = _Page(render_started, render_release)
        second_page = _Page()
        pages = [first_page, second_page]
        document = _Document(pages)
        upload = _TrackingUploadFile()
        closed_images: list[PILImage.Image] = []
        original_close = PILImage.Image.close

        def track_close(image: PILImage.Image) -> None:
            closed_images.append(image)
            original_close(image)

        original_create_task = asyncio.create_task
        conversion_tasks: list[asyncio.Task[list[str]]] = []

        def capture_conversion_task(
            coroutine: Coroutine[Any, Any, list[str]],
        ) -> asyncio.Task[list[str]]:
            task = original_create_task(coroutine)
            conversion_tasks.append(task)
            return task

        with (
            patch(
                "catlabel.services.uploads.pdfium.PdfDocument",
                return_value=document,
            ),
            patch.object(PILImage.Image, "close", track_close),
        ):
            caller = original_create_task(uploads.convert_uploaded_pdf(upload))
            try:
                with patch.object(
                    uploads.asyncio,
                    "create_task",
                    side_effect=capture_conversion_task,
                ):
                    started = await self._wait_for_thread_event(render_started)

                self.assertEqual(len(conversion_tasks), 1)
                conversion_tasks[0].cancel("independent conversion task cancellation")
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(caller), timeout=1)
                worker_still_running = document.close_calls == 0
                upload_closed_while_worker_running = upload.close_calls == 1
            finally:
                render_release.set()
                closed_after_release = await self._wait_for_thread_event(
                    document.closed
                )

        self.assertTrue(started)
        self.assertTrue(worker_still_running)
        self.assertTrue(upload_closed_while_worker_running)
        self.assertTrue(closed_after_release)
        self.assertEqual(first_page.render_calls, 1)
        self.assertEqual(second_page.render_calls, 0)
        await self._assert_conversion_resources_closed(
            upload, document, pages, closed_images
        )


if __name__ == "__main__":
    unittest.main()
