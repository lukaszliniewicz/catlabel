from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from ...protocol.families import split_prefixed_bulk_stream
from ...protocol.families.v5x import (
    V5X_CONNECT_INIT_PACKET,
    V5X_FINALIZE_PACKET,
    V5X_GET_SERIAL_PACKET,
    V5X_GRAY_MODE_SUFFIX,
    V5X_NOTIFY_PAUSE_PACKETS,
    V5X_NOTIFY_RESUME_PACKETS,
    V5X_STATUS_POLL_PACKET,
)
from ...protocol.family import ProtocolFamily
from ...protocol.packet import (
    make_packet,
    prefixed_packet_opcode,
    prefixed_packet_payload,
)
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
    pending_get_serial: asyncio.Task | None = None
    pending_status_poll: asyncio.Task | None = None
    command_ack_events: dict[int, asyncio.Event] = field(default_factory=dict)
    start_ready_event: asyncio.Event | None = None
    connect_info_event: asyncio.Event | None = None


@dataclass(frozen=True)
class _V5XJobContext:
    coverage_ratio: float = 0.0
    is_gray: bool = False


class V5XRuntimeController(RuntimeController):
    _COMPLETION_QUIET_S = 3.0
    _COMPLETION_GRACE_S = 3.0
    _COMPLETION_MAX_S = 60.0

    def __init__(self) -> None:
        self._state = _V5XSessionState()

    def adopt_previous(self, previous: RuntimeController | None) -> None:
        if not isinstance(previous, V5XRuntimeController):
            return
        pending_get_serial = self._state.pending_get_serial
        pending_status_poll = self._state.pending_status_poll
        command_ack_events = self._state.command_ack_events
        start_ready_event = self._state.start_ready_event
        connect_info_event = self._state.connect_info_event
        self._state = previous._state
        self._state.pending_get_serial = pending_get_serial
        self._state.pending_status_poll = pending_status_poll
        self._state.command_ack_events = command_ack_events
        self._state.start_ready_event = start_ready_event
        self._state.connect_info_event = connect_info_event

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
            "pending_command_ack_opcodes": sorted(
                self._state.command_ack_events.keys()
            ),
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
        self._cancel_pending_get_serial()
        self._cancel_pending_status_poll()

    async def send_payload(self, session, data: bytes, *, timeout: float) -> bool:
        split = split_prefixed_bulk_stream(
            data,
            ProtocolFamily.V5X,
            (V5X_FINALIZE_PACKET,),
        )
        if not session.can_send_control_packet():
            raise RuntimeError("V5X control packet send unavailable")
        if split.bulk_payload and not session.can_send_bulk_payload():
            raise RuntimeError("V5X bulk payload send unavailable")

        split_context = self.build_split_context(session, split)
        for packet in split.commands:
            packet, density_updated = self.prepare_split_command(
                session,
                packet,
                split_context,
            )
            if packet is None:
                continue
            await self.before_split_command(
                session,
                packet,
                split_context,
                timeout=timeout,
                density_updated=density_updated,
            )
            ack_token = self.arm_command_ack(session, packet)
            try:
                sent = await session.send_control_packet(packet, timeout=timeout)
                if not sent:
                    raise RuntimeError("V5X control packet send unavailable")
                await self.after_split_command(
                    session,
                    packet,
                    split_context,
                    timeout=timeout,
                    density_updated=density_updated,
                    ack_token=ack_token,
                )
            except Exception:
                self.clear_command_ack(session, ack_token)
                raise

        if split.bulk_payload:
            sent = await session.send_bulk_payload(split.bulk_payload, timeout=timeout)
            if not sent:
                raise RuntimeError("V5X bulk payload send unavailable")

        for packet in split.trailing_commands:
            sent = await session.send_control_packet(packet, timeout=timeout)
            if not sent:
                raise RuntimeError("V5X trailing control packet send unavailable")
        return True

    def build_split_context(self, session, split) -> _V5XJobContext:
        is_gray = False
        for packet in split.commands:
            if prefixed_packet_opcode(packet, ProtocolFamily.V5X) != 0xA9:
                continue
            payload = prefixed_packet_payload(packet, ProtocolFamily.V5X)
            if payload is None:
                continue
            if len(payload) == 2:
                is_gray = True
            elif len(payload) >= 6:
                is_gray = payload[2:6] == V5X_GRAY_MODE_SUFFIX
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
        self._state.last_density_payload = payload
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
            await self._wait_for_start_ready(timeout)

    def arm_command_ack(
        self, session, packet: bytes
    ) -> tuple[int, asyncio.Event] | None:
        opcode = prefixed_packet_opcode(packet, ProtocolFamily.V5X)
        if opcode not in (0xA7, 0xA9):
            return None
        if opcode == 0xA7:
            self._state.start_ready_event = asyncio.Event()
        event = asyncio.Event()
        self._state.command_ack_events[opcode] = event
        return opcode, event

    async def after_split_command(
        self,
        session,
        packet: bytes,
        split_context: _V5XJobContext,
        *,
        timeout: float,
        density_updated: bool,
        ack_token,
    ) -> None:
        opcode = prefixed_packet_opcode(packet, ProtocolFamily.V5X)
        if ack_token is not None:
            ack_opcode, event = ack_token
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
                self._validate_command_ack(ack_opcode)
            finally:
                if self._state.command_ack_events.get(ack_opcode) is event:
                    self._state.command_ack_events.pop(ack_opcode, None)
                    if (
                        ack_opcode == 0xA7
                        and self._state.start_ready_event is not None
                        and not self._state.start_ready_event.is_set()
                    ):
                        self._state.start_ready_event = None
        if opcode == 0xA9:
            delay_ms = self._compute_start_delay_ms(
                split_context, density_updated=density_updated
            )
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

    def clear_command_ack(self, session, ack_token) -> None:
        if ack_token is None:
            return
        opcode, _event = ack_token
        self._state.command_ack_events.pop(opcode, None)
        if (
            opcode == 0xA7
            and self._state.start_ready_event is not None
            and not self._state.start_ready_event.is_set()
        ):
            self._state.start_ready_event = None

    async def wait_for_completion(self, session, *, timeout: float) -> None:
        # V5X devices stream A1 state while the mechanism is moving. Waiting is
        # passive: polling A3 here would move paper on affected firmware.
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
            self._release_command_ack(session, 0xA7)
        elif opcode == 0xA1:
            self._update_status(session, payload)
        elif opcode == 0xA3:
            self._mark_status_poll_ack(session)
        elif opcode == 0xA6:
            self._schedule_get_serial(session)
        elif opcode == 0xAA:
            self._release_start_ready(session)
        elif opcode == 0xA9:
            status = self._extract_status_byte(session, payload)
            self._state.last_a9_status = status
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
            self._mark_sign_request(session)

    async def _wait_for_start_ready(self, timeout: float) -> None:
        if self._state.start_ready_event is None:
            return
        event = self._state.start_ready_event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        finally:
            if self._state.start_ready_event is event:
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
            self._state.start_ready_event is None
            or self._state.start_ready_event.is_set()
        ):
            return
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
        if (
            0xA7 in self._state.command_ack_events
            or self._state.start_ready_event is not None
        ):
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

    def _cancel_pending_get_serial(self) -> None:
        if self._state.pending_get_serial is None:
            return
        self._state.pending_get_serial.cancel()
        self._state.pending_get_serial = None

    def _cancel_pending_status_poll(self) -> None:
        if self._state.pending_status_poll is None:
            return
        self._state.pending_status_poll.cancel()
        self._state.pending_status_poll = None

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
        if raw:
            return raw[0]
        prefix = ProtocolFamily.V5X.require_packet_prefix()
        if len(payload) < len(prefix) + 2 or payload[: len(prefix)] != prefix:
            return None
        return payload[len(prefix) + 1]

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

    def _mark_sign_request(self, session) -> None:
        if self._state.mxw_sign_requested:
            return
        self._state.mxw_sign_requested = True
        session.report_warning(
            short="V5X printer requested an additional signing step",
            detail="Continuing without the optional signing command for this session.",
        )

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
