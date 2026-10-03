"""Private, process-local storage for encoded protocol jobs."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import suppress
from types import TracebackType
from typing import BinaryIO, TypedDict, cast

from ..core.resource_limits import MAX_PRINT_JOBS, MAX_REQUEST_BYTES, ResourceLimitError
from ..protocol.job import ProtocolJob
from ..protocol.steps import (
    ProtocolReplyExpectation,
    ProtocolReplyMatcher,
    ProtocolStep,
    ProtocolStepOperation,
    ProtocolWriteChannel,
)


class _StepMetadata(TypedDict):
    label: str
    data_offset: int
    data_length: int
    operation: str
    expect: str
    timeout_sec: float | None
    include_in_payload: bool
    reply_matcher_id: int | None
    repeat_interval_sec: float | None
    repeat_timeout_sec: float | None
    write_channel: str
    reply_required: bool


class _JobMetadata(TypedDict):
    payload_offset: int
    payload_length: int
    wait_for_completion: bool
    steps: list[_StepMetadata]


class ProtocolJobSpool:
    """Hold pre-encoded protocol jobs in a private temporary binary file."""

    def __init__(self, *, max_bytes: int = MAX_REQUEST_BYTES * 4) -> None:
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or max_bytes < 0
        ):
            raise ValueError("max_bytes must be a non-negative integer")

        self._max_bytes = max_bytes
        # Keep the handle open until explicit close or context-manager exit.
        self._file: BinaryIO = tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115
        self._records: list[tuple[int, int, int]] = []
        self._total_bytes = 0
        self._reply_matchers: dict[int, ProtocolReplyMatcher] = {}
        self._matcher_ids: dict[int, int] = {}
        self._next_matcher_id = 1
        self._closed = False
        self._invalid = False

    def __enter__(self) -> ProtocolJobSpool:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def append(self, job: ProtocolJob) -> None:
        """Append one job, leaving prior records intact if this append fails."""
        self._ensure_open()
        if len(self._records) >= MAX_PRINT_JOBS:
            raise ResourceLimitError(
                f"Protocol job spool exceeds the {MAX_PRINT_JOBS}-job limit."
            )

        pending_matchers: dict[int, ProtocolReplyMatcher] = {}
        pending_matcher_ids: dict[int, int] = {}
        next_matcher_id = self._next_matcher_id
        steps_metadata: list[_StepMetadata] = []
        data_offset = len(job.payload)

        for step in job.steps:
            matcher_id: int | None = None
            matcher = step.reply_matcher
            if matcher is not None:
                matcher_identity = id(matcher)
                existing_id = self._matcher_ids.get(matcher_identity)
                if (
                    existing_id is not None
                    and self._reply_matchers.get(existing_id) is matcher
                ):
                    matcher_id = existing_id
                else:
                    matcher_id = pending_matcher_ids.get(matcher_identity)
                    if matcher_id is None:
                        matcher_id = next_matcher_id
                        next_matcher_id += 1
                        pending_matcher_ids[matcher_identity] = matcher_id
                        pending_matchers[matcher_id] = matcher

            steps_metadata.append(
                {
                    "label": step.label,
                    "data_offset": data_offset,
                    "data_length": len(step.data),
                    "operation": step.operation.value,
                    "expect": step.expect.value,
                    "timeout_sec": step.timeout_sec,
                    "include_in_payload": step.include_in_payload,
                    "reply_matcher_id": matcher_id,
                    "repeat_interval_sec": step.repeat_interval_sec,
                    "repeat_timeout_sec": step.repeat_timeout_sec,
                    "write_channel": step.write_channel.value,
                    "reply_required": step.reply_required,
                }
            )
            data_offset += len(step.data)

        record: _JobMetadata = {
            "payload_offset": 0,
            "payload_length": len(job.payload),
            "wait_for_completion": job.wait_for_completion,
            "steps": steps_metadata,
        }
        metadata = json.dumps(
            record,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=True,
        ).encode("utf-8")
        append_size = data_offset + len(metadata)
        if self._total_bytes + append_size > self._max_bytes:
            raise ResourceLimitError(
                f"Protocol job spool exceeds its {self._max_bytes}-byte limit."
            )

        start = self._file.seek(0, os.SEEK_END)
        original_record_count = len(self._records)
        original_total_bytes = self._total_bytes
        original_next_matcher_id = self._next_matcher_id
        try:
            self._write(job.payload)
            for step in job.steps:
                self._write(step.data)

            metadata_offset = self._file.tell()
            self._write(metadata)
            self._records.append((start, metadata_offset, len(metadata)))
            for matcher_id, matcher in pending_matchers.items():
                self._reply_matchers[matcher_id] = matcher
                self._matcher_ids[id(matcher)] = matcher_id
            self._total_bytes = original_total_bytes + append_size
            self._next_matcher_id = next_matcher_id
        except BaseException:
            del self._records[original_record_count:]
            for matcher_id, matcher in pending_matchers.items():
                if self._reply_matchers.get(matcher_id) is matcher:
                    self._reply_matchers.pop(matcher_id, None)
                matcher_identity = id(matcher)
                if self._matcher_ids.get(matcher_identity) == matcher_id:
                    self._matcher_ids.pop(matcher_identity, None)
            self._total_bytes = original_total_bytes
            self._next_matcher_id = original_next_matcher_id
            rollback_error = self._rollback(start)
            if rollback_error is not None:
                self._invalidate()
                raise RuntimeError(
                    "Could not roll back a failed protocol job spool append; "
                    "the spool has been invalidated."
                ) from rollback_error
            raise

    def __iter__(self) -> Iterator[ProtocolJob]:
        self._ensure_open()
        records = tuple(self._records)

        def read_jobs() -> Iterator[ProtocolJob]:
            for record_start, metadata_offset, metadata_length in records:
                self._ensure_open()
                self._file.seek(metadata_offset)
                metadata_bytes = self._read_exact(metadata_length)
                record = cast(_JobMetadata, json.loads(metadata_bytes.decode("utf-8")))
                payload = self._read_span(
                    record_start,
                    record["payload_offset"],
                    record["payload_length"],
                )
                steps = tuple(
                    self._restore_step(record_start, step) for step in record["steps"]
                )
                yield ProtocolJob(
                    payload=payload,
                    steps=steps,
                    wait_for_completion=record["wait_for_completion"],
                )

        return read_jobs()

    def __len__(self) -> int:
        self._ensure_open()
        return len(self._records)

    def close(self) -> None:
        """Clear in-memory indexes and close the private temporary file."""
        if self._closed:
            return
        self._closed = True
        self._records.clear()
        self._reply_matchers.clear()
        self._matcher_ids.clear()
        self._total_bytes = 0
        self._next_matcher_id = 1
        self._file.close()

    def _ensure_open(self) -> None:
        if self._invalid:
            raise RuntimeError(
                "Protocol job spool is invalid after append rollback failed"
            )
        if self._closed:
            raise RuntimeError("Protocol job spool is closed")

    def _write(self, data: bytes) -> None:
        if not data:
            return
        written = self._file.write(data)
        if written != len(data):
            raise OSError("Protocol job spool wrote an incomplete record")

    def _read_exact(self, size: int) -> bytes:
        data = self._file.read(size)
        if len(data) != size:
            raise OSError("Protocol job spool record is truncated")
        return data

    def _read_span(self, record_start: int, offset: int, length: int) -> bytes:
        self._file.seek(record_start + offset)
        return self._read_exact(length)

    def _restore_step(self, record_start: int, metadata: _StepMetadata) -> ProtocolStep:
        matcher_id = metadata["reply_matcher_id"]
        matcher = None if matcher_id is None else self._reply_matchers[matcher_id]
        return ProtocolStep(
            label=metadata["label"],
            data=self._read_span(
                record_start,
                metadata["data_offset"],
                metadata["data_length"],
            ),
            operation=cast(ProtocolStepOperation, metadata["operation"]),
            expect=cast(ProtocolReplyExpectation, metadata["expect"]),
            timeout_sec=metadata["timeout_sec"],
            include_in_payload=metadata["include_in_payload"],
            reply_matcher=matcher,
            repeat_interval_sec=metadata["repeat_interval_sec"],
            repeat_timeout_sec=metadata["repeat_timeout_sec"],
            write_channel=cast(ProtocolWriteChannel, metadata["write_channel"]),
            reply_required=metadata["reply_required"],
        )

    def _rollback(self, start: int) -> BaseException | None:
        first_error: BaseException | None = None
        for operation in (
            self._file.flush,
            lambda: self._file.truncate(start),
            lambda: self._file.seek(start),
        ):
            try:
                operation()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        return first_error

    def _invalidate(self) -> None:
        self._invalid = True
        self._records.clear()
        self._reply_matchers.clear()
        self._matcher_ids.clear()
        self._total_bytes = 0
        self._next_matcher_id = 1
        with suppress(BaseException):
            self._file.close()
