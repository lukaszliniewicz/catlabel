"""Resolve LuckP A41 print controls for each live connection.

The firmware threshold policy and the ``10 ff c0 <speed>`` dialect packet are
attributed to Dejniel/TiMini-Print commit
``76b3171bb956603277f7d97863d7e607d3de2e89`` (Apache-2.0). This local
implementation uses strict ASCII numeric parsing, conservative unknown-firmware
ranges (density 0..2, default 1; speed disabled), and a bounded BLE notification
collector to match this repository's transport API.
"""

from __future__ import annotations

import re

from ...protocol.families.luck_transactions import QUERY_TIMEOUT_SEC
from ...protocol.runtime import (
    RuntimeControlRange,
    RuntimePrintCapabilities,
    RuntimePrintControls,
)
from ...protocol.steps import (
    ProtocolReplyExpectation,
    ProtocolReplyMatcher,
    ProtocolStep,
)
from ..step_execution import execute_protocol_step
from .base import RuntimeController, RuntimeSessionApi

LUCK_VERSION_QUERY_PACKET = b"\x10\xff\x20\xf1"
_TEXT_REPLY = ProtocolReplyMatcher(complete=lambda _reply: False)
_TRIM_BYTES = bytes(range(0x21))
_FIRMWARE_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)+")
_UNKNOWN_DENSITY = RuntimeControlRange(low=0, default=1, high=2)
_OLD_DENSITY = RuntimeControlRange(low=0, default=1, high=2)
_MODERN_DENSITY = RuntimeControlRange(low=1, default=8, high=15)
_MODERN_SPEED = RuntimeControlRange(low=0, default=4, high=8)


class LuckA41RuntimeController(RuntimeController):
    """Resolve A41 print controls from one connection's firmware response."""

    def __init__(self) -> None:
        self._firmware_version: str | None = None
        self._capabilities: RuntimePrintCapabilities | None = None

    async def probe_capabilities(
        self, session: RuntimeSessionApi, *, timeout: float
    ) -> None:
        # A controller can be reused by connection management; never carry a
        # previous connection's firmware or ranges into this probe.
        self._firmware_version = None
        self._capabilities = None

        firmware_version = await self._query_firmware(session, timeout=timeout)
        self._firmware_version = firmware_version
        if firmware_version is None:
            density = _UNKNOWN_DENSITY
            speed = None
            session.report_warning(
                short="Luck A41 firmware unavailable",
                detail=(
                    "The firmware reply was missing or invalid. Using density "
                    "0..2 (default 1) and leaving speed disabled."
                ),
            )
        elif firmware_version < "1.26":
            density = _OLD_DENSITY
            speed = None
        else:
            density = _MODERN_DENSITY
            speed = _MODERN_SPEED

        controls = RuntimePrintControls(density=density, speed=speed)
        self._capabilities = RuntimePrintCapabilities(print_controls=controls)
        session.report_debug(
            f"Luck A41 firmware={firmware_version!r} "
            f"density={density.low}..{density.high} default={density.default} "
            f"speed={self._range_text(speed)}"
        )

    def runtime_capabilities(self) -> RuntimePrintCapabilities | None:
        return self._capabilities

    def debug_snapshot(self) -> dict[str, object]:
        controls = (
            None if self._capabilities is None else self._capabilities.print_controls
        )
        return {
            "firmware_version": self._firmware_version,
            "resolved_ranges": None
            if controls is None
            else {
                "density": self._range_snapshot(controls.density),
                "speed": self._range_snapshot(controls.speed),
            },
        }

    async def _query_firmware(
        self, session: RuntimeSessionApi, *, timeout: float
    ) -> str | None:
        has_query_route = session.can_query_control_packet()
        has_notification_route = (
            not has_query_route and session.can_send_control_packet_wait_notification()
        )
        if not has_query_route and not has_notification_route:
            return None

        use_notification_route = not has_query_route
        collected_reply = bytearray()

        def collect_notification(payload: bytes) -> bool:
            if len(collected_reply) <= 128:
                collected_reply.extend(payload[: 129 - len(collected_reply)])
            return False

        step = ProtocolStep.query(
            "firmware",
            LUCK_VERSION_QUERY_PACKET,
            expect=ProtocolReplyExpectation.NONE,
            timeout_sec=min(timeout, QUERY_TIMEOUT_SEC),
            include_in_payload=False,
            reply_matcher=(
                ProtocolReplyMatcher(complete=collect_notification)
                if use_notification_route
                else _TEXT_REPLY
            ),
            reply_required=False,
        )
        try:
            route_reply = await execute_protocol_step(
                session, step, timeout=timeout, log_prefix="Luck A41"
            )
        except TimeoutError:
            if not use_notification_route:
                return None
            route_reply = None

        # Native query transports return their own aggregated reply. The BLE
        # waiter returns only matching notifications, so its always-false
        # matcher feeds a bounded full-window collector and then times out.
        reply = bytes(collected_reply) if use_notification_route else route_reply
        if reply is None or len(reply) > 128:
            return None

        text_bytes = reply.strip(_TRIM_BYTES)
        try:
            text = text_bytes.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return None
        if text.startswith(("v", "V")):
            text = text[1:]
        if _FIRMWARE_VERSION.fullmatch(text) is None:
            return None
        return text

    @staticmethod
    def _range_text(value: RuntimeControlRange | None) -> str:
        if value is None:
            return "disabled"
        return f"{value.low}..{value.high} default {value.default}"

    @staticmethod
    def _range_snapshot(
        value: RuntimeControlRange | None,
    ) -> dict[str, int] | None:
        if value is None:
            return None
        return {
            "low": value.low,
            "default": value.default,
            "high": value.high,
        }
