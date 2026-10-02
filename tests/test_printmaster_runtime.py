from __future__ import annotations

import asyncio
import unittest
from collections.abc import Awaitable, Callable

from catlabel.printing.runtime.base import RuntimeController
from catlabel.printing.runtime.printmaster_esc import PrintMasterRuntimeController
from catlabel.protocol.job import ProtocolJob
from tests.runtime_session_fake import RuntimeSessionFake

_COMPLETION = b"\x0f\x0c"
_FAULTS = (
    (b"\x03\xa9", "printer_overheated"),
    (b"\x05\x99", "cover_open"),
    (b"\x06\x88", "paper_out"),
    (b"\x0b\xb8", "job_cancelled"),
)


class _PrintMasterSession(RuntimeSessionFake):
    def __init__(
        self,
        *,
        can_wait: bool = True,
        wait_history: bytes = b"",
        notifications: tuple[bytes, ...] = (),
        wait_action: Callable[[], Awaitable[None]] | None = None,
        send_error: Exception | None = None,
    ) -> None:
        self.wait_available = can_wait
        self.wait_history = wait_history
        self.notifications = list(notifications)
        self.wait_action = wait_action
        self.send_error = send_error
        self.controller: PrintMasterRuntimeController | None = None
        self.wait_calls: list[tuple[str, float, bool]] = []
        self.wait_match_inputs: list[bytes] = []
        self.payloads: list[bytes] = []
        self.warnings: list[tuple[str, str]] = []
        self.debug: list[str] = []

    def can_wait_for_notification(self) -> bool:
        return self.wait_available

    def bind(self, controller: PrintMasterRuntimeController) -> None:
        self.controller = controller

    def deliver(self, payload: bytes) -> None:
        if self.controller is None:
            raise AssertionError("no Print Master controller is bound")
        self.controller.handle_notification(self, payload)

    async def send_standard_payload(self, data: bytes) -> object:
        self.payloads.append(bytes(data))
        if self.send_error is not None:
            raise self.send_error
        return None

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        self.wait_calls.append((label, timeout, required))
        notifications = tuple(self.notifications)
        self.notifications.clear()
        for payload in notifications:
            self.deliver(payload)
        if self.wait_action is not None:
            await self.wait_action()
        candidate = self.wait_history + b"".join(notifications)
        self.wait_history = candidate
        self.wait_match_inputs.append(candidate)
        return candidate if match(candidate) else None

    def report_debug(self, message: str) -> None:
        self.debug.append(message)

    def report_warning(self, *, short: str, detail: str) -> None:
        self.warnings.append((short, detail))


def _job(*, wait: bool = True) -> ProtocolJob:
    return ProtocolJob(payload=b"pixels", wait_for_completion=wait)


class PrintMasterRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def _initialized(
        self,
        *,
        session: _PrintMasterSession | None = None,
        controller: PrintMasterRuntimeController | None = None,
    ) -> tuple[PrintMasterRuntimeController, _PrintMasterSession]:
        active_controller = (
            PrintMasterRuntimeController() if controller is None else controller
        )
        active_session = _PrintMasterSession() if session is None else session
        active_session.bind(active_controller)
        await active_controller.initialize_connection(
            active_session, mtu_size=23, timeout=0.1
        )
        return active_controller, active_session

    async def test_job_scope_prearms_completion_and_accepts_bare_and_prefixed_frames(
        self,
    ) -> None:
        for wire_reply in (_COMPLETION, b"\x1a" + _COMPLETION, b"\x1b" + _COMPLETION):
            with self.subTest(wire_reply=wire_reply.hex()):
                controller, session = await self._initialized()

                async with controller.job_scope(session, _job(), timeout=0.1):
                    for byte in wire_reply:
                        session.deliver(bytes((byte,)))
                    await controller.wait_for_completion(session, timeout=0.1)

                self.assertEqual(session.wait_calls, [])
                self.assertFalse(controller.debug_snapshot()["active"])

    async def test_live_wait_receives_notifications_before_matching(self) -> None:
        controller, session = await self._initialized(
            session=_PrintMasterSession(notifications=(_COMPLETION,))
        )

        async with controller.job_scope(session, _job(), timeout=0.1):
            await controller.wait_for_completion(session, timeout=0.1)

        self.assertEqual(session.wait_match_inputs, [_COMPLETION])
        self.assertEqual(session.wait_calls[0][0], "Print Master completion")
        self.assertEqual(session.wait_calls[0][1], 180.0)
        self.assertFalse(session.wait_calls[0][2])

    async def test_auxiliary_reply_payloads_do_not_match_embedded_completion_or_faults(
        self,
    ) -> None:
        # Opcode 08 is a single 16-byte reply; the apparent statuses are payload.
        auxiliary = b"\x08" + b"\x00" * 5 + b"\x0f\x0c\x03\xa9\x05\x99\x06\x88\x0b\xb8"
        self.assertEqual(len(auxiliary), 16)
        controller, session = await self._initialized(
            session=_PrintMasterSession(notifications=(auxiliary,))
        )

        with self.assertRaisesRegex(RuntimeError, "completion timed out"):
            async with controller.job_scope(session, _job(), timeout=0.1):
                await controller.wait_for_completion(session, timeout=0.1)

        self.assertEqual(session.wait_match_inputs, [auxiliary])

    async def test_old_partial_completion_is_fenced_and_next_fresh_frame_completes(
        self,
    ) -> None:
        controller, session = await self._initialized()
        session.deliver(_COMPLETION[:1])

        with self.assertRaisesRegex(RuntimeError, "completion timed out"):
            async with controller.job_scope(session, _job(), timeout=0.1):
                session.deliver(_COMPLETION[1:])
                await controller.wait_for_completion(session, timeout=0.1)

        async with controller.job_scope(session, _job(), timeout=0.1):
            session.deliver(_COMPLETION)
            await controller.wait_for_completion(session, timeout=0.1)

        self.assertEqual(controller.debug_snapshot()["received_byte_count"], 4)

    async def test_old_partial_fault_remains_fatal_for_active_job(self) -> None:
        controller, session = await self._initialized()
        session.deliver(b"\x03")

        with self.assertRaisesRegex(RuntimeError, "printer_overheated"):
            async with controller.job_scope(session, _job(wait=False), timeout=0.1):
                session.deliver(b"\xa9")

    async def test_each_exact_fault_is_raised_even_without_a_completion_wait(
        self,
    ) -> None:
        for frame, condition in _FAULTS:
            with self.subTest(condition=condition):
                controller, session = await self._initialized()
                with self.assertRaisesRegex(RuntimeError, condition):
                    async with controller.job_scope(
                        session, _job(wait=False), timeout=0.1
                    ):
                        session.deliver(b"\x1a" + frame)

    async def test_coalesced_completion_and_fault_leave_fault_sticky_in_both_orders(
        self,
    ) -> None:
        for stream in (_COMPLETION + b"\x05\x99", b"\x05\x99" + _COMPLETION):
            with self.subTest(stream=stream.hex()):
                controller, session = await self._initialized()
                with self.assertRaisesRegex(RuntimeError, "cover_open"):
                    async with controller.job_scope(session, _job(), timeout=0.1):
                        session.deliver(stream)
                        await controller.wait_for_completion(session, timeout=0.1)

    async def test_historical_completion_bytes_do_not_finish_a_waiting_job(
        self,
    ) -> None:
        controller, session = await self._initialized(
            session=_PrintMasterSession(wait_history=b"\x1a" + _COMPLETION)
        )

        with self.assertRaisesRegex(RuntimeError, "completion timed out"):
            async with controller.job_scope(session, _job(), timeout=0.1):
                await controller.wait_for_completion(session, timeout=0.1)

        self.assertEqual(session.wait_match_inputs, [b"\x1a" + _COMPLETION])

    async def test_timeout_uses_finite_budget_and_does_not_resend_payload(self) -> None:
        controller, session = await self._initialized()

        with self.assertRaisesRegex(RuntimeError, "completion timed out"):
            async with controller.job_scope(session, _job(), timeout=0.1):
                await session.send_standard_payload(b"pixels")
                await controller.wait_for_completion(session, timeout=240.0)

        self.assertEqual(session.payloads, [b"pixels"])
        self.assertEqual(session.wait_calls[0][1], 240.0)

    async def test_job_scopes_reject_overlap_before_second_payload(self) -> None:
        controller, session = await self._initialized()

        async with controller.job_scope(session, _job(wait=False), timeout=0.1):
            with self.assertRaisesRegex(RuntimeError, "active print job"):
                async with controller.job_scope(session, _job(wait=False), timeout=0.1):
                    await session.send_standard_payload(b"second pixels")

        self.assertEqual(session.payloads, [])

    async def test_successful_scope_exit_raises_fault_for_job_without_wait(
        self,
    ) -> None:
        controller, session = await self._initialized()

        with self.assertRaisesRegex(RuntimeError, "paper_out"):
            async with controller.job_scope(session, _job(wait=False), timeout=0.1):
                session.deliver(b"\x06\x88")

    async def test_send_failure_and_cancellation_remain_primary_over_fault_cleanup(
        self,
    ) -> None:
        controller, session = await self._initialized()
        with self.assertRaisesRegex(OSError, "payload write failed"):
            async with controller.job_scope(session, _job(wait=False), timeout=0.1):
                session.deliver(b"\x03\xa9")
                session.send_error = OSError("payload write failed")
                await session.send_standard_payload(b"pixels")

        controller, session = await self._initialized()
        with self.assertRaises(asyncio.CancelledError):
            async with controller.job_scope(session, _job(wait=False), timeout=0.1):
                session.deliver(b"\x03\xa9")
                raise asyncio.CancelledError

    async def test_stop_during_wait_preserves_captured_closed_completion(self) -> None:
        controller = PrintMasterRuntimeController()
        session = _PrintMasterSession()
        session.bind(controller)
        await controller.initialize_connection(session, mtu_size=23, timeout=0.1)

        async def stop_controller() -> None:
            await controller.stop(session)
            await controller.stop(session)

        session.wait_action = stop_controller
        with self.assertRaisesRegex(RuntimeError, "connection closed"):
            async with controller.job_scope(session, _job(), timeout=0.1):
                await controller.wait_for_completion(session, timeout=0.1)

        self.assertFalse(controller.debug_snapshot()["observing"])
        self.assertFalse(controller.debug_snapshot()["active"])

    async def test_stop_during_nonwaiting_job_still_fails_the_active_scope(
        self,
    ) -> None:
        controller, session = await self._initialized()

        with self.assertRaisesRegex(RuntimeError, "connection closed"):
            async with controller.job_scope(session, _job(wait=False), timeout=0.1):
                await controller.stop(session)

    async def test_stop_after_live_completion_before_scope_exit_is_sticky(self) -> None:
        controller, session = await self._initialized()

        with self.assertRaisesRegex(RuntimeError, "connection closed"):
            async with controller.job_scope(session, _job(), timeout=0.1):
                session.deliver(_COMPLETION)
                await controller.wait_for_completion(session, timeout=0.1)
                await controller.stop(session)

    async def test_stop_does_not_replace_an_existing_device_fault(self) -> None:
        controller, session = await self._initialized()

        with self.assertRaisesRegex(RuntimeError, "cover_open"):
            async with controller.job_scope(session, _job(), timeout=0.1):
                session.deliver(b"\x05\x99")
                await controller.stop(session)

    async def test_next_job_does_not_reuse_previous_live_completion(self) -> None:
        controller, session = await self._initialized(
            session=_PrintMasterSession(wait_history=_COMPLETION)
        )
        async with controller.job_scope(session, _job(), timeout=0.1):
            session.deliver(_COMPLETION)
            await controller.wait_for_completion(session, timeout=0.1)
        session.wait_calls.clear()
        session.wait_match_inputs.clear()

        with self.assertRaisesRegex(RuntimeError, "completion timed out"):
            async with controller.job_scope(session, _job(), timeout=0.1):
                await controller.wait_for_completion(session, timeout=0.1)

        self.assertEqual(len(session.wait_calls), 1)
        self.assertEqual(session.wait_match_inputs, [_COMPLETION])

    async def test_unobservable_waiting_job_fails_before_payload_send(self) -> None:
        controller = PrintMasterRuntimeController()
        session = _PrintMasterSession(can_wait=False)
        session.bind(controller)
        await controller.initialize_connection(session, mtu_size=23, timeout=0.1)

        with self.assertRaisesRegex(RuntimeError, "observer unavailable"):
            async with controller.job_scope(session, _job(), timeout=0.1):
                await session.send_standard_payload(b"pixels")

        self.assertEqual(session.payloads, [])

    async def test_unobservable_no_wait_job_can_send_without_completion_claim(
        self,
    ) -> None:
        controller = PrintMasterRuntimeController()
        session = _PrintMasterSession(can_wait=False)
        session.bind(controller)
        await controller.initialize_connection(session, mtu_size=23, timeout=0.1)

        async with controller.job_scope(session, _job(wait=False), timeout=0.1):
            await session.send_standard_payload(b"pixels")

        self.assertEqual(session.payloads, [b"pixels"])
        self.assertEqual(session.warnings, [])

    async def test_adoption_reuses_decoder_and_observer_only_when_both_are_idle(
        self,
    ) -> None:
        previous, session = await self._initialized()
        session.deliver(b"\x0f")
        adopted = PrintMasterRuntimeController()

        adopted.adopt_previous(previous)
        session.bind(adopted)

        self.assertIs(adopted._decoder, previous._decoder)
        self.assertTrue(adopted.debug_snapshot()["observing"])

        with self.assertRaisesRegex(RuntimeError, "completion timed out"):
            async with adopted.job_scope(session, _job(), timeout=0.1):
                session.deliver(b"\x0c")
                await adopted.wait_for_completion(session, timeout=0.1)

        async with adopted.job_scope(session, _job(), timeout=0.1):
            session.deliver(_COMPLETION)
            await adopted.wait_for_completion(session, timeout=0.1)

        unrelated = PrintMasterRuntimeController()
        unrelated.adopt_previous(RuntimeController())
        self.assertIsNot(unrelated._decoder, adopted._decoder)

        active_previous, active_session = await self._initialized()
        active_candidate = PrintMasterRuntimeController()
        async with active_previous.job_scope(
            active_session, _job(wait=False), timeout=0.1
        ):
            active_candidate.adopt_previous(active_previous)
            self.assertIsNot(active_candidate._decoder, active_previous._decoder)


if __name__ == "__main__":
    unittest.main()
