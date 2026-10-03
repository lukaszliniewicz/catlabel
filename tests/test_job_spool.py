from __future__ import annotations

import gc
import unittest
import weakref
from typing import BinaryIO, cast

from catlabel.core.resource_limits import MAX_PRINT_JOBS, ResourceLimitError
from catlabel.printing.job_spool import ProtocolJobSpool
from catlabel.protocol.job import ProtocolJob
from catlabel.protocol.steps import (
    ProtocolReplyExpectation,
    ProtocolReplyMatcher,
    ProtocolStep,
    ProtocolWriteChannel,
)


class _FailingBinaryFile:
    def __init__(self, file: BinaryIO) -> None:
        self.file = file
        self.writes_before_failure: int | None = None
        self.fail_truncate = False

    def write(self, data: bytes) -> int:
        if self.writes_before_failure is not None:
            if self.writes_before_failure == 0:
                self.writes_before_failure = None
                raise OSError("injected spool write failure")
            self.writes_before_failure -= 1
        return self.file.write(data)

    def read(self, size: int = -1) -> bytes:
        return self.file.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.file.seek(offset, whence)

    def tell(self) -> int:
        return self.file.tell()

    def truncate(self, size: int | None = None) -> int:
        if self.fail_truncate:
            raise OSError("injected spool rollback failure")
        return self.file.truncate(size)

    def flush(self) -> None:
        self.file.flush()

    def close(self) -> None:
        self.file.close()


def _job_signature(job: ProtocolJob) -> tuple[object, ...]:
    return (
        job.payload,
        job.wait_for_completion,
        tuple(
            (
                step.label,
                step.data,
                step.operation,
                step.expect,
                step.timeout_sec,
                step.include_in_payload,
                step.reply_matcher,
                step.repeat_interval_sec,
                step.repeat_timeout_sec,
                step.write_channel,
                step.reply_required,
            )
            for step in job.steps
        ),
    )


class ProtocolJobSpoolTests(unittest.TestCase):
    def test_round_trip_preserves_every_step_field_and_matcher_identity(self) -> None:
        complete_calls: list[bytes] = []

        def complete(reply: bytes) -> bool:
            complete_calls.append(reply)
            return reply.endswith(b"!")

        def matches(reply: bytes | None) -> bool:
            return reply == b"accepted"

        query_matcher = ProtocolReplyMatcher(complete=complete, matches=matches)
        wait_matcher = ProtocolReplyMatcher(
            complete=lambda reply: reply.startswith(b"done"),
            matches=None,
        )
        original = ProtocolJob(
            steps=(
                ProtocolStep.send(
                    "binary header",
                    b"header",
                    write_channel=ProtocolWriteChannel.CONTROL,
                ),
                ProtocolStep.query(
                    "status query",
                    b"status?",
                    expect=ProtocolReplyExpectation.OK_OR_AA,
                    timeout_sec=3.5,
                    include_in_payload=False,
                    reply_matcher=query_matcher,
                    repeat_interval_sec=0.25,
                    repeat_timeout_sec=6.75,
                    reply_required=False,
                ),
                ProtocolStep.wait(
                    "completion wait",
                    reply_matcher=wait_matcher,
                    timeout_sec=8.0,
                    reply_required=False,
                ),
            ),
            wait_for_completion=True,
        )

        with ProtocolJobSpool() as spool:
            spool.append(original)
            restored = next(iter(spool))

        self.assertEqual(restored.payload, original.payload)
        self.assertTrue(restored.wait_for_completion)
        self.assertEqual(len(restored.steps), len(original.steps))
        for actual, expected in zip(restored.steps, original.steps, strict=True):
            self.assertEqual(actual.label, expected.label)
            self.assertEqual(actual.data, expected.data)
            self.assertIs(actual.operation, expected.operation)
            self.assertIs(actual.expect, expected.expect)
            self.assertEqual(actual.timeout_sec, expected.timeout_sec)
            self.assertEqual(actual.include_in_payload, expected.include_in_payload)
            self.assertEqual(actual.repeat_interval_sec, expected.repeat_interval_sec)
            self.assertEqual(actual.repeat_timeout_sec, expected.repeat_timeout_sec)
            self.assertIs(actual.write_channel, expected.write_channel)
            self.assertEqual(actual.reply_required, expected.reply_required)
            self.assertIs(actual.reply_matcher, expected.reply_matcher)

        restored_query = restored.steps[1].reply_matcher
        self.assertIsNotNone(restored_query)
        assert restored_query is not None
        self.assertIs(restored_query.complete, complete)
        self.assertIs(restored_query.matches, matches)
        assert restored_query.matches is not None
        self.assertTrue(restored_query.complete(b"reply!"))
        self.assertTrue(restored_query.matches(b"accepted"))
        self.assertEqual(complete_calls, [b"reply!"])
        self.assertIs(restored.steps[2].reply_matcher, wait_matcher)

    def test_no_step_payload_is_preserved_and_iteration_repeats_in_order(self) -> None:
        jobs = (
            ProtocolJob(payload=b"opaque\x00first", wait_for_completion=True),
            ProtocolJob(payload=b"second", wait_for_completion=False),
            ProtocolJob(payload=b"third", wait_for_completion=True),
        )
        with ProtocolJobSpool() as spool:
            for job in jobs:
                spool.append(job)

            self.assertEqual(len(spool), len(jobs))
            first_pass = [_job_signature(job) for job in spool]
            second_pass = [_job_signature(job) for job in spool]

        expected = [_job_signature(job) for job in jobs]
        self.assertEqual(first_pass, expected)
        self.assertEqual(second_pass, expected)

    def test_byte_limit_counts_payload_and_metadata_and_preserves_prior_jobs(
        self,
    ) -> None:
        first = ProtocolJob(payload=b"first")
        with ProtocolJobSpool(max_bytes=128) as spool:
            spool.append(first)
            with self.assertRaises(ResourceLimitError):
                spool.append(ProtocolJob(payload=b"x" * 128))

            self.assertEqual([job.payload for job in spool], [first.payload])

        with ProtocolJobSpool(max_bytes=1) as spool:
            self.assertEqual(len(spool), 0)
            with self.assertRaises(ResourceLimitError):
                spool.append(ProtocolJob(payload=b""))
            self.assertEqual(len(spool), 0)
            self.assertEqual(list(spool), [])

    def test_job_count_limit_preserves_existing_jobs(self) -> None:
        with ProtocolJobSpool() as spool:
            for index in range(MAX_PRINT_JOBS):
                spool.append(ProtocolJob(payload=str(index).encode("ascii")))

            with self.assertRaises(ResourceLimitError):
                spool.append(ProtocolJob(payload=b"overflow"))

            self.assertEqual(len(list(spool)), MAX_PRINT_JOBS)
            self.assertEqual(len(spool), MAX_PRINT_JOBS)
            self.assertEqual(next(iter(spool)).payload, b"0")

    def test_failed_second_append_rolls_back_and_keeps_first_readable(self) -> None:
        spool = ProtocolJobSpool()
        file = cast(BinaryIO, _FailingBinaryFile(spool._file))
        spool._file = file
        first = ProtocolJob(payload=b"first")
        spool.append(first)
        failing_file = cast(_FailingBinaryFile, file)
        failing_file.writes_before_failure = 1

        with self.assertRaisesRegex(OSError, "injected spool write failure"):
            spool.append(ProtocolJob(payload=b"second"))

        self.assertEqual([job.payload for job in spool], [first.payload])
        spool.close()

    def test_failed_rollback_invalidates_spool(self) -> None:
        spool = ProtocolJobSpool()
        file = cast(BinaryIO, _FailingBinaryFile(spool._file))
        spool._file = file
        failing_file = cast(_FailingBinaryFile, file)
        spool.append(ProtocolJob(payload=b"first"))
        failing_file.writes_before_failure = 1
        failing_file.fail_truncate = True

        with self.assertRaisesRegex(
            RuntimeError, "Could not roll back a failed protocol job spool append"
        ):
            spool.append(ProtocolJob(payload=b"second"))

        with self.assertRaisesRegex(
            RuntimeError, "invalid after append rollback failed"
        ):
            list(spool)
        self.assertTrue(failing_file.file.closed)

    def test_context_exit_closes_temp_file_when_base_exception_escapes(self) -> None:
        class StopNow(BaseException):
            pass

        captured_file: BinaryIO | None = None
        spool: ProtocolJobSpool | None = None
        with self.assertRaises(StopNow), ProtocolJobSpool() as active_spool:
            spool = active_spool
            captured_file = active_spool._file
            active_spool.append(ProtocolJob(payload=b"encoded"))
            raise StopNow

        self.assertIsNotNone(captured_file)
        assert captured_file is not None
        self.assertTrue(captured_file.closed)
        self.assertIsNotNone(spool)
        assert spool is not None
        self.assertEqual(spool._records, [])
        self.assertEqual(spool._reply_matchers, {})

    def test_closed_spool_rejects_append_iteration_and_context_entry(self) -> None:
        spool = ProtocolJobSpool()
        spool.append(ProtocolJob(payload=b"encoded"))
        iterator = iter(spool)
        spool.close()

        with self.assertRaisesRegex(RuntimeError, "Protocol job spool is closed"):
            spool.append(ProtocolJob(payload=b"later"))
        with self.assertRaisesRegex(RuntimeError, "Protocol job spool is closed"):
            iter(spool)
        with self.assertRaisesRegex(RuntimeError, "Protocol job spool is closed"):
            next(iterator)
        with self.assertRaisesRegex(RuntimeError, "Protocol job spool is closed"):
            len(spool)
        with self.assertRaisesRegex(RuntimeError, "Protocol job spool is closed"):
            spool.__enter__()
        spool.close()

    def test_indexes_do_not_retain_jobs_or_step_data(self) -> None:
        matcher = ProtocolReplyMatcher(complete=lambda reply: bool(reply))
        payload_step = ProtocolStep.send("payload", b"payload bytes")
        step = ProtocolStep.query(
            "status",
            b"query bytes",
            expect=ProtocolReplyExpectation.OK,
            include_in_payload=False,
            reply_matcher=matcher,
        )
        job = ProtocolJob(payload=b"payload bytes", steps=(payload_step, step))
        job_reference = weakref.ref(job)
        step_reference = weakref.ref(step)
        spool = ProtocolJobSpool()
        spool.append(job)

        del job
        del step
        gc.collect()

        self.assertIsNone(job_reference())
        self.assertIsNone(step_reference())
        self.assertTrue(
            all(
                all(type(offset) is int for offset in record)
                for record in spool._records
            )
        )
        self.assertTrue(
            all(
                isinstance(retained, ProtocolReplyMatcher)
                and callable(retained.complete)
                and (retained.matches is None or callable(retained.matches))
                for retained in spool._reply_matchers.values()
            )
        )
        self.assertTrue(all(type(identity) is int for identity in spool._matcher_ids))
        self.assertTrue(
            all(type(matcher_id) is int for matcher_id in spool._matcher_ids.values())
        )
        self.assertIs(next(iter(spool)).steps[1].reply_matcher, matcher)
        spool.close()


if __name__ == "__main__":
    unittest.main()
