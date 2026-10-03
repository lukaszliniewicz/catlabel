"""Passive status checks and estimated pacing for released Phomemo recipes.

Copyright 2026 Daniel Banecki (TiMini-Print).
Licensed under the Apache License, Version 2.0. See LICENSE for the full terms.

Ordinary M02/M02S/M02X/T02 status handling and estimated page timings are
adapted from TiMini-Print commit ``7be93f549597fe7e82ef67e3102c6233aa875f28``.
See NOTICE for attribution. These timings do not confirm physical completion.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Protocol

from ...core.resource_limits import MAX_DIMENSION
from ...protocol.families.phomemo_replies import PhomemoReplyDecoder
from .base import RuntimeController, RuntimeSessionApi

_MAX_PAGE_DELAY_SEC = MAX_DIMENSION * 0.01375


class PhomemoPacingTransport(Protocol):
    """The notification wait surface used to drive estimated pacing."""

    def can_wait_for_notification(self) -> bool: ...

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None: ...


class PhomemoReleasedStatus(RuntimeController):
    """Observe unsolicited Phomemo statuses without claiming print completion."""

    def __init__(self) -> None:
        self._decoder = PhomemoReplyDecoder()
        self._lock = threading.RLock()
        self._cover_open = False
        self._paper_out = False
        self._overheated = False
        self._sequence = 0
        self._observing = False
        self._closed = False
        self._active = False
        self._start_offset = 0
        self._error: RuntimeError | None = None

    @property
    def observing(self) -> bool:
        with self._lock:
            return self._observing and not self._closed

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def mark_native_observing(self) -> None:
        """Record that the client installed the native Classic callback."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Phomemo status controller is closed")
            self._observing = True

    async def initialize_connection(
        self,
        session: RuntimeSessionApi,
        *,
        mtu_size: int,
        timeout: float,
    ) -> None:
        _ = mtu_size, timeout
        with self._lock:
            self._observing = not self._closed and session.can_wait_for_notification()

    def handle_notification(
        self,
        session: RuntimeSessionApi,
        payload: bytes,
    ) -> None:
        _ = session
        self.receive(payload)

    def receive(self, payload: bytes) -> None:
        """Accept bytes from a passive callback, including foreign reader threads."""
        with self._lock:
            if self._closed:
                return
            for reply in self._decoder.feed_with_offsets(payload):
                self._sequence += 1
                self._record_reply(reply.frame, reply.start_offset)

    def _record_reply(self, frame: bytes, start_offset: int) -> None:
        opcode, value = frame[:2]
        if opcode == 0x05 and value in (0x98, 0x99):
            self._cover_open = value == 0x99
            if value == 0x99:
                self._record_active_fault(start_offset, "Phomemo cover opened")
        elif opcode == 0x06:
            self._paper_out = value == 0x88
            if self._paper_out:
                self._record_active_fault(start_offset, "Phomemo ran out of paper")
        elif opcode == 0x03 and value in (0xA8, 0xA9):
            self._overheated = value == 0xA9
            if value == 0xA9:
                self._record_active_fault(
                    start_offset,
                    "Phomemo print head overheated",
                )

        if not self._active or start_offset < self._start_offset:
            return
        if opcode == 0x0B and value == 0xB8:
            self._set_job_error("Phomemo cancelled the active print job")
        elif opcode == 0x0F and value != 0x0C:
            self._set_job_error(
                f"Phomemo reported print failure (status=0x{value:02x})"
            )

    def _record_active_fault(self, start_offset: int, message: str) -> None:
        if self._active and start_offset >= self._start_offset:
            self._set_job_error(message)

    def _set_job_error(self, message: str) -> None:
        if self._error is None:
            self._error = RuntimeError(message)

    def _raise_if_not_ready_locked(self) -> None:
        if self._error is not None:
            raise self._error
        if self._closed:
            raise RuntimeError("Phomemo status connection is closed")
        if self._cover_open:
            raise RuntimeError("Phomemo cover is open")
        if self._paper_out:
            raise RuntimeError("Phomemo is out of paper")
        if self._overheated:
            raise RuntimeError("Phomemo print head is overheated")

    def raise_if_not_ready(self) -> None:
        with self._lock:
            self._raise_if_not_ready_locked()

    @asynccontextmanager
    async def released_job_scope(self) -> AsyncGenerator[None, None]:
        """Fence active-job replies and check status before and after its writes."""
        with self._lock:
            if self._active:
                raise RuntimeError("Phomemo already has an active released job")
            self._error = None
            self._raise_if_not_ready_locked()
            self._start_offset = self._decoder.received_byte_count
            self._active = True
        try:
            yield
            self.raise_if_not_ready()
        finally:
            with self._lock:
                self._active = False

    async def pace(
        self,
        transport: PhomemoPacingTransport,
        delay_sec: float,
    ) -> None:
        """Wait the recipe's estimated page time while observing passive status."""
        if (
            not math.isfinite(delay_sec)
            or delay_sec < 0
            or delay_sec > _MAX_PAGE_DELAY_SEC
        ):
            raise ValueError(
                f"Phomemo page delay must be finite and between 0 and {_MAX_PAGE_DELAY_SEC} seconds"
            )

        self.raise_if_not_ready()
        deadline = time.monotonic() + delay_sec
        while True:
            self.raise_if_not_ready()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            with self._lock:
                observing = self._observing and not self._closed
                sequence = self._sequence
            if observing and transport.can_wait_for_notification():
                timeout = min(1.0, remaining)
                wait_started = time.monotonic()
                with suppress(TimeoutError):
                    await transport.wait_for_notification(
                        "Phomemo pacing",
                        lambda _payload, observed=sequence: self._sequence_changed(
                            observed
                        ),
                        timeout=timeout,
                        required=False,
                    )
                # A transport that lost its passive route may return or time
                # out immediately despite ``required=False``. Avoid spinning
                # unless a callback already advanced the frame sequence.
                if (
                    not self._sequence_changed(sequence)
                    and time.monotonic() - wait_started < timeout * 0.5
                    and time.monotonic() < deadline
                ):
                    await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
            else:
                await asyncio.sleep(min(0.1, remaining))
            self.raise_if_not_ready()

        self.raise_if_not_ready()

    def _sequence_changed(self, sequence: int) -> bool:
        with self._lock:
            return self._sequence != sequence

    async def stop(self, session: RuntimeSessionApi) -> None:
        _ = session
        self.abort()

    def abort(self) -> None:
        """Close observation and preserve a stop error for any active job."""
        with self._lock:
            if self._active and self._error is None:
                self._error = RuntimeError(
                    "Phomemo connection closed during the active print job"
                )
            self._observing = False
            self._closed = True
