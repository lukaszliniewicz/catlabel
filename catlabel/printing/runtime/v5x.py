from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from ...protocol.families.base import SplitWritePlan
from ...protocol.families.v5x import (
    V5X_CONNECT_INIT_PACKET,
    V5X_FINALIZE_PACKET,
    V5X_GET_SERIAL_PACKET,
    V5X_NOTIFY_PAUSE_PACKETS,
    V5X_NOTIFY_RESUME_PACKETS,
    V5X_STATUS_POLL_PACKET,
    build_sign_response,
    split_print_stream,
)
from ...protocol.family import ProtocolFamily
from ...protocol.packet import (
    make_packet,
    prefixed_packet_length,
    prefixed_packet_opcode,
    prefixed_packet_payload,
)
from ...protocol.steps import ProtocolStep, ProtocolStepOperation, ProtocolWriteChannel
from .base import RuntimeController


@dataclass
class _V5XSessionState:
    task_state_name: str = "normal"
    last_density_payload: bytes | None = None
    print_head_type: str = "gaoya"
    firmware_version: str = ""
    connect_info_received: bool = False
    device_serial: str = ""
    serial_valid: bool | None = None
    last_a7_payload: bytes = b""
    last_a9_status: int | None = None
    task_state: int | None = None
    battery_level: int | None = None
    temperature_c: int | None = None
    error_group: int | None = None
    error_code: int | None = None
    last_error_signature: tuple[int, int] | None = None
    status_poll_ack_seen: bool = False
    last_ab_status: int | None = None
    mxw_sign_requested: bool = False
    mxw_sign_responses_sent: int = 0
    pending_sign_responses: set[asyncio.Task[None]] = field(default_factory=set)
    pending_get_serial: asyncio.Task | None = None
    pending_status_poll: asyncio.Task | None = None
    command_ack_events: dict[int, asyncio.Event] = field(default_factory=dict)
    await_start_ready: bool = False
    start_ready_seen: bool = False
    start_ready_event: asyncio.Event | None = None
    connect_info_event: asyncio.Event | None = None


@dataclass(frozen=True)
class _V5XJobContext:
    coverage_ratio: float = 0.0
    is_gray: bool = False


class V5XRuntimeController(RuntimeController):
    _START_READY_MAX_S = 60.0
    _COMPLETION_QUIET_S = 3.0
    _COMPLETION_GRACE_S = 3.0
    _COMPLETION_MAX_S = 60.0

    def __init__(self) -> None:
        self._state = _V5XSessionState()

    def adopt_previous(self, previous: RuntimeController | None) -> None:
        if not isinstance(previous, V5XRuntimeController):
            return
        current_state = self._state
        previous_state = previous._state
        previous_state.pending_get_serial = current_state.pending_get_serial
        previous_state.pending_status_poll = current_state.pending_status_poll
        previous_state.command_ack_events = current_state.command_ack_events
        previous_state.await_start_ready = current_state.await_start_ready
        previous_state.start_ready_seen = current_state.start_ready_seen
        previous_state.start_ready_event = current_state.start_ready_event
        previous_state.connect_info_event = current_state.connect_info_event
        previous_state.pending_sign_responses.update(
            current_state.pending_sign_responses
        )
        self._state = previous_state

    def debug_snapshot(self) -> dict[str, object]:
        return {
            "task_state_name": self._state.task_state_name,
            "last_density_payload": self._state.last_density_payload,
            "print_head_type": self._state.print_head_type,
            "firmware_version": self._state.firmware_version,
            "connect_info_received": self._state.connect_info_received,
            "device_serial": self._state.device_serial,
            "serial_valid": self._state.serial_valid,
            "last_a7_payload": self._state.last_a7_payload,
            "last_a9_status": self._state.last_a9_status,
            "task_state": self._state.task_state,
            "battery_level": self._state.battery_level,
            "temperature_c": self._state.temperature_c,
            "error_group": self._state.error_group,
            "error_code": self._state.error_code,
            "last_error_signature": self._state.last_error_signature,
            "status_poll_ack_seen": self._state.status_poll_ack_seen,
            "last_ab_status": self._state.last_ab_status,
            "mxw_sign_requested": self._state.mxw_sign_requested,
            "mxw_sign_responses_sent": self._state.mxw_sign_responses_sent,
            "pending_command_ack_opcodes": sorted(
                self._state.command_ack_events.keys()
            ),
            "await_start_ready": self._state.await_start_ready,
            "start_ready_seen": self._state.start_ready_seen,
            "has_start_ready_event": self._state.start_ready_event is not None,
            "has_connect_info_event": self._state.connect_info_event is not None,
        }

    def debug_update(self, **changes: object) -> None:
        for key, value in changes.items():
            if not hasattr(self._state, key):
                raise KeyError(f"Unknown V5X debug field '{key}'")
            setattr(self._state, key, value)

    async def initialize_connection(
        self, session, *, mtu_size: int, timeout: float
    ) -> None:
        _ = mtu_size
        self._state.connect_info_event = asyncio.Event()
        await asyncio.sleep(0.2)
        sent = await session.send_control_packet(
            V5X_CONNECT_INIT_PACKET, timeout=timeout
        )
        if not sent:
            raise RuntimeError("V5X connect init send unavailable")

    async def after_initialize(self, session, *, timeout: float) -> None:
        if session.notify_started:
            await self._wait_for_connect_info(session, min(timeout, 0.4))

    async def stop(self, session) -> None:
        pending_background = tuple(
            task
            for task in (
                self._state.pending_get_serial,
                self._state.pending_status_poll,
                *self._state.pending_sign_responses,
            )
            if task is not None
        )
        for task in pending_background:
            task.cancel()
        self._state.pending_get_serial = None
        self._state.pending_status_poll = None
        self._state.pending_sign_responses.clear()
        if pending_background:
            await asyncio.gather(*pending_background, return_exceptions=True)
        self._state.command_ack_events.clear()
        self._clear_start_ready()
        self._state.last_a9_status = None
        self._state.connect_info_event = None

    async def send_payload(self, session, data: bytes, *, timeout: float) -> bool:
        split = split_print_stream(data)
        has_bulk = bool(split.bulk_payload)
        self._validate_split_plan(split, has_bulk=has_bulk)
        self._preflight(session, split, has_bulk=has_bulk)
        await self._execute_split_plan(session, split, timeout=timeout)
        return True

    async def send_protocol_steps(
        self,
        session,
        steps: tuple[ProtocolStep, ...],
        *,
        timeout: float,
    ) -> bool:
        split_result = self._split_protocol_steps(steps)
        if split_result is None:
            return False
        split, has_bulk = split_result
        self._validate_split_plan(split, has_bulk=has_bulk)
        self._preflight(session, split, has_bulk=has_bulk)
        await self._execute_split_plan(session, split, timeout=timeout)
        return True

    def _split_protocol_steps(
        self, steps: tuple[ProtocolStep, ...]
    ) -> tuple[SplitWritePlan, bool] | None:
        if any(
            step.operation is not ProtocolStepOperation.SEND
            or step.write_channel is ProtocolWriteChannel.STANDARD
            for step in steps
        ):
            return None
        leading: list[bytes] = []
        trailing: list[bytes] = []
        bulk_payload = b""
        has_bulk = False
        bulk_seen = False
        for step in steps:
            if step.write_channel is ProtocolWriteChannel.CONTROL:
                (trailing if bulk_seen else leading).append(step.data)
                continue
            if step.write_channel is ProtocolWriteChannel.BULK:
                if has_bulk:
                    raise ValueError("V5X plans may contain at most one bulk step")
                has_bulk = True
                bulk_seen = True
                bulk_payload = step.data
        if not has_bulk:
            start_index = next(
                (
                    index
                    for index, packet in enumerate(leading)
                    if prefixed_packet_opcode(packet, ProtocolFamily.V5X) == 0xA9
                ),
                None,
            )
            if start_index is not None:
                trailing.extend(leading[start_index + 1 :])
                leading = leading[: start_index + 1]
        return (
            SplitWritePlan(
                commands=tuple(leading),
                bulk_payload=bulk_payload,
                trailing_commands=tuple(trailing),
            ),
            has_bulk,
        )

    def _validate_split_plan(self, split: SplitWritePlan, *, has_bulk: bool) -> None:
        packets = split.commands + split.trailing_commands
        if not packets:
            raise ValueError("V5X plans must contain at least one control packet")
        for packet in packets:
            if not self._is_complete_control_packet(packet):
                raise ValueError("V5X control step must contain one complete packet")

        opcodes = [
            prefixed_packet_opcode(packet, ProtocolFamily.V5X) for packet in packets
        ]
        start_indexes = [
            index for index, opcode in enumerate(opcodes) if opcode == 0xA9
        ]
        if len(start_indexes) > 1:
            raise ValueError("V5X plans may contain at most one A9 start command")
        if split.bulk_payload and not has_bulk:
            has_bulk = True
        if has_bulk and not start_indexes:
            raise ValueError("V5X bulk payload requires an A9 start command")

        if start_indexes:
            start_packet = packets[start_indexes[0]]
            if not self._is_valid_start_packet(start_packet):
                raise ValueError("Invalid V5X A9 start command")
            if start_indexes[0] != len(split.commands) - 1:
                raise ValueError("V5X A9 must be the final leading control command")
            if (
                not split.trailing_commands
                or split.trailing_commands[-1] != V5X_FINALIZE_PACKET
            ):
                raise ValueError("V5X A9 job must end with its finalizer")
            if any(opcode == 0xAD for opcode in opcodes[: start_indexes[0]]):
                raise ValueError("V5X finalizer cannot precede the A9 start command")
        else:
            if has_bulk or split.bulk_payload:
                raise ValueError("V5X raster payload requires an A9 start command")
            finalizer_indexes = [
                index for index, opcode in enumerate(opcodes) if opcode == 0xAD
            ]
            if finalizer_indexes and finalizer_indexes != [len(opcodes) - 1]:
                raise ValueError("V5X finalizer must be the last control command")

        if sum(opcode == 0xAD for opcode in opcodes) > 1:
            raise ValueError("V5X plans may contain only one finalizer")

    @staticmethod
    def _is_complete_control_packet(packet: bytes) -> bool:
        packet_length = prefixed_packet_length(packet, 0, ProtocolFamily.V5X)
        return packet_length is not None and packet_length == len(packet)

    @staticmethod
    def _is_valid_start_packet(packet: bytes) -> bool:
        prefix = ProtocolFamily.V5X.require_packet_prefix()
        if not packet.startswith(prefix + b"\xa9\x00\x04\x00"):
            return False
        payload = prefixed_packet_payload(packet, ProtocolFamily.V5X)
        return (
            payload is not None
            and len(payload) == 4
            and payload[2] == 0x30
            and payload[3] in (0x00, 0x01, 0x02)
            and packet.endswith(b"\x00\x00")
        )

    def _preflight(self, session, split: SplitWritePlan, *, has_bulk: bool) -> None:
        if not session.can_send_control_packet():
            raise RuntimeError("V5X control packet send unavailable")
        if (has_bulk or split.bulk_payload) and not session.can_send_bulk_payload():
            raise RuntimeError("V5X bulk payload send unavailable")
        if (
            any(
                prefixed_packet_opcode(packet, ProtocolFamily.V5X) == 0xA9
                for packet in split.commands + split.trailing_commands
            )
            and not session.can_send_control_packet_wait_notification()
        ):
            raise RuntimeError("V5X atomic A9 acknowledgment unavailable")

    async def _execute_split_plan(
        self,
        session,
        split: SplitWritePlan,
        *,
        timeout: float,
    ) -> None:
        split_context = self.build_split_context(session, split)
        density_changed = False
        for packet in split.commands:
            prepared_packet, density_updated = self.prepare_split_command(
                session, packet, split_context
            )
            if prepared_packet is None:
                continue
            packet = prepared_packet
            opcode = prefixed_packet_opcode(packet, ProtocolFamily.V5X)
            if opcode == 0xAD:
                await self._send_finalizer(session, packet, timeout=timeout)
                continue
            density_changed = density_changed or density_updated
            await self.before_split_command(
                session,
                packet,
                split_context,
                timeout=timeout,
                density_updated=density_changed,
            )
            if opcode == 0xA9:
                await self._send_a9_and_validate(session, packet, timeout=timeout)
            else:
                sent = await session.send_control_packet(packet, timeout=timeout)
                if not sent:
                    raise RuntimeError("V5X control packet send unavailable")
            if density_updated:
                density_payload = prefixed_packet_payload(packet, ProtocolFamily.V5X)
                if density_payload is not None:
                    self._state.last_density_payload = density_payload

        if split.bulk_payload:
            sent = await session.send_bulk_payload(split.bulk_payload, timeout=timeout)
            if not sent:
                raise RuntimeError("V5X bulk payload send unavailable")

        for packet in split.trailing_commands:
            if packet == V5X_FINALIZE_PACKET:
                await self._send_finalizer(session, packet, timeout=timeout)
                continue
            sent = await session.send_control_packet(packet, timeout=timeout)
            if not sent:
                raise RuntimeError("V5X trailing control packet send unavailable")

    async def _send_a9_and_validate(
        self, session, packet: bytes, *, timeout: float
    ) -> None:
        ack_token = self.arm_command_ack(session, packet)
        self._state.last_a9_status = None
        try:
            reply = await session.send_control_packet_wait_notification(
                packet,
                label="V5X command ack 0xa9",
                match=self._is_valid_a9_notification,
                timeout=timeout,
                required=True,
            )
            status = self._extract_status_byte(session, reply or b"")
            self._state.last_a9_status = status
            self._validate_command_ack(0xA9)
        finally:
            self.clear_command_ack(session, ack_token)

    @staticmethod
    def _is_valid_a9_notification(payload: bytes) -> bool:
        prefix = ProtocolFamily.V5X.require_packet_prefix()
        if len(payload) == len(prefix) + 4:
            return payload.startswith(prefix + b"\xa9")
        packet_length = prefixed_packet_length(payload, 0, ProtocolFamily.V5X)
        raw = prefixed_packet_payload(payload, ProtocolFamily.V5X)
        return (
            payload.startswith(prefix + b"\xa9")
            and packet_length == len(payload)
            and raw is not None
            and len(raw) >= 1
        )

    async def _send_finalizer(self, session, packet: bytes, *, timeout: float) -> None:
        self._arm_start_ready()
        try:
            sent = await session.send_control_packet(packet, timeout=timeout)
            if not sent:
                raise RuntimeError("V5X finalizer send unavailable")
        except BaseException:
            self._clear_start_ready()
            raise

    def build_split_context(self, session, split) -> _V5XJobContext:
        is_gray = False
        for packet in split.commands:
            if prefixed_packet_opcode(packet, ProtocolFamily.V5X) != 0xA9:
                continue
            payload = prefixed_packet_payload(packet, ProtocolFamily.V5X)
            if payload is None:
                continue
            if len(payload) >= 4:
                is_gray = payload[3] == 0x02
            break
        coverage_ratio = 0.0
        if split.bulk_payload and not is_gray:
            total_bits = len(split.bulk_payload) * 8
            if total_bits > 0:
                black_bits = sum(chunk.bit_count() for chunk in split.bulk_payload)
                coverage_ratio = black_bits / total_bits
        return _V5XJobContext(coverage_ratio=coverage_ratio, is_gray=is_gray)

    def prepare_split_command(
        self, session, packet: bytes, split_context: _V5XJobContext
    ) -> tuple[bytes | None, bool]:
        opcode = prefixed_packet_opcode(packet, ProtocolFamily.V5X)
        if opcode != 0xA2:
            return packet, False
        payload = prefixed_packet_payload(packet, ProtocolFamily.V5X)
        if payload is None:
            return packet, False
        adjusted_payload = self._adjust_density_payload(payload, split_context)
        if adjusted_payload != payload:
            packet = make_packet(0xA2, adjusted_payload, ProtocolFamily.V5X)
            payload = adjusted_payload
        if self._state.last_density_payload == payload:
            session.report_debug(
                f"skipping unchanged V5X density packet: {payload.hex()}"
            )
            return None, False
        return packet, True

    async def before_split_command(
        self,
        session,
        packet: bytes,
        split_context: _V5XJobContext,
        *,
        timeout: float,
        density_updated: bool,
    ) -> None:
        opcode = prefixed_packet_opcode(packet, ProtocolFamily.V5X)
        if opcode in (0xA2, 0xA9):
            await self._wait_for_start_ready(session, timeout)
        if opcode == 0xA9:
            delay_ms = self._compute_start_delay_ms(
                split_context, density_updated=density_updated
            )
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

    def arm_command_ack(
        self, session, packet: bytes
    ) -> tuple[int, asyncio.Event] | None:
        opcode = prefixed_packet_opcode(packet, ProtocolFamily.V5X)
        if opcode != 0xA9:
            return None
        event = asyncio.Event()
        self._state.command_ack_events[opcode] = event
        return opcode, event

    def clear_command_ack(self, session, ack_token) -> None:
        if ack_token is None:
            return
        opcode, event = ack_token
        if self._state.command_ack_events.get(opcode) is event:
            self._state.command_ack_events.pop(opcode, None)

    async def wait_for_completion(self, session, *, timeout: float) -> None:
        # V5X devices stream A1 state while the mechanism is moving. Waiting is
        # passive: polling A3 here would move paper on affected firmware.
        self._clear_start_ready()
        if not session.can_wait_for_notification():
            return
        session.report_debug("V5X waiting for print completion before disconnect")
        deadline = time.monotonic() + self._COMPLETION_MAX_S
        capped = True
        while time.monotonic() < deadline:
            frame = await session.wait_for_notification(
                "V5X print completion 0xa1",
                lambda payload: (
                    prefixed_packet_opcode(payload, ProtocolFamily.V5X) == 0xA1
                ),
                timeout=self._COMPLETION_QUIET_S,
                required=False,
            )
            if frame is None:
                session.report_debug("V5X status quiet; print assumed finished")
                capped = False
                break
            raw = prefixed_packet_payload(frame, ProtocolFamily.V5X)
            if raw and raw[0] == 0x00:
                session.report_debug("V5X reported idle (task_state=0); print finished")
                capped = False
                break
        if capped:
            session.report_debug(
                "V5X completion wait hit max cap; disconnecting anyway"
            )
        if self._COMPLETION_GRACE_S > 0:
            await asyncio.sleep(self._COMPLETION_GRACE_S)

    def handle_notification(self, session, payload: bytes) -> None:
        if payload in V5X_NOTIFY_PAUSE_PACKETS:
            session.set_flow_paused(True, payload=payload)
            return
        if payload in V5X_NOTIFY_RESUME_PACKETS:
            session.set_flow_paused(False, payload=payload)
            return
        opcode = prefixed_packet_opcode(payload, ProtocolFamily.V5X)
        if opcode == 0xA7:
            self._update_info_from_a7(session, payload)
        elif opcode == 0xA1:
            self._update_status(session, payload)
        elif opcode == 0xA3:
            self._mark_status_poll_ack(session)
        elif opcode == 0xA6:
            self._schedule_get_serial(session)
        elif opcode == 0xAA:
            self._release_start_ready(session)
        elif opcode == 0xA9:
            if self._is_valid_a9_notification(payload):
                self._release_command_ack(session, 0xA9)
        elif opcode == 0xAB:
            self._update_ab_status(session, payload)
        elif opcode == 0xB0:
            self._update_head_type_from_b0(session, payload)
        elif opcode == 0xB1:
            self._update_info_from_b1(session, payload)
            self._release_connect_info(session)
        elif opcode == 0xB2:
            self._schedule_status_poll(session)
        elif opcode == 0xB3:
            self._schedule_sign_response(session, payload)

    async def _wait_for_start_ready(self, session, timeout: float) -> None:
        event = self._state.start_ready_event
        if not self._state.await_start_ready or event is None:
            return
        try:
            wait_timeout = max(timeout, self._START_READY_MAX_S)
            await asyncio.wait_for(event.wait(), timeout=wait_timeout)
        except TimeoutError:
            self._clear_start_ready()
            raise TimeoutError("Timed out waiting for V5X start ready 0xaa") from None
        self._clear_start_ready()

    def _arm_start_ready(self) -> None:
        self._state.await_start_ready = True
        self._state.start_ready_seen = False
        self._state.start_ready_event = asyncio.Event()

    def _clear_start_ready(self) -> None:
        self._state.await_start_ready = False
        self._state.start_ready_seen = False
        self._state.start_ready_event = None

    async def _wait_for_connect_info(self, session, timeout: float) -> None:
        if self._state.connect_info_event is None:
            return
        event = self._state.connect_info_event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            session.report_debug(
                "V5X connect info was not received during the initial settle window"
            )
        finally:
            if self._state.connect_info_event is event:
                self._state.connect_info_event = None

    def _release_command_ack(self, session, opcode: int) -> None:
        event = self._state.command_ack_events.pop(opcode, None)
        if event is not None and not event.is_set():
            event.set()
            session.report_debug(f"command ack: 0x{opcode:02x}")

    def _release_start_ready(self, session) -> None:
        if (
            not self._state.await_start_ready
            or self._state.start_ready_event is None
            or self._state.start_ready_event.is_set()
        ):
            return
        self._state.start_ready_seen = True
        self._state.start_ready_event.set()
        session.report_debug("start ready: 0xaa")

    def _release_connect_info(self, session) -> None:
        if (
            self._state.connect_info_event is None
            or self._state.connect_info_event.is_set()
        ):
            return
        self._state.connect_info_event.set()
        session.report_debug("connect info ready: 0xb1")

    def _schedule_status_poll(self, session) -> None:
        if (
            self._state.pending_status_poll is not None
            and not self._state.pending_status_poll.done()
        ):
            return
        if not session.can_send_control_packet():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._state.pending_status_poll = loop.create_task(
            self._send_status_poll(session)
        )
        self._state.pending_status_poll.add_done_callback(
            lambda _task: setattr(self._state, "pending_status_poll", None)
        )

    def _schedule_get_serial(self, session) -> None:
        if (
            self._state.pending_get_serial is not None
            and not self._state.pending_get_serial.done()
        ):
            return
        if not session.can_send_control_packet():
            return
        if self._state.await_start_ready:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._state.pending_get_serial = loop.create_task(
            self._send_command(session, V5X_GET_SERIAL_PACKET)
        )
        self._state.pending_get_serial.add_done_callback(
            lambda _task: setattr(self._state, "pending_get_serial", None)
        )

    async def _send_status_poll(self, session) -> None:
        await asyncio.sleep(0.7)
        await self._send_command(session, V5X_STATUS_POLL_PACKET)
        session.report_debug("scheduled status poll: 0xa3")

    async def _send_command(self, session, packet: bytes) -> None:
        await session.send_control_packet(packet, timeout=1.0)

    def _validate_command_ack(self, opcode: int) -> None:
        if opcode != 0xA9:
            return
        status = self._state.last_a9_status
        if status is None:
            raise RuntimeError("V5X start print response did not include a status byte")
        if status != 0x00:
            raise RuntimeError(f"V5X start print was rejected (status=0x{status:02x})")

    def _adjust_density_payload(self, payload: bytes, context: _V5XJobContext) -> bytes:
        if len(payload) != 1:
            return payload
        user_density = payload[0]
        temperature_c = self._state.temperature_c or 0
        coverage_ratio = context.coverage_ratio
        head_type = self._state.print_head_type
        is_gray = context.is_gray
        if is_gray:
            target_density = self._gray_density_target(
                temperature_c, user_density, head_type
            )
        else:
            target_density = self._dot_density_target(
                temperature_c, user_density, head_type, coverage_ratio
            )
        target_density = max(0, min(user_density, target_density))
        return bytes([target_density])

    def _compute_start_delay_ms(
        self, context: _V5XJobContext, *, density_updated: bool
    ) -> int:
        # High-coverage gaoya heads need a noticeably longer settle window
        # before the print-start command becomes reliable.
        if self._state.print_head_type == "gaoya" and context.coverage_ratio > 0.4:
            return 200
        if density_updated:
            return 60
        return 0

    @staticmethod
    def _coverage_band(coverage_ratio: float) -> int:
        if coverage_ratio <= 0.4:
            return 1
        if coverage_ratio < 0.5:
            return 2
        if coverage_ratio < 0.7:
            return 3
        return 4

    def _gray_density_target(
        self, temperature_c: int, user_density: int, head_type: str
    ) -> int:
        # Gray-mode thresholds are head-specific lookup tables rather than a
        # smooth formula.
        if head_type == "gaoya":
            thresholds = ((70, 56), (65, 65), (60, 75), (55, 80), (50, 85))
        else:
            thresholds = ((70, 56), (65, 60), (60, 65), (55, 75), (50, 80))
        for threshold, value in thresholds:
            if temperature_c >= threshold:
                return min(user_density, value)
        return user_density

    def _dot_density_target(
        self,
        temperature_c: int,
        user_density: int,
        head_type: str,
        coverage_ratio: float,
    ) -> int:
        if temperature_c <= 60:
            return user_density
        band = self._coverage_band(coverage_ratio)
        # Dot-mode fallback uses one table per head type and temperature band,
        # then picks a slot based on black coverage.
        if head_type == "gaoya":
            values = (
                (48, 15, 15, 10)
                if temperature_c < 65
                else ((36, 9, 5, 5) if temperature_c < 70 else (22, 5, 3, 3))
            )
        else:
            values = (
                (60, 50, 50, 30)
                if temperature_c <= 65
                else ((50, 40, 40, 20) if temperature_c <= 70 else (40, 30, 30, 10))
            )
        return min(user_density, values[band - 1])

    def _update_info_from_a7(self, session, payload: bytes) -> None:
        raw = prefixed_packet_payload(payload, ProtocolFamily.V5X)
        if raw is None:
            return
        self._state.last_a7_payload = raw
        serial_hex = raw[:6].hex()
        self._state.device_serial = serial_hex
        self._state.serial_valid = bool(serial_hex) and serial_hex not in {
            "000000000000",
            "ffffffffffff",
        }

    def _extract_status_byte(self, session, payload: bytes) -> int | None:
        raw = prefixed_packet_payload(payload, ProtocolFamily.V5X)
        packet_length = prefixed_packet_length(payload, 0, ProtocolFamily.V5X)
        if raw and packet_length == len(payload):
            return raw[0]
        prefix = ProtocolFamily.V5X.require_packet_prefix()
        if (
            len(payload) != len(prefix) + 4
            or payload[: len(prefix) + 1] != prefix + b"\xa9"
        ):
            return None
        return payload[-2]

    def _update_status(self, session, payload: bytes) -> None:
        raw = prefixed_packet_payload(payload, ProtocolFamily.V5X)
        if raw is None or len(raw) < 8:
            return
        self._state.task_state = raw[0]
        self._state.task_state_name = self._task_state_name(raw[0])
        self._state.battery_level = raw[3]
        self._state.temperature_c = raw[4]
        self._state.error_group = raw[6]
        self._state.error_code = raw[7]
        self._handle_error_state(session, raw[6], raw[7])

    @staticmethod
    def _task_state_name(task_state: int) -> str:
        if task_state == 0x00:
            return "normal"
        if task_state == 0x01:
            return "printing"
        if task_state == 0x02:
            return "feeding"
        if task_state == 0x03:
            return "retracting"
        return f"0x{task_state:02x}"

    def _handle_error_state(self, session, error_group: int, error_code: int) -> None:
        signature = (error_group, error_code)
        if signature == (0x00, 0x00):
            self._state.last_error_signature = signature
            return
        if self._state.last_error_signature == signature:
            return
        self._state.last_error_signature = signature
        session.report_warning(
            short="V5X printer reported an error status",
            detail=(
                f"Task={self._state.task_state_name}, "
                f"error_group=0x{error_group:02x}, error_code=0x{error_code:02x}."
            ),
        )

    def _mark_status_poll_ack(self, session) -> None:
        self._state.status_poll_ack_seen = True
        session.report_debug("V5X status poll acknowledged: 0xa3")

    def _update_ab_status(self, session, payload: bytes) -> None:
        raw = prefixed_packet_payload(payload, ProtocolFamily.V5X)
        if not raw:
            return
        self._state.last_ab_status = raw[-1]

    def _schedule_sign_response(self, session, payload: bytes) -> None:
        self._state.mxw_sign_requested = True
        challenge = prefixed_packet_payload(payload, ProtocolFamily.V5X)
        if challenge is None or len(challenge) < 10:
            session.report_warning(
                short="V5X signing challenge was invalid",
                detail="A B3 challenge requires ten bytes; no response was sent.",
            )
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            session.report_warning(
                short="V5X signing response could not be scheduled",
                detail="No active runtime event loop was available for the B3 response.",
            )
            return
        packet = build_sign_response(
            challenge[:10], timestamp_ms=int(time.time() * 1000)
        )
        task = loop.create_task(self._send_sign_response(session, packet))
        self._state.pending_sign_responses.add(task)
        task.add_done_callback(
            lambda completed: self._state.pending_sign_responses.discard(completed)
        )

    async def _send_sign_response(self, session, packet: bytes) -> None:
        try:
            if not await session.send_control_packet(packet, timeout=1.0):
                raise RuntimeError("V5X signing response send unavailable")
        except Exception as exc:
            session.report_warning(
                short="V5X signing response could not be sent",
                detail=str(exc),
            )
            return
        self._state.mxw_sign_responses_sent += 1
        session.report_debug("V5X local signing response sent: 0xb3")

    def _update_head_type_from_b0(self, session, payload: bytes) -> None:
        raw = prefixed_packet_payload(payload, ProtocolFamily.V5X)
        if not raw:
            return
        value = raw[0]
        if value == 0x01:
            self._state.print_head_type = "gaoya"
        elif value == 0xFF:
            self._state.print_head_type = "weishibie"
        else:
            self._state.print_head_type = "diya"

    def _update_info_from_b1(self, session, payload: bytes) -> None:
        raw = prefixed_packet_payload(payload, ProtocolFamily.V5X)
        if not raw:
            return
        self._state.connect_info_received = True
        firmware = raw.decode("ascii", errors="ignore").rstrip("\x00")
        if not firmware:
            return
        self._state.firmware_version = firmware
        marker = firmware[-1]
        if marker == "2":
            self._state.print_head_type = "gaoya"
        elif marker == "1":
            self._state.print_head_type = "diya"
        else:
            self._state.print_head_type = "weishibie"
