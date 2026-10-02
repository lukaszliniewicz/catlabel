from __future__ import annotations

from collections.abc import Callable

from catlabel.printing.runtime.base import RuntimeSessionApi


class RuntimeSessionFake(RuntimeSessionApi):
    """Complete inert runtime session for focused printing tests."""

    notify_started: bool = False

    def report_debug(self, message: str) -> None:
        pass

    def report_warning(self, *, short: str, detail: str) -> None:
        pass

    def can_send_control_packet(self) -> bool:
        return False

    def can_query_control_packet(self) -> bool:
        return False

    def can_send_standard_payload(self) -> bool:
        return False

    def can_send_bulk_payload(self) -> bool:
        return False

    def can_wait_for_notification(self) -> bool:
        return False

    def can_send_control_packet_wait_notification(self) -> bool:
        return False

    def set_flow_paused(self, paused: bool, *, payload: bytes = b"") -> None:
        pass

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        raise AssertionError("unexpected control-packet send")

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float = 1.0,
        reply_complete: Callable[[bytes], bool] | None = None,
    ) -> bytes | None:
        raise AssertionError("unexpected control-packet query")

    async def send_standard_payload(self, data: bytes) -> object:
        raise AssertionError("unexpected standard-payload send")

    async def send_bulk_payload(self, data: bytes, *, timeout: float = 1.0) -> bool:
        raise AssertionError("unexpected bulk-payload send")

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        raise AssertionError("unexpected atomic control-packet query")

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        raise AssertionError("unexpected notification wait")
