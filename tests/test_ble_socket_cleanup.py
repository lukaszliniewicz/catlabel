from __future__ import annotations

import asyncio
import unittest
from typing import Any

from catlabel.devices import BleTransportProfile
from catlabel.transport.bluetooth.adapters.bleak_adapter import _BleakSocket


class _FakeClient:
    def __init__(self, *, disconnect_error: BaseException | None = None) -> None:
        self.disconnect_error = disconnect_error
        self.disconnect_calls = 0

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.disconnect_error is not None:
            raise self.disconnect_error


class _StopController:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def stop(self, _session: Any) -> None:
        raise self.error


class _SetupFailureSocket(_BleakSocket):
    def __init__(
        self,
        steps: list[tuple[_FakeClient, BaseException | None, BaseException | None]],
    ) -> None:
        super().__init__(ble_profile=BleTransportProfile())
        self.steps = steps
        self.setup_loops: list[asyncio.AbstractEventLoop] = []

    async def _connect_async(self, address: str) -> None:
        _ = address
        loop = self._loop
        if loop is None:
            raise AssertionError("connect did not prepare its private event loop")
        self.setup_loops.append(loop)
        client, setup_error, stop_error = self.steps.pop(0)
        self._client = client
        self._connected = True
        if stop_error is not None:
            self._transport._runtime_controller = _StopController(stop_error)
        if setup_error is not None:
            raise setup_error


class BleSocketCleanupTests(unittest.TestCase):
    def _attach_loop_and_client(
        self,
        socket: _BleakSocket,
        client: _FakeClient,
        *,
        stop_error: BaseException | None = None,
    ) -> asyncio.AbstractEventLoop:
        loop = asyncio.new_event_loop()
        socket._loop = loop
        socket._client = client
        socket._connected = True
        if stop_error is not None:
            socket._transport._runtime_controller = _StopController(stop_error)
        return loop

    def test_close_resets_socket_and_closes_loop_after_stop_cancellation(self) -> None:
        stop_error = asyncio.CancelledError("runtime stop cancelled")
        client = _FakeClient()
        socket = _BleakSocket()
        loop = self._attach_loop_and_client(socket, client, stop_error=stop_error)
        old_transport = socket._transport

        with self.assertRaises(asyncio.CancelledError) as raised:
            socket.close()

        self.assertIs(raised.exception, stop_error)
        self.assertEqual(client.disconnect_calls, 1)
        self.assertFalse(socket._connected)
        self.assertIsNone(socket._client)
        self.assertIsNone(socket._loop)
        self.assertTrue(loop.is_closed())
        self.assertIsNot(socket._transport, old_transport)

    def test_close_resets_socket_and_closes_loop_after_disconnect_cancellation(
        self,
    ) -> None:
        disconnect_error = asyncio.CancelledError("physical disconnect cancelled")
        client = _FakeClient(disconnect_error=disconnect_error)
        socket = _BleakSocket()
        loop = self._attach_loop_and_client(socket, client)

        with self.assertRaises(asyncio.CancelledError) as raised:
            socket.close()

        self.assertIs(raised.exception, disconnect_error)
        self.assertEqual(client.disconnect_calls, 1)
        self.assertFalse(socket._connected)
        self.assertIsNone(socket._client)
        self.assertIsNone(socket._loop)
        self.assertTrue(loop.is_closed())

    def test_close_keeps_ordinary_disconnect_errors_best_effort(self) -> None:
        client = _FakeClient(disconnect_error=RuntimeError("disconnect failed"))
        socket = _BleakSocket()
        loop = self._attach_loop_and_client(socket, client)

        socket.close()

        self.assertEqual(client.disconnect_calls, 1)
        self.assertFalse(socket._connected)
        self.assertIsNone(socket._client)
        self.assertIsNone(socket._loop)
        self.assertTrue(loop.is_closed())

    def test_connect_preserves_setup_error_restores_previous_loop_and_allows_reconnect(
        self,
    ) -> None:
        previous_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(previous_loop)
        setup_error = RuntimeError("primary setup failure")
        cleanup_cancel = asyncio.CancelledError("cleanup cancelled")
        first_client = _FakeClient(disconnect_error=RuntimeError("disconnect failed"))
        second_client = _FakeClient()
        socket = _SetupFailureSocket(
            [
                (first_client, setup_error, cleanup_cancel),
                (second_client, None, None),
            ]
        )
        first_transport = socket._transport
        try:
            with self.assertRaises(RuntimeError) as raised:
                socket.connect(("fake-printer", 0))

            self.assertIs(raised.exception, setup_error)
            self.assertEqual(first_client.disconnect_calls, 1)
            self.assertFalse(socket._connected)
            self.assertIsNone(socket._client)
            self.assertIsNone(socket._loop)
            self.assertIsNot(socket._transport, first_transport)
            self.assertTrue(socket.setup_loops[0].is_closed())
            self.assertIs(asyncio.get_event_loop(), previous_loop)

            socket.connect(("fake-printer", 0))

            self.assertTrue(socket._connected)
            self.assertIs(socket._client, second_client)
            reconnect_loop = socket._loop
            if reconnect_loop is None:
                self.fail("reconnect did not retain its private event loop")
            self.assertFalse(reconnect_loop.is_closed())
            self.assertIs(asyncio.get_event_loop(), previous_loop)
            socket.close()
            self.assertEqual(second_client.disconnect_calls, 1)
        finally:
            if socket._loop is not None:
                socket.close()
            asyncio.set_event_loop(None)
            previous_loop.close()

    def test_connect_cancellation_is_preserved_over_cleanup_failure(self) -> None:
        previous_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(previous_loop)
        setup_cancel = asyncio.CancelledError("setup cancelled")
        cleanup_error = RuntimeError("runtime stop failed")
        client = _FakeClient(
            disconnect_error=asyncio.CancelledError("disconnect cancelled")
        )
        socket = _SetupFailureSocket([(client, setup_cancel, cleanup_error)])
        try:
            with self.assertRaises(asyncio.CancelledError) as raised:
                socket.connect(("fake-printer", 0))

            self.assertIs(raised.exception, setup_cancel)
            self.assertEqual(client.disconnect_calls, 1)
            self.assertFalse(socket._connected)
            self.assertIsNone(socket._client)
            self.assertIsNone(socket._loop)
            self.assertTrue(socket.setup_loops[0].is_closed())
            self.assertIs(asyncio.get_event_loop(), previous_loop)
        finally:
            if socket._loop is not None:
                socket.close()
            asyncio.set_event_loop(None)
            previous_loop.close()


if __name__ == "__main__":
    unittest.main()
