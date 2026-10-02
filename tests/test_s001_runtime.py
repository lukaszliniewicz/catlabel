from __future__ import annotations

import unittest
from collections.abc import Callable

from catlabel.printing.runtime.base import RuntimeController, RuntimeSessionApi
from catlabel.printing.runtime.yk_astra_p1 import AstraP1RuntimeController
from catlabel.protocol.families.yk_astra_session import (
    pack_paper_query,
    pack_status_query,
)
from catlabel.protocol.families.yk_common import pack_yk_frame
from tests.runtime_session_fake import RuntimeSessionFake


def _status_packet(status_bits: int, *, command: int = 0x81) -> bytes:
    return pack_yk_frame(
        command,
        b"\x34\x12" + status_bits.to_bytes(2, "little") + bytes((9, 6, 25, 72)),
    )


class _AstraP1Session(RuntimeSessionFake):
    def __init__(
        self,
        *,
        query_replies: tuple[bytes | None, ...] = (),
        can_query: bool = True,
        can_wait: bool = True,
        wait_chunks: tuple[bytes, ...] = (),
        passive_history: bytes = b"",
        query_error: Exception | None = None,
        wait_error: Exception | None = None,
    ) -> None:
        self.query_replies = list(query_replies)
        self.query_available = can_query
        self.wait_available = can_wait
        self.wait_chunks = list(wait_chunks)
        self.passive_history = passive_history
        self.query_error = query_error
        self.wait_error = wait_error
        self.queries: list[bytes] = []
        self.query_timeouts: list[float] = []
        self.query_matches: list[bool | None] = []
        self.wait_calls: list[tuple[str, float, bool]] = []
        self.wait_match_inputs: list[bytes] = []
        self.warnings: list[tuple[str, str]] = []
        self.debug: list[str] = []
        self.notification_handler: Callable[[bytes], None] | None = None

    def connect_controller(self, controller: AstraP1RuntimeController) -> None:
        self.notification_handler = lambda payload: controller.handle_notification(
            self, payload
        )

    def can_query_control_packet(self) -> bool:
        return self.query_available

    def can_wait_for_notification(self) -> bool:
        return self.wait_available

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float = 1.0,
        reply_complete: Callable[[bytes], bool] | None = None,
    ) -> bytes | None:
        self.queries.append(bytes(packet))
        self.query_timeouts.append(timeout)
        if self.query_error is not None:
            raise self.query_error
        reply = self.query_replies.pop(0) if self.query_replies else None
        self.query_matches.append(
            None if reply_complete is None or reply is None else reply_complete(reply)
        )
        return reply

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        self.wait_calls.append((label, timeout, required))
        if self.wait_error is not None:
            raise self.wait_error
        chunks = tuple(self.wait_chunks)
        self.wait_chunks.clear()
        if self.notification_handler is not None:
            for chunk in chunks:
                self.notification_handler(chunk)
        stream = self.passive_history + b"".join(chunks)
        self.passive_history = stream
        self.wait_match_inputs.append(stream)
        return stream if match(stream) else None

    def report_debug(self, message: str) -> None:
        self.debug.append(message)

    def report_warning(self, *, short: str, detail: str) -> None:
        self.warnings.append((short, detail))


class S001RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_uses_independent_modulo_64_status_and_paper_sequences(
        self,
    ) -> None:
        status = _status_packet((1 << 13) | (1 << 15))
        paper = pack_yk_frame(0x73, b"\x01\x54\x5a\x02")
        session = _AstraP1Session(query_replies=(status, paper))
        controller = AstraP1RuntimeController(paper_query_on_valid=True)
        controller._astra_state.next_sequence = 63

        await controller.probe_capabilities(session, timeout=0.1)

        self.assertEqual(
            session.queries,
            [pack_status_query(sequence=63), pack_paper_query(sequence=0)],
        )
        self.assertEqual(session.query_timeouts, [1.0, 1.0])
        self.assertEqual(session.query_matches, [True, True])
        self.assertEqual(controller.debug_snapshot()["next_sequence"], 1)
        self.assertEqual(
            controller.debug_snapshot()["paper_details"],
            {"paper_type": 1, "width": 84, "length": 90, "color": 2},
        )
        self.assertIsNone(controller.runtime_capabilities())

    async def test_status_unavailable_and_unusable_status_warn_without_inventing_capabilities(
        self,
    ) -> None:
        unavailable_session = _AstraP1Session(can_query=False)
        unavailable = AstraP1RuntimeController()
        await unavailable.probe_capabilities(unavailable_session, timeout=0.2)
        self.assertEqual(unavailable_session.queries, [])
        self.assertEqual(
            unavailable_session.warnings[0][0], "YK Astra P1 status unavailable"
        )
        self.assertFalse(unavailable.debug_snapshot()["status_probe_available"])
        self.assertIsNone(unavailable.runtime_capabilities())

        invalid_session = _AstraP1Session(query_replies=(pack_yk_frame(0x42),))
        invalid = AstraP1RuntimeController()
        await invalid.probe_capabilities(invalid_session, timeout=0.2)
        self.assertEqual(invalid_session.warnings[0][0], "YK Astra P1 status timeout")
        self.assertFalse(invalid.debug_snapshot()["status_probe_available"])
        self.assertEqual(len(invalid_session.queries), 1)

    async def test_paper_query_requires_configuration_and_valid_paper(self) -> None:
        valid_status = _status_packet(1 << 13)
        configured = AstraP1RuntimeController(paper_query_on_valid=True)
        configured_session = _AstraP1Session(query_replies=(valid_status, None))
        await configured.probe_capabilities(configured_session, timeout=0.2)
        self.assertEqual(len(configured_session.queries), 2)
        self.assertEqual(
            configured_session.warnings[0][0], "YK Astra P1 paper query timeout"
        )

        unconfigured = AstraP1RuntimeController()
        unconfigured_session = _AstraP1Session(query_replies=(valid_status,))
        await unconfigured.probe_capabilities(unconfigured_session, timeout=0.2)
        self.assertEqual(unconfigured_session.queries, [pack_status_query(sequence=0)])

        invalid_paper_status = AstraP1RuntimeController(paper_query_on_valid=True)
        invalid_paper_session = _AstraP1Session(query_replies=(_status_packet(0),))
        await invalid_paper_status.probe_capabilities(
            invalid_paper_session, timeout=0.2
        )
        self.assertEqual(invalid_paper_session.queries, [pack_status_query(sequence=0)])

    async def test_fragmented_and_coalesced_notifications_are_decoded(self) -> None:
        controller = AstraP1RuntimeController()
        session = _AstraP1Session()
        error_status = _status_packet(1 << 8)
        idle_status = _status_packet(0)

        controller.handle_notification(session, error_status[:6])
        self.assertEqual(controller.debug_snapshot()["pending_reply_bytes"], 6)
        controller.handle_notification(session, error_status[6:] + idle_status)

        self.assertEqual(controller.debug_snapshot()["pending_reply_bytes"], 0)
        self.assertEqual(controller.debug_snapshot()["status_bits"], 0)
        self.assertEqual(len(session.warnings), 1)
        self.assertIn("cover open", session.warnings[0][1])

    async def test_status_error_warnings_are_deduplicated_until_bits_change(
        self,
    ) -> None:
        controller = AstraP1RuntimeController()
        session = _AstraP1Session()
        cover_open = _status_packet(1 << 8)
        cover_and_paper_out = _status_packet((1 << 8) | (1 << 11))

        controller.handle_notification(session, cover_open)
        controller.handle_notification(session, cover_open)
        controller.handle_notification(session, cover_and_paper_out)
        controller.handle_notification(session, cover_and_paper_out)

        self.assertEqual(len(session.warnings), 2)
        self.assertIn("cover open", session.warnings[0][1])
        self.assertNotIn("out of paper", session.warnings[0][1])
        self.assertIn("out of paper", session.warnings[1][1])

    async def test_80_printing_to_idle_is_not_completion(self) -> None:
        controller = AstraP1RuntimeController()
        session = _AstraP1Session()
        controller.handle_notification(session, _status_packet(1 << 3, command=0x80))
        controller.handle_notification(session, _status_packet(0, command=0x80))

        await controller.wait_for_completion(session, timeout=0.2)

        self.assertEqual(controller.debug_snapshot()["completion_count"], 0)
        self.assertEqual(len(session.wait_calls), 1)
        self.assertEqual(session.warnings[0][0], "YK Astra P1 completion timeout")

    async def test_81_and_ff_printing_to_idle_completions_are_consumed_early(
        self,
    ) -> None:
        for command in (0x81, 0xFF):
            with self.subTest(command=command):
                controller = AstraP1RuntimeController()
                session = _AstraP1Session()
                controller.on_standard_send_started(session)
                controller.handle_notification(
                    session, _status_packet(1 << 3, command=command)
                )
                controller.handle_notification(
                    session, _status_packet(0, command=command)
                )

                await controller.wait_for_completion(session, timeout=0.2)

                snapshot = controller.debug_snapshot()
                self.assertEqual(snapshot["completion_count"], 1)
                self.assertFalse(snapshot["saw_printing"])
                self.assertFalse(snapshot["finished"])
                self.assertEqual(session.wait_calls, [])

    async def test_wait_matches_accumulated_passive_notification_stream(self) -> None:
        controller = AstraP1RuntimeController()
        printing = _status_packet(1 << 3)
        idle = _status_packet(0)
        stream = printing + idle
        session = _AstraP1Session(wait_chunks=(printing, idle))
        session.connect_controller(controller)
        controller.on_standard_send_started(session)

        await controller.wait_for_completion(session, timeout=0.2)

        self.assertEqual(session.wait_match_inputs, [stream])
        self.assertEqual(session.wait_calls[0][0], "YK Astra P1 print completion")
        self.assertEqual(session.wait_calls[0][1], 30.0)
        self.assertFalse(session.wait_calls[0][2])
        self.assertEqual(controller.debug_snapshot()["completion_count"], 1)
        self.assertEqual(session.warnings, [])

    async def test_live_fragmented_and_coalesced_81_and_ff_streams_complete_once(
        self,
    ) -> None:
        for command in (0x81, 0xFF):
            with self.subTest(command=command):
                controller = AstraP1RuntimeController()
                printing = _status_packet(1 << 3, command=command)
                idle = _status_packet(0, command=command)
                session = _AstraP1Session(
                    wait_chunks=(printing[:5], printing[5:] + idle)
                )
                session.connect_controller(controller)
                controller.on_standard_send_started(session)

                await controller.wait_for_completion(session, timeout=0.1)

                self.assertEqual(session.wait_match_inputs, [printing + idle])
                self.assertEqual(controller.debug_snapshot()["completion_count"], 1)
                self.assertFalse(controller.debug_snapshot()["saw_printing"])
                self.assertFalse(controller.debug_snapshot()["finished"])
                self.assertEqual(session.warnings, [])

    async def test_old_completed_passive_history_cannot_complete_a_new_send(
        self,
    ) -> None:
        controller = AstraP1RuntimeController()
        printing = _status_packet(1 << 3)
        idle = _status_packet(0)
        session = _AstraP1Session(passive_history=printing + idle)
        session.connect_controller(controller)
        controller.on_standard_send_started(session)
        controller.handle_notification(session, printing)
        controller.handle_notification(session, idle)

        await controller.wait_for_completion(session, timeout=0.1)
        self.assertEqual(controller.debug_snapshot()["completion_count"], 1)
        self.assertEqual(session.wait_calls, [])

        controller.on_standard_send_started(session)
        await controller.wait_for_completion(session, timeout=0.1)

        self.assertEqual(len(session.wait_calls), 1)
        self.assertEqual(controller.debug_snapshot()["completion_count"], 1)
        self.assertEqual(session.warnings[-1][0], "YK Astra P1 completion timeout")

    async def test_stale_printing_history_and_new_idle_do_not_complete_new_send(
        self,
    ) -> None:
        controller = AstraP1RuntimeController()
        stale_printing = _status_packet(1 << 3)
        new_idle = _status_packet(0)
        session = _AstraP1Session(
            passive_history=stale_printing,
            wait_chunks=(new_idle,),
        )
        session.connect_controller(controller)
        controller.on_standard_send_started(session)

        await controller.wait_for_completion(session, timeout=0.1)

        self.assertEqual(session.wait_match_inputs, [stale_printing + new_idle])
        self.assertEqual(controller.debug_snapshot()["completion_count"], 0)
        self.assertEqual(session.warnings[0][0], "YK Astra P1 completion timeout")

    async def test_new_send_clears_intermediate_completion_flags(self) -> None:
        controller = AstraP1RuntimeController()
        session = _AstraP1Session()
        controller.handle_notification(session, _status_packet(1 << 3))
        controller.handle_notification(session, _status_packet(0))
        self.assertTrue(controller.debug_snapshot()["finished"])
        self.assertEqual(controller.debug_snapshot()["completion_count"], 1)

        controller.on_standard_send_started(session)

        self.assertFalse(controller.debug_snapshot()["finished"])
        self.assertFalse(controller.debug_snapshot()["saw_printing"])
        self.assertEqual(controller.debug_snapshot()["completion_count"], 1)

    async def test_timeout_and_unsupported_wait_reset_only_active_completion_tracking(
        self,
    ) -> None:
        printing = _status_packet(1 << 3)

        timeout_controller = AstraP1RuntimeController()
        timeout_session = _AstraP1Session()
        timeout_controller.handle_notification(timeout_session, printing)
        await timeout_controller.wait_for_completion(timeout_session, timeout=0.1)
        self.assertEqual(
            timeout_session.warnings[0][0], "YK Astra P1 completion timeout"
        )
        self.assertFalse(timeout_controller.debug_snapshot()["saw_printing"])
        timeout_controller.handle_notification(timeout_session, _status_packet(0))
        self.assertEqual(timeout_controller.debug_snapshot()["completion_count"], 0)

        unsupported_controller = AstraP1RuntimeController()
        unsupported_session = _AstraP1Session(can_wait=False)
        unsupported_controller.handle_notification(unsupported_session, printing)
        await unsupported_controller.wait_for_completion(
            unsupported_session, timeout=0.1
        )
        self.assertEqual(
            unsupported_session.warnings[0][0],
            "YK Astra P1 completion unavailable",
        )
        self.assertFalse(unsupported_controller.debug_snapshot()["saw_printing"])
        self.assertEqual(unsupported_session.wait_calls, [])

    async def test_adoption_shares_pending_decoder_state_only_with_same_controller(
        self,
    ) -> None:
        first = AstraP1RuntimeController()
        session = _AstraP1Session()
        packet = _status_packet(1 << 8)
        first.handle_notification(session, packet[:7])

        adopted = AstraP1RuntimeController()
        adopted.adopt_previous(first)
        adopted.handle_notification(session, packet[7:])

        self.assertIs(adopted._astra_state, first._astra_state)
        self.assertEqual(adopted.debug_snapshot()["status_bits"], 1 << 8)
        self.assertEqual(len(session.warnings), 1)

        unrelated = AstraP1RuntimeController()
        unrelated.adopt_previous(RuntimeController())
        self.assertIsNot(unrelated._astra_state, first._astra_state)

    async def test_stop_clears_partial_decoder_and_active_tracking_without_completion(
        self,
    ) -> None:
        controller = AstraP1RuntimeController()
        session: RuntimeSessionApi = _AstraP1Session()
        controller.handle_notification(session, _status_packet(1 << 3))
        controller.handle_notification(
            session, pack_yk_frame(0x73, b"\x01\x54\x5a\x02")[:7]
        )
        self.assertTrue(controller.debug_snapshot()["saw_printing"])
        pending_reply_bytes = controller.debug_snapshot()["pending_reply_bytes"]
        assert isinstance(pending_reply_bytes, int)
        self.assertGreater(pending_reply_bytes, 0)

        await controller.stop(session)

        snapshot = controller.debug_snapshot()
        self.assertFalse(snapshot["saw_printing"])
        self.assertFalse(snapshot["finished"])
        self.assertEqual(snapshot["completion_count"], 0)
        self.assertEqual(snapshot["pending_reply_bytes"], 0)
        controller.handle_notification(session, _status_packet(0))
        self.assertEqual(controller.debug_snapshot()["completion_count"], 0)

    async def test_transport_errors_propagate_without_replay_or_warning_conversion(
        self,
    ) -> None:
        query_error = OSError("query transport failed")
        query_session = _AstraP1Session(query_error=query_error)
        with self.assertRaisesRegex(OSError, "query transport failed"):
            await AstraP1RuntimeController().probe_capabilities(
                query_session, timeout=0.2
            )
        self.assertEqual(len(query_session.queries), 1)
        self.assertEqual(query_session.warnings, [])

        wait_error = OSError("notification transport failed")
        wait_session = _AstraP1Session(wait_error=wait_error)
        with self.assertRaisesRegex(OSError, "notification transport failed"):
            await AstraP1RuntimeController().wait_for_completion(
                wait_session, timeout=0.2
            )
        self.assertEqual(len(wait_session.wait_calls), 1)
        self.assertEqual(wait_session.warnings, [])


if __name__ == "__main__":
    unittest.main()
