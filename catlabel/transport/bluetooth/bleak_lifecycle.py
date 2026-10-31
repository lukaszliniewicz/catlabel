"""Owned BLE operations with deadlines that do not wait for cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, TypeVar
from weakref import WeakKeyDictionary

_T = TypeVar("_T")


def _chain_cleanup_error(primary: BaseException, cleanup: BaseException) -> None:
    """Retain an existing primary cause when reporting an additional failure."""
    tail = primary
    seen = {id(primary)}
    while tail.__cause__ is not None and id(tail.__cause__) not in seen:
        tail = tail.__cause__
        seen.add(id(tail))
    extra: BaseException | None = cleanup
    while extra is not None:
        if id(extra) in seen:
            return
        seen.add(id(extra))
        extra = extra.__cause__
    tail.__cause__ = cleanup


class _BleakLifecycle:
    """Keep cancellation-resistant operations reachable until they finish."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task[Any]] = set()
        self._operations: dict[str, asyncio.Task[Any]] = {}
        self._finished_at: WeakKeyDictionary[asyncio.Task[Any], float] = (
            WeakKeyDictionary()
        )

    def start(
        self, key: str, operation: Callable[[], Awaitable[_T]]
    ) -> asyncio.Task[_T]:
        existing = self._operations.get(key)
        if existing is not None and not existing.done():
            return existing

        async def invoke() -> _T:
            try:
                return await operation()
            finally:
                current = asyncio.current_task()
                if current is not None:
                    self._finished_at[current] = asyncio.get_running_loop().time()

        task = asyncio.create_task(invoke(), name=f"ble:{key}")
        self.tasks.add(task)
        self._operations[key] = task

        def finished(completed: asyncio.Task[Any]) -> None:
            # Retrieving the exception also covers operations whose caller has
            # already timed out. Never drop a live operation's only handle.
            if not completed.cancelled():
                with suppress(BaseException):
                    completed.exception()
            self.tasks.discard(completed)
            if self._operations.get(key) is completed:
                del self._operations[key]

        task.add_done_callback(finished)
        return task

    async def wait(
        self,
        task: asyncio.Task[_T],
        *,
        deadline: float,
        cancel_on_cancel: bool = True,
    ) -> _T:
        loop = asyncio.get_running_loop()
        if loop.time() >= deadline:
            task.cancel()
            raise TimeoutError(f"BLE operation {task.get_name()} timed out")
        try:
            done, _ = await asyncio.wait(
                (task,), timeout=max(0.0, deadline - loop.time())
            )
        except asyncio.CancelledError:
            if cancel_on_cancel:
                task.cancel()
            raise
        if not done or self._finished_at.get(task, loop.time()) > deadline:
            task.cancel()
            raise TimeoutError(f"BLE operation {task.get_name()} timed out")
        return task.result()

    async def run(
        self,
        key: str,
        operation: Callable[[], Awaitable[_T]],
        *,
        deadline: float,
    ) -> _T:
        return await self.wait(self.start(key, operation), deadline=deadline)

    def pending(self) -> set[asyncio.Task[Any]]:
        current = asyncio.current_task()
        return {task for task in self.tasks if task is not current and not task.done()}

    def cancel_pending(self) -> None:
        for task in self.pending():
            if not task.cancelling():
                task.cancel()

    async def quiesce(self, *, deadline: float) -> bool:
        pending = self.pending()
        if pending:
            await asyncio.wait(
                pending, timeout=max(0.0, deadline - asyncio.get_running_loop().time())
            )
        return not self.pending()
