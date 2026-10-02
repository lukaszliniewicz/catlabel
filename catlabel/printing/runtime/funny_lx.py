from __future__ import annotations

import asyncio
import re
import secrets
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress

from ...protocol.families.funny_lx import challenge_crc
from ...protocol.steps import ProtocolStep, ProtocolStepOperation
from ..step_execution import (
    bytes_preview,
    execute_protocol_step,
    reply_complete_for,
    reply_matches_for,
)
from .base import RuntimeController, RuntimeSessionApi

_HANDSHAKE_RANDOM_BYTES = 10
_MAX_RETRY_REQUESTS = 10
_DEFAULT_PACKET_DELAY_SEC = 0.02
_MAX_PACKET_DELAY_SEC = 0.5
_DEFAULT_DARKNESS_CODE = 3


class FunnyLxRuntimeController(RuntimeController):
    def __init__(
        self,
        *,
        bluetooth_address: str,
        random_bytes_factory: Callable[[], bytes] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._bluetooth_address = bluetooth_address
        self._random_bytes_factory = random_bytes_factory or _random_challenge
        self._sleep = sleep or asyncio.sleep
        self._verified = False
        self._retry_requests: deque[int] = deque()
        self._packet_delay_sec = _DEFAULT_PACKET_DELAY_SEC
        self._supports_darkness = False
        self._darkness_code: int | None = None

    def adopt_previous(self, previous: RuntimeController | None) -> None:
        if not isinstance(previous, FunnyLxRuntimeController):
            return
        self._verified = previous._verified
        self._packet_delay_sec = previous._packet_delay_sec
        self._supports_darkness = previous._supports_darkness
        self._darkness_code = previous._darkness_code

    async def initialize_connection(
        self,
        session: RuntimeSessionApi,
        *,
        mtu_size: int,
        timeout: float,
    ) -> None:
        if self._verified:
            return
        if not session.can_send_control_packet_wait_notification():
            raise RuntimeError(
                "Funny LX verification requires BLE notification queries"
            )
        handshake_timeout = max(5.0, timeout)
        status = await session.send_control_packet_wait_notification(
            b"\x5a\x01\x00",
            label="Funny LX status",
            match=lambda reply: reply.startswith(b"\x5a\x01"),
            timeout=handshake_timeout,
        )
        self._supports_darkness = bool(
            status and len(status) >= 4 and status[2:4] == b"\x00\x03"
        )
        mac = _mac_bytes_from_status(status or b"") or _mac_bytes_from_address(
            self._bluetooth_address
        )
        if mac is None:
            raise RuntimeError(
                "Funny LX verification could not resolve printer MAC address"
            )
        random_bytes = self._random_bytes_factory()
        if len(random_bytes) != _HANDSHAKE_RANDOM_BYTES:
            raise ValueError("Funny LX challenge must contain 10 random bytes")
        crc = challenge_crc(random_bytes, mac)
        await session.send_control_packet_wait_notification(
            b"\x5a\x0a" + random_bytes,
            label="Funny LX challenge low CRC",
            match=lambda reply: (
                reply.startswith(b"\x5a\x0a") and reply[2 : 2 + len(crc.low)] == crc.low
            ),
            timeout=handshake_timeout,
        )
        await session.send_control_packet_wait_notification(
            b"\x5a\x0b" + crc.high,
            label="Funny LX challenge high CRC",
            match=lambda reply: reply.startswith(b"\x5a\x0b\x01"),
            timeout=handshake_timeout,
        )
        self._verified = True
        if self._supports_darkness:
            await self._send_default_darkness(session, timeout=timeout)
        session.report_debug(
            f"Funny LX verification complete mtu_payload={mtu_size} mac={mac.hex(':')}"
        )

    async def _send_default_darkness(
        self,
        session: RuntimeSessionApi,
        *,
        timeout: float,
    ) -> None:
        if self._darkness_code == _DEFAULT_DARKNESS_CODE:
            return
        if await session.send_control_packet(
            b"\x5a\x0c" + bytes([_DEFAULT_DARKNESS_CODE]),
            timeout=timeout,
        ):
            self._darkness_code = _DEFAULT_DARKNESS_CODE

    async def send_protocol_steps(
        self,
        session: RuntimeSessionApi,
        steps: tuple[ProtocolStep, ...],
        *,
        timeout: float,
    ) -> bool:
        if not any(_is_image_packet(step) for step in steps):
            return False
        if any(
            step.operation is ProtocolStepOperation.QUERY for step in steps
        ) and not (
            session.can_query_control_packet()
            or session.can_send_control_packet_wait_notification()
        ):
            raise RuntimeError("Funny LX requires request/reply protocol support")
        if (
            not session.can_send_standard_payload()
            or not session.can_wait_for_notification()
        ):
            return False
        self._retry_requests.clear()
        index = 0
        while index < len(steps):
            step = steps[index]
            if _is_image_packet(step):
                image_steps = _image_step_run(steps, index)
                following = (
                    steps[index + len(image_steps)]
                    if index + len(image_steps) < len(steps)
                    else None
                )
                accepted = (
                    following
                    if following and following.operation is ProtocolStepOperation.WAIT
                    else None
                )
                ready = await self._send_images_with_retry(
                    session,
                    image_steps,
                    accepted_step=accepted,
                    timeout=timeout,
                )
                if accepted is not None and not ready:
                    raise RuntimeError(
                        "Funny LX image transfer did not reach printer-ready state before footer"
                    )
                index += len(image_steps) + (1 if accepted is not None else 0)
                continue
            await self._execute_non_image_step(session, step, timeout=timeout)
            index += 1
        return True

    async def _execute_non_image_step(
        self,
        session: RuntimeSessionApi,
        step: ProtocolStep,
        *,
        timeout: float,
    ) -> None:
        darkness = _darkness_code_from_step(step)
        if darkness is not None and darkness == self._darkness_code:
            return
        reply = await execute_protocol_step(
            session,
            step,
            timeout=timeout,
            log_prefix="Funny LX protocol",
        )
        if step.operation is not ProtocolStepOperation.SEND and not reply_matches_for(
            step, reply
        ):
            raise RuntimeError(
                f"Funny LX step {step.label!r} received {bytes_preview(reply)}"
            )
        if darkness is not None:
            self._darkness_code = darkness

    async def _send_images_with_retry(
        self,
        session: RuntimeSessionApi,
        image_steps: tuple[ProtocolStep, ...],
        *,
        accepted_step: ProtocolStep | None,
        timeout: float,
    ) -> bool:
        image_index = 0
        retries = 0
        while True:
            while image_index < len(image_steps) or self._retry_requests:
                if self._retry_requests:
                    requested = self._retry_requests.popleft()
                    retries, image_index = _apply_retry(
                        session,
                        requested,
                        retries,
                        len(image_steps),
                        image_index,
                    )
                    continue
                if self._packet_delay_sec > 0:
                    await self._sleep(self._packet_delay_sec)
                await session.send_standard_payload(image_steps[image_index].data)
                image_index += 1
            if accepted_step is None:
                return True
            reply = await _wait_ready_or_retry(
                session,
                accepted_step,
                timeout=timeout,
            )
            requested = _retry_index(reply or b"")
            if requested is None:
                return reply_matches_for(accepted_step, reply)
            with suppress(ValueError):
                self._retry_requests.remove(requested)
            retries, image_index = _apply_retry(
                session,
                requested,
                retries,
                len(image_steps),
                image_index,
            )

    def handle_notification(self, session: RuntimeSessionApi, payload: bytes) -> None:
        requested = _retry_index(payload)
        if requested is not None:
            self._retry_requests.append(requested)
            session.report_debug(f"Funny LX retry requested packet={requested}")
            return
        if len(payload) >= 3 and payload[:2] == b"\x5a\x07":
            self._packet_delay_sec = max(
                0.0,
                min(payload[2] / 1000.0, _MAX_PACKET_DELAY_SEC),
            )
        elif payload.startswith(b"\x5a\x08"):
            session.report_debug(f"Funny LX pause notification: {payload.hex(' ')}")

    def debug_snapshot(self) -> dict[str, object]:
        return {
            "verified": self._verified,
            "bluetooth_address": self._bluetooth_address,
            "packet_delay_hint_sec": self._packet_delay_sec,
            "supports_darkness": self._supports_darkness,
            "darkness_code": self._darkness_code,
        }


def _random_challenge() -> bytes:
    return bytes(secrets.randbelow(0xFE) + 1 for _ in range(_HANDSHAKE_RANDOM_BYTES))


def _mac_bytes_from_address(address: str) -> bytes | None:
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", str(address))
    if len(cleaned) != 12:
        return None
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return None


def _mac_bytes_from_status(status: bytes) -> bytes | None:
    return bytes(status[4:10]) if len(status) >= 10 else None


def _is_image_packet(step: ProtocolStep) -> bool:
    return (
        step.operation is ProtocolStepOperation.SEND
        and len(step.data) >= 3
        and step.data[0] == 0x55
    )


def _darkness_code_from_step(step: ProtocolStep) -> int | None:
    if (
        step.operation is ProtocolStepOperation.SEND
        and len(step.data) == 3
        and step.data[:2] == b"\x5a\x0c"
    ):
        return step.data[2]
    return None


def _image_step_run(
    steps: tuple[ProtocolStep, ...], start: int
) -> tuple[ProtocolStep, ...]:
    end = start
    while end < len(steps) and _is_image_packet(steps[end]):
        end += 1
    return steps[start:end]


def _retry_index(payload: bytes) -> int | None:
    if len(payload) < 4 or payload[:2] != b"\x5a\x05":
        return None
    return int.from_bytes(payload[2:4], "big")


def _apply_retry(
    session, requested: int, retries: int, count: int, current: int
) -> tuple[int, int]:
    if retries >= _MAX_RETRY_REQUESTS:
        session.report_warning(
            short="Funny LX retry limit exceeded",
            detail="Printer kept requesting image packet resend.",
        )
        return retries, current
    resume = max(0, min(requested - 1, max(0, count - 1)))
    session.report_debug(f"Funny LX retry request packet={requested} resume={resume}")
    return retries + 1, resume


async def _wait_ready_or_retry(
    session: RuntimeSessionApi,
    step: ProtocolStep,
    *,
    timeout: float,
) -> bytes | None:
    ready = reply_complete_for(step)
    if ready is None:
        return None

    def match(reply: bytes) -> bool:
        return _retry_index(reply) is not None or ready(reply)

    return await session.wait_for_notification(
        step.label,
        match,
        timeout=step.timeout_sec if step.timeout_sec is not None else timeout,
        required=False,
    )
