from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from catlabel.api import routes_print
from catlabel.transport.bluetooth.backend import SppBackend
from catlabel.vendors import VendorRegistry


class _ThreadRecordingBackend(SppBackend):
    def __init__(self) -> None:
        super().__init__()
        self.worker_threads: list[int] = []

    def _record(self) -> None:
        self.worker_threads.append(threading.get_ident())

    def _connect_attempts_blocking(self, attempts, pairing_hint) -> None:
        self._record()

    def _write_blocking(self, data, chunk_size, delay_ms, interval_ms=None) -> None:
        self._record()

    def _disconnect_blocking(self) -> None:
        self._record()


class _FakeClient:
    def __init__(self, *, connected=True, connection_error=None, print_error=None) -> None:
        self.connected = connected
        self.last_error = connection_error
        self.print_error = print_error
        self.disconnect = AsyncMock()

    async def connect(self) -> bool:
        return self.connected

    async def print_images(self, images, split_mode=False, dither=True) -> None:
        if self.print_error:
            raise self.print_error


class BluetoothThreadAffinityTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_io_and_disconnect_stay_on_one_worker_thread(self) -> None:
        backend = _ThreadRecordingBackend()
        try:
            await backend.connect_attempts([object()])
            await backend.write(b"test", chunk_size=4)
            await backend.disconnect()
        finally:
            backend._executor.shutdown(wait=True)

        self.assertEqual(len(backend.worker_threads), 3)
        self.assertEqual(len(set(backend.worker_threads)), 1)
        self.assertNotEqual(backend.worker_threads[0], threading.get_ident())


class PrintErrorReportingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._original_engine = routes_print.engine
        self._original_scanned_devices_cache = routes_print._scanned_devices_cache
        self.device = SimpleNamespace(
            name="Test Printer",
            address="AA:BB:CC:DD:EE:FF",
            paired=True,
        )
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        routes_print.engine = self.engine
        routes_print._scanned_devices_cache = [self.device]
        self.addCleanup(self._restore_route_state)

    def _restore_route_state(self) -> None:
        routes_print.engine = self._original_engine
        routes_print._scanned_devices_cache = self._original_scanned_devices_cache
        self.engine.dispose()

    async def _execute_with_client(self, client: _FakeClient) -> HTTPException:
        manifest = SimpleNamespace(get_client=lambda *args: client)
        hardware_info = {"vendor": "generic", "model_id": "test"}
        with (
            patch.object(VendorRegistry, "identify_device", return_value=hardware_info),
            patch.object(VendorRegistry, "get_manifest", return_value=manifest),
            patch.object(routes_print.logger, "error"),
            self.assertRaises(HTTPException) as raised,
        ):
            await routes_print.execute_print_jobs(
                "aa-bb-cc-dd-ee-ff",
                [object()],
            )
        return raised.exception

    async def test_connection_failure_includes_the_underlying_error(self) -> None:
        exc = await self._execute_with_client(
            _FakeClient(
                connected=False,
                connection_error=PermissionError("Access is denied"),
            )
        )

        self.assertEqual(exc.status_code, 503)
        self.assertEqual(exc.detail["stage"], "connect")
        self.assertEqual(exc.detail["error"], "Access is denied")
        self.assertRegex(exc.detail["error_id"], r"^[0-9a-f]{8}$")

    async def test_print_failure_is_structured_and_disconnects(self) -> None:
        client = _FakeClient(print_error=RuntimeError("printer rejected start command"))
        exc = await self._execute_with_client(client)

        self.assertEqual(exc.status_code, 500)
        self.assertEqual(exc.detail["stage"], "print")
        self.assertEqual(exc.detail["error"], "printer rejected start command")
        client.disconnect.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
