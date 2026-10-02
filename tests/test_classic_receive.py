from __future__ import annotations

import selectors
import socket
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from catlabel.transport.bluetooth.classic_receive import ClassicReceiveHub


class _FailingSelector:
    def __init__(self) -> None:
        self.closed = False

    def register(self, fileobj, events):
        return SimpleNamespace(fileobj=fileobj, events=events)

    def select(self, timeout=None):
        raise OSError("test selector failure")

    def close(self) -> None:
        self.closed = True


class _AlwaysReadableSelector:
    def __init__(self) -> None:
        self.closed = False
        self._key = None

    def register(self, fileobj, events):
        self._key = SimpleNamespace(fileobj=fileobj, events=events)
        return self._key

    def select(self, timeout=None):
        return [(self._key, selectors.EVENT_READ)]

    def close(self) -> None:
        self.closed = True


class ClassicReceiveHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reader, self.writer = socket.socketpair()
        self.addCleanup(self.writer.close)
        self.addCleanup(self.reader.close)
        self.hub: ClassicReceiveHub | None = None

    def start_hub(self, **kwargs) -> ClassicReceiveHub:
        hub = ClassicReceiveHub(self.reader, poll_timeout=0.01, **kwargs)
        self.hub = hub
        self.addCleanup(hub.stop)
        hub.start()
        return hub

    def test_requires_a_native_socket(self) -> None:
        with self.assertRaisesRegex(TypeError, "native socket.socket"):
            ClassicReceiveHub(SimpleNamespace(recv=lambda _size: b""))  # type: ignore[arg-type]

    def test_ensure_healthy_checks_lifecycle(self) -> None:
        hub = ClassicReceiveHub(self.reader, poll_timeout=0.01)
        with self.assertRaisesRegex(RuntimeError, "has not been started"):
            hub.ensure_healthy()

        hub.start()
        hub.ensure_healthy()
        hub.stop()
        with self.assertRaisesRegex(RuntimeError, "is stopped"):
            hub.ensure_healthy()

    def test_fragmented_reply_runs_listener_before_predicate(self) -> None:
        order: list[tuple[str, bytes]] = []
        listener_seen = threading.Event()

        def listener(payload: bytes) -> None:
            order.append(("listener", payload))
            listener_seen.set()

        def match(payload: bytes) -> bool:
            order.append(("predicate", payload))
            return payload.endswith(b"ABC")

        hub = self.start_hub(listener=listener)
        waiter = hub.register_waiter(hub.mark(), match)

        self.writer.sendall(b"A")
        self.assertTrue(listener_seen.wait(0.1))
        listener_seen.clear()
        self.writer.sendall(b"BC")

        self.assertEqual(hub.wait(waiter, timeout=0.1), b"ABC")
        self.assertEqual(
            [kind for kind, _ in order],
            ["listener", "predicate", "listener", "predicate"],
        )

    def test_coalesced_bytes_support_multiple_absolute_offsets(self) -> None:
        read_chunks: list[bytes] = []
        hub = self.start_hub(listener=read_chunks.append)
        start = hub.mark()
        whole = hub.register_waiter(start, lambda payload: payload.endswith(b"abcdef"))
        suffix = hub.register_waiter(
            start + 3,
            lambda payload: payload.endswith(b"def"),
        )

        self.writer.sendall(b"abcdef")

        self.assertEqual(hub.wait(whole, timeout=0.1), b"abcdef")
        self.assertEqual(hub.wait(suffix, timeout=0.1), b"def")
        self.assertEqual(b"".join(read_chunks), b"abcdef")

    def test_waiter_is_armed_before_an_immediate_reply(self) -> None:
        hub = self.start_hub()
        waiter = hub.register_waiter(hub.mark(), lambda payload: payload == b"OK")

        def reply_to_request() -> None:
            self.assertEqual(self.writer.recv(4), b"PING")
            self.writer.sendall(b"OK")

        responder = threading.Thread(target=reply_to_request, daemon=True)
        responder.start()
        self.reader.sendall(b"PING")

        self.assertEqual(hub.wait(waiter, timeout=0.1), b"OK")
        responder.join(timeout=0.1)
        self.assertFalse(responder.is_alive())

    def test_passive_waiter_advances_only_through_claimed_bytes(self) -> None:
        hub = self.start_hub()
        first = hub.register_passive_waiter(lambda payload: payload.endswith(b"A"))
        self.writer.sendall(b"A")
        self.assertEqual(hub.wait(first, timeout=0.1, claim_passive=True), b"A")

        second = hub.register_passive(lambda payload: payload.endswith(b"B"))
        self.writer.sendall(b"B")
        self.assertEqual(hub.wait(second, timeout=0.1, claim_passive=True), b"B")

    def test_timeout_returns_partial_bytes_or_none_and_claims_cursor(self) -> None:
        observed = threading.Event()
        hub = self.start_hub(listener=lambda _payload: observed.set())
        start = hub.mark()
        partial = hub.register_waiter(start, lambda _payload: False)
        self.writer.sendall(b"part")
        self.assertTrue(observed.wait(0.1))

        self.assertEqual(hub.wait(partial, timeout=0.01, claim_passive=True), b"part")
        self.assertIsNone(partial.result)

        empty = hub.register_waiter(hub.mark(), lambda _payload: False)
        self.assertIsNone(hub.wait(empty, timeout=0.01))

    def test_history_trim_fails_active_and_stale_offset_waiters(self) -> None:
        observed = threading.Event()
        hub = self.start_hub(
            max_history_bytes=4, listener=lambda _payload: observed.set()
        )
        active = hub.register_waiter(hub.mark(), lambda _payload: False)
        self.writer.sendall(b"abcdefgh")
        self.assertTrue(observed.wait(0.1))

        with self.assertRaisesRegex(RuntimeError, "trimmed past active waiter"):
            hub.wait(active, timeout=0.1)

        stale = hub.register_waiter(0, lambda _payload: False)
        with self.assertRaisesRegex(RuntimeError, "start offset was trimmed"):
            hub.wait(stale, timeout=0.1)

    def test_eof_is_propagated_to_waiter_and_health_check(self) -> None:
        hub = self.start_hub()
        waiter = hub.register_waiter(hub.mark(), lambda _payload: False)
        self.writer.shutdown(socket.SHUT_WR)

        with self.assertRaisesRegex(RuntimeError, "reached EOF"):
            hub.wait(waiter, timeout=0.1)
        with self.assertRaisesRegex(RuntimeError, "reached EOF"):
            hub.ensure_healthy()

    def test_listener_exception_is_propagated(self) -> None:
        def fail_listener(_payload: bytes) -> None:
            raise ValueError("listener exploded")

        hub = self.start_hub(listener=fail_listener)
        waiter = hub.register_waiter(hub.mark(), lambda _payload: True)
        self.writer.sendall(b"reply")

        with self.assertRaisesRegex(RuntimeError, "listener failed") as raised:
            hub.wait(waiter, timeout=0.1)
        self.assertIsInstance(raised.exception.__cause__, ValueError)

    def test_predicate_exception_is_propagated(self) -> None:
        def fail_predicate(_payload: bytes) -> bool:
            raise ValueError("predicate exploded")

        hub = self.start_hub()
        waiter = hub.register_waiter(hub.mark(), fail_predicate)
        self.writer.sendall(b"reply")

        with self.assertRaisesRegex(RuntimeError, "predicate failed") as raised:
            hub.wait(waiter, timeout=0.1)
        self.assertIsInstance(raised.exception.__cause__, ValueError)

    def test_selector_exception_is_propagated_and_selector_closed(self) -> None:
        selector = _FailingSelector()
        hub = ClassicReceiveHub(self.reader, poll_timeout=0.01)
        self.hub = hub
        self.addCleanup(hub.stop)
        waiter = hub.register_waiter(0, lambda _payload: False)

        with patch(
            "catlabel.transport.bluetooth.classic_receive.selectors.DefaultSelector",
            return_value=selector,
        ):
            hub.start()
            with self.assertRaisesRegex(RuntimeError, "selector failed"):
                hub.wait(waiter, timeout=0.1)

        self.assertTrue(selector.closed)

    def test_recv_exception_is_propagated_without_changing_socket_mode(self) -> None:
        self.reader.settimeout(0.0)
        selector = _AlwaysReadableSelector()
        hub = ClassicReceiveHub(self.reader, poll_timeout=0.01)
        self.hub = hub
        self.addCleanup(hub.stop)
        waiter = hub.register_waiter(0, lambda _payload: False)

        with patch(
            "catlabel.transport.bluetooth.classic_receive.selectors.DefaultSelector",
            return_value=selector,
        ):
            hub.start()
            with self.assertRaisesRegex(RuntimeError, "recv failed"):
                hub.wait(waiter, timeout=0.1)

        self.assertTrue(selector.closed)
        self.assertEqual(self.reader.gettimeout(), 0.0)
        self.assertFalse(self.reader.getblocking())

    def test_cancelled_waiter_does_not_claim_passive_cursor(self) -> None:
        hub = self.start_hub()
        cancelled = hub.register_passive_waiter(lambda _payload: True)
        hub.cancel_waiter(cancelled)
        hub.cancel_waiter(cancelled)
        self.assertTrue(cancelled.event.is_set())
        with self.assertRaisesRegex(RuntimeError, "waiter was cancelled"):
            hub.wait(cancelled, timeout=0.1, claim_passive=True)

        self.writer.sendall(b"still pending")
        next_waiter = hub.register_passive_waiter(
            lambda payload: payload == b"still pending"
        )
        self.assertEqual(hub.wait(next_waiter, timeout=0.1), b"still pending")

    def test_stop_is_idempotent_wakes_waiters_and_preserves_socket(self) -> None:
        self.reader.settimeout(0.35)
        callbacks: list[bytes] = []
        hub = self.start_hub(listener=callbacks.append)
        waiter = hub.register_waiter(hub.mark(), lambda _payload: False)
        self.assertEqual(self.reader.gettimeout(), 0.35)
        self.assertTrue(self.reader.getblocking())

        hub.stop()
        hub.stop()
        with self.assertRaisesRegex(RuntimeError, "hub stopped"):
            hub.wait(waiter, timeout=0.1)
        with self.assertRaisesRegex(RuntimeError, "is stopped"):
            hub.ensure_healthy()

        self.assertEqual(self.reader.gettimeout(), 0.35)
        self.assertTrue(self.reader.getblocking())
        self.writer.sendall(b"socket remains open")
        self.assertEqual(self.reader.recv(64), b"socket remains open")
        self.assertEqual(callbacks, [])


if __name__ == "__main__":
    unittest.main()
