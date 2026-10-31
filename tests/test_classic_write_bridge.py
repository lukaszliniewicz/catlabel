from __future__ import annotations

import asyncio
import threading
import unittest
from collections.abc import Callable

from catlabel.printing.runtime.base import RuntimeController, RuntimeSessionApi
from catlabel.transport.bluetooth import SppBackend
from catlabel.vendors.generic.client import _GenericBackendConnection


class _ChunkBackend(SppBackend):
    def __init__(self) -> None:
        self.permission: Callable[[int, float], None] | None = None
        self.writes: list[bytes] = []

    def can_attach_runtime_controller(self) -> bool:
        return False

    def can_receive_passively(self) -> bool:
        return True

    def register_notify_callback(
        self, callback: Callable[[bytes], None] | None
    ) -> None:
        pass

    def register_before_write_callback(
        self, callback: Callable[[int, float], None] | None
    ) -> None:
        self.permission = callback

    async def write(
        self,
        data: bytes,
        chunk_size: int,
        delay_ms: int = 0,
        interval_ms: int | None = None,
    ) -> None:
        def send() -> None:
            permission = self.permission
            assert permission is not None
            for offset in range(0, len(data), chunk_size):
                chunk = data[offset : offset + chunk_size]
                permission(len(chunk), 0.5)
                self.writes.append(chunk)

        await asyncio.to_thread(send)


class _FaultController(RuntimeController):
    def __init__(self) -> None:
        self.calls: list[tuple[int, float, int]] = []

    async def before_write(
        self, session: RuntimeSessionApi, *, size: int, timeout: float
    ) -> None:
        self.calls.append((size, timeout, threading.get_ident()))
        if len(self.calls) == 2:
            raise RuntimeError("Device fault before second physical chunk")


class ClassicWriteBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_permission_runs_on_controller_loop_and_aborts_remaining_chunks(
        self,
    ) -> None:
        backend = _ChunkBackend()
        connection = _GenericBackendConnection(backend, chunk_size=2, delay_ms=0)
        controller = _FaultController()
        await connection.attach_runtime_controller(controller)
        try:
            with self.assertRaisesRegex(RuntimeError, "Device fault"):
                await connection.send_standard_payload(b"abcdef")
            self.assertEqual(backend.writes, [b"ab"])
            self.assertEqual(controller.calls, [(2, 0.5, threading.get_ident())] * 2)
        finally:
            await connection.stop_runtime_controller()
        self.assertIsNone(backend.permission)


if __name__ == "__main__":
    unittest.main()
