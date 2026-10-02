from __future__ import annotations

import selectors
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(eq=False)
class _ReplyWaiter:
    start_offset: int
    match: Callable[[bytes], bool] | None
    event: threading.Event = field(default_factory=threading.Event)
    result: bytes | None = None
    result_end_offset: int | None = None
    error: RuntimeError | None = None
    cancelled: bool = False


class ClassicReceiveHub:
    """Single-reader byte inbox for a selectable Classic Bluetooth socket.

    The hub owns reads while started, but never owns or changes the socket.
    Callers should register waiters before writing commands that can reply.
    Listener callbacks run synchronously before waiter predicates, so listeners
    must return promptly.
    """

    def __init__(
        self,
        sock: object,
        *,
        listener: Callable[[bytes], None] | None = None,
        max_history_bytes: int = 65536,
        poll_timeout: float = 0.1,
    ) -> None:
        if not isinstance(sock, socket.socket):
            raise TypeError("ClassicReceiveHub requires a native socket.socket")
        if max_history_bytes <= 0:
            raise ValueError("max_history_bytes must be positive")
        if poll_timeout <= 0:
            raise ValueError("poll_timeout must be positive")

        self._sock = sock
        self._listener = listener
        self._max_history_bytes = int(max_history_bytes)
        self._poll_timeout = float(poll_timeout)
        self._condition = threading.Condition()
        self._history = bytearray()
        self._base_offset = 0
        self._passive_offset = 0
        self._waiters: list[_ReplyWaiter] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._stopped = False
        self._failure: RuntimeError | None = None

    def set_listener(self, listener: Callable[[bytes], None] | None) -> None:
        with self._condition:
            self._listener = listener

    def start(self) -> None:
        with self._condition:
            if self._started:
                return
            if self._stopped:
                raise RuntimeError("Classic receive hub is stopped")
            if self._failure is not None:
                self._raise_failure(self._failure)

            selector = selectors.DefaultSelector()
            try:
                selector.register(self._sock, selectors.EVENT_READ)
            except Exception:
                selector.close()
                raise

            thread = threading.Thread(
                target=self._read_loop,
                args=(selector,),
                name="catlabel-classic-receive",
                daemon=True,
            )
            self._thread = thread
            self._started = True
            try:
                thread.start()
            except Exception:
                self._thread = None
                self._started = False
                selector.close()
                raise

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._stopped = True
            self._fail_locked("Classic receive hub stopped")
            thread = self._thread

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.2, self._poll_timeout * 2))
            if thread.is_alive():
                raise RuntimeError(
                    "Classic receive reader did not stop within its join bound"
                )

    def ensure_healthy(self) -> None:
        with self._condition:
            if not self._started:
                raise RuntimeError("Classic receive hub has not been started")
            if self._stopped:
                raise RuntimeError("Classic receive hub is stopped")
            if self._failure is not None:
                self._raise_failure(self._failure)
            if self._thread is None or not self._thread.is_alive():
                raise RuntimeError("Classic receive reader is not running")

    def mark(self) -> int:
        with self._condition:
            return self._end_offset()

    def register_waiter(
        self,
        start_offset: int,
        match: Callable[[bytes], bool] | None,
    ) -> _ReplyWaiter:
        waiter = _ReplyWaiter(start_offset=max(0, int(start_offset)), match=match)
        with self._condition:
            self._waiters.append(waiter)
            if waiter.start_offset < self._base_offset:
                waiter.error = RuntimeError(
                    "Classic receive waiter start offset was trimmed from history"
                )
                waiter.event.set()
            elif self._failure is not None:
                waiter.error = self._copy_failure(self._failure)
                waiter.event.set()
            else:
                self._match_waiter_locked(waiter)
        return waiter

    def register(
        self,
        start_offset: int,
        match: Callable[[bytes], bool] | None,
    ) -> _ReplyWaiter:
        """Compatibility alias for the released ``register`` interface."""
        return self.register_waiter(start_offset, match)

    def register_passive_waiter(
        self,
        match: Callable[[bytes], bool],
    ) -> _ReplyWaiter:
        with self._condition:
            waiter = _ReplyWaiter(
                start_offset=max(self._base_offset, self._passive_offset),
                match=match,
            )
            self._waiters.append(waiter)
            if self._failure is not None:
                waiter.error = self._copy_failure(self._failure)
                waiter.event.set()
            else:
                self._match_waiter_locked(waiter)
            return waiter

    def register_passive(
        self,
        match: Callable[[bytes], bool],
    ) -> _ReplyWaiter:
        """Compatibility alias for the released ``register_passive`` interface."""
        return self.register_passive_waiter(match)

    def cancel_waiter(self, waiter: _ReplyWaiter) -> None:
        with self._condition:
            waiter.cancelled = True
            if waiter in self._waiters:
                self._waiters.remove(waiter)
            waiter.event.set()
            self._condition.notify_all()

    def wait(
        self,
        waiter: _ReplyWaiter,
        *,
        timeout: float,
        claim_passive: bool = False,
    ) -> bytes | None:
        waiter.event.wait(timeout=max(0.0, timeout))
        failure: RuntimeError | None = None
        result: bytes | None = None
        with self._condition:
            try:
                if waiter.result is not None:
                    result = waiter.result
                elif waiter.error is not None:
                    failure = waiter.error
                elif waiter.cancelled:
                    failure = RuntimeError("Classic receive waiter was cancelled")
                elif waiter.start_offset < self._base_offset:
                    failure = RuntimeError(
                        "Classic receive waiter start offset was trimmed from history"
                    )
                else:
                    result = self._slice_from_locked(waiter.start_offset) or None
            finally:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
                if claim_passive and not waiter.cancelled:
                    self._passive_offset = (
                        waiter.result_end_offset
                        if waiter.result_end_offset is not None
                        else self._end_offset()
                    )

        if failure is not None:
            self._raise_failure(failure)
        return result

    def _read_loop(self, selector: selectors.BaseSelector) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    events = selector.select(timeout=self._poll_timeout)
                except Exception as exc:
                    self._record_failure("Classic receive selector failed", exc)
                    return
                if not events:
                    continue
                if self._stop_event.is_set():
                    return

                try:
                    payload = self._sock.recv(4096)
                except Exception as exc:
                    self._record_failure("Classic receive recv failed", exc)
                    return
                if not payload:
                    self._record_failure("Classic receive socket reached EOF")
                    return

                data = bytes(payload)
                with self._condition:
                    if self._stop_event.is_set() or self._failure is not None:
                        return
                    listener = self._listener
                if listener is not None:
                    try:
                        listener(data)
                    except Exception as exc:
                        self._record_failure("Classic receive listener failed", exc)
                        return

                with self._condition:
                    if self._stop_event.is_set() or self._failure is not None:
                        return
                    self._history.extend(data)
                    self._trim_history_locked()
                    for waiter in tuple(self._waiters):
                        self._match_waiter_locked(waiter)
                        if self._failure is not None:
                            break
                    self._condition.notify_all()
        except Exception as exc:
            self._record_failure("Classic receive reader failed", exc)
        finally:
            try:
                selector.close()
            except Exception as exc:
                self._record_failure("Classic receive selector close failed", exc)
            with self._condition:
                if not self._stop_event.is_set() and self._failure is None:
                    self._fail_locked("Classic receive reader stopped unexpectedly")
                for waiter in self._waiters:
                    if waiter.result is None and waiter.error is None:
                        waiter.error = (
                            self._copy_failure(self._failure)
                            if self._failure is not None
                            else RuntimeError("Classic receive reader stopped")
                        )
                    waiter.event.set()
                self._condition.notify_all()

    def _match_waiter_locked(self, waiter: _ReplyWaiter) -> None:
        if (
            waiter.result is not None
            or waiter.error is not None
            or waiter.cancelled
            or waiter.match is None
        ):
            return
        if waiter.start_offset < self._base_offset:
            waiter.error = RuntimeError(
                "Classic receive waiter start offset was trimmed from history"
            )
            waiter.event.set()
            return

        candidate = self._slice_from_locked(waiter.start_offset)
        if not candidate:
            return
        try:
            matched = waiter.match(candidate)
        except Exception as exc:
            self._fail_locked("Classic receive waiter predicate failed", exc)
            return
        if matched:
            waiter.result = candidate
            waiter.result_end_offset = self._end_offset()
            waiter.event.set()

    def _trim_history_locked(self) -> None:
        extra = len(self._history) - self._max_history_bytes
        if extra <= 0:
            return
        del self._history[:extra]
        self._base_offset += extra
        self._passive_offset = max(self._passive_offset, self._base_offset)
        for waiter in self._waiters:
            if (
                waiter.result is None
                and waiter.error is None
                and not waiter.cancelled
                and waiter.start_offset < self._base_offset
            ):
                waiter.error = RuntimeError(
                    "Classic receive history trimmed past active waiter start offset"
                )
                waiter.event.set()

    def _record_failure(
        self,
        message: str,
        cause: Exception | None = None,
    ) -> None:
        with self._condition:
            self._fail_locked(message, cause)

    def _fail_locked(
        self,
        message: str,
        cause: Exception | None = None,
    ) -> None:
        if self._failure is None:
            self._failure = RuntimeError(message)
            if cause is not None:
                self._failure.__cause__ = cause
        self._stop_event.set()
        for waiter in self._waiters:
            if waiter.result is None and waiter.error is None:
                waiter.error = self._copy_failure(self._failure)
                waiter.event.set()
        self._condition.notify_all()

    @staticmethod
    def _copy_failure(failure: RuntimeError) -> RuntimeError:
        copied = RuntimeError(str(failure))
        if failure.__cause__ is not None:
            copied.__cause__ = failure.__cause__
        return copied

    @staticmethod
    def _raise_failure(failure: RuntimeError) -> None:
        if failure.__cause__ is not None:
            raise RuntimeError(str(failure)) from failure.__cause__
        raise RuntimeError(str(failure))

    def _slice_from_locked(self, start_offset: int) -> bytes:
        if start_offset < self._base_offset:
            raise RuntimeError(
                "Classic receive waiter start offset was trimmed from history"
            )
        start = start_offset - self._base_offset
        return bytes(self._history[start:])

    def _end_offset(self) -> int:
        return self._base_offset + len(self._history)


__all__ = ["ClassicReceiveHub"]
