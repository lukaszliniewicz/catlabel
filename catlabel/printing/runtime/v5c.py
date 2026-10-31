from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass

from ...protocol.families.v5c import (
    V5C_CONNECT_INIT_PACKET,
    V5C_NOTIFY_PAUSE,
    V5C_NOTIFY_RESUME,
    V5C_QUERY_STATUS_PACKET,
)
from ...protocol.family import ProtocolFamily
from ...protocol.job import ProtocolJob
from ...protocol.packet import PrefixedPacket, PrefixedPacketStreamDecoder
from ...protocol.steps import (
    ProtocolStep,
    ProtocolStepOperation,
    ProtocolWriteChannel,
)
from .base import RuntimeController, RuntimeSessionApi

_COMPLETION_TIMEOUT_SEC = 60.0
_SETUP_LABEL = "V5C setup"
_RASTER_LABEL = "V5C raster"
_FINALIZE_LABEL = "V5C finalize"
_PHASE_LABELS = (_SETUP_LABEL, _RASTER_LABEL, _FINALIZE_LABEL)
_HEALTHY_STATUSES = frozenset((0x00, 0x80, 0x10, 0x11))
_FAULT_NAMES = {
    0x01: "paper_out",
    0x02: "paper_out",
    0x03: "paper_out",
    0x04: "overheated",
    0x08: "low_battery",
}


@dataclass
class _V5CSessionState:
    status_code: int | None = None
    status_name: str = "unknown"
    is_charging: bool = False
    query_status_in_flight: bool = False
    print_complete_seen: bool = False
    max_print_height: int | None = None
    device_serial: str = ""
    serial_valid: bool | None = None
    last_auth_payload: bytes = b""
    last_error_status: int | None = None


@dataclass
class _V5CJobScope:
    wait_requested: bool
    loop: asyncio.AbstractEventLoop
    changed: asyncio.Event
    completion_fence: int | None = None
    finished: bool = False
    error: RuntimeError | None = None


class V5CRuntimeController(RuntimeController):
    """V5C faults from TiMini-Print v0.9.1, adapted to scoped local completion.

    Source: fea985b20dbfe06067be122b4b28c5e39b8fb48a. CatLabel additionally
    fences completion at the first byte of a fresh finalizer-phase reply.
    """

    def __init__(self) -> None:
        self._state = _V5CSessionState()
        self._decoder = PrefixedPacketStreamDecoder(ProtocolFamily.V5C)
        self._lock = threading.RLock()
        self._active_scope: _V5CJobScope | None = None
        self._scope_open = False
        self._observing = False
        self._scope_context: ContextVar[_V5CJobScope | None] = ContextVar(
            "v5c_runtime_scope", default=None
        )

    def adopt_previous(self, previous: RuntimeController | None) -> None:
        if type(previous) is not type(self) or not isinstance(
            previous, V5CRuntimeController
        ):
            return
        controllers = sorted((self, previous), key=id)
        with controllers[0]._lock, controllers[1]._lock:
            if self._scope_open or previous._scope_open:
                return
            # The prior controller is no longer attached after adoption. Reuse
            # its stream decoder to preserve an in-flight partial notification.
            self._decoder = previous._decoder
            self._state = _V5CSessionState(**vars(previous._state))
            self._observing = previous._observing

    async def initialize_connection(
        self,
        session: RuntimeSessionApi,
        *,
        mtu_size: int,
        timeout: float,
    ) -> None:
        _ = mtu_size
        with self._lock:
            self._observing = session.can_wait_for_notification()
        await asyncio.sleep(0.6)
        sent = await session.send_control_packet(
            V5C_CONNECT_INIT_PACKET, timeout=timeout
        )
        if not sent:
            raise RuntimeError("V5C connect init send unavailable")

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
                raise RuntimeError("V5C already has an active print job")
            if self._state.last_error_status is not None:
                raise self._fault_error(self._state.last_error_status)
            if job.wait_for_completion and not (
                self._observing and session.can_wait_for_notification()
            ):
                raise RuntimeError(
                    "V5C completion observer unavailable before print job"
                )
            scope = _V5CJobScope(
                wait_requested=job.wait_for_completion,
                loop=asyncio.get_running_loop(),
                changed=asyncio.Event(),
            )
            self._scope_open = True
            self._active_scope = scope
        token = self._scope_context.set(scope)
        try:
            yield
        except BaseException:
            self._scope_context.reset(token)
            with self._lock:
                if self._active_scope is scope:
                    self._active_scope = None
                self._scope_open = False
            raise
        else:
            self._scope_context.reset(token)
            with self._lock:
                error = scope.error
                if error is None and scope.wait_requested and not scope.finished:
                    error = TimeoutError(
                        "V5C page completion was not current at job scope exit"
                    )
                if self._active_scope is scope:
                    self._active_scope = None
                self._scope_open = False
            if error is not None:
                raise error

    async def stop(self, session: RuntimeSessionApi) -> None:
        _ = session
        with self._lock:
            scope = self._active_scope
            if scope is not None:
                if scope.error is None:
                    scope.error = RuntimeError(
                        "V5C connection closed before job completion"
                    )
                scope.finished = True
                self._wake_scope(scope)
            self._observing = False

    def handle_notification(self, session: RuntimeSessionApi, payload: bytes) -> None:
        with self._lock:
            packets = self._decoder.feed(payload)
            for packet in packets:
                self._handle_packet(session, packet)

    def _handle_packet(
        self, session: RuntimeSessionApi, packet: PrefixedPacket
    ) -> None:
        if packet.raw == V5C_NOTIFY_PAUSE:
            session.set_flow_paused(True, payload=packet.raw)
        elif packet.raw == V5C_NOTIFY_RESUME:
            session.set_flow_paused(False, payload=packet.raw)
        elif packet.opcode == 0xA1:
            self._update_status(session, packet)
        elif packet.opcode == 0xAA:
            self._update_max_print_height(packet.payload)
        elif packet.opcode in (0xA8, 0xA9):
            self._update_identity(packet.payload, packet.opcode)

    def track_outgoing_query_status(
        self, session: RuntimeSessionApi, data: bytes
    ) -> None:
        _ = session
        with self._lock:
            self._state.query_status_in_flight = V5C_QUERY_STATUS_PACKET in data

    def _update_status(
        self, session: RuntimeSessionApi, packet: PrefixedPacket
    ) -> None:
        if not packet.payload:
            return
        status = packet.payload[0]
        previous_status = self._state.status_code
        self._state.status_code = status
        self._state.status_name = self._status_name(status)
        self._state.is_charging = status in (0x10, 0x11)
        if status == 0x80:
            self._state.print_complete_seen = False
        elif status == 0x00:
            self._state.query_status_in_flight = False
            if previous_status == 0x80:
                self._state.print_complete_seen = True
        self._handle_status(session, status)
        self._record_job_status(status, packet.start_offset)

    @staticmethod
    def _status_name(status: int) -> str:
        if status == 0x00:
            return "normal"
        if status == 0x80:
            return "printing"
        if status in (0x10, 0x11):
            return "charging"
        if status in (0x01, 0x02, 0x03):
            return "attention"
        if status == 0x04:
            return "overheat"
        if status == 0x08:
            return "low_power"
        return f"0x{status:02x}"

    def _handle_status(self, session: RuntimeSessionApi, status: int) -> None:
        if status in _HEALTHY_STATUSES:
            if self._active_scope is None:
                self._state.last_error_status = None
            return
        if self._state.last_error_status == status:
            return
        self._state.last_error_status = status
        if status in (0x01, 0x02, 0x03):
            short = "V5C printer reported a paper-out state"
        elif status == 0x04:
            short = "V5C printer reported an overheat state"
        elif status == 0x08:
            short = "V5C printer reported a low-battery state"
        else:
            short = "V5C printer reported an error status"
        session.report_warning(
            short=short,
            detail=f"status=0x{status:02x} ({self._state.status_name}).",
        )

    def _record_job_status(self, status: int, start_offset: int) -> None:
        scope = self._active_scope
        if scope is None:
            return
        fault_name = _FAULT_NAMES.get(status)
        if status not in _HEALTHY_STATUSES and fault_name is None:
            fault_name = "printer_error"
        if fault_name is not None:
            if scope.error is None:
                scope.error = self._fault_error(status)
            scope.finished = True
            self._wake_scope(scope)
            return
        if status == 0x80:
            # An idle candidate followed by busy in the same notification batch
            # is not a page-completion edge.
            if scope.finished and scope.error is None:
                scope.finished = False
                self._wake_scope(scope)
            return
        if (
            status == 0x00
            and scope.wait_requested
            and scope.completion_fence is not None
            and start_offset >= scope.completion_fence
            and scope.error is None
        ):
            scope.finished = True
            self._wake_scope(scope)

    @staticmethod
    def _fault_error(status: int) -> RuntimeError:
        name = _FAULT_NAMES.get(status, "printer_error")
        return RuntimeError(f"V5C printer reported {name} (status=0x{status:02x})")

    @staticmethod
    def _wake_scope(scope: _V5CJobScope) -> None:
        with suppress(RuntimeError):
            scope.loop.call_soon_threadsafe(scope.changed.set)

    def _raise_scope_error(self, scope: _V5CJobScope) -> None:
        if scope.error is not None:
            raise scope.error

    def _scope_is_finished(self, scope: _V5CJobScope) -> bool:
        with self._lock:
            return scope.finished or scope.error is not None

    async def wait_for_completion(
        self,
        session: RuntimeSessionApi,
        *,
        timeout: float,
    ) -> None:
        scope = self._scope_context.get()
        if scope is None:
            raise RuntimeError("V5C completion wait requires an active job")
        if not scope.wait_requested:
            with self._lock:
                self._raise_scope_error(scope)
            return

        deadline = asyncio.get_running_loop().time() + max(
            timeout, _COMPLETION_TIMEOUT_SEC
        )
        while True:
            with self._lock:
                self._raise_scope_error(scope)
                if scope.finished:
                    return
                if not self._observing or not session.can_wait_for_notification():
                    raise RuntimeError("V5C completion observer unavailable")
                scope.changed.clear()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for fresh V5C page completion")

            notification_wait = asyncio.create_task(
                session.wait_for_notification(
                    "V5C print completion",
                    lambda _payload: self._scope_is_finished(scope),
                    timeout=remaining,
                    required=False,
                )
            )
            changed_wait = asyncio.create_task(scope.changed.wait())
            try:
                done, _ = await asyncio.wait(
                    (notification_wait, changed_wait),
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except BaseException:
                notification_wait.cancel()
                changed_wait.cancel()
                await asyncio.gather(
                    notification_wait, changed_wait, return_exceptions=True
                )
                raise
            if changed_wait in done:
                notification_wait.cancel()
                await asyncio.gather(notification_wait, return_exceptions=True)
                with self._lock:
                    self._raise_scope_error(scope)
                    if scope.finished:
                        return
                    scope.changed.clear()
                continue
            changed_wait.cancel()
            await asyncio.gather(changed_wait, return_exceptions=True)
            await notification_wait
            with self._lock:
                self._raise_scope_error(scope)
                if scope.finished:
                    return
            raise TimeoutError("Timed out waiting for fresh V5C page completion")

    async def send_payload(
        self,
        session: RuntimeSessionApi,
        data: bytes,
        *,
        timeout: float,
    ) -> bool:
        phases = self._parse_raw_job(data)
        await self._send_phases(session, phases, timeout=timeout)
        return True

    async def send_protocol_steps(
        self,
        session: RuntimeSessionApi,
        steps: tuple[ProtocolStep, ...],
        *,
        timeout: float,
    ) -> bool:
        phases = self._validate_steps(steps)
        await self._send_phases(session, phases, timeout=timeout)
        return True

    async def before_write(
        self,
        session: RuntimeSessionApi,
        *,
        size: int,
        timeout: float,
    ) -> None:
        _ = session, size, timeout
        with self._lock:
            scope = self._active_scope
            if scope is not None:
                self._raise_scope_error(scope)

    async def _send_phases(
        self,
        session: RuntimeSessionApi,
        phases: tuple[bytes, bytes, bytes],
        *,
        timeout: float,
    ) -> None:
        if not session.can_send_standard_payload():
            raise RuntimeError("V5C standard payload send unavailable")
        _ = timeout
        scope = self._scope_context.get()
        if scope is None:
            raise RuntimeError("V5C sends require an active print job")

        for index, phase in enumerate(phases):
            with self._lock:
                self._raise_scope_error(scope)
                if index == 2:
                    # Fence immediately before the finalizer phase begins. Bytes
                    # for any already-buffered frame retain their older offsets.
                    scope.completion_fence = self._decoder.received_byte_count
            await session.send_standard_payload(phase)
            # The transport calls before_write for every physical chunk; this
            # check also covers non-BLE standard-send implementations.
            with self._lock:
                self._raise_scope_error(scope)

    def _parse_raw_job(self, data: bytes) -> tuple[bytes, bytes, bytes]:
        packets = self._decode_complete_frames(data)
        return self._group_packets(packets)

    @staticmethod
    def _decode_complete_frames(data: bytes) -> tuple[PrefixedPacket, ...]:
        decoder = PrefixedPacketStreamDecoder(ProtocolFamily.V5C)
        packets = decoder.feed(data)
        if not packets or b"".join(packet.raw for packet in packets) != data:
            raise ValueError("V5C payload must contain only complete valid frames")
        return packets

    @classmethod
    def _validate_steps(
        cls, steps: tuple[ProtocolStep, ...]
    ) -> tuple[bytes, bytes, bytes]:
        if len(steps) != 3:
            raise ValueError("V5C plans must contain exactly three phases")
        if tuple(step.label for step in steps) != _PHASE_LABELS:
            raise ValueError("V5C plan phases have unexpected names")
        if any(
            step.operation is not ProtocolStepOperation.SEND
            or step.write_channel is not ProtocolWriteChannel.STANDARD
            or not step.include_in_payload
            for step in steps
        ):
            raise ValueError("V5C phases must be included standard SEND steps")
        packets_by_phase = tuple(
            cls._decode_complete_frames(step.data) for step in steps
        )
        grouped = cls._group_packets(
            tuple(packet for group in packets_by_phase for packet in group)
        )
        if grouped != tuple(step.data for step in steps):
            raise ValueError("V5C step data does not match setup/raster/finalize order")
        return grouped

    @staticmethod
    def _group_packets(
        packets: tuple[PrefixedPacket, ...],
    ) -> tuple[bytes, bytes, bytes]:
        opcodes = tuple(packet.opcode for packet in packets)
        if len(packets) < 5 or opcodes[:2] != (0xA2, 0xA3):
            raise ValueError("V5C job must start with A2 settings and A3 start")
        if opcodes[-2:] != (0xA6, 0xA1):
            raise ValueError("V5C job must end with A6 finalizer and A1 status query")
        raster_opcodes = opcodes[2:-2]
        if (
            not raster_opcodes
            or len(set(raster_opcodes)) != 1
            or raster_opcodes[0] not in (0xA4, 0xA5)
        ):
            raise ValueError("V5C job requires one or more uniform A4/A5 raster frames")
        if (
            packets[0].flags != 0
            or len(packets[0].payload) != 2
            or packets[0].payload[0] not in (0x01, 0x02, 0x03)
            or packets[0].payload[1] not in (0x01, 0x02)
        ):
            raise ValueError("V5C A2 settings packet has an invalid shape")
        if packets[1].flags != 0 or packets[1].payload != b"\x01":
            raise ValueError("V5C A3 start packet has an invalid shape")
        for packet in packets[2:-2]:
            if packet.flags != 0 or not packet.payload:
                raise ValueError("V5C raster frame has an invalid shape")
            if packet.opcode == 0xA5:
                if len(packet.payload) < 5:
                    raise ValueError("V5C A5 raster frame has an invalid shape")
                raw_length = int.from_bytes(packet.payload[:2], "little")
                compressed_length = int.from_bytes(packet.payload[2:4], "little")
                if raw_length == 0 or compressed_length != len(packet.payload) - 4:
                    raise ValueError("V5C A5 raster lengths do not match its payload")
        if (
            raster_opcodes[0] == 0xA4
            and len({len(packet.payload) for packet in packets[2:-2]}) != 1
        ):
            raise ValueError("V5C A4 raster rows must have a consistent width")
        if packets[-2].flags != 0 or packets[-2].payload != b"\x30\x00":
            raise ValueError("V5C A6 finalizer packet has an invalid shape")
        if packets[-1].raw != V5C_QUERY_STATUS_PACKET:
            raise ValueError("V5C final A1 packet must be the status query")
        return (
            b"".join(packet.raw for packet in packets[:2]),
            b"".join(packet.raw for packet in packets[2:-2]),
            b"".join(packet.raw for packet in packets[-2:]),
        )

    def _update_max_print_height(self, raw: bytes) -> None:
        if len(raw) < 4:
            return
        height = int.from_bytes(raw[:4], "little")
        if height > 0:
            self._state.max_print_height = height

    def _update_identity(self, raw: bytes, opcode: int) -> None:
        self._state.last_auth_payload = raw
        if opcode == 0xA8:
            self._state.device_serial = ""
            self._state.serial_valid = None
            return
        serial_hex = raw[:8].hex()
        self._state.device_serial = serial_hex
        self._state.serial_valid = bool(serial_hex) and int(serial_hex, 16) != 0

    def debug_snapshot(self) -> dict[str, object]:
        with self._lock:
            scope = self._active_scope
            return {
                "status_code": self._state.status_code,
                "status_name": self._state.status_name,
                "is_charging": self._state.is_charging,
                "query_status_in_flight": self._state.query_status_in_flight,
                "print_complete_seen": self._state.print_complete_seen,
                "max_print_height": self._state.max_print_height,
                "device_serial": self._state.device_serial,
                "serial_valid": self._state.serial_valid,
                "last_auth_payload": self._state.last_auth_payload,
                "last_error_status": self._state.last_error_status,
                "active": self._scope_open,
                "completion_finished": False if scope is None else scope.finished,
                "completion_fence": None if scope is None else scope.completion_fence,
                "completion_error": (
                    None if scope is None or scope.error is None else str(scope.error)
                ),
                "received_byte_count": self._decoder.received_byte_count,
                "observing": self._observing,
            }

    def debug_update(self, **changes: object) -> None:
        with self._lock:
            for key, value in changes.items():
                if not hasattr(self._state, key):
                    raise KeyError(f"Unknown V5C debug field '{key}'")
                setattr(self._state, key, value)
