from __future__ import annotations

import asyncio
import sys
import time
import unittest
from types import ModuleType
from typing import Any
from unittest.mock import patch

from catlabel.devices import BleTransportProfile
from catlabel.transport.bluetooth.adapters.bleak_adapter import _BleakSocket
from catlabel.transport.bluetooth.adapters.bleak_adapter_transport import (
    _BleakTransportSession,
)
from catlabel.transport.bluetooth.bleak_lifecycle import _BleakLifecycle

NOTIFY = "0000ffe2-0000-1000-8000-00805f9b34fb"
CONTROL = "0000ffe3-0000-1000-8000-00805f9b34fb"


class _Characteristic:
    def __init__(self, uuid: str, properties: list[str]) -> None:
        self.uuid = uuid
        self.properties = properties
        self.max_write_without_response_size = 20


class _Service:
    uuid = "0000ffe0-0000-1000-8000-00805f9b34fb"
    characteristics = [
        _Characteristic("0000ffe1-0000-1000-8000-00805f9b34fb", ["write"]),
        _Characteristic(NOTIFY, ["notify"]),
        _Characteristic(CONTROL, ["notify"]),
    ]


class _Client:
    services = [_Service()]
    mtu_size = 23

    def __init__(self, stage: str = "") -> None:
        self.stage = stage
        self.disconnect_calls = 0
        self.start_calls: list[str] = []
        self.stop_calls: list[str] = []
        self.disconnect_error: BaseException | None = None
        self.stop_errors: dict[str, BaseException] = {}
        self.release = asyncio.Event()
        self.cancelled = False

    async def stall(self, stage: str) -> None:
        if self.stage == stage:
            await asyncio.sleep(1)
        if self.stage == f"resistant-{stage}":
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                await self.release.wait()

    async def connect(self) -> None:
        await self.stall("connect")

    async def pair(self) -> None:
        await self.stall("pair")

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        await self.stall("disconnect")
        if self.disconnect_error is not None:
            raise self.disconnect_error

    async def start_notify(self, endpoint: _Characteristic, _callback: Any) -> None:
        uuid = endpoint.uuid
        self.start_calls.append(uuid)
        await self.stall("subscribe")
        if self.stage == "failed-subscribe" and uuid == CONTROL:
            raise RuntimeError("subscribe failed")

    async def stop_notify(self, endpoint: _Characteristic) -> None:
        uuid = endpoint.uuid
        self.stop_calls.append(uuid)
        if uuid in self.stop_errors:
            raise self.stop_errors[uuid]


class _StageSocket(_BleakSocket):
    def __init__(self, client: _Client) -> None:
        super().__init__(
            pairing_hint=True,
            ble_profile=BleTransportProfile(
                notify_char_uuid=NOTIFY, control_notify_char_uuid=CONTROL
            ),
        )
        self.fake = client
        self._pairing_hint = True
        self._timeout = 0.01
        self._cleanup_timeout = 0.025

    async def _resolve_client_target(self, address: str) -> str:
        await self.fake.stall("resolve")
        return address

    async def _find_write_characteristic(self):
        await self.fake.stall("endpoints")
        return await super()._find_write_characteristic()

    async def _acquire_bluez_mtu_payload(self) -> int | None:
        await self.fake.stall("mtu")
        return None


class _LateConnectClient(_Client):
    def __init__(self, final_disconnect: str = "") -> None:
        super().__init__("resistant-connect")
        self.final_disconnect = final_disconnect
        self.is_connected = False
        self.events: list[str] = []
        self.owner: _BleakSocket | None = None
        self.owned_during_disconnect: list[bool] = []

    async def connect(self) -> None:
        await super().connect()
        self.is_connected = True
        self.events.append("connected")

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.events.append(f"disconnect:{self.disconnect_calls}")
        owner = self.owner
        self.owned_during_disconnect.append(
            owner is not None
            and owner._client is self
            and owner._loop is not None
            and not owner._loop.is_closed()
        )
        if self.disconnect_calls == 2:
            if self.final_disconnect == "error":
                raise RuntimeError("final disconnect failed")
            if self.final_disconnect == "timeout":
                await asyncio.Event().wait()
        self.is_connected = False
        if self.disconnect_calls == 1:
            self.release.set()


def _bleak(client: _Client) -> ModuleType:
    module = ModuleType("bleak")
    module.__dict__["BleakClient"] = lambda _target: client
    return module


class BleSetupDeadlineTests(unittest.TestCase):
    def test_late_connect_settling_during_cleanup_gets_final_disconnect(self) -> None:
        client = _LateConnectClient()
        socket = _StageSocket(client)
        client.owner = socket
        with (
            patch.dict(sys.modules, {"bleak": _bleak(client)}),
            self.assertRaises(TimeoutError),
        ):
            socket.connect(("fake", 0))
        self.assertEqual(client.events, ["disconnect:1", "connected", "disconnect:2"])
        self.assertEqual(client.owned_during_disconnect, [True, True])
        self.assertFalse(client.is_connected)
        self.assertFalse(socket._connected)
        self.assertIsNone(socket._client)
        self.assertIsNone(socket._loop)

    def test_failed_final_disconnect_retains_late_connection_for_retry(self) -> None:
        for failure in ("error", "timeout"):
            with self.subTest(failure=failure):
                client = _LateConnectClient(failure)
                socket = _StageSocket(client)
                client.owner = socket
                transport = socket._transport
                try:
                    with (
                        patch.dict(sys.modules, {"bleak": _bleak(client)}),
                        self.assertRaises(TimeoutError),
                    ):
                        socket.connect(("fake", 0))
                    loop = socket._loop
                    self.assertEqual(
                        client.events, ["disconnect:1", "connected", "disconnect:2"]
                    )
                    self.assertTrue(client.is_connected)
                    self.assertFalse(socket._physical_disconnected)
                    self.assertFalse(socket._connected)
                    self.assertIs(socket._client, client)
                    self.assertIs(socket._transport, transport)
                    self.assertIsNotNone(loop)
                    assert loop is not None
                    self.assertFalse(loop.is_closed())
                    client.final_disconnect = ""
                    socket.close()
                    self.assertFalse(client.is_connected)
                    self.assertEqual(client.disconnect_calls, 3)
                    self.assertEqual(client.owned_during_disconnect, [True, True, True])
                    self.assertIsNone(socket._client)
                    self.assertIsNone(socket._loop)
                    self.assertTrue(loop.is_closed())
                finally:
                    client.final_disconnect = ""
                    socket.close()

    def test_entire_setup_is_bounded_at_each_stage(self) -> None:
        for stage in (
            "resolve",
            "connect",
            "pair",
            "endpoints",
            "mtu",
            "subscribe",
            "initialize",
        ):
            with self.subTest(stage=stage):
                client = _Client(stage)
                socket = _StageSocket(client)
                original_initialize = _BleakTransportSession.initialize_connection

                async def initialize(
                    session: _BleakTransportSession,
                    *args,
                    client=client,
                    original_initialize=original_initialize,
                    **kwargs,
                ):
                    await client.stall("initialize")
                    await original_initialize(session, *args, **kwargs)

                started = time.monotonic()
                with (
                    patch.dict(sys.modules, {"bleak": _bleak(client)}),
                    patch.object(
                        _BleakTransportSession, "initialize_connection", initialize
                    ),
                    self.assertRaises(TimeoutError),
                ):
                    socket.connect(("fake", 0))
                self.assertLess(time.monotonic() - started, 0.3)
                self.assertFalse(socket._connected)
                self.assertIsNone(socket._client)
                self.assertIsNone(socket._loop)
                self.assertEqual(client.disconnect_calls, int(stage != "resolve"))
                self.assertFalse(socket._lifecycle.tasks)

    def test_successful_setup_preserves_endpoints_and_mtu(self) -> None:
        client = _Client()
        socket = _StageSocket(client)
        with patch.dict(sys.modules, {"bleak": _bleak(client)}):
            socket.connect(("fake", 0))
        self.assertTrue(socket._connected)
        self.assertEqual(socket._mtu_size, 20)
        self.assertEqual(client.start_calls, [NOTIFY, CONTROL])
        socket.close()
        socket.close()
        self.assertEqual(client.disconnect_calls, 1)
        with self.assertRaisesRegex(RuntimeError, "Not connected"):
            socket.send(b"late send")

    def test_cancellation_resistant_setup_retains_ownership_until_retry(self) -> None:
        client = _Client("resistant-connect")
        socket = _StageSocket(client)
        transport = socket._transport
        with (
            patch.dict(sys.modules, {"bleak": _bleak(client)}),
            self.assertRaises(TimeoutError),
        ):
            socket.connect(("fake", 0))
        loop = socket._loop
        assert loop is not None
        self.assertTrue(client.cancelled)
        self.assertIs(socket._client, client)
        self.assertIs(socket._transport, transport)
        self.assertFalse(loop.is_closed())
        self.assertTrue(any(not task.done() for task in socket._lifecycle.tasks))
        self.assertFalse(socket._connected)
        with self.assertRaisesRegex(RuntimeError, "Not connected"):
            socket.send(b"late send")
        with self.assertRaises(TimeoutError):
            socket.connect(("replacement", 0))
        self.assertIs(socket._loop, loop)
        self.assertIs(socket._client, client)
        client.release.set()
        socket.close()
        self.assertIsNone(socket._client)
        self.assertIsNone(socket._loop)
        self.assertTrue(loop.is_closed())
        self.assertFalse(socket._connected)

    def test_failed_subscription_rollback_keeps_retry_tracking(self) -> None:
        client = _Client("failed-subscribe")
        client.stop_errors[NOTIFY] = RuntimeError("unsubscribe failed")
        client.disconnect_error = RuntimeError("disconnect failed")
        socket = _StageSocket(client)
        transport = socket._transport
        with (
            patch.dict(sys.modules, {"bleak": _bleak(client)}),
            self.assertRaisesRegex(RuntimeError, "subscribe failed") as raised,
        ):
            socket.connect(("fake", 0))
        self.assertIsNotNone(raised.exception.__cause__)
        self.assertEqual(transport._started_notify_uuids, [NOTIFY])
        self.assertIs(socket._client, client)
        client.stop_errors.clear()
        client.disconnect_error = None
        socket.close()
        self.assertEqual(transport._started_notify_uuids, [])
        self.assertIsNone(socket._loop)


class BleCleanupDeadlineTests(unittest.TestCase):
    def attach(self, client: _Client) -> _BleakSocket:
        socket = _BleakSocket()
        socket._cleanup_timeout = 0.025
        socket._loop = asyncio.new_event_loop()
        socket._client = client
        socket._connected = True
        return socket

    def test_disconnect_timeout_retains_resources_then_retries(self) -> None:
        for stage in ("disconnect", "resistant-disconnect"):
            with self.subTest(stage=stage):
                client = _Client(stage)
                socket = self.attach(client)
                loop = socket._loop
                transport = socket._transport
                assert loop is not None
                with self.assertRaises(TimeoutError):
                    socket.close()
                self.assertIs(socket._client, client)
                self.assertIs(socket._loop, loop)
                self.assertIs(socket._transport, transport)
                self.assertFalse(loop.is_closed())
                self.assertFalse(socket._connected)
                if stage == "resistant-disconnect":
                    self.assertTrue(
                        any(not task.done() for task in socket._lifecycle.tasks)
                    )
                    client.release.set()
                else:
                    client.stage = ""
                socket.close()
                self.assertIsNone(socket._client)
                self.assertTrue(loop.is_closed())

    def test_runtime_stop_failure_releases_resources_after_disconnect(self) -> None:
        client = _Client()
        socket = self.attach(client)
        loop = socket._loop
        error = RuntimeError("stop failed")

        class Controller:
            async def stop(self, _session: Any) -> None:
                raise error

        socket._transport._runtime_controller = Controller()
        with self.assertRaises(RuntimeError) as raised:
            socket.close()
        self.assertIs(raised.exception, error)
        self.assertEqual(client.disconnect_calls, 1)
        self.assertIsNone(socket._client)
        assert loop is not None
        self.assertTrue(loop.is_closed())

    def test_unsubscribe_retries_only_failed_entries(self) -> None:
        client = _Client()
        client.stop_errors[NOTIFY] = RuntimeError("unsubscribe failed")
        client.disconnect_error = RuntimeError("disconnect failed")
        socket = self.attach(client)
        transport = socket._transport
        transport._started_notify_endpoints = list(_Service.characteristics[1:])
        with self.assertRaisesRegex(RuntimeError, "unsubscribe failed"):
            socket.close()
        self.assertEqual(client.stop_calls, [NOTIFY, CONTROL])
        self.assertEqual(transport._started_notify_uuids, [NOTIFY])
        client.stop_errors.clear()
        client.disconnect_error = None
        socket.close()
        self.assertEqual(client.stop_calls, [NOTIFY, CONTROL, NOTIFY])
        self.assertEqual(transport._started_notify_uuids, [])

    def test_resistant_runtime_stop_cannot_prevent_physical_disconnect(self) -> None:
        client = _Client("resistant-stop")
        socket = self.attach(client)
        loop = socket._loop
        transport = socket._transport

        class Controller:
            async def stop(self, _session: Any) -> None:
                await client.stall("stop")

        transport._runtime_controller = Controller()
        transport._started_notify_endpoints = list(_Service.characteristics[1:])
        with self.assertRaises(TimeoutError):
            socket.close()
        self.assertEqual(client.disconnect_calls, 1)
        self.assertEqual(client.stop_calls, [NOTIFY, CONTROL])
        self.assertIs(socket._transport, transport)
        self.assertIs(socket._client, client)
        self.assertTrue(any(not task.done() for task in socket._lifecycle.tasks))
        client.release.set()
        socket.close()
        self.assertIsNone(socket._client)
        assert loop is not None
        self.assertTrue(loop.is_closed())


class BleAsyncOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_deadline_cancels_before_operation_runs(self) -> None:
        lifecycle = _BleakLifecycle()
        called = False

        async def operation() -> None:
            nonlocal called
            called = True

        with self.assertRaises(TimeoutError):
            await lifecycle.run(
                "already-expired",
                operation,
                deadline=asyncio.get_running_loop().time() - 0.01,
            )
        await asyncio.sleep(0)
        self.assertFalse(called)
        self.assertFalse(lifecycle.pending())

    async def test_operation_finishing_after_absolute_deadline_is_not_success(
        self,
    ) -> None:
        lifecycle = _BleakLifecycle()
        loop = asyncio.get_running_loop()
        now = [loop.time()]
        deadline = now[0] + 0.01

        async def operation() -> str:
            now[0] = deadline + 0.001
            return "too late"

        with (
            patch.object(loop, "time", lambda: now[0]),
            self.assertRaises(TimeoutError),
        ):
            await lifecycle.run("overrun", operation, deadline=deadline)
        self.assertFalse(lifecycle.pending())

    async def test_owned_expired_operation_is_reaped_after_eventual_exception(
        self,
    ) -> None:
        lifecycle = _BleakLifecycle()
        release = asyncio.Event()

        async def operation() -> None:
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            raise RuntimeError("late failure")

        with self.assertRaises(TimeoutError):
            await lifecycle.run(
                "resistant",
                operation,
                deadline=asyncio.get_running_loop().time() + 0.005,
            )
        self.assertEqual(len(lifecycle.tasks), 1)
        release.set()
        self.assertTrue(
            await lifecycle.quiesce(deadline=asyncio.get_running_loop().time() + 0.02)
        )
        await asyncio.sleep(0)
        self.assertFalse(lifecycle.tasks)

    async def test_caller_cancellation_still_attempts_physical_disconnect(self) -> None:
        client = _Client()
        socket = _BleakSocket()
        socket._client = client
        socket._connected = True
        socket._cleanup_timeout = 0.025
        entered = asyncio.Event()
        release = asyncio.Event()

        class Controller:
            async def stop(self, _session: Any) -> None:
                entered.set()
                await release.wait()

        socket._transport._runtime_controller = Controller()
        socket._transport._started_notify_endpoints = list(_Service.characteristics[1:])
        cleanup = asyncio.create_task(socket._safe_disconnect_async())
        await entered.wait()
        cleanup.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cleanup
        self.assertEqual(client.disconnect_calls, 1)
        self.assertEqual(client.stop_calls, [NOTIFY, CONTROL])
        self.assertFalse(socket._connected)
        self.assertFalse(socket._lifecycle.pending())
        self.assertTrue(socket._physical_disconnected)

    async def test_unsubscribe_cancellation_attempts_every_subscription_and_retains_failure(
        self,
    ) -> None:
        client = _Client()
        client.stop_errors[NOTIFY] = asyncio.CancelledError("unsubscribe cancelled")
        socket = _BleakSocket()
        session = socket._transport
        session._started_notify_endpoints = list(_Service.characteristics[1:])
        with self.assertRaises(asyncio.CancelledError):
            await session.stop_notify_if_started(client)
        self.assertEqual(client.stop_calls, [NOTIFY, CONTROL])
        self.assertEqual(session._started_notify_uuids, [NOTIFY])
        client.stop_errors.clear()
        await session.stop_notify_if_started(client)
        self.assertEqual(client.stop_calls, [NOTIFY, CONTROL, NOTIFY])
        self.assertEqual(session._started_notify_uuids, [])


if __name__ == "__main__":
    unittest.main()
