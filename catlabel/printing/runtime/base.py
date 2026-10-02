from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ...protocol.runtime import RuntimePrintCapabilities
from ...protocol.steps import ProtocolStep

if TYPE_CHECKING:
    from ...protocol.job import ProtocolJob


@dataclass(frozen=True)
class PreparedRuntimeContext:
    """Live runtime state prepared before rendering and job construction."""

    runtime_controller: RuntimeController | None = None
    capabilities: RuntimePrintCapabilities | None = None


class RuntimeSessionApi(Protocol):
    def report_debug(self, message: str) -> None: ...

    def report_warning(self, *, short: str, detail: str) -> None: ...

    def can_send_control_packet(self) -> bool: ...

    def can_query_control_packet(self) -> bool: ...

    def can_send_standard_payload(self) -> bool: ...

    def can_send_bulk_payload(self) -> bool: ...

    def can_wait_for_notification(self) -> bool: ...

    def can_send_control_packet_wait_notification(self) -> bool: ...

    def set_flow_paused(self, paused: bool, *, payload: bytes = b"") -> None: ...

    async def send_control_packet(
        self, packet: bytes, *, timeout: float = 1.0
    ) -> bool: ...

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float = 1.0,
        reply_complete: Callable[[bytes], bool] | None = None,
    ) -> bytes | None: ...

    async def send_standard_payload(self, data: bytes) -> object:
        """Payload sends have no common timeout or acknowledgment semantics."""
        ...

    async def send_bulk_payload(self, data: bytes, *, timeout: float = 1.0) -> bool: ...

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool = True,
    ) -> bytes | None: ...

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None: ...


class NotificationRuntimeSessionApi(RuntimeSessionApi, Protocol):
    """Runtime methods that require a notification subscription."""

    notify_started: bool


class RuntimeController:
    @asynccontextmanager
    async def job_scope(
        self,
        session: RuntimeSessionApi,
        job: ProtocolJob,
        *,
        timeout: float,
    ) -> AsyncIterator[None]:
        """Own live state across all writes and completion for one print job."""

        yield

    def adopt_previous(self, previous: RuntimeController | None) -> None:
        return None

    async def initialize_connection(
        self,
        session: RuntimeSessionApi,
        *,
        mtu_size: int,
        timeout: float,
    ) -> None:
        return None

    async def after_initialize(
        self, session: NotificationRuntimeSessionApi, *, timeout: float
    ) -> None:
        return None

    async def stop(self, session: RuntimeSessionApi) -> None:
        return None

    async def wait_for_completion(
        self,
        session: RuntimeSessionApi,
        *,
        timeout: float,
    ) -> None:
        return None

    async def send_payload(
        self,
        session: RuntimeSessionApi,
        data: bytes,
        *,
        timeout: float,
    ) -> bool:
        """Send a family-specific payload, returning whether it was handled."""

        return False

    async def send_protocol_steps(
        self,
        session: RuntimeSessionApi,
        steps: tuple[ProtocolStep, ...],
        *,
        timeout: float,
    ) -> bool:
        """Handle a family-specific ordered step plan, if required."""

        return False

    async def probe_capabilities(
        self,
        session: RuntimeSessionApi,
        *,
        timeout: float,
    ) -> None:
        return None

    def runtime_capabilities(self) -> RuntimePrintCapabilities | None:
        return None

    def prepare_standard_payload(
        self, session: RuntimeSessionApi, data: bytes
    ) -> bytes:
        return data

    def on_standard_send_started(self, session: RuntimeSessionApi) -> None:
        return None

    def on_standard_send_finished(self, session: RuntimeSessionApi) -> None:
        return None

    def track_outgoing_query_status(
        self, session: RuntimeSessionApi, data: bytes
    ) -> None:
        return None

    def handle_notification(self, session: RuntimeSessionApi, payload: bytes) -> None:
        return None

    def handle_control_notification(
        self, session: RuntimeSessionApi, payload: bytes
    ) -> None:
        """Receive BLE flow-control notifications separate from printer replies."""

        return None

    async def before_write(
        self, session: RuntimeSessionApi, *, size: int, timeout: float
    ) -> None:
        """Reserve permission for exactly one physical BLE write chunk.

        Returning permits one write. Raising prevents it and aborts subsequent
        chunks. A failed physical write does not refund permission or retry it.
        """

        return None

    def debug_snapshot(self) -> dict[str, Any]:
        return {}

    def debug_update(self, **changes: Any) -> None:
        if changes:
            unknown = ", ".join(sorted(changes.keys()))
            raise KeyError(
                f"Runtime controller does not support debug_update fields: {unknown}"
            )
