"""Run image decoding off-thread while keeping returned images explicitly owned."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from threading import Lock

from PIL import Image


def _close_images(images: list[Image.Image] | None) -> None:
    if images is None:
        return
    for image in images:
        with suppress(Exception):
            image.close()


class _ImageOwner:
    """Move decoded images between a worker thread and its awaiting caller."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._images: list[Image.Image] | None = None
        self._abandoned = False

    def publish(self, images: list[Image.Image]) -> None:
        with self._lock:
            abandoned = self._abandoned
            if not abandoned:
                self._images = images
        if abandoned:
            _close_images(images)

    def take(self) -> list[Image.Image]:
        with self._lock:
            images = self._images
            self._images = None
        if images is None:
            raise RuntimeError(
                "The image worker completed without publishing its result."
            )
        return images

    def abandon(self) -> None:
        with self._lock:
            self._abandoned = True
            images = self._images
            self._images = None
        _close_images(images)


def _consume_task_result(task: asyncio.Task[None]) -> None:
    if not task.done() or task.cancelled():
        return
    with suppress(BaseException):
        task.exception()


async def _drain_shielded_task(task: asyncio.Task[None]) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                break
        except BaseException:
            break
    _consume_task_result(task)


async def decode_owned(
    worker: Callable[[], list[Image.Image]],
) -> list[Image.Image]:
    """Decode in a thread and transfer image ownership safely to this caller.

    The worker publishes its image list into a locked owner box and returns no
    images through the asyncio task. Normal cancellation of this caller abandons
    the box, drains the same shielded task (including repeated cancellation),
    then re-raises the original cancellation.

    If the asyncio wrapper task is independently cancelled, or the event loop is
    shutting down, its wrapper may finish while the underlying thread continues.
    The worker retains the abandoned owner box and closes any late publication.
    A completed asyncio task only describes its wrapper; it does not prove that
    an underlying thread has stopped.
    """
    owner = _ImageOwner()

    def run_worker() -> None:
        owner.publish(worker())

    task = asyncio.create_task(asyncio.to_thread(run_worker))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError as cancellation:
        owner.abandon()
        caller_task = asyncio.current_task()
        if caller_task is not None and caller_task.cancelling() > 0:
            await _drain_shielded_task(task)
        raise cancellation
    except BaseException:
        owner.abandon()
        _consume_task_result(task)
        raise

    return owner.take()
