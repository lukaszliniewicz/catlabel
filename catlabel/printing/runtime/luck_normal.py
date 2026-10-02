from __future__ import annotations

from dataclasses import dataclass

from ...protocol.runtime import RuntimePrintCapabilities
from .base import RuntimeController, RuntimeSessionApi

LUCK_MODEL_QUERY_PACKET = bytes([0x10, 0xFF, 0x20, 0xF0])
LUCK_VERSION_QUERY_PACKET = bytes([0x10, 0xFF, 0x20, 0xF1])


@dataclass
class _LuckNormalProbeState:
    protocol_variant: str
    probed_model: str | None = None
    firmware_version: str | None = None
    capabilities: RuntimePrintCapabilities | None = None
    degraded_warning_emitted: bool = False


class LuckNormalRuntimeController(RuntimeController):
    def __init__(self, *, protocol_variant: str) -> None:
        self._state = _LuckNormalProbeState(protocol_variant=protocol_variant)

    def adopt_previous(self, previous: RuntimeController | None) -> None:
        if not isinstance(previous, LuckNormalRuntimeController):
            return
        if previous._state.protocol_variant == self._state.protocol_variant:
            self._state = previous._state

    async def probe_capabilities(
        self, session: RuntimeSessionApi, *, timeout: float
    ) -> None:
        gray_override = (
            12 if self._state.protocol_variant == "lujiang_normal_h" else None
        )
        if not session.can_query_control_packet():
            self._warn_degraded(session, "query transport is unavailable")
            self._state.capabilities = RuntimePrintCapabilities(
                supports_gray=False,
                gray_level_override=gray_override,
            )
            return

        reply = await self._query(session, LUCK_MODEL_QUERY_PACKET, "model", timeout)
        if not reply:
            self._warn_degraded(session, "model query returned no reply")
            self._state.capabilities = RuntimePrintCapabilities(
                supports_gray=False,
                gray_level_override=gray_override,
            )
            return

        model_name = reply.decode("gb2312", errors="ignore").replace("\x00", "").strip()
        self._state.probed_model = model_name
        version = await self._query(
            session, LUCK_VERSION_QUERY_PACKET, "firmware", timeout
        )
        if version:
            self._state.firmware_version = (
                version.decode("gb2312", errors="ignore").replace("\x00", "").strip()
            )
        self._state.capabilities = RuntimePrintCapabilities(
            supports_gray=bool(model_name) and model_name.endswith("_GY"),
            gray_level_override=gray_override,
        )

    def runtime_capabilities(self) -> RuntimePrintCapabilities | None:
        return self._state.capabilities

    def debug_snapshot(self) -> dict[str, object]:
        return {
            "protocol_variant": self._state.protocol_variant,
            "probed_model": self._state.probed_model,
            "firmware_version": self._state.firmware_version,
            "capabilities": self._state.capabilities,
            "degraded_warning_emitted": self._state.degraded_warning_emitted,
        }

    def _warn_degraded(self, session: RuntimeSessionApi, reason: str) -> None:
        if self._state.degraded_warning_emitted:
            return
        self._state.degraded_warning_emitted = True
        session.report_warning(
            short="Luck capability probe unavailable",
            detail=(
                "PPA2L/PPA2LH is running in mono-only mode because the live "
                f"model probe failed ({reason})."
            ),
        )

    async def _query(
        self,
        session: RuntimeSessionApi,
        packet: bytes,
        label: str,
        timeout: float,
    ) -> bytes | None:
        reply = await session.query_control_packet(packet, timeout=timeout)
        session.report_debug(
            f"Luck query {label}: tx={packet.hex(' ')} "
            f"rx={'<none>' if reply is None else reply.hex(' ')}"
        )
        return reply
