from __future__ import annotations

from ...protocol.family import ProtocolFamily
from ...protocol.packet import PrefixedPacketStreamDecoder
from .base import RuntimeController, RuntimeSessionApi


class TinyRuntimeController(RuntimeController):
    def __init__(self) -> None:
        self._decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)

    def adopt_previous(self, previous: RuntimeController | None) -> None:
        if not isinstance(previous, TinyRuntimeController):
            return
        self._decoder = previous._decoder
        previous._decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)

    def handle_notification(self, session: RuntimeSessionApi, payload: bytes) -> None:
        for packet in self._decoder.feed(payload):
            if packet.opcode != 0xAE or packet.flags != 0x01:
                continue
            if packet.payload == b"\x10":
                session.set_flow_paused(True, payload=packet.raw)
            elif packet.payload == b"\x00":
                session.set_flow_paused(False, payload=packet.raw)

    async def stop(self, session: RuntimeSessionApi) -> None:
        self._decoder = PrefixedPacketStreamDecoder(ProtocolFamily.LEGACY)
        session.set_flow_paused(False)
