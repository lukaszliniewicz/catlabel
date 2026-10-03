from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable
from typing import cast

from catlabel.printing.runtime.base import RuntimeSessionApi
from catlabel.printing.runtime.luck_a41 import (
    LUCK_VERSION_QUERY_PACKET,
    LuckA41RuntimeController,
)
from catlabel.protocol.runtime import RuntimeControlRange


class ProbeSession:
    def __init__(
        self,
        reply: bytes | None | BaseException = b"1.26",
        *,
        route: str | None = "query",
        fragments: tuple[bytes, ...] | None = None,
    ) -> None:
        self.reply = reply
        self.route = route
        self.fragments = fragments
        self.queries: list[tuple[bytes, float]] = []
        self.notifications: list[tuple[bytes, str, float, bool]] = []
        self.completion_results: list[bool] = []
        self.active_waiters: list[Callable[[bytes], bool]] = []
        self.warnings: list[tuple[str, str]] = []
        self.debug: list[str] = []

    def can_query_control_packet(self) -> bool:
        return self.route == "query"

    def can_send_control_packet_wait_notification(self) -> bool:
        return self.route == "notification"

    def report_debug(self, message: str) -> None:
        self.debug.append(message)

    def report_warning(self, *, short: str, detail: str) -> None:
        self.warnings.append((short, detail))

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float,
        reply_complete: Callable[[bytes], bool] | None = None,
    ) -> bytes | None:
        self.queries.append((packet, timeout))
        if isinstance(self.reply, BaseException):
            raise self.reply
        if reply_complete is not None:
            pending = b""
            for fragment in self._fragments():
                pending += fragment
                self.completion_results.append(reply_complete(pending))
        return self.reply

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool,
    ) -> bytes | None:
        self.notifications.append((packet, label, timeout, required))
        self.active_waiters.append(match)
        try:
            if isinstance(self.reply, BaseException):
                raise self.reply
            for fragment in self._fragments():
                self.completion_results.append(match(fragment))
            # The adapter's optional full-window wait ends without returning
            # data because the matcher intentionally never completes.
            return None
        finally:
            self.active_waiters.remove(match)

    def _fragments(self) -> tuple[bytes, ...]:
        if self.fragments is not None:
            return self.fragments
        if self.reply is None or isinstance(self.reply, BaseException):
            return ()
        return (self.reply,)


def _range_tuple(value: RuntimeControlRange | None) -> tuple[int, int, int] | None:
    if value is None:
        return None
    return (value.low, value.default, value.high)


async def _probe(
    controller: LuckA41RuntimeController,
    session: ProbeSession,
    *,
    timeout: float,
) -> None:
    await controller.probe_capabilities(
        cast(RuntimeSessionApi, session), timeout=timeout
    )


class LuckA41RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_unprobed_controller_has_no_runtime_capabilities(self) -> None:
        controller = LuckA41RuntimeController()

        self.assertIsNone(controller.runtime_capabilities())
        self.assertEqual(
            controller.debug_snapshot(),
            {"firmware_version": None, "resolved_ranges": None},
        )

    async def test_version_gate_and_ascii_padding(self) -> None:
        cases = (
            (b"1.25", "1.25", (0, 1, 2), None),
            (b"1.26", "1.26", (1, 8, 15), (0, 4, 8)),
            (b"\x00 \tv1.26\r\n", "1.26", (1, 8, 15), (0, 4, 8)),
            # The firmware threshold is intentionally a normalized text gate.
            (b"1.9", "1.9", (1, 8, 15), (0, 4, 8)),
        )
        for reply, expected_version, density, speed in cases:
            with self.subTest(reply=reply):
                session = ProbeSession(reply, fragments=(reply[:2], reply[2:]))
                controller = LuckA41RuntimeController()
                await _probe(controller, session, timeout=0.5)

                capabilities = controller.runtime_capabilities()
                self.assertIsNotNone(capabilities)
                assert capabilities is not None
                self.assertIsNotNone(capabilities.print_controls)
                assert capabilities.print_controls is not None
                self.assertEqual(
                    _range_tuple(capabilities.print_controls.density), density
                )
                self.assertEqual(_range_tuple(capabilities.print_controls.speed), speed)
                self.assertEqual(
                    controller.debug_snapshot()["firmware_version"], expected_version
                )
                self.assertEqual(
                    controller.debug_snapshot()["resolved_ranges"],
                    {
                        "density": {
                            "low": density[0],
                            "default": density[1],
                            "high": density[2],
                        },
                        "speed": None
                        if speed is None
                        else {
                            "low": speed[0],
                            "default": speed[1],
                            "high": speed[2],
                        },
                    },
                )
                self.assertEqual(session.completion_results, [False, False])
                self.assertEqual(session.warnings, [])

    async def test_both_query_routes_use_full_window_and_clamped_timeout(self) -> None:
        for route in ("query", "notification"):
            with self.subTest(route=route):
                session = ProbeSession(b"v1.26", route=route, fragments=(b"v1.", b"26"))
                await _probe(LuckA41RuntimeController(), session, timeout=9.0)

                if route == "notification":
                    self.assertEqual(session.queries, [])
                    self.assertEqual(
                        session.notifications,
                        [(LUCK_VERSION_QUERY_PACKET, "firmware", 3.0, False)],
                    )
                    self.assertEqual(session.completion_results, [False, False])
                    self.assertEqual(session.active_waiters, [])
                else:
                    self.assertEqual(
                        session.queries, [(LUCK_VERSION_QUERY_PACKET, 3.0)]
                    )
                    self.assertEqual(session.notifications, [])

    async def test_query_uses_caller_timeout_when_shorter_than_budget(self) -> None:
        session = ProbeSession(b"1.26")
        await _probe(LuckA41RuntimeController(), session, timeout=1.25)

        self.assertEqual(session.queries, [(LUCK_VERSION_QUERY_PACKET, 1.25)])

    async def test_unknown_responses_use_conservative_range_and_warn(self) -> None:
        invalid_replies = (
            None,
            b"",
            b"firmware 1.26",
            b"1.26x",
            b"vv1.26",
            b"1.26\xff",
            b"1.26" + b" " * 125,
        )
        for reply in invalid_replies:
            with self.subTest(reply=reply):
                session = ProbeSession(reply)
                controller = LuckA41RuntimeController()
                await _probe(controller, session, timeout=0.5)

                capabilities = controller.runtime_capabilities()
                self.assertIsNotNone(capabilities)
                assert capabilities is not None
                self.assertIsNotNone(capabilities.print_controls)
                assert capabilities.print_controls is not None
                self.assertEqual(
                    _range_tuple(capabilities.print_controls.density), (0, 1, 2)
                )
                self.assertIsNone(capabilities.print_controls.speed)
                self.assertIsNone(controller.debug_snapshot()["firmware_version"])
                self.assertEqual(len(session.warnings), 1)

    async def test_ble_collector_rejects_suffix_and_oversize(self) -> None:
        cases = (
            (b"1.26", b"x"),
            (b"1.26", b" " * 124, b"x"),
        )
        for fragments in cases:
            with self.subTest(fragments=fragments):
                # A BLE waiter returns None at the end of its optional window;
                # only the callback-collected notification fragments count.
                session = ProbeSession(
                    b"1.26", route="notification", fragments=fragments
                )
                controller = LuckA41RuntimeController()

                await _probe(controller, session, timeout=1.0)

                self.assertIsNone(controller.debug_snapshot()["firmware_version"])
                self.assertEqual(len(session.warnings), 1)
                self.assertTrue(session.completion_results)
                self.assertTrue(
                    all(not complete for complete in session.completion_results)
                )

    async def test_response_at_128_byte_limit_is_accepted(self) -> None:
        reply = b"V1.26" + b" " * 123
        self.assertEqual(len(reply), 128)
        session = ProbeSession(None, route="notification", fragments=(reply,))
        controller = LuckA41RuntimeController()
        await _probe(controller, session, timeout=1.0)
        self.assertEqual(controller.debug_snapshot()["firmware_version"], "1.26")
        self.assertEqual(session.warnings, [])

    async def test_no_route_skips_query_and_resolves_unknown(self) -> None:
        session = ProbeSession(route=None)
        controller = LuckA41RuntimeController()

        await _probe(controller, session, timeout=1.0)

        self.assertEqual(session.queries, [])
        self.assertEqual(session.notifications, [])
        self.assertIsNone(controller.debug_snapshot()["firmware_version"])
        self.assertEqual(len(session.warnings), 1)

    async def test_timeout_resolves_unknown_on_both_routes(self) -> None:
        for route in ("query", "notification"):
            with self.subTest(route=route):
                session = ProbeSession(
                    TimeoutError("reply window elapsed"), route=route
                )
                controller = LuckA41RuntimeController()

                await _probe(controller, session, timeout=5.0)

                self.assertIsNone(controller.debug_snapshot()["firmware_version"])
                self.assertEqual(len(session.warnings), 1)

    async def test_transport_errors_and_cancellation_propagate(self) -> None:
        for failure in (RuntimeError("transport failed"), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__):
                route = (
                    "notification"
                    if isinstance(failure, asyncio.CancelledError)
                    else "query"
                )
                session = ProbeSession(failure, route=route)
                controller = LuckA41RuntimeController()
                with self.assertRaises(type(failure)):
                    await _probe(controller, session, timeout=1.0)
                self.assertIsNone(controller.runtime_capabilities())
                self.assertEqual(session.warnings, [])
                if isinstance(failure, asyncio.CancelledError):
                    self.assertEqual(session.active_waiters, [])

    async def test_repeat_probe_replaces_previous_connection_state(self) -> None:
        session = ProbeSession(b"1.26")
        controller = LuckA41RuntimeController()
        await _probe(controller, session, timeout=1.0)
        self.assertEqual(controller.debug_snapshot()["firmware_version"], "1.26")

        old_session = ProbeSession(b"1.25")
        await _probe(controller, old_session, timeout=1.0)

        snapshot = controller.debug_snapshot()
        self.assertEqual(snapshot["firmware_version"], "1.25")
        self.assertEqual(
            snapshot["resolved_ranges"],
            {
                "density": {"low": 0, "default": 1, "high": 2},
                "speed": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
