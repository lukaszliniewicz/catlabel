"""Family-agnostic BLE transport helpers for the bleak adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from .... import reporting
from ....core.async_operations import await_operation
from ....devices import BleTransportProfile
from .bleak_adapter_endpoint_resolver import _BleWriteEndpointResolver, _WriteSelection


@dataclass
class _BleakBindings:
    write_char: Any = None
    bulk_write_char: Any = None
    notify_char: Any = None
    write_selection_strategy: str = "unknown"
    write_response_preference: bool | None = None
    write_service_uuid: str = ""
    write_char_uuid: str = ""
    bulk_write_char_uuid: str = ""
    notify_char_uuid: str = ""


@dataclass
class _NotificationWaiter:
    label: str
    match: Callable[[bytes], bool]
    future: asyncio.Future[bytes]


class _BleakTransportSession:
    """Encapsulates endpoint binding and delegates family runtime to controllers."""

    def __init__(
        self,
        transport_profile: BleTransportProfile,
        write_resolver: _BleWriteEndpointResolver,
        reporter: reporting.Reporter,
    ) -> None:
        self._transport_profile = transport_profile
        self._write_resolver = write_resolver
        self._reporter = reporter
        self.bindings = _BleakBindings()
        self.notify_started = False
        self.flow_can_write = True
        self._client: Any = None
        self._mtu_size = 180
        # Stateful protocol behavior is selected by the printing layer and
        # attached explicitly. Transport never selects a controller by family.
        self._runtime_controller: Any = None
        self._runtime_initialized = False
        self._notification_history: list[bytes] = []
        self._notification_waiters: list[_NotificationWaiter] = []

    def apply_write_selection(self, selection: _WriteSelection) -> None:
        self.bindings.write_char = selection.char
        self.bindings.write_selection_strategy = selection.strategy
        self.bindings.write_response_preference = selection.response_preference
        self.bindings.write_service_uuid = selection.service_uuid
        self.bindings.write_char_uuid = selection.char_uuid
        self.report_debug(
            "selected write characteristic "
            f"service={self.bindings.write_service_uuid} char={self.bindings.write_char_uuid} "
            f"strategy={self.bindings.write_selection_strategy} "
            f"response_preference={self.bindings.write_response_preference}"
        )

    def configure_endpoints(self, services: Iterable[object]) -> None:
        transport = self._transport_profile

        self.bindings.bulk_write_char = None
        self.bindings.bulk_write_char_uuid = ""
        bulk_write = transport.bulk_write
        if bulk_write is not None:
            self.bindings.bulk_write_char = self._find_characteristic_by_uuid(
                services,
                bulk_write.char_uuid,
                preferred_service_uuid=transport.preferred_service_uuid,
            )
            self.bindings.bulk_write_char_uuid = (
                _BleWriteEndpointResolver._normalize_uuid(
                    getattr(self.bindings.bulk_write_char, "uuid", "")
                )
            )
            if self.bindings.bulk_write_char:
                self.report_debug(
                    f"selected bulk characteristic char={self.bindings.bulk_write_char_uuid}"
                )
            else:
                self.report_debug("configured bulk characteristic not found")

        self.bindings.notify_char = None
        self.bindings.notify_char_uuid = ""
        if transport.notify_char_uuid:
            self.bindings.notify_char = self._find_characteristic_by_uuid(
                services,
                transport.notify_char_uuid,
                preferred_service_uuid=transport.preferred_service_uuid,
            )
        elif transport.prefer_generic_notify:
            self.bindings.notify_char = self.find_notify_characteristic(services)

        self.bindings.notify_char_uuid = _BleWriteEndpointResolver._normalize_uuid(
            getattr(self.bindings.notify_char, "uuid", "")
        )
        if self.bindings.notify_char:
            self.report_debug(
                f"selected notify characteristic char={self.bindings.notify_char_uuid}"
            )
        elif transport.notify_char_uuid or transport.prefer_generic_notify:
            self.report_debug("configured notify characteristic not found")

    async def start_notify_if_available(self, client: Any, callback) -> None:
        if not self.bindings.notify_char or not self.bindings.notify_char_uuid:
            return
        start_notify = getattr(client, "start_notify", None)
        if not callable(start_notify):
            return
        await await_operation(
            start_notify(self.bindings.notify_char_uuid, callback),
            operation="start_notify",
        )
        self.notify_started = True
        self.report_debug(
            f"subscribed to notify characteristic {self.bindings.notify_char_uuid}"
        )

    async def attach_runtime_controller(
        self,
        runtime_controller: Any,
        *,
        mtu_size: int,
        timeout: float,
    ) -> None:
        if runtime_controller is None:
            return
        if runtime_controller is not self._runtime_controller:
            runtime_controller.adopt_previous(self._runtime_controller)
            self._runtime_controller = runtime_controller
            self._runtime_initialized = False
        if not self._runtime_initialized:
            await self._runtime_controller.initialize_connection(
                self,
                mtu_size=mtu_size,
                timeout=timeout,
            )
            await self._runtime_controller.after_initialize(self, timeout=timeout)
            self._runtime_initialized = True

    async def stop_notify_if_started(self, client: Any) -> None:
        if self._runtime_controller is not None:
            await self._runtime_controller.stop(self)
        if not self.notify_started or not self.bindings.notify_char_uuid:
            return
        stop_notify = getattr(client, "stop_notify", None)
        if not callable(stop_notify):
            return
        with suppress(Exception):
            await await_operation(
                stop_notify(self.bindings.notify_char_uuid),
                operation="stop_notify",
            )
        self.notify_started = False
        for waiter in self._notification_waiters:
            if not waiter.future.done():
                waiter.future.cancel()
        self._notification_waiters.clear()

    async def initialize_connection(
        self,
        client: Any,
        *,
        mtu_size: int,
        timeout: float,
    ) -> None:
        self._client = client
        self._mtu_size = mtu_size
        _ = timeout

    async def send(
        self,
        client: Any,
        data: bytes,
        *,
        mtu_size: int,
        timeout: float,
    ) -> None:
        self._client = client
        self._mtu_size = mtu_size
        if not self.bindings.write_char:
            raise RuntimeError("No write characteristic available")
        await self._send_standard(client, data, mtu_size=mtu_size, timeout=timeout)

    async def _send_standard(
        self,
        client: Any,
        data: bytes,
        *,
        mtu_size: int,
        timeout: float,
    ) -> None:
        if self._runtime_controller is not None:
            self._runtime_controller.on_standard_send_started(self)
            data = self._runtime_controller.prepare_standard_payload(self, data)
            self._runtime_controller.track_outgoing_query_status(self, data)
        try:
            response = self._resolve_response_mode(
                self.bindings.write_char,
                self.bindings.write_selection_strategy,
                self.bindings.write_response_preference,
            )
            self.report_debug(
                f"write mode response={response} strategy={self.bindings.write_selection_strategy} "
                f"char={self.bindings.write_char_uuid}"
            )
            mtu_payload = self._effective_mtu_payload(
                self.bindings.write_char,
                mtu_size,
                response=response,
                reserve=self._transport_profile.write_without_response_payload_reserve,
            )
            await self._write_chunks(
                client,
                self.bindings.write_char,
                data,
                response=response,
                chunk_size=min(mtu_payload, self._transport_profile.standard_chunk_cap),
                delay_seconds=self._transport_profile.standard_write_delay_ms / 1000.0,
                timeout=timeout,
                wait_for_flow=self._transport_profile.flow_controlled_standard_write,
            )
        finally:
            if self._runtime_controller is not None:
                self._runtime_controller.on_standard_send_finished(self)

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
        flow_timeout = self._transport_profile.flow_resume_timeout_s
        deadline = asyncio.get_running_loop().time() + (
            timeout if flow_timeout is None else flow_timeout
        )
        while not self.flow_can_write:
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("Timed out waiting for BLE flow-control resume")
            await asyncio.sleep(0.01)

    def handle_notification(self, payload: bytes) -> None:
        self._notification_history.append(bytes(payload))
        if len(self._notification_history) > 64:
            del self._notification_history[:-64]
        if self._runtime_controller is not None:
            self._runtime_controller.handle_notification(self, payload)
        for waiter in tuple(self._notification_waiters):
            if waiter.future.done() or not waiter.match(payload):
                continue
            with suppress(ValueError):
                self._notification_history.remove(payload)
            waiter.future.set_result(bytes(payload))
            self._notification_waiters.remove(waiter)
        self.report_debug(f"BLE notify: {payload.hex()}")

    def set_flow_paused(self, paused: bool, *, payload: bytes = b"") -> None:
        self.flow_can_write = not paused
        state = "pause" if paused else "resume"
        self.report_debug(f"flow {state}: {payload.hex()}")

    def can_wait_for_notification(self) -> bool:
        return self.notify_started

    def can_send_control_packet_wait_notification(self) -> bool:
        return self.can_send_control_packet() and self.can_wait_for_notification()

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        for index in range(len(self._notification_history) - 1, -1, -1):
            payload = self._notification_history[index]
            if match(payload):
                del self._notification_history[index]
                return payload
        if not self.can_wait_for_notification():
            if required:
                raise RuntimeError(f"BLE notification wait unavailable for {label}")
            return None
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        waiter = _NotificationWaiter(label=label, match=match, future=future)
        self._notification_waiters.append(waiter)
        try:
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=max(0.0, timeout)
            )
        except TimeoutError as exc:
            if required:
                raise TimeoutError(
                    f"Timed out waiting for BLE notification: {label}"
                ) from exc
            return None
        finally:
            if waiter in self._notification_waiters:
                self._notification_waiters.remove(waiter)

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        if not self.can_send_control_packet_wait_notification():
            if required:
                raise RuntimeError(f"BLE notification query unavailable for {label}")
            return None
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        waiter = _NotificationWaiter(label=label, match=match, future=future)
        self._notification_waiters.append(waiter)
        try:
            sent = await self.send_control_packet(packet, timeout=timeout)
            if not sent:
                if required:
                    raise RuntimeError(
                        f"BLE control send failed before waiting for {label}"
                    )
                return None
            try:
                return await asyncio.wait_for(
                    asyncio.shield(future),
                    timeout=max(0.0, timeout),
                )
            except TimeoutError as exc:
                if required:
                    raise TimeoutError(
                        f"Timed out waiting for BLE notification: {label}"
                    ) from exc
                return None
        finally:
            if waiter in self._notification_waiters:
                self._notification_waiters.remove(waiter)

    @staticmethod
    def _find_characteristic_by_uuid(
        services: Iterable[object],
        char_uuid: str,
        *,
        preferred_service_uuid: str = "",
    ) -> Any | None:
        target = _BleWriteEndpointResolver._normalize_uuid(char_uuid)
        preferred_service = _BleWriteEndpointResolver._normalize_uuid(
            preferred_service_uuid
        )
        if preferred_service:
            for service in services:
                service_uuid = _BleWriteEndpointResolver._normalize_uuid(
                    getattr(service, "uuid", "")
                )
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
                    _BleWriteEndpointResolver._normalize_uuid(
                        getattr(characteristic, "uuid", "")
                    )
                    == target
                ):
                    return characteristic
        return None

    @classmethod
    def find_notify_characteristic(cls, services: Iterable[object]) -> Any | None:
        preferred: list[tuple[str, str, Any]] = []
        generic: list[tuple[str, str, Any]] = []
        for service in services:
            service_uuid = _BleWriteEndpointResolver._normalize_uuid(
                getattr(service, "uuid", "")
            )
            for characteristic in getattr(service, "characteristics", []):
                props = {
                    str(item).strip().lower()
                    for item in getattr(characteristic, "properties", [])
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
        response_preference: bool | None,
    ) -> bool:
        return self._write_resolver.resolve_response_mode(
            getattr(characteristic, "properties", []),
            strategy,
            response_preference,
        )

    @staticmethod
    def _effective_mtu_payload(
        characteristic: Any,
        fallback: int,
        *,
        response: bool,
        reserve: int = 0,
    ) -> int:
        if response:
            return fallback
        payload = fallback
        try:
            max_without_response = getattr(
                characteristic,
                "max_write_without_response_size",
                None,
            )
        except Exception:
            max_without_response = None
        if isinstance(max_without_response, int) and max_without_response > 0:
            payload = min(max_without_response, 512)
        if reserve > 0:
            payload -= reserve
        return max(1, payload)

    def report_debug(self, message: str) -> None:
        self._reporter.debug(short="BLE", detail=message)

    def report_warning(self, *, short: str, detail: str) -> None:
        self._reporter.warning(short=short, detail=detail)

    def can_send_control_packet(self) -> bool:
        return bool(self._client and self.bindings.write_char)

    def can_send_standard_payload(self) -> bool:
        return self.can_send_control_packet()

    def can_send_bulk_payload(self) -> bool:
        return bool(
            self._client
            and self.bindings.bulk_write_char
            and self._transport_profile.bulk_write is not None
        )

    def can_query_control_packet(self) -> bool:
        # GATT request/reply is represented by an atomic write+notification
        # operation, not by a socket-style read.
        return False

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        if not self.can_send_control_packet():
            return False
        response = self._resolve_response_mode(
            self.bindings.write_char,
            self.bindings.write_selection_strategy,
            self.bindings.write_response_preference,
        )
        await self._write_chunks(
            self._client,
            self.bindings.write_char,
            packet,
            response=response,
            chunk_size=min(
                self._effective_mtu_payload(
                    self.bindings.write_char,
                    self._mtu_size,
                    response=response,
                    reserve=self._transport_profile.write_without_response_payload_reserve,
                ),
                self._transport_profile.standard_chunk_cap,
            ),
            delay_seconds=self._transport_profile.standard_write_delay_ms / 1000.0,
            timeout=timeout,
        )
        return True

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float = 1.0,
        reply_complete=None,
    ) -> bytes | None:
        _ = packet, timeout, reply_complete
        return None

    async def send_standard_payload(self, data: bytes, *, timeout: float = 1.0) -> bool:
        if not self.can_send_standard_payload():
            return False
        response = self._resolve_response_mode(
            self.bindings.write_char,
            self.bindings.write_selection_strategy,
            self.bindings.write_response_preference,
        )
        await self._write_chunks(
            self._client,
            self.bindings.write_char,
            data,
            response=response,
            chunk_size=min(
                self._effective_mtu_payload(
                    self.bindings.write_char,
                    self._mtu_size,
                    response=response,
                    reserve=self._transport_profile.write_without_response_payload_reserve,
                ),
                self._transport_profile.standard_chunk_cap,
            ),
            delay_seconds=self._transport_profile.standard_write_delay_ms / 1000.0,
            timeout=timeout,
            wait_for_flow=self._transport_profile.flow_controlled_standard_write,
        )
        return True

    async def send_bulk_payload(self, data: bytes, *, timeout: float = 1.0) -> bool:
        bulk_write = self._transport_profile.bulk_write
        if not self.can_send_bulk_payload() or bulk_write is None:
            return False
        response = self._resolve_response_mode(
            self.bindings.bulk_write_char,
            "preferred_uuid",
            False,
        )
        await self._write_chunks(
            self._client,
            self.bindings.bulk_write_char,
            data,
            response=response,
            chunk_size=min(
                self._effective_mtu_payload(
                    self.bindings.bulk_write_char,
                    self._mtu_size,
                    response=response,
                    reserve=self._transport_profile.write_without_response_payload_reserve,
                ),
                bulk_write.chunk_cap,
            ),
            delay_seconds=bulk_write.write_delay_ms / 1000.0,
            timeout=timeout,
            wait_for_flow=bulk_write.flow_controlled,
        )
        return True
