from __future__ import annotations

import asyncio
import unittest
from contextlib import suppress
from threading import Event
from unittest.mock import patch

from PIL import Image

from catlabel.rendering.owned_decode import decode_owned


class OwnedDecodeTests(unittest.IsolatedAsyncioTestCase):
    async def _wait_for_event(self, event: Event) -> None:
        signaled = await asyncio.wait_for(asyncio.to_thread(event.wait, 2), timeout=2)
        self.assertTrue(signaled)

    async def _wait_for_closed(self, image: Image.Image) -> None:
        deadline = asyncio.get_running_loop().time() + 2
        while asyncio.get_running_loop().time() < deadline:
            try:
                image.getpixel((0, 0))
            except ValueError:
                return
            await asyncio.sleep(0.01)
        self.fail("late-published image was not closed")

    async def test_success_returns_usable_images_to_the_caller(self) -> None:
        image = Image.new("RGB", (2, 2), (12, 34, 56))

        images = await decode_owned(lambda: [image])

        self.assertEqual(images, [image])
        self.assertEqual(images[0].getpixel((0, 0)), (12, 34, 56))
        images[0].close()
        with self.assertRaises(ValueError):
            images[0].getpixel((0, 0))

    async def test_worker_failure_propagates(self) -> None:
        def fail() -> list[Image.Image]:
            raise RuntimeError("decode failed")

        with self.assertRaisesRegex(RuntimeError, "decode failed"):
            await decode_owned(fail)

    async def test_caller_cancellation_drains_worker_and_closes_its_result(
        self,
    ) -> None:
        started = Event()
        release = Event()
        images: list[Image.Image] = []

        def worker() -> list[Image.Image]:
            started.set()
            if not release.wait(2):
                raise TimeoutError("test worker was not released")
            image = Image.new("RGB", (2, 2), (1, 2, 3))
            images.append(image)
            return [image]

        task = asyncio.create_task(decode_owned(worker))
        try:
            await self._wait_for_event(started)
            task.cancel("caller-stop")
            done, _ = await asyncio.wait({task}, timeout=0.05)
            self.assertFalse(done)

            release.set()
            with self.assertRaises(asyncio.CancelledError) as raised:
                await asyncio.wait_for(task, timeout=2)
            self.assertEqual(raised.exception.args, ("caller-stop",))
            self.assertEqual(len(images), 1)
            with self.assertRaises(ValueError):
                images[0].getpixel((0, 0))
        finally:
            release.set()
            if not task.done():
                task.cancel()
                with suppress(BaseException):
                    await task

    async def test_repeated_caller_cancellation_does_not_end_drain_early(self) -> None:
        started = Event()
        release = Event()
        images: list[Image.Image] = []

        def worker() -> list[Image.Image]:
            started.set()
            if not release.wait(2):
                raise TimeoutError("test worker was not released")
            image = Image.new("RGB", (2, 2), (4, 5, 6))
            images.append(image)
            return [image]

        task = asyncio.create_task(decode_owned(worker))
        try:
            await self._wait_for_event(started)
            task.cancel("original-stop")
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())

            task.cancel("repeated-stop")
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())

            release.set()
            with self.assertRaises(asyncio.CancelledError) as raised:
                await asyncio.wait_for(task, timeout=2)
            self.assertEqual(raised.exception.args, ("original-stop",))
            self.assertEqual(len(images), 1)
            with self.assertRaises(ValueError):
                images[0].getpixel((0, 0))
        finally:
            release.set()
            if not task.done():
                task.cancel()
                with suppress(BaseException):
                    await task

    async def test_independent_wrapper_cancellation_closes_late_publication(
        self,
    ) -> None:
        started = Event()
        release = Event()
        produced = Event()
        images: list[Image.Image] = []

        def worker() -> list[Image.Image]:
            started.set()
            if not release.wait(2):
                raise TimeoutError("test worker was not released")
            image = Image.new("RGB", (2, 2), (7, 8, 9))
            images.append(image)
            produced.set()
            return [image]

        original_create_task = asyncio.create_task
        child_tasks: list[asyncio.Task[None]] = []

        def capture_task(coroutine, *args, **kwargs):
            task = original_create_task(coroutine, *args, **kwargs)
            child_tasks.append(task)
            return task

        task = original_create_task(decode_owned(worker))
        try:
            with patch.object(asyncio, "create_task", side_effect=capture_task):
                await self._wait_for_event(started)
            self.assertEqual(len(child_tasks), 1)

            child_tasks[0].cancel("wrapper-stop")
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=0.5)
            self.assertTrue(task.done())

            release.set()
            await self._wait_for_event(produced)
            await self._wait_for_closed(images[0])
        finally:
            release.set()
            if not task.done():
                task.cancel()
                with suppress(BaseException):
                    await task

    async def test_worker_error_during_cancel_drain_preserves_cancellation(
        self,
    ) -> None:
        started = Event()
        release = Event()
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()

        def capture_exception(_loop, context) -> None:
            contexts.append(context)

        def worker() -> list[Image.Image]:
            started.set()
            if not release.wait(2):
                raise TimeoutError("test worker was not released")
            raise ValueError("late worker failure")

        task = asyncio.create_task(decode_owned(worker))
        loop.set_exception_handler(capture_exception)
        try:
            await self._wait_for_event(started)
            task.cancel("original-stop")
            done, _ = await asyncio.wait({task}, timeout=0.05)
            self.assertFalse(done)

            release.set()
            with self.assertRaises(asyncio.CancelledError) as raised:
                await asyncio.wait_for(task, timeout=2)
            self.assertEqual(raised.exception.args, ("original-stop",))
            await asyncio.sleep(0)
            self.assertEqual(contexts, [])
        finally:
            release.set()
            loop.set_exception_handler(previous_handler)
            if not task.done():
                task.cancel()
                with suppress(BaseException):
                    await task


if __name__ == "__main__":
    unittest.main()
