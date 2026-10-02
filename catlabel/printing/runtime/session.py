from __future__ import annotations

from collections.abc import Callable

from ... import reporting
from ...core.async_operations import await_operation, optional_bytes


class RuntimeConnectionSession:
    """Runtime-controller API layered over a live transport connection."""

    def __init__(self, connection, *, reporter: reporting.Reporter) -> None:
        self._connection = connection
        self._reporter = reporter

    async def attach_runtime_controller(
        self, runtime_controller, *, timeout: float
    ) -> None:
        attach = getattr(self._connection, "attach_runtime_controller", None)
        if callable(attach):
            await await_operation(
                attach(runtime_controller, timeout=timeout),
                operation="attach_runtime_controller",
            )

    def report_debug(self, message: str) -> None:
        self._reporter.debug(short="Runtime", detail=message)

    def report_warning(self, *, short: str, detail: str) -> None:
        self._reporter.warning(short=short, detail=detail)

    def set_flow_paused(self, paused: bool, *, payload: bytes = b"") -> None:
        setter = getattr(self._connection, "set_flow_paused", None)
        if callable(setter):
            setter(paused, payload=payload)

    def can_send_control_packet(self) -> bool:
        checker = getattr(self._connection, "can_send_control_packet", None)
        return bool(checker()) if callable(checker) else False

    def can_query_control_packet(self) -> bool:
        checker = getattr(self._connection, "can_query_control_packet", None)
        return bool(checker()) if callable(checker) else False

    def can_send_standard_payload(self) -> bool:
        return callable(getattr(self._connection, "send_standard_payload", None))

    def can_send_bulk_payload(self) -> bool:
        checker = getattr(self._connection, "can_send_bulk_payload", None)
        return bool(checker()) if callable(checker) else False

    def can_wait_for_notification(self) -> bool:
        checker = getattr(self._connection, "can_wait_for_notification", None)
        return bool(checker()) if callable(checker) else False

    def can_send_control_packet_wait_notification(self) -> bool:
        checker = getattr(
            self._connection,
            "can_send_control_packet_wait_notification",
            None,
        )
        return bool(checker()) if callable(checker) else False

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        sender = getattr(self._connection, "send_control_packet", None)
        if not callable(sender):
            return False
        result = await await_operation(
            sender(packet, timeout=timeout),
            operation="send_control_packet",
        )
        return bool(result)

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float = 1.0,
        reply_complete: Callable[[bytes], bool] | None = None,
    ) -> bytes | None:
        query = getattr(self._connection, "query_control_packet", None)
        if not callable(query):
            return None
        if reply_complete is None:
            result = await await_operation(
                query(packet, timeout=timeout),
                operation="query_control_packet",
            )
        else:
            result = await await_operation(
                query(packet, timeout=timeout, reply_complete=reply_complete),
                operation="query_control_packet",
            )
        return optional_bytes(result, operation="query_control_packet")

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        waiter = getattr(self._connection, "wait_for_notification", None)
        if not callable(waiter):
            if required:
                raise RuntimeError("Connection does not support notification waits")
            return None
        result = await await_operation(
            waiter(label, match, timeout=timeout, required=required),
            operation="wait_for_notification",
        )
        return optional_bytes(result, operation="wait_for_notification")

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        sender = getattr(
            self._connection,
            "send_control_packet_wait_notification",
            None,
        )
        if not callable(sender) or not self.can_send_control_packet_wait_notification():
            if required:
                raise RuntimeError("Connection does not support notification queries")
            return None
        result = await await_operation(
            sender(
                packet,
                label=label,
                match=match,
                timeout=timeout,
                required=required,
            ),
            operation="send_control_packet_wait_notification",
        )
        return optional_bytes(result, operation="send_control_packet_wait_notification")

    async def send_standard_payload(self, data: bytes) -> None:
        sender = getattr(self._connection, "send_standard_payload", None)
        if not callable(sender):
            raise RuntimeError("Connection does not support standard payload sends")
        await await_operation(sender(data), operation="send_standard_payload")

    async def send_bulk_payload(self, data: bytes, *, timeout: float = 1.0) -> bool:
        sender = getattr(self._connection, "send_bulk_payload", None)
        if not callable(sender):
            return False
        result = await await_operation(
            sender(data, timeout=timeout),
            operation="send_bulk_payload",
        )
        return bool(result)
