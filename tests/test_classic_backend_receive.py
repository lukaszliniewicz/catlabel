from __future__ import annotations

import asyncio
import socket
import threading
import time
import unittest
from collections.abc import Callable
from contextlib import suppress
from unittest.mock import patch

from catlabel import reporting
from catlabel.devices import BleTransportProfile
from catlabel.transport.bluetooth import backend as backend_module
from catlabel.transport.bluetooth.backend import SppBackend
from catlabel.transport.bluetooth.classic_receive import ClassicReceiveHub
from catlabel.transport.bluetooth.types import DeviceInfo, DeviceTransport


class _NativePairSocket(socket.socket):
    def __init__(self, source: socket.socket) -> None:
        super().__init__(
            family=source.family,
            type=source.type,
            proto=source.proto,
            fileno=source.detach(),
        )

    def connect(self, address: object) -> None:
        _ = address


class _ClassicAdapter:
    def __init__(
        self,
        create_socket: Callable[[], object],
        channels: list[int] | None = None,
    ) -> None:
        self.create_socket_factory = create_socket
        self.channels = channels or [1]
        self.created: list[object] = []

    def ensure_paired(self, address: str, pairing_hint: bool | None) -> None:
        _ = address, pairing_hint

    def resolve_rfcomm_channels(self, address: str) -> list[int]:
        _ = address
        return list(self.channels)

    def create_socket(
        self,
        pairing_hint: bool | None,
        *,
        ble_profile: BleTransportProfile | None = None,
        reporter: reporting.Reporter | None = None,
    ) -> object:
        _ = pairing_hint, ble_profile, reporter
        sock = self.create_socket_factory()
        self.created.append(sock)
        return sock


class _CustomPairSocket:
    """A non-native Classic wrapper used to guard the direct-receive fallback."""

    def __init__(self, source: socket.socket) -> None:
        self.source = source
        self.call_threads: list[int] = []

    def _record(self) -> None:
        self.call_threads.append(threading.get_ident())

    def settimeout(self, value: float | None) -> None:
        self._record()
        self.source.settimeout(value)

    def gettimeout(self) -> float | None:
        self._record()
        return self.source.gettimeout()

    def connect(self, address: object) -> None:
        _ = address
        self._record()

    def sendall(self, data: bytes) -> None:
        self._record()
        self.source.sendall(data)

    def recv(self, size: int) -> bytes:
        self._record()
        return self.source.recv(size)

    def close(self) -> None:
        self._record()
        self.source.close()


class ClassicBackendReceiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.backends: list[SppBackend] = []
        self.peers: list[socket.socket] = []
        self.sockets: list[object] = []

    async def asyncTearDown(self) -> None:
        for backend in reversed(self.backends):
            with suppress(Exception):
                await backend.disconnect()
            backend._executor.shutdown(wait=True)
        for peer in self.peers:
            with suppress(OSError):
                peer.close()

    def _native_socket_factory(self) -> _NativePairSocket:
        endpoint, peer = socket.socketpair()
        self.peers.append(peer)
        sock = _NativePairSocket(endpoint)
        self.sockets.append(sock)
        return sock

    def _custom_socket_factory(self) -> _CustomPairSocket:
        endpoint, peer = socket.socketpair()
        self.peers.append(peer)
        sock = _CustomPairSocket(endpoint)
        self.sockets.append(sock)
        return sock

    async def _connect(
        self,
        adapter: _ClassicAdapter,
        *,
        backend: SppBackend | None = None,
        profile: BleTransportProfile | None = None,
    ) -> SppBackend:
        target = backend or SppBackend(reporting.DUMMY_REPORTER)
        if target not in self.backends:
            self.backends.append(target)
        device = DeviceInfo(
            name="Socket pair printer",
            address="00:11:22:33:44:55",
            transport=DeviceTransport.CLASSIC,
            ble_profile=profile,
        )
        with patch.object(backend_module, "_get_classic_adapter", return_value=adapter):
            await target.connect(device)
        return target

    async def _wait_event(self, event: threading.Event) -> None:
        self.assertTrue(await asyncio.to_thread(event.wait, 2.0))

    async def _wait_hub_failure(self, backend: SppBackend) -> None:
        hub = backend._classic_receive
        assert hub is not None
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                hub.ensure_healthy()
            except RuntimeError:
                return
            await asyncio.sleep(0.005)
        self.fail("Classic receive hub did not report its reader failure")

    async def test_native_query_arms_before_send_collects_fragments_and_ignores_stale(
        self,
    ) -> None:
        backend = await self._connect(_ClassicAdapter(self._native_socket_factory))
        peer = self.peers[-1]
        sock = backend._sock
        assert isinstance(sock, _NativePairSocket)
        self.assertTrue(backend.can_receive_passively())
        self.assertEqual(sock.gettimeout(), 8.0)

        notifications: list[bytes] = []
        stale_seen = threading.Event()

        def notify(payload: bytes) -> None:
            notifications.append(payload)
            if b"stale" in payload:
                stale_seen.set()

        backend.register_notify_callback(notify)
        peer.sendall(b"stale")
        await self._wait_event(stale_seen)

        first_fragment = threading.Event()
        second_fragment = threading.Event()

        def answer() -> None:
            self.assertEqual(peer.recv(4), b"ask!")
            peer.sendall(b"reply-")
            first_fragment.set()
            if second_fragment.wait(2.0):
                peer.sendall(b"done")

        responder = threading.Thread(target=answer, daemon=True)
        responder.start()
        predicate_inputs: list[bytes] = []

        def complete(payload: bytes) -> bool:
            predicate_inputs.append(payload)
            return payload.endswith(b"done")

        query = asyncio.create_task(
            backend.query_control_packet(b"ask!", timeout=1.0, reply_complete=complete)
        )
        await self._wait_event(first_fragment)
        self.assertFalse(query.done())
        second_fragment.set()
        result = await query
        responder.join(timeout=1.0)

        self.assertEqual(result, b"reply-done")
        self.assertTrue(predicate_inputs)
        self.assertTrue(all(b"stale" not in item for item in predicate_inputs))
        self.assertEqual(sock.gettimeout(), 8.0)
        self.assertEqual(b"".join(notifications), b"stalereply-done")

    async def test_native_atomic_query_catches_immediate_fragmented_reply(self) -> None:
        backend = await self._connect(_ClassicAdapter(self._native_socket_factory))
        peer = self.peers[-1]
        first_fragment = threading.Event()
        second_fragment = threading.Event()

        def answer() -> None:
            self.assertEqual(peer.recv(5), b"state")
            peer.sendall(b"sta")
            first_fragment.set()
            if second_fragment.wait(2.0):
                peer.sendall(b"tus-ok")

        responder = threading.Thread(target=answer, daemon=True)
        responder.start()
        query = asyncio.create_task(
            backend.send_control_packet_wait_notification(
                b"state",
                label="state response",
                match=lambda payload: payload.endswith(b"status-ok"),
                timeout=1.0,
            )
        )
        await self._wait_event(first_fragment)
        self.assertFalse(query.done())
        second_fragment.set()
        result = await query
        responder.join(timeout=1.0)
        self.assertEqual(result, b"status-ok")

    async def test_passive_callback_runs_before_waiter_match(self) -> None:
        backend = await self._connect(_ClassicAdapter(self._native_socket_factory))
        peer = self.peers[-1]
        notifications: list[bytes] = []
        callback_ran = threading.Event()

        def notify(payload: bytes) -> None:
            notifications.append(payload)
            callback_ran.set()

        backend.register_notify_callback(notify)
        match_observations: list[tuple[bytes, bool]] = []

        def match(payload: bytes) -> bool:
            match_observations.append((payload, callback_ran.is_set()))
            return payload.endswith(b"alert")

        wait = asyncio.create_task(
            backend.wait_for_notification("alert", match, timeout=1.0)
        )
        await asyncio.sleep(0.01)
        peer.sendall(b"alert")
        self.assertEqual(await wait, b"alert")
        self.assertEqual(notifications, [b"alert"])
        self.assertTrue(match_observations)
        self.assertTrue(
            all(callback_had_run for _, callback_had_run in match_observations)
        )
        backend.register_notify_callback(None)
        second_wait = asyncio.create_task(
            backend.wait_for_notification(
                "second alert",
                lambda payload: payload.endswith(b"again"),
                timeout=1.0,
            )
        )
        await asyncio.sleep(0.01)
        peer.sendall(b"again")
        self.assertEqual(await second_wait, b"again")
        self.assertEqual(notifications, [b"alert"])

    async def test_unmatched_query_returns_partial_bytes_and_passive_timeout_policy(
        self,
    ) -> None:
        backend = await self._connect(_ClassicAdapter(self._native_socket_factory))
        peer = self.peers[-1]

        def answer() -> None:
            self.assertEqual(peer.recv(3), b"get")
            peer.sendall(b"partial")

        responder = threading.Thread(target=answer, daemon=True)
        responder.start()
        started = time.monotonic()
        partial = await backend.query_control_packet(
            b"get", timeout=0.08, reply_complete=None
        )
        elapsed = time.monotonic() - started
        responder.join(timeout=1.0)
        self.assertEqual(partial, b"partial")
        self.assertGreaterEqual(elapsed, 0.06)

        self.assertIsNone(
            await backend.wait_for_notification(
                "optional alert",
                lambda payload: payload.endswith(b"never"),
                timeout=0.01,
                required=False,
            )
        )
        with self.assertRaisesRegex(TimeoutError, "required alert"):
            await backend.wait_for_notification(
                "required alert",
                lambda payload: payload.endswith(b"never"),
                timeout=0.01,
                required=True,
            )

    async def test_atomic_unmatched_timeout_is_optional_or_labeled_required(
        self,
    ) -> None:
        backend = await self._connect(_ClassicAdapter(self._native_socket_factory))
        peer = self.peers[-1]

        def drain_two_requests() -> None:
            self.assertEqual(peer.recv(1), b"x")
            self.assertEqual(peer.recv(1), b"y")

        drainer = threading.Thread(target=drain_two_requests, daemon=True)
        drainer.start()
        self.assertIsNone(
            await backend.send_control_packet_wait_notification(
                b"x",
                label="optional result",
                match=lambda _: False,
                timeout=0.01,
                required=False,
            )
        )
        with self.assertRaisesRegex(TimeoutError, "required result"):
            await backend.send_control_packet_wait_notification(
                b"y",
                label="required result",
                match=lambda _: False,
                timeout=0.01,
                required=True,
            )
        drainer.join(timeout=1.0)

    async def test_callback_failure_poisoning_prevents_later_control_write(
        self,
    ) -> None:
        backend = await self._connect(_ClassicAdapter(self._native_socket_factory))
        peer = self.peers[-1]
        callback_called = threading.Event()

        def fail_callback(payload: bytes) -> None:
            _ = payload
            callback_called.set()
            raise ValueError("callback failed")

        backend.register_notify_callback(fail_callback)
        peer.sendall(b"trigger")
        await self._wait_event(callback_called)
        await self._wait_hub_failure(backend)
        with self.assertRaisesRegex(RuntimeError, "listener failed"):
            await backend.send_control_packet(b"must-not-send")
        peer.settimeout(0.03)
        with self.assertRaises(TimeoutError):
            peer.recv(1)

    async def test_eof_poisoning_prevents_later_control_write(self) -> None:
        backend = await self._connect(_ClassicAdapter(self._native_socket_factory))
        peer = self.peers[-1]
        peer.shutdown(socket.SHUT_WR)
        await self._wait_hub_failure(backend)
        with self.assertRaisesRegex(RuntimeError, "EOF"):
            await backend.send_control_packet(b"must-not-send")

    async def test_reader_failure_interrupts_a_paused_standard_write(self) -> None:
        backend = await self._connect(
            _ClassicAdapter(self._native_socket_factory),
            profile=BleTransportProfile(
                flow_controlled_standard_write=True,
                flow_resume_timeout_s=10.0,
            ),
        )
        peer = self.peers[-1]
        callback_called = threading.Event()

        def fail_callback(payload: bytes) -> None:
            _ = payload
            callback_called.set()
            raise ValueError("callback failed while flow paused")

        backend.register_notify_callback(fail_callback)
        backend.set_flow_paused(True)
        write = asyncio.create_task(backend.write(b"blocked", chunk_size=2))
        await asyncio.sleep(0.01)
        peer.sendall(b"trigger")
        await self._wait_event(callback_called)
        with self.assertRaisesRegex(RuntimeError, "listener failed"):
            await write

    async def test_eof_interrupts_a_paused_standard_write(self) -> None:
        backend = await self._connect(
            _ClassicAdapter(self._native_socket_factory),
            profile=BleTransportProfile(
                flow_controlled_standard_write=True,
                flow_resume_timeout_s=10.0,
            ),
        )
        peer = self.peers[-1]
        backend.set_flow_paused(True)
        write = asyncio.create_task(backend.write(b"blocked", chunk_size=2))
        await asyncio.sleep(0.01)
        peer.shutdown(socket.SHUT_WR)
        with self.assertRaisesRegex(RuntimeError, "EOF"):
            await write

    async def test_receive_history_overflow_fails_the_active_waiter(self) -> None:
        backend = await self._connect(_ClassicAdapter(self._native_socket_factory))
        peer = self.peers[-1]

        def overflow_after_request() -> None:
            self.assertEqual(peer.recv(1), b"o")
            peer.sendall(b"x" * 70_000)

        responder = threading.Thread(target=overflow_after_request, daemon=True)
        responder.start()
        with self.assertRaisesRegex(RuntimeError, "trimmed past active waiter"):
            await backend.query_control_packet(
                b"o", timeout=1.0, reply_complete=lambda _: False
            )
        responder.join(timeout=1.0)

    async def test_flow_pause_stops_between_chunks_until_receive_callback_resumes(
        self,
    ) -> None:
        profile = BleTransportProfile(
            flow_controlled_standard_write=True,
            flow_resume_timeout_s=0.5,
        )
        backend = await self._connect(
            _ClassicAdapter(self._native_socket_factory), profile=profile
        )
        peer = self.peers[-1]
        paused = threading.Event()
        resumed = threading.Event()

        def flow_callback(payload: bytes) -> None:
            if payload == b"pause":
                backend.set_flow_paused(True, payload=payload)
                paused.set()
            elif payload == b"resume":
                backend.set_flow_paused(False, payload=payload)
                resumed.set()

        backend.register_notify_callback(flow_callback)
        write = asyncio.create_task(backend.write(b"abcdef", chunk_size=2, delay_ms=20))
        self.assertEqual(await asyncio.to_thread(peer.recv, 2), b"ab")
        peer.sendall(b"pause")
        await self._wait_event(paused)
        peer.settimeout(0.04)
        with self.assertRaises(TimeoutError):
            await asyncio.to_thread(peer.recv, 2)
        peer.settimeout(None)

        peer.sendall(b"resume")
        await self._wait_event(resumed)
        self.assertEqual(await asyncio.to_thread(peer.recv, 2), b"cd")
        self.assertEqual(await asyncio.to_thread(peer.recv, 2), b"ef")
        await write

    async def test_control_packet_bypasses_flow_gate_when_worker_is_available(
        self,
    ) -> None:
        backend = await self._connect(
            _ClassicAdapter(self._native_socket_factory),
            profile=BleTransportProfile(flow_controlled_standard_write=True),
        )
        peer = self.peers[-1]
        backend.set_flow_paused(True)
        self.assertTrue(await backend.send_control_packet(b"status"))
        self.assertEqual(await asyncio.to_thread(peer.recv, 6), b"status")

    async def test_flow_timeout_and_disconnect_wake_paused_write(self) -> None:
        backend = await self._connect(
            _ClassicAdapter(self._native_socket_factory),
            profile=BleTransportProfile(
                flow_controlled_standard_write=True,
                flow_resume_timeout_s=0.03,
            ),
        )
        peer = self.peers[-1]
        backend.set_flow_paused(True)
        with self.assertRaisesRegex(TimeoutError, "flow-control resume"):
            await backend.write(b"no", chunk_size=2)
        peer.settimeout(0.02)
        with self.assertRaises(TimeoutError):
            peer.recv(1)
        peer.settimeout(None)

        backend._flow_resume_timeout_s = 10.0
        hub = backend._classic_receive
        assert hub is not None
        write = asyncio.create_task(backend.write(b"wake", chunk_size=2))
        await asyncio.sleep(0.02)
        await backend.disconnect()
        with self.assertRaisesRegex(RuntimeError, "disconnect requested"):
            await write
        self.assertFalse(backend.is_connected())
        self.assertIsNone(backend._classic_receive)
        self.assertIsNotNone(hub._thread)
        assert hub._thread is not None
        self.assertFalse(hub._thread.is_alive())

    async def test_disconnect_wakes_outstanding_query_and_reconnect_resets_state(
        self,
    ) -> None:
        adapter = _ClassicAdapter(self._native_socket_factory)
        backend = await self._connect(adapter)
        first_peer = self.peers[-1]
        hub = backend._classic_receive
        assert hub is not None
        request_seen = threading.Event()

        def read_query() -> None:
            self.assertEqual(first_peer.recv(4), b"wait")
            request_seen.set()

        responder = threading.Thread(target=read_query, daemon=True)
        responder.start()
        query = asyncio.create_task(backend.query_control_packet(b"wait", timeout=30.0))
        await self._wait_event(request_seen)
        main_thread_id = threading.get_ident()
        stop_threads: list[int] = []
        original_stop = hub.stop

        def record_stop_thread() -> None:
            stop_threads.append(threading.get_ident())
            original_stop()

        with patch.object(hub, "stop", side_effect=record_stop_thread):
            await backend.disconnect()
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            await query
        responder.join(timeout=1.0)
        self.assertTrue(stop_threads)
        self.assertNotEqual(stop_threads[0], main_thread_id)
        self.assertFalse(backend.is_connected())
        self.assertFalse(hub._thread.is_alive() if hub._thread is not None else True)

        old_hub = hub
        backend.set_flow_paused(True)
        replacement = await self._connect(
            adapter,
            backend=backend,
            profile=BleTransportProfile(flow_controlled_standard_write=True),
        )
        self.assertIs(replacement, backend)
        self.assertTrue(backend.is_connected())
        self.assertTrue(backend.can_receive_passively())
        self.assertIsNot(backend._classic_receive, old_hub)
        self.assertTrue(backend._flow_resume_event.is_set())
        self.assertFalse(backend._disconnect_requested.is_set())
        self.assertIsNone(backend._notify_callback)

    async def test_custom_classic_wrapper_keeps_direct_query_on_single_worker(
        self,
    ) -> None:
        backend = await self._connect(_ClassicAdapter(self._custom_socket_factory))
        peer = self.peers[-1]
        wrapper = backend._sock
        assert isinstance(wrapper, _CustomPairSocket)
        self.assertIsNone(backend._classic_receive)
        self.assertFalse(backend.can_receive_passively())

        def answer() -> None:
            self.assertEqual(peer.recv(4), b"read")
            peer.sendall(b"wrapped")

        responder = threading.Thread(target=answer, daemon=True)
        responder.start()
        result = await backend.query_control_packet(
            b"read",
            timeout=1.0,
            reply_complete=lambda payload: payload.endswith(b"wrapped"),
        )
        responder.join(timeout=1.0)
        self.assertEqual(result, b"wrapped")
        self.assertGreaterEqual(len(wrapper.call_threads), 5)
        self.assertEqual(len(set(wrapper.call_threads)), 1)

    async def test_failed_hub_start_rolls_back_socket_before_next_channel(self) -> None:
        adapter = _ClassicAdapter(self._native_socket_factory, channels=[1, 2])
        original_start = ClassicReceiveHub.start
        starts = 0

        def fail_first_start(hub: ClassicReceiveHub) -> None:
            nonlocal starts
            starts += 1
            if starts == 1:
                raise OSError("selector startup failed")
            original_start(hub)

        with patch.object(ClassicReceiveHub, "start", new=fail_first_start):
            backend = await self._connect(adapter)
        self.assertTrue(backend.is_connected())
        self.assertEqual(starts, 2)
        first_sock = adapter.created[0]
        assert isinstance(first_sock, socket.socket)
        self.assertTrue(first_sock.fileno() < 0)
        self.assertIs(backend._sock, adapter.created[1])
        self.assertIsNotNone(backend._classic_receive)


if __name__ == "__main__":
    unittest.main()
