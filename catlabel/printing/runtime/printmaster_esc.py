# Copyright 2026 Daniel Banecki (TiMini-Print).
# Licensed under the Apache License, Version 2.0. See LICENSE for the full terms.
# Print Master status mapping adapted from Dejniel/TiMini-Print at
# fe603ca2ee1d21866f66f86d63ca2fc101916de8:
# timiniprint/printing/runtime/phomemo_esc.py
# Reply-boundary behavior follows 43b3203e229c271b75e86703e3a8f2ce428a8c45.
# Local adaptations: job-scoped observation, receive-offset fencing, and faults
# from the live decoder take precedence over completion through scope exit.

from __future__ import annotations

import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from ...protocol.families.phomemo_replies import (
    DecodedReply,
    PrintMasterReplyDecoder,
)
from ...protocol.job import ProtocolJob
from .base import RuntimeController, RuntimeSessionApi

_COMPLETION_TIMEOUT_SEC = 180.0
_COMPLETION_REPLY = b"\x0f\x0c"
_FAULTS = {
    b"\x03\xa9": "printer_overheated",
    b"\x05\x99": "cover_open",
    b"\x06\x88": "paper_out",
    b"\x0b\xb8": "job_cancelled",
}


@dataclass
class _PrintMasterCompletion:
    start_offset: int
    wait_requested: bool
    finished: bool = False
    error: RuntimeError | None = None


class PrintMasterRuntimeController(RuntimeController):
    def __init__(self) -> None:
        self._decoder = PrintMasterReplyDecoder()
        self._lock = threading.RLock()
        self._active_scope: _PrintMasterCompletion | None = None
        self._scope_open = False
        self._observing = False
        self._scope_context: ContextVar[_PrintMasterCompletion | None] = ContextVar(
            "printmaster_runtime_scope", default=None
        )

    def adopt_previous(self, previous: RuntimeController | None) -> None:
        if type(previous) is not type(self) or not isinstance(
            previous, PrintMasterRuntimeController
        ):
            return
        controllers = sorted((self, previous), key=id)
        with controllers[0]._lock, controllers[1]._lock:
            if self._scope_open or previous._scope_open:
                return
            self._decoder = previous._decoder
            self._observing = previous._observing

    async def initialize_connection(
        self,
        session: RuntimeSessionApi,
        *,
        mtu_size: int,
        timeout: float,
    ) -> None:
        _ = mtu_size, timeout
        with self._lock:
            self._observing = session.can_wait_for_notification()

    @asynccontextmanager
    async def job_scope(
        self,
        session: RuntimeSessionApi,
        job: ProtocolJob,
        *,
        timeout: float,
    ) -> AsyncGenerator[None, None]:
        _ = timeout
        with self._lock:
            if self._scope_open:
                raise RuntimeError("Print Master already has an active print job")
            if job.wait_for_completion and not (
                self._observing and session.can_wait_for_notification()
            ):
                raise RuntimeError(
                    "Print Master completion observer unavailable before print job"
                )
            completion = _PrintMasterCompletion(
                start_offset=self._decoder.received_byte_count,
                wait_requested=job.wait_for_completion,
            )
            self._scope_open = True
            self._active_scope = completion
        token = self._scope_context.set(completion)
        try:
            yield
        except BaseException:
            self._scope_context.reset(token)
            with self._lock:
                if self._active_scope is completion:
                    self._active_scope = None
                self._scope_open = False
            raise
        else:
            self._scope_context.reset(token)
            with self._lock:
                error = completion.error
                if self._active_scope is completion:
                    self._active_scope = None
                self._scope_open = False
            if error is not None:
                raise error

    def handle_notification(
        self,
        session: RuntimeSessionApi,
        payload: bytes,
    ) -> None:
        _ = session
        with self._lock:
            replies = self._decoder.feed_with_offsets(payload)
            self._record_replies(replies)

    async def wait_for_completion(
        self,
        session: RuntimeSessionApi,
        *,
        timeout: float,
    ) -> None:
        completion = self._scope_context.get()
        if completion is None:
            raise RuntimeError("Print Master completion wait requires an active job")
        if not completion.wait_requested:
            self._raise_completion_error(completion)
            return

        with self._lock:
            self._raise_completion_error(completion)
            if completion.finished:
                return
            observing = self._observing and session.can_wait_for_notification()
        if not observing:
            with self._lock:
                self._raise_completion_error(completion)
                if completion.finished:
                    return
            raise RuntimeError("Print Master completion observer unavailable")
        await session.wait_for_notification(
            "Print Master completion",
            lambda _data: self._completion_finished(completion),
            timeout=max(timeout, _COMPLETION_TIMEOUT_SEC),
            required=False,
        )
        with self._lock:
            self._raise_completion_error(completion)
            if not completion.finished:
                raise RuntimeError("Print Master page completion timed out")

    async def stop(self, session: RuntimeSessionApi) -> None:
        _ = session
        with self._lock:
            completion = self._active_scope
            if completion is not None and completion.error is None:
                completion.error = RuntimeError(
                    "Print Master connection closed before completion"
                )
                completion.finished = True
            self._active_scope = None
            self._observing = False

    def debug_snapshot(self) -> dict[str, object]:
        with self._lock:
            completion = self._active_scope
            return {
                "observing": self._observing,
                "active": self._scope_open,
                "completion_finished": (
                    False if completion is None else completion.finished
                ),
                "completion_error": (
                    None
                    if completion is None or completion.error is None
                    else str(completion.error)
                ),
                "received_byte_count": self._decoder.received_byte_count,
            }

    def _record_replies(self, replies: list[DecodedReply]) -> None:
        completion = self._active_scope
        if completion is None:
            return
        for reply in replies:
            condition = _FAULTS.get(reply.frame)
            if condition is not None:
                if completion.error is None:
                    completion.error = RuntimeError(
                        f"Print Master reported {condition} "
                        f"(status=0x{reply.frame.hex()})"
                    )
                completion.finished = True
            elif (
                reply.frame == _COMPLETION_REPLY
                and reply.start_offset >= completion.start_offset
                and completion.error is None
            ):
                completion.finished = True

    def _completion_finished(self, completion: _PrintMasterCompletion) -> bool:
        with self._lock:
            return completion.finished

    def _raise_completion_error(self, completion: _PrintMasterCompletion) -> None:
        if completion.error is not None:
            raise completion.error


__all__ = ["PrintMasterRuntimeController"]
