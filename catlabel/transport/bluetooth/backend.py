from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress

from ... import reporting
from ...core.async_operations import optional_bytes
from .adapters import _get_ble_adapter, _get_classic_adapter
from .constants import IS_MACOS, IS_WINDOWS, RFCOMM_CHANNELS
from .types import DeviceInfo, DeviceTransport, ScanFailure, SocketLike

_MACOS_FALLBACK_COOLDOWN_SEC = 0.35
_MACOS_BLE_REFRESH_TIMEOUT_SEC = 3.0


class SppBackend:
    def __init__(self, reporter: reporting.Reporter = reporting.DUMMY_REPORTER) -> None:
        self._sock: SocketLike | None = None
        self._lock = threading.Lock()
        # WinRT and Bleak both retain event-loop/native state for the lifetime
        # of a connection. The default asyncio executor may run consecutive
        # operations on different threads, which is unsafe for those objects
        # on Windows. Keep every operation for this backend on one worker.
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="catlabel-bluetooth",
        )
        self._connected = False
        self._channel: int | None = None
        self._transport: DeviceTransport | None = None
        self._reporter = reporter

    @staticmethod
    async def scan(timeout: float = 5.0) -> list[DeviceInfo]:
        devices, _failures = await SppBackend.scan_with_failures(timeout=timeout)
        return devices

    @staticmethod
    async def scan_with_failures(
        timeout: float = 5.0,
        include_classic: bool = True,
        include_ble: bool = True,
    ) -> tuple[list[DeviceInfo], list[ScanFailure]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            _scan_blocking,
            timeout,
            include_classic,
            include_ble,
        )

    async def connect(
        self,
        device: DeviceInfo,
        pairing_hint: bool | None = None,
    ) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            self._executor,
            self._connect_attempts_blocking,
            [device],
            pairing_hint,
        )

    async def connect_attempts(
        self,
        attempts: list[DeviceInfo],
        pairing_hint: bool | None = None,
    ) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            self._executor,
            self._connect_attempts_blocking,
            attempts,
            pairing_hint,
        )

    def is_connected(self) -> bool:
        return self._connected

    def register_notify_callback(self, callback) -> None:
        """Allows a vendor client to intercept raw incoming packets."""
        sock = self._sock
        if sock is not None:
            register_callback = getattr(sock, "register_notify_callback", None)
            if callable(register_callback):
                register_callback(callback)

    async def disconnect(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._disconnect_blocking)

    async def attach_runtime_controller(
        self,
        runtime_controller,
        *,
        timeout: float = 1.0,
    ) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            self._executor,
            self._attach_runtime_controller_blocking,
            runtime_controller,
            timeout,
        )

    def can_send_control_packet(self) -> bool:
        return self._can_send_control_packet_blocking()

    def can_send_bulk_payload(self) -> bool:
        return self._can_send_bulk_payload_blocking()

    def can_query_control_packet(self) -> bool:
        return self._can_query_control_packet_blocking()

    def can_wait_for_notification(self) -> bool:
        return self._can_wait_for_notification_blocking()

    def can_send_control_packet_wait_notification(self) -> bool:
        return self._can_send_control_packet_wait_notification_blocking()

    async def send_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float = 1.0,
    ) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._send_control_packet_blocking,
            packet,
            timeout,
        )

    async def send_bulk_payload(
        self,
        data: bytes,
        *,
        timeout: float = 1.0,
    ) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._send_bulk_payload_blocking,
            data,
            timeout,
        )

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float = 1.0,
        reply_complete: Callable[[bytes], bool] | None = None,
    ) -> bytes | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._query_control_packet_blocking,
            packet,
            timeout,
            reply_complete,
        )

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._wait_for_notification_blocking,
            label,
            match,
            timeout,
            required,
        )

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._send_control_packet_wait_notification_blocking,
            packet,
            label,
            match,
            timeout,
            required,
        )

    async def write(
        self,
        data: bytes,
        chunk_size: int,
        delay_ms: int = 0,
        interval_ms: int | None = None,
    ) -> None:
        if interval_ms is not None and not delay_ms:
            delay_ms = interval_ms
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            self._executor,
            self._write_blocking,
            data,
            chunk_size,
            delay_ms,
        )

    def _connect_attempts_blocking(
        self,
        attempts: list[DeviceInfo],
        pairing_hint: bool | None,
    ) -> None:
        if self._connected:
            self._reporter.debug(
                short="Bluetooth", detail="Bluetooth connect skipped: already connected"
            )
            return
        if not attempts:
            raise RuntimeError(
                "Bluetooth connection failed (no transport attempts provided)"
            )
        unique_attempts = _unique_attempts(attempts)
        self._reporter.debug(
            short="Bluetooth",
            detail=(
                "Bluetooth connect plan: "
                + ", ".join(
                    f"{item.transport.value}({item.address})"
                    for item in unique_attempts
                )
            ),
        )
        errors: list[tuple[DeviceInfo, Exception]] = []

        for index, candidate in enumerate(unique_attempts):
            if (
                IS_MACOS
                and index > 0
                and candidate.transport == DeviceTransport.BLE
                and unique_attempts[index - 1].transport == DeviceTransport.CLASSIC
            ):
                refreshed = _refresh_ble_attempt_macos_workaround(
                    candidate, self._reporter
                )
                if refreshed.address != candidate.address:
                    self._reporter.debug(
                        short="Bluetooth",
                        detail=(
                            "Refreshed BLE endpoint before fallback: "
                            f"{candidate.address} -> {refreshed.address}"
                        ),
                    )
                candidate = refreshed

            self._reporter.debug(
                short="Bluetooth",
                detail=(
                    f"Bluetooth attempt {index + 1}/{len(unique_attempts)}: "
                    f"transport={candidate.transport.value} address={candidate.address}"
                ),
            )
            try:
                self._connect_with_device(candidate, pairing_hint)
                self._reporter.debug(
                    short="Bluetooth",
                    detail=(
                        f"Bluetooth attempt {index + 1} succeeded: "
                        f"transport={candidate.transport.value} address={candidate.address}"
                    ),
                )
                return
            except Exception as exc:
                errors.append((candidate, exc))
                self._reporter.debug(
                    short="Bluetooth",
                    detail=(
                        f"Bluetooth attempt {index + 1} failed: "
                        f"transport={candidate.transport.value} address={candidate.address} error={exc}"
                    ),
                )
                if index < len(unique_attempts) - 1:
                    next_transport = unique_attempts[index + 1].transport
                    if (
                        IS_MACOS
                        and candidate.transport == DeviceTransport.CLASSIC
                        and next_transport == DeviceTransport.BLE
                    ):
                        self._reporter.debug(
                            short="Bluetooth",
                            detail=(
                                "Applying macOS Classic->BLE cooldown "
                                f"({_MACOS_FALLBACK_COOLDOWN_SEC:.2f}s)"
                            ),
                        )
                        time.sleep(_MACOS_FALLBACK_COOLDOWN_SEC)
                    self._reporter.warning(
                        detail=(
                            f"{_transport_label(candidate.transport)} Bluetooth connection failed, "
                            f"retrying over {_transport_label(next_transport)} "
                            f"(device: {candidate.name or candidate.address})."
                        ),
                    )

        if not errors:
            raise RuntimeError("Bluetooth connection failed")
        if len(errors) == 1:
            raise errors[0][1]

        parts = []
        for index, (attempt, error) in enumerate(errors):
            suffix = "fallback error" if index else "error"
            parts.append(f"{attempt.transport.value} {suffix}: {error}")
        detail = "; ".join(parts)
        raise RuntimeError(f"Bluetooth connection failed ({detail})")

    def _connect_with_device(
        self, device: DeviceInfo, pairing_hint: bool | None
    ) -> None:
        self._reporter.debug(
            short="Bluetooth",
            detail=(
                f"Connecting using {device.transport.value}: "
                f"address={device.address} pairing_hint={pairing_hint}"
            ),
        )
        adapter = _select_adapter(device.transport)
        if adapter is None:
            raise RuntimeError(
                f"{device.transport.value} Bluetooth is not supported on this platform"
            )
        pair_error = None
        try:
            if pairing_hint and IS_WINDOWS:
                self._reporter.status(reporting.STATUS_PAIRING_CONFIRM)
            adapter.ensure_paired(device.address, pairing_hint)
            self._reporter.debug(
                short="Bluetooth", detail=f"Pairing check done for {device.address}"
            )
        except Exception as exc:
            pair_error = exc
            self._reporter.debug(
                short="Bluetooth",
                detail=f"Pairing check failed for {device.address}: {exc}",
            )
        channels = _resolve_rfcomm_channels(adapter, device.address)
        self._reporter.debug(
            short="Bluetooth",
            detail=f"RFCOMM channels for {device.transport.value} {device.address}: {channels}",
        )
        last_error = None
        for channel in channels:
            sock = None
            try:
                self._reporter.debug(
                    short="Bluetooth",
                    detail=f"Trying RFCOMM channel {channel} for {device.address}",
                )
                sock = adapter.create_socket(
                    pairing_hint,
                    ble_profile=(
                        device.ble_profile
                        if device.transport is DeviceTransport.BLE
                        else None
                    ),
                    reporter=self._reporter,
                )
                set_timeout = getattr(sock, "settimeout", None)
                if callable(set_timeout):
                    set_timeout(8)
                sock.connect((device.address, channel))
                self._sock = sock
                self._connected = True
                self._channel = channel
                self._transport = device.transport
                self._reporter.debug(
                    short="Bluetooth",
                    detail=(
                        f"Connected via {device.transport.value} {device.address} "
                        f"on RFCOMM channel {channel}"
                    ),
                )
                return
            except Exception as exc:
                last_error = exc
                self._reporter.debug(
                    short="Bluetooth",
                    detail=f"RFCOMM channel {channel} failed for {device.address}: {exc}",
                )
                _safe_close(sock)
        if last_error and _is_timeout_error(last_error):
            if pair_error:
                raise RuntimeError(
                    "Bluetooth connection timed out. Pairing attempt failed: "
                    f"{pair_error}. Tried RFCOMM channels: {channels}."
                )
            raise RuntimeError(
                "Bluetooth connection timed out. Make sure the printer is on, in range, and paired. "
                f"Tried RFCOMM channels: {channels}."
            )
        detail = f"channels tried: {channels}"
        if pair_error:
            detail += f", pairing failed: {pair_error}"
        if last_error:
            detail += f", last error: {last_error}"
        raise RuntimeError("Bluetooth connection failed (" + detail + ")")

    def _disconnect_blocking(self) -> None:
        if not self._sock:
            self._connected = False
            self._channel = None
            self._transport = None
            return
        try:
            self._sock.close()
        finally:
            self._sock = None
            self._connected = False
            self._channel = None
            self._transport = None

    def _attach_runtime_controller_blocking(
        self,
        runtime_controller,
        timeout: float,
    ) -> None:
        if runtime_controller is None or not self._sock or not self._connected:
            return
        attach = getattr(self._sock, "attach_runtime_controller", None)
        if callable(attach):
            attach(runtime_controller, timeout=timeout)

    def _can_send_control_packet_blocking(self) -> bool:
        if not self._sock or not self._connected:
            return False
        if self._transport == DeviceTransport.BLE:
            checker = getattr(self._sock, "can_send_control_packet", None)
            if callable(checker):
                return bool(checker())
            return callable(getattr(self._sock, "send_control_packet", None))
        return True

    def _can_send_bulk_payload_blocking(self) -> bool:
        if (
            not self._sock
            or not self._connected
            or self._transport != DeviceTransport.BLE
        ):
            return False
        checker = getattr(self._sock, "can_send_bulk_payload", None)
        if callable(checker):
            return bool(checker())
        return callable(getattr(self._sock, "send_bulk_payload", None))

    def _can_query_control_packet_blocking(self) -> bool:
        if not self._sock or not self._connected:
            return False
        if self._transport == DeviceTransport.BLE:
            checker = getattr(self._sock, "can_query_control_packet", None)
            return bool(checker()) if callable(checker) else False
        return callable(getattr(self._sock, "recv", None))

    def _can_wait_for_notification_blocking(self) -> bool:
        if (
            not self._sock
            or not self._connected
            or self._transport != DeviceTransport.BLE
        ):
            return False
        checker = getattr(self._sock, "can_wait_for_notification", None)
        return bool(checker()) if callable(checker) else False

    def _can_send_control_packet_wait_notification_blocking(self) -> bool:
        if (
            not self._sock
            or not self._connected
            or self._transport != DeviceTransport.BLE
        ):
            return False
        checker = getattr(
            self._sock,
            "can_send_control_packet_wait_notification",
            None,
        )
        return bool(checker()) if callable(checker) else False

    def _send_control_packet_blocking(self, packet: bytes, timeout: float) -> bool:
        if not self._sock or not self._connected:
            return False
        if self._transport == DeviceTransport.BLE:
            sender = getattr(self._sock, "send_control_packet", None)
            return bool(sender(packet, timeout=timeout)) if callable(sender) else False
        with self._lock:
            return _send_control_packet(self._sock, packet, timeout=timeout)

    def _send_bulk_payload_blocking(self, data: bytes, timeout: float) -> bool:
        if (
            not self._sock
            or not self._connected
            or self._transport != DeviceTransport.BLE
        ):
            return False
        sender = getattr(self._sock, "send_bulk_payload", None)
        if not callable(sender):
            return False
        with self._lock:
            return bool(sender(data, timeout=timeout))

    def _query_control_packet_blocking(
        self,
        packet: bytes,
        timeout: float,
        reply_complete: Callable[[bytes], bool] | None = None,
    ) -> bytes | None:
        if not self._sock or not self._connected:
            return None
        if self._transport == DeviceTransport.BLE:
            query = getattr(self._sock, "query_control_packet", None)
            if not callable(query):
                return None
            if reply_complete is None:
                result = query(packet, timeout=timeout)
            else:
                result = query(
                    packet,
                    timeout=timeout,
                    reply_complete=reply_complete,
                )
            return optional_bytes(result, operation="query_control_packet")
        with self._lock:
            return _query_control_packet(
                self._sock,
                packet,
                timeout=timeout,
                reply_complete=reply_complete,
            )

    def _wait_for_notification_blocking(
        self,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool,
    ) -> bytes | None:
        if (
            not self._sock
            or not self._connected
            or self._transport != DeviceTransport.BLE
        ):
            if required:
                raise RuntimeError("BLE notification wait unavailable")
            return None
        waiter = getattr(self._sock, "wait_for_notification", None)
        if not callable(waiter):
            if required:
                raise RuntimeError("BLE notification wait unavailable")
            return None
        result = waiter(label, match, timeout=timeout, required=required)
        return optional_bytes(result, operation="wait_for_notification")

    def _send_control_packet_wait_notification_blocking(
        self,
        packet: bytes,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool,
    ) -> bytes | None:
        if (
            not self._sock
            or not self._connected
            or self._transport != DeviceTransport.BLE
        ):
            if required:
                raise RuntimeError("BLE notification query unavailable")
            return None
        sender = getattr(self._sock, "send_control_packet_wait_notification", None)
        if not callable(sender):
            if required:
                raise RuntimeError("BLE notification query unavailable")
            return None
        with self._lock:
            result = sender(
                packet,
                label=label,
                match=match,
                timeout=timeout,
                required=required,
            )
        return optional_bytes(result, operation="send_control_packet_wait_notification")

    def _write_blocking(
        self,
        data: bytes,
        chunk_size: int,
        delay_ms: int,
        interval_ms: int | None = None,
    ) -> None:
        if interval_ms is not None and not delay_ms:
            delay_ms = interval_ms
        if not self._sock or not self._connected:
            raise RuntimeError("Not connected to a Bluetooth device")

        if self._transport == DeviceTransport.BLE:
            with self._lock:
                _send_all(self._sock, data)
            return

        delay = max(0.0, delay_ms / 1000.0)

        # Windows timer resolution is typically ~15.6ms, so very small sleeps
        # like 4ms can oversleep badly and starve the printer buffer. Group
        # writes together so any intentional pacing stays above that floor.
        if delay > 0 and delay < 0.02:
            group_factor = int(0.02 / delay) + 1
            effective_chunk_size = chunk_size * group_factor
            effective_delay = delay * group_factor
        else:
            effective_chunk_size = chunk_size
            effective_delay = delay

        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + effective_chunk_size]
            with self._lock:
                _send_all(self._sock, chunk)
            offset += len(chunk)
            if effective_delay:
                time.sleep(effective_delay)


def _scan_blocking(
    timeout: float,
    include_classic: bool,
    include_ble: bool,
) -> tuple[list[DeviceInfo], list[ScanFailure]]:
    classic_devices: list[DeviceInfo] = []
    ble_devices: list[DeviceInfo] = []
    failures: list[ScanFailure] = []
    classic_failure: Exception | None = None
    ble_failure: Exception | None = None
    attempts = 0
    if include_classic:
        attempts += 1
        adapter = _get_classic_adapter()
        if adapter is None:
            classic_failure = RuntimeError("Classic Bluetooth not supported")
        else:
            try:
                classic_devices = adapter.scan_blocking(timeout)
            except Exception as exc:
                classic_failure = exc
    if include_ble:
        attempts += 1
        adapter = _get_ble_adapter()
        if adapter is None:
            ble_failure = RuntimeError("BLE Bluetooth not supported")
        else:
            try:
                ble_devices = adapter.scan_blocking(timeout)
            except Exception as exc:
                ble_failure = exc

    if classic_failure:
        failures.append(ScanFailure(DeviceTransport.CLASSIC, classic_failure))
    if ble_failure:
        failures.append(ScanFailure(DeviceTransport.BLE, ble_failure))
    all_devices = classic_devices + ble_devices
    if all_devices:
        return DeviceInfo.dedupe(all_devices), failures
    if attempts and failures and len(failures) >= attempts:
        detail = "; ".join(f"{item.transport.value}: {item.error}" for item in failures)
        raise RuntimeError(f"Bluetooth scan failed ({detail})")
    return [], failures


def _select_adapter(transport: DeviceTransport):
    if transport == DeviceTransport.BLE:
        return _get_ble_adapter()
    return _get_classic_adapter()


def _unique_attempts(attempts: list[DeviceInfo]) -> list[DeviceInfo]:
    unique: list[DeviceInfo] = []
    seen = set()
    for device in attempts:
        key = (
            device.transport,
            (device.address or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(device)
    return unique


def _safe_close(sock: SocketLike | None) -> None:
    if not sock:
        return
    with suppress(Exception):
        sock.close()


def _send_all(sock: SocketLike, data: bytes) -> None:
    send_payload = getattr(sock, "send_payload", None)
    if callable(send_payload):
        send_payload(data)
        return
    sendall = getattr(sock, "sendall", None)
    if callable(sendall):
        sendall(data)
        return
    send = getattr(sock, "send", None)
    if not callable(send):
        raise RuntimeError("Bluetooth socket does not support send")
    offset = 0
    while offset < len(data):
        remaining = len(data) - offset
        sent = send(data[offset:])
        if not isinstance(sent, int) or sent <= 0 or sent > remaining:
            raise RuntimeError("Bluetooth send failed")
        offset += sent


def _recv_until_match_or_timeout(
    sock: SocketLike,
    *,
    timeout: float,
    reply_complete: Callable[[bytes], bool] | None = None,
) -> bytes | None:
    recv = getattr(sock, "recv", None)
    if not callable(recv):
        return None
    settimeout = getattr(sock, "settimeout", None)
    gettimeout = getattr(sock, "gettimeout", None)
    previous_timeout = None
    if callable(gettimeout):
        try:
            previous_timeout = gettimeout()
        except Exception:
            previous_timeout = None
    deadline = time.monotonic() + max(0.0, timeout)
    chunks = bytearray()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if callable(settimeout):
                settimeout(remaining)
            try:
                chunk = recv(4096)
            except Exception as exc:
                if _is_timeout_error(exc):
                    break
                raise
            if not isinstance(chunk, bytes):
                raise TypeError("Bluetooth recv returned an invalid byte response.")
            if not chunk:
                break
            chunks.extend(chunk)
            if reply_complete is not None and reply_complete(bytes(chunks)):
                break
    finally:
        if callable(settimeout):
            with suppress(Exception):
                settimeout(previous_timeout)
    return bytes(chunks) if chunks else None


def _send_control_packet(
    sock: SocketLike,
    packet: bytes,
    *,
    timeout: float,
) -> bool:
    _ = timeout
    _send_all(sock, packet)
    return True


def _query_control_packet(
    sock: SocketLike,
    packet: bytes,
    *,
    timeout: float,
    reply_complete: Callable[[bytes], bool] | None = None,
) -> bytes | None:
    _send_all(sock, packet)
    return _recv_until_match_or_timeout(
        sock,
        timeout=timeout,
        reply_complete=reply_complete,
    )


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, OSError):
        if exc.errno in {60, 110, 10060}:
            return True
        winerror = getattr(exc, "winerror", None)
        if winerror in {60, 110, 10060}:
            return True
    return False


def _resolve_rfcomm_channels(adapter, address: str) -> list[int]:
    try:
        resolved = list(adapter.resolve_rfcomm_channels(address) or [])
    except Exception:
        resolved = []
    explicit_channels: list[int] = []
    for item in resolved:
        try:
            channel_id = int(item)
        except Exception:
            continue
        if channel_id > 0 and channel_id not in explicit_channels:
            explicit_channels.append(channel_id)
    if explicit_channels:
        return explicit_channels

    return [RFCOMM_CHANNELS[0]]


def _transport_label(transport: DeviceTransport) -> str:
    if transport == DeviceTransport.BLE:
        return "BLE"
    return "Classic"


def _refresh_ble_attempt_macos_workaround(
    candidate: DeviceInfo,
    reporter: reporting.Reporter,
) -> DeviceInfo:
    adapter = _get_ble_adapter()
    if adapter is None:
        return candidate
    try:
        scanned = adapter.scan_blocking(_MACOS_BLE_REFRESH_TIMEOUT_SEC)
    except Exception as exc:
        reporter.debug(short="Bluetooth", detail=f"BLE refresh scan failed: {exc}")
        return candidate
    ble_devices = [item for item in scanned if item.transport == DeviceTransport.BLE]
    if not ble_devices:
        return candidate

    target_address = (candidate.address or "").strip().lower()
    for item in ble_devices:
        if (item.address or "").strip().lower() == target_address:
            return item

    target_name = (candidate.name or "").strip().lower()
    if not target_name:
        return candidate

    name_matches = [
        item for item in ble_devices if (item.name or "").strip().lower() == target_name
    ]
    if name_matches:
        name_matches.sort(key=lambda item: (item.name or "", item.address))
        return name_matches[0]
    return candidate
