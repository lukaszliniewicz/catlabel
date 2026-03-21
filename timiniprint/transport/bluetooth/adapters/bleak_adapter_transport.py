"""Family-aware BLE transport helpers for the bleak adapter.

This module owns resolved GATT bindings, optional flow-control state and
family-specific write routing. `_BleakSocket` uses it as a thin transport layer
once the BLE connection itself is established.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Tuple

from .... import reporting
from ....protocol.families import BleTransportProfile, split_prefixed_bulk_stream
from ....protocol.family import ProtocolFamily
from .bleak_adapter_endpoint_resolver import _BleWriteEndpointResolver, _WriteSelection


@dataclass
class _BleakBindings:
    """Resolved GATT endpoints and write preferences for one connection."""

    write_char: Any = None
    bulk_write_char: Any = None
    notify_char: Any = None
    write_selection_strategy: str = "unknown"
    write_response_preference: Optional[bool] = None
    write_service_uuid: str = ""
    write_char_uuid: str = ""
    bulk_write_char_uuid: str = ""
    notify_char_uuid: str = ""


class _BleakTransportSession:
    """Encapsulates family-specific endpoint binding and write routing."""

    def __init__(
        self,
        protocol_family: ProtocolFamily,
        transport_profile: BleTransportProfile,
        write_resolver: _BleWriteEndpointResolver,
        reporter: reporting.Reporter,
    ) -> None:
        self._protocol_family = protocol_family
        self._transport_profile = transport_profile
        self._write_resolver = write_resolver
        self._reporter = reporter
        self.bindings = _BleakBindings()
        self.notify_started = False
        self.flow_can_write = True

    def apply_write_selection(self, selection: _WriteSelection) -> None:
        self.bindings.write_char = selection.char
        self.bindings.write_selection_strategy = selection.strategy
        self.bindings.write_response_preference = selection.response_preference
        self.bindings.write_service_uuid = selection.service_uuid
        self.bindings.write_char_uuid = selection.char_uuid
        self._report_debug(
            "selected write characteristic "
            f"service={self.bindings.write_service_uuid} char={self.bindings.write_char_uuid} "
            f"strategy={self.bindings.write_selection_strategy} "
            f"response_preference={self.bindings.write_response_preference}"
        )

    def configure_endpoints(self, services: Iterable[object]) -> None:
        """Bind optional bulk and notify endpoints from the transport profile."""
        transport = self._transport_profile

        self.bindings.bulk_write_char = None
        self.bindings.bulk_write_char_uuid = ""
        if transport.bulk_char_uuid:
            self.bindings.bulk_write_char = self._find_characteristic_by_uuid(
                services,
                transport.bulk_char_uuid,
                preferred_service_uuid=transport.preferred_service_uuid,
            )
            self.bindings.bulk_write_char_uuid = _BleWriteEndpointResolver._normalize_uuid(
                getattr(self.bindings.bulk_write_char, "uuid", "")
            )
            if self.bindings.bulk_write_char:
                self._report_debug(
                    f"selected bulk characteristic char={self.bindings.bulk_write_char_uuid}"
                )
            else:
                self._report_debug("configured bulk characteristic not found")

        self.bindings.notify_char = None
        self.bindings.notify_char_uuid = ""
        if transport.notify_char_uuid:
            self.bindings.notify_char = self._find_characteristic_by_uuid(
                services,
                transport.notify_char_uuid,
                preferred_service_uuid=transport.preferred_service_uuid,
            )
        elif transport.prefer_generic_notify or transport.flow_control is not None:
            # Some families only expose a generic notifier, so fall back to any
            # notify/indicate characteristic when the profile asks for it.
            self.bindings.notify_char = self._find_notify_characteristic(services)

        self.bindings.notify_char_uuid = _BleWriteEndpointResolver._normalize_uuid(
            getattr(self.bindings.notify_char, "uuid", "")
        )
        if self.bindings.notify_char:
            self._report_debug(
                f"selected notify characteristic char={self.bindings.notify_char_uuid}"
            )
        elif transport.flow_control is not None:
            self._report_debug("configured notify characteristic not found")

    async def start_notify_if_available(self, client: Any, callback) -> None:
        if not self.bindings.notify_char or not self.bindings.notify_char_uuid:
            return
        start_notify = getattr(client, "start_notify", None)
        if not callable(start_notify):
            return
        await start_notify(self.bindings.notify_char_uuid, callback)
        self.notify_started = True
        self._report_debug(
            f"subscribed to notify characteristic {self.bindings.notify_char_uuid}"
        )

    async def stop_notify_if_started(self, client: Any) -> None:
        if not self.notify_started or not self.bindings.notify_char_uuid:
            return
        stop_notify = getattr(client, "stop_notify", None)
        if not callable(stop_notify):
            return
        try:
            await stop_notify(self.bindings.notify_char_uuid)
        except Exception:
            pass
        self.notify_started = False

    async def send(
        self,
        client: Any,
        data: bytes,
        *,
        mtu_size: int,
        timeout: float,
        write_delay_ms: int,
        bulk_write_delay_ms: int,
    ) -> None:
        if not self.bindings.write_char:
            raise RuntimeError("No write characteristic available")

        if self._transport_profile.split_bulk_writes:
            await self._send_split(
                client,
                data,
                mtu_size=mtu_size,
                timeout=timeout,
                write_delay_ms=write_delay_ms,
                bulk_write_delay_ms=bulk_write_delay_ms,
            )
            return
        await self._send_standard(
            client,
            data,
            mtu_size=mtu_size,
            timeout=timeout,
            write_delay_ms=write_delay_ms,
        )

    async def _send_standard(
        self,
        client: Any,
        data: bytes,
        *,
        mtu_size: int,
        timeout: float,
        write_delay_ms: int,
    ) -> None:
        response = self._resolve_response_mode(
            self.bindings.write_char,
            self.bindings.write_selection_strategy,
            self.bindings.write_response_preference,
        )
        self._report_debug(
            f"write mode response={response} strategy={self.bindings.write_selection_strategy} "
            f"char={self.bindings.write_char_uuid}"
        )
        await self._write_chunks(
            client,
            self.bindings.write_char,
            data,
            response=response,
            chunk_size=min(mtu_size, 20),
            delay_seconds=write_delay_ms / 1000.0,
            timeout=timeout,
            wait_for_flow=self._transport_profile.wait_for_flow_on_standard_write,
        )

    async def _send_split(
        self,
        client: Any,
        data: bytes,
        *,
        mtu_size: int,
        timeout: float,
        write_delay_ms: int,
        bulk_write_delay_ms: int,
    ) -> None:
        if not self.bindings.bulk_write_char:
            raise RuntimeError("Bulk write characteristic not found")

        split = split_prefixed_bulk_stream(
            data,
            self._protocol_family,
            self._transport_profile.split_tail_packets,
        )
        # Split-bulk families send framed control packets on one endpoint and
        # stream the raster payload over another.
        cmd_response = self._resolve_response_mode(
            self.bindings.write_char,
            self.bindings.write_selection_strategy,
            self.bindings.write_response_preference,
        )
        self._report_debug(
            f"split write response={cmd_response} cmd_char={self.bindings.write_char_uuid} "
            f"bulk_char={self.bindings.bulk_write_char_uuid or '<missing>'} "
            f"notify_char={self.bindings.notify_char_uuid or '<missing>'}"
        )

        for packet in split.commands:
            await self._write_chunks(
                client,
                self.bindings.write_char,
                packet,
                response=cmd_response,
                chunk_size=min(mtu_size, 20),
                delay_seconds=write_delay_ms / 1000.0,
                timeout=timeout,
            )

        if split.bulk_payload:
            bulk_response = self._resolve_response_mode(
                self.bindings.bulk_write_char,
                "preferred_uuid",
                False,
            )
            await self._write_chunks(
                client,
                self.bindings.bulk_write_char,
                split.bulk_payload,
                response=bulk_response,
                chunk_size=min(mtu_size, self._transport_profile.bulk_chunk_size),
                delay_seconds=bulk_write_delay_ms / 1000.0,
                timeout=timeout,
                wait_for_flow=self._transport_profile.flow_control is not None,
            )

        for packet in split.trailing_commands:
            await self._write_chunks(
                client,
                self.bindings.write_char,
                packet,
                response=cmd_response,
                chunk_size=min(mtu_size, 20),
                delay_seconds=write_delay_ms / 1000.0,
                timeout=timeout,
            )

    async def _write_chunks(
        self,
        client: Any,
        char: Any,
        data: bytes,
        *,
        response: bool,
        chunk_size: int,
        delay_seconds: float,
        timeout: float,
        wait_for_flow: bool = False,
    ) -> None:
        for offset in range(0, len(data), chunk_size):
            if wait_for_flow:
                await self._wait_for_flow(timeout)
            chunk = data[offset : offset + chunk_size]
            await client.write_gatt_char(char, chunk, response=response)
            if delay_seconds:
                await asyncio.sleep(delay_seconds)

    async def _wait_for_flow(self, timeout: float) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not self.flow_can_write:
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("Timed out waiting for BLE flow-control resume")
            await asyncio.sleep(0.01)

    def handle_notification(self, payload: bytes) -> None:
        flow_control = self._transport_profile.flow_control
        if flow_control is not None:
            # Pause/resume packets gate writes for families that require
            # application-level flow control.
            if payload in flow_control.pause_packets:
                self.flow_can_write = False
                self._report_debug(f"flow pause: {payload.hex()}")
                return
            if payload in flow_control.resume_packets:
                self.flow_can_write = True
                self._report_debug(f"flow resume: {payload.hex()}")
                return
        self._report_debug(f"BLE notify: {payload.hex()}")

    @staticmethod
    def _find_characteristic_by_uuid(
        services: Iterable[object],
        char_uuid: str,
        *,
        preferred_service_uuid: str = "",
    ) -> Optional[Any]:
        """Resolve a known characteristic UUID, preferring one service when requested."""
        target = _BleWriteEndpointResolver._normalize_uuid(char_uuid)
        preferred_service = _BleWriteEndpointResolver._normalize_uuid(preferred_service_uuid)
        if preferred_service:
            for service in services:
                service_uuid = _BleWriteEndpointResolver._normalize_uuid(getattr(service, "uuid", ""))
                if service_uuid != preferred_service:
                    continue
                for characteristic in getattr(service, "characteristics", []):
                    if (
                        _BleWriteEndpointResolver._normalize_uuid(
                            getattr(characteristic, "uuid", "")
                        )
                        == target
                    ):
                        return characteristic
        for service in services:
            for characteristic in getattr(service, "characteristics", []):
                if (
                    _BleWriteEndpointResolver._normalize_uuid(getattr(characteristic, "uuid", ""))
                    == target
                ):
                    return characteristic
        return None

    @classmethod
    def find_notify_characteristic(cls, services: Iterable[object]) -> Optional[Any]:
        preferred: List[Tuple[str, str, Any]] = []
        generic: List[Tuple[str, str, Any]] = []
        for service in services:
            service_uuid = _BleWriteEndpointResolver._normalize_uuid(getattr(service, "uuid", ""))
            for characteristic in getattr(service, "characteristics", []):
                props = {
                    str(item).strip().lower() for item in getattr(characteristic, "properties", [])
                }
                if "notify" not in props and "indicate" not in props:
                    continue
                char_uuid = _BleWriteEndpointResolver._normalize_uuid(
                    getattr(characteristic, "uuid", "")
                )
                candidate = (service_uuid, char_uuid, characteristic)
                if _BleWriteEndpointResolver._uuid_is_preferred(
                    char_uuid,
                    _BleWriteEndpointResolver._PREFERRED_NOTIFY_UUIDS,
                    _BleWriteEndpointResolver._PREFERRED_NOTIFY_SHORT,
                ):
                    preferred.append(candidate)
                else:
                    generic.append(candidate)
        candidates = sorted(preferred or generic, key=lambda item: (item[0], item[1]))
        return candidates[0][2] if candidates else None

    def _resolve_response_mode(
        self,
        characteristic: Any,
        strategy: str,
        response_preference: Optional[bool],
    ) -> bool:
        return self._write_resolver.resolve_response_mode(
            getattr(characteristic, "properties", []),
            strategy,
            response_preference,
        )

    def _report_debug(self, message: str) -> None:
        self._reporter.debug(short="BLE", detail=message)
