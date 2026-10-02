from __future__ import annotations

import asyncio
import socket
import threading
import unittest
from collections.abc import Callable
from contextlib import asynccontextmanager
from unittest.mock import patch

from catlabel.printing.runtime.base import RuntimeController, RuntimeSessionApi
from catlabel.printing.runtime.tiny import TinyRuntimeController
from catlabel.printing.runtime.yk_astra_p1 import AstraP1RuntimeController
from catlabel.protocol.families.yk_common import pack_yk_frame
from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.packet import make_packet
from catlabel.transport.bluetooth import SppBackend
from catlabel.transport.bluetooth import backend as backend_module
from catlabel.transport.bluetooth.types import DeviceInfo, DeviceTransport
from catlabel.vendors.generic.client import _GenericBackendConnection
from tests.test_classic_backend_receive import _ClassicAdapter, _NativePairSocket


class _Backend(SppBackend):
    def __init__(self, *, passive: bool = True) -> None:
        super().__init__()
        self.passive = passive
        self.callback: Callable[[bytes], None] | None = None
        self.flow: list[tuple[bool, bytes]] = []
        self.attach_calls: list[object] = []

    def can_receive_passively(self) -> bool:
        return self.passive

    def register_notify_callback(self, callback) -> None:
        self.callback = callback

    def set_flow_paused(self, paused: bool, *, payload: bytes = b"") -> None:
        self.flow.append((paused, payload))

    async def attach_runtime_controller(
        self, runtime_controller, *, timeout=1.0
    ) -> None:
        self.attach_calls.append(runtime_controller)


class _Controller(RuntimeController):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.initialized = 0
        self.stopped = 0
        self.previous: RuntimeController | None = None
        self.notifications: list[tuple[bytes, int, asyncio.AbstractEventLoop]] = []

    def adopt_previous(self, previous: RuntimeController | None) -> None:
        self.previous = previous

    async def initialize_connection(
        self, session: RuntimeSessionApi, *, mtu_size: int, timeout: float
    ) -> None:
        self.initialized += 1
        if self.fail:
            raise RuntimeError("initialization failed")

    async def stop(self, session: RuntimeSessionApi) -> None:
        self.stopped += 1

    def handle_notification(self, session: RuntimeSessionApi, payload: bytes) -> None:
        self.notifications.append(
            (payload, threading.get_ident(), asyncio.get_running_loop())
        )


class GenericClassicRuntimeTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def native_connection(self):
        endpoint, peer = socket.socketpair()
        native = _NativePairSocket(endpoint)
        backend = SppBackend()
        connection = _GenericBackendConnection(backend, chunk_size=5, delay_ms=0)
        from catlabel.devices import get_ble_transport_profile

        device = DeviceInfo(
            name="Socketpair Tiny",
            address="00:11:22:33:44:55",
            transport=DeviceTransport.CLASSIC,
            ble_profile=get_ble_transport_profile(ProtocolFamily.LEGACY),
        )
        try:
            with patch.object(
                backend_module,
                "_get_classic_adapter",
                return_value=_ClassicAdapter(lambda: native),
            ):
                await backend.connect(device)
            yield backend, connection, peer
        finally:
            await connection.stop_runtime_controller()
            await backend.disconnect()
            backend._executor.shutdown(wait=True)
            peer.close()

    async def test_tiny_actual_classic_reader_gates_and_resumes_writes(self) -> None:
        async with self.native_connection() as (backend, connection, peer):
            await connection.attach_runtime_controller(TinyRuntimeController())
            pause = bytes.fromhex("5178AE0101001070FF")
            peer.sendall(pause[:4])
            peer.sendall(pause[4:])
            deadline = asyncio.get_running_loop().time() + 1.0
            while backend._flow_resume_event.is_set():
                self.assertLess(asyncio.get_running_loop().time(), deadline)
                await asyncio.sleep(0.005)
            write = asyncio.create_task(connection.send_standard_payload(b"abcdefghij"))
            peer.settimeout(0.03)
            try:
                with self.assertRaises(TimeoutError):
                    await asyncio.to_thread(peer.recv, 10)
                peer.sendall(bytes.fromhex("5178AE0101000000FF"))
                await asyncio.wait_for(write, 1.0)
                peer.settimeout(1.0)
                received = bytearray()
                while len(received) < 10:
                    received.extend(
                        await asyncio.to_thread(peer.recv, 10 - len(received))
                    )
                self.assertEqual(received, b"abcdefghij")
            finally:
                if not write.done():
                    write.cancel()
                await asyncio.gather(write, return_exceptions=True)

    async def test_s001_actual_classic_history_cannot_finish_later_job(self) -> None:
        async with self.native_connection() as (_backend, connection, peer):
            controller = AstraP1RuntimeController()
            await connection.attach_runtime_controller(controller)
            session = connection._session
            assert session is not None
            printing = pack_yk_frame(0x81, bytes.fromhex("0000080009000264"))
            idle = pack_yk_frame(0x81, bytes.fromhex("0000000009000264"))
            await connection.send_standard_payload(b"job1")
            peer.sendall(printing + idle)
            deadline = asyncio.get_running_loop().time() + 1.0
            while not controller.debug_snapshot()["finished"]:
                self.assertLess(asyncio.get_running_loop().time(), deadline)
                await asyncio.sleep(0.005)
            await controller.wait_for_completion(session, timeout=0.1)
            await connection.send_standard_payload(b"job2")
            completion = asyncio.create_task(
                controller.wait_for_completion(session, timeout=0.1)
            )
            try:
                await asyncio.sleep(0.01)
                self.assertFalse(completion.done())
                peer.sendall(idle)
                await asyncio.sleep(0.01)
                self.assertFalse(completion.done())
                peer.sendall(printing[:8])
                peer.sendall(printing[8:] + idle)
                await asyncio.wait_for(completion, 1.0)
                self.assertEqual(controller.debug_snapshot()["completion_count"], 2)
            finally:
                if not completion.done():
                    completion.cancel()
                await asyncio.gather(completion, return_exceptions=True)

    async def test_reader_callback_runs_on_owning_loop_before_returning(self) -> None:
        backend = _Backend()
        connection = _GenericBackendConnection(backend, chunk_size=64, delay_ms=0)
        controller = _Controller()
        await connection.attach_runtime_controller(controller)
        callback = backend.callback
        assert callback is not None
        await asyncio.to_thread(callback, b"reply")
        self.assertEqual(
            controller.notifications,
            [(b"reply", threading.get_ident(), asyncio.get_running_loop())],
        )
        await connection.stop_runtime_controller()

    async def test_same_controller_initializes_once_and_replacement_adopts(
        self,
    ) -> None:
        backend = _Backend()
        connection = _GenericBackendConnection(backend, chunk_size=64, delay_ms=0)
        first, second = _Controller(), _Controller()
        await connection.attach_runtime_controller(first)
        await connection.attach_runtime_controller(first)
        await connection.attach_runtime_controller(second)
        self.assertEqual(first.initialized, 1)
        self.assertIs(second.previous, first)
        self.assertEqual(second.initialized, 1)
        await connection.stop_runtime_controller()
        await connection.stop_runtime_controller()
        self.assertEqual(second.stopped, 1)
        self.assertIsNone(backend.callback)

    async def test_failure_removes_callback_and_stops_runtime(self) -> None:
        backend = _Backend()
        connection = _GenericBackendConnection(backend, chunk_size=64, delay_ms=0)
        controller = _Controller(fail=True)
        with self.assertRaisesRegex(RuntimeError, "initialization failed"):
            await connection.attach_runtime_controller(controller)
        self.assertIsNone(backend.callback)
        self.assertEqual(controller.stopped, 1)

    async def test_platform_transport_retains_attachment_ownership(self) -> None:
        backend = _Backend(passive=False)
        connection = _GenericBackendConnection(backend, chunk_size=64, delay_ms=0)
        controller = _Controller()
        await connection.attach_runtime_controller(controller)
        self.assertEqual(backend.attach_calls, [controller])
        self.assertEqual(controller.initialized, 0)
        self.assertIsNone(backend.callback)

    async def test_tiny_fragmented_pause_is_visible_when_callback_returns(self) -> None:
        backend = _Backend()
        connection = _GenericBackendConnection(backend, chunk_size=64, delay_ms=0)
        await connection.attach_runtime_controller(TinyRuntimeController())
        callback = backend.callback
        assert callback is not None
        command = make_packet(0xAE, b"\x10", ProtocolFamily.LEGACY)
        packet = command[:3] + b"\x01" + command[4:]
        await asyncio.to_thread(callback, packet[:3])
        self.assertEqual(backend.flow, [])
        await asyncio.to_thread(callback, packet[3:])
        self.assertEqual(backend.flow, [(True, packet)])
        await connection.stop_runtime_controller()
        self.assertEqual(backend.flow[-1], (False, b""))


if __name__ == "__main__":
    unittest.main()
