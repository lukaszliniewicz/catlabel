"""Bluetooth Low Energy adapter using bleak for BLE communication.

The adapter keeps connection lifecycle in `_BleakSocket` and delegates endpoint
binding plus byte-transfer policy to `_BleakTransportSession`.
"""

from __future__ import annotations

import asyncio
import math
import sys
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from .... import reporting
from ....core.async_operations import await_operation
from ....devices import BleTransportProfile, get_ble_transport_profile
from ..constants import IS_MACOS
from ..types import DeviceInfo, DeviceTransport, SocketLike
from .base import _BleBluetoothAdapter
from .bleak_adapter_endpoint_resolver import _BleWriteEndpointResolver, _WriteSelection
from .bleak_adapter_transport import _BleakTransportSession


def _missing_bleak_error() -> RuntimeError:
    return RuntimeError(
        "bleak is required for BLE Bluetooth support. Install it with: pip install bleak"
    )


class _BleakSocket:
    """Socket-like wrapper around a bleak BLE client.

    It owns connection setup/teardown and uses `_BleakTransportSession` for
    characteristic selection, byte routing, and notification delivery.
    """

    def __init__(
        self,
        pairing_hint: bool | None = None,
        ble_profile: BleTransportProfile | None = None,
        reporter: reporting.Reporter = reporting.DUMMY_REPORTER,
        device_cache: dict[str, Any] | None = None,
    ) -> None:
        self._client: Any = None
        self._address: str | None = None
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mtu_size = 180
        self._timeout = 30.0
        self._pairing_hint = pairing_hint is True and not IS_MACOS
        self._ble_profile = ble_profile or get_ble_transport_profile(None)
        self._reporter = reporter
        self._device_cache = device_cache if device_cache is not None else {}
        self._write_resolver = _BleWriteEndpointResolver(reporter=self._reporter)
        self._transport = _BleakTransportSession(
            transport_profile=self._ble_profile,
            write_resolver=self._write_resolver,
            reporter=self._reporter,
        )

    def settimeout(self, timeout: float) -> None:
        """Store the timeout used by async BLE operations."""
        self._timeout = timeout

    @property
    def _flow_can_write(self) -> bool:
        return self._transport.flow_can_write

    @_flow_can_write.setter
    def _flow_can_write(self, value: bool) -> None:
        self._transport.flow_can_write = value

    @property
    def _notify_started(self) -> bool:
        return self._transport.notify_started

    @_notify_started.setter
    def _notify_started(self, value: bool) -> None:
        self._transport.notify_started = value

    def connect(self, address_channel: tuple[str, int]) -> None:
        """Connect to the BLE device and prepare family-specific endpoints."""
        address, _ = address_channel
        self._address = address
        previous_loop = None

        try:
            try:
                previous_loop = asyncio.get_event_loop()
            except RuntimeError:
                previous_loop = None
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._connect_async(address))
        except BaseException:
            try:
                self._disconnect_after_failed_connect()
            except BaseException as cleanup_error:
                with suppress(BaseException):
                    self._reporter.debug(
                        short="BLE",
                        detail=f"BLE setup cleanup failed: {cleanup_error}",
                    )
            finally:
                try:
                    self._cleanup_loop()
                except BaseException as cleanup_error:
                    with suppress(BaseException):
                        self._reporter.debug(
                            short="BLE",
                            detail=f"BLE event loop cleanup failed: {cleanup_error}",
                        )
            raise
        finally:
            with suppress(BaseException):
                asyncio.set_event_loop(previous_loop)

    async def _connect_async(self, address: str) -> None:
        """Create the client, connect it and bind writable characteristics."""
        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise _missing_bleak_error() from exc

        self._client = BleakClient(await self._resolve_client_target(address))

        try:
            await self._client.connect()
            self._connected = True
        except Exception as exc:
            detail = str(exc).strip() or repr(exc) or exc.__class__.__name__
            raise RuntimeError(
                f"Failed to connect to BLE device {address}: {detail}"
            ) from exc

        if self._pairing_hint:
            await self._pair_if_supported()

        selection = await self._find_write_characteristic()
        if not selection:
            await self._client.disconnect()
            self._connected = False
            raise RuntimeError(
                f"Could not find a writable GATT characteristic on device {address}. "
                "The device may not support BLE printing, or uses unknown UUIDs."
            )

        verified_payload = await self._acquire_bluez_mtu_payload()
        try:
            reported_mtu = getattr(self._client, "mtu_size", None)
        except Exception as exc:
            self._reporter.debug(
                short="BLE",
                detail=f"Could not read the reported MTU; using fallback payload: {exc}",
            )
        else:
            if isinstance(reported_mtu, int) and reported_mtu:
                self._mtu_size = min(reported_mtu - 3, 512)

        self._transport.apply_write_selection(selection)
        self._transport.configure_endpoints(
            getattr(self._client, "services", None) or []
        )
        await self._transport.start_notify_if_available(
            self._client, self._handle_notification
        )
        await self._transport.initialize_connection(
            self._client,
            mtu_size=self._mtu_size,
            timeout=self._timeout,
            verified_payload=verified_payload,
        )

    async def _acquire_bluez_mtu_payload(self) -> int | None:
        """Best-effort acquire and validate the Linux BlueZ negotiated MTU."""
        if not self._ble_profile.acquire_bluez_mtu or sys.platform != "linux":
            return None
        client = self._client
        if client is None:
            return None
        backend = getattr(client, "_backend", None)
        backend_module = getattr(type(backend), "__module__", "")
        if backend_module != "bleak.backends.bluezdbus.client" and not str(
            backend_module
        ).startswith("bleak.backends.bluezdbus."):
            return None

        try:
            acquire_mtu = getattr(backend, "_acquire_mtu", None)
        except Exception as exc:
            self._reporter.warning(
                short="BLE MTU negotiation unavailable",
                detail=f"Could not inspect the BlueZ MTU method: {exc}",
            )
            return None
        if not callable(acquire_mtu):
            self._reporter.debug(
                short="BLE",
                detail="BlueZ MTU negotiation method is unavailable; using reported MTU",
            )
            return None

        timeout = min(self._timeout, 5.0)
        if not math.isfinite(timeout) or timeout <= 0:
            self._reporter.debug(
                short="BLE",
                detail="BlueZ MTU negotiation skipped because its timeout is not positive",
            )
            return None
        try:
            await asyncio.wait_for(
                await_operation(acquire_mtu(), operation="acquire_mtu"),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._reporter.warning(
                short="BLE MTU negotiation failed",
                detail=f"Using the reported MTU after BlueZ negotiation failed: {exc}",
            )
            return None

        try:
            mtu_size = getattr(client, "mtu_size", None)
        except Exception as exc:
            self._reporter.warning(
                short="BLE MTU negotiation failed",
                detail=f"Could not read the negotiated MTU; using reported MTU: {exc}",
            )
            return None
        if not isinstance(mtu_size, int) or not 24 <= mtu_size <= 517:
            self._reporter.warning(
                short="BLE MTU negotiation failed",
                detail=(
                    "BlueZ returned an invalid negotiated MTU; "
                    f"using reported MTU (value: {mtu_size!r})"
                ),
            )
            return None
        self._reporter.debug(
            short="BLE",
            detail=f"Verified BlueZ MTU {mtu_size}; payload={min(mtu_size - 3, 512)}",
        )
        return min(mtu_size - 3, 512)

    async def _resolve_client_target(self, address: str) -> Any:
        """Return the address or discovered device object passed to BleakClient."""
        # On macOS, reuse of a cached BLEDevice from a previous scan loop can
        # fail with "Future attached to a different loop". Pass the CoreBluetooth
        # address string directly instead.
        if IS_MACOS:
            return address
        cached = self._device_cache.get(address.upper())
        if cached is not None:
            return cached

        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise _missing_bleak_error() from exc

        devices = await BleakScanner.discover(timeout=5.0)
        for dev in devices:
            if dev.address.upper() == address.upper():
                return dev
            if dev.name and address.upper() in dev.name.upper():
                return dev
        return address

    async def _find_write_characteristic(self) -> _WriteSelection | None:
        """Resolve the primary writable characteristic for this connection."""
        if not self._client or not self._connected:
            return None
        return self._write_resolver.resolve(
            self._client.services,
            preferred_service_uuid=self._ble_profile.preferred_service_uuid,
            preferred_write_char_uuid=self._ble_profile.preferred_write_char_uuid,
        )

    def send(self, data: bytes) -> int:
        return self.send_payload(data)

    def send_payload(self, data: bytes) -> int:
        """Send one payload using the active BLE transport session."""
        if not self._connected or not self._client:
            raise RuntimeError("Not connected to BLE device")
        if not self._loop:
            raise RuntimeError("Event loop not initialized")

        try:
            self._loop.run_until_complete(self._send_async(data))
            return len(data)
        except Exception as exc:
            bindings = self._transport.bindings
            detail = (
                f"service={bindings.write_service_uuid} char={bindings.write_char_uuid}"
            )
            raise RuntimeError(f"BLE write failed ({detail}): {exc}") from exc

    def sendall(self, data: bytes) -> None:
        """Compatibility alias matching socket-style APIs."""
        self.send_payload(data)

    def attach_runtime_controller(
        self,
        runtime_controller,
        *,
        timeout: float = 1.0,
    ) -> None:
        if not self._connected or not self._client:
            raise RuntimeError("Not connected to BLE device")
        if not self._loop:
            raise RuntimeError("Event loop not initialized")
        self._loop.run_until_complete(
            self._transport.attach_runtime_controller(
                runtime_controller,
                mtu_size=self._mtu_size,
                timeout=timeout,
            )
        )

    def can_send_control_packet(self) -> bool:
        return bool(
            self._connected
            and self._client
            and self._transport.can_send_control_packet()
        )

    def send_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float = 1.0,
    ) -> bool:
        if not self.can_send_control_packet():
            return False
        if not self._loop:
            raise RuntimeError("Event loop not initialized")
        return bool(
            self._loop.run_until_complete(
                self._transport.send_control_packet(packet, timeout=timeout)
            )
        )

    def can_send_bulk_payload(self) -> bool:
        return bool(
            self._connected and self._client and self._transport.can_send_bulk_payload()
        )

    def send_bulk_payload(
        self,
        data: bytes,
        *,
        timeout: float = 1.0,
    ) -> bool:
        if not self.can_send_bulk_payload():
            return False
        if not self._loop:
            raise RuntimeError("Event loop not initialized")
        return bool(
            self._loop.run_until_complete(
                self._transport.send_bulk_payload(data, timeout=timeout)
            )
        )

    def can_query_control_packet(self) -> bool:
        return bool(
            self._connected
            and self._client
            and self._transport.can_query_control_packet()
        )

    def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float = 1.0,
        reply_complete: Callable[[bytes], bool] | None = None,
    ) -> bytes | None:
        if not self.can_query_control_packet():
            return None
        if not self._loop:
            raise RuntimeError("Event loop not initialized")
        return self._loop.run_until_complete(
            self._transport.query_control_packet(
                packet,
                timeout=timeout,
                reply_complete=reply_complete,
            )
        )

    def can_wait_for_notification(self) -> bool:
        return bool(
            self._connected
            and self._client
            and self._transport.can_wait_for_notification()
        )

    def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        if not self._connected or not self._client:
            if required:
                raise RuntimeError("Not connected to BLE device")
            return None
        if not self._loop:
            raise RuntimeError("Event loop not initialized")
        return self._loop.run_until_complete(
            self._transport.wait_for_notification(
                label,
                match,
                timeout=timeout,
                required=required,
            )
        )

    def can_send_control_packet_wait_notification(self) -> bool:
        return bool(
            self._connected
            and self._client
            and self._transport.can_send_control_packet_wait_notification()
        )

    def send_control_packet_wait_notification(
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
                raise RuntimeError("BLE notification query unavailable")
            return None
        if not self._loop:
            raise RuntimeError("Event loop not initialized")
        return self._loop.run_until_complete(
            self._transport.send_control_packet_wait_notification(
                packet,
                label=label,
                match=match,
                timeout=timeout,
                required=required,
            )
        )

    async def _send_async(self, data: bytes) -> None:
        """Delegate payload routing and chunking to the transport session."""
        await self._transport.send(
            self._client,
            data,
            mtu_size=self._mtu_size,
            timeout=self._timeout,
        )

    async def _pair_if_supported(self) -> None:
        """Run platform pairing when the bleak client exposes it."""
        pair = getattr(self._client, "pair", None)
        if not callable(pair):
            return
        try:
            result = await await_operation(pair(), operation="pair")
        except Exception as exc:
            raise RuntimeError(f"BLE pairing failed: {exc}") from exc
        if result is False:
            raise RuntimeError("BLE pairing failed")

    def close(self) -> None:
        """Close the BLE connection and release the private event loop."""
        close_error: BaseException | None = None
        try:
            self._disconnect_after_failed_connect()
        except BaseException as exc:
            close_error = exc
        finally:
            try:
                self._cleanup_loop()
            except BaseException as exc:
                if close_error is None:
                    close_error = exc
        if close_error is not None:
            raise close_error

    def _disconnect_after_failed_connect(self) -> None:
        """Best-effort disconnect path shared by connect failures and close()."""
        try:
            if self._loop and self._client:
                with suppress(Exception):
                    self._loop.run_until_complete(self._safe_disconnect_async())
        finally:
            self._connected = False
            self._client = None
            self._transport = _BleakTransportSession(
                transport_profile=self._ble_profile,
                write_resolver=self._write_resolver,
                reporter=self._reporter,
            )

    async def _safe_disconnect_async(self) -> None:
        """Stop notifications before disconnecting the bleak client."""
        if not self._client:
            return
        stop_error: BaseException | None = None
        try:
            await self._transport.stop_notify_if_started(self._client)
        except BaseException as exc:
            stop_error = exc

        disconnect_error: BaseException | None = None
        try:
            disconnect = getattr(self._client, "disconnect", None)
        except BaseException as exc:
            disconnect_error = exc
        else:
            if callable(disconnect):
                try:
                    await await_operation(disconnect(), operation="disconnect")
                except BaseException as exc:
                    if stop_error is not None or not isinstance(exc, Exception):
                        disconnect_error = exc

        if stop_error is not None:
            if disconnect_error is not None:
                with suppress(BaseException):
                    self._transport.report_debug(
                        f"disconnect also failed after runtime stop: {disconnect_error}"
                    )
            raise stop_error
        if disconnect_error is not None:
            raise disconnect_error

    def _cleanup_loop(self) -> None:
        """Dispose the temporary event loop used by the socket wrapper."""
        loop = self._loop
        if loop is None:
            return
        try:
            with suppress(Exception):
                loop.close()
        finally:
            self._loop = None

    def _handle_notification(self, sender: Any, data: Any) -> None:
        source_uuid = getattr(sender, "uuid", sender)
        self._transport.handle_notification(bytes(data), source_uuid=str(source_uuid))

    @classmethod
    def _find_notify_characteristic(cls, services):
        return _BleakTransportSession.find_notify_characteristic(services)


class _BleakBleAdapter(_BleBluetoothAdapter):
    """Bluetooth Low Energy adapter using bleak for GATT writes."""

    def __init__(self) -> None:
        self._device_cache: dict[str, Any] = {}

    def scan_blocking(self, timeout: float) -> list[DeviceInfo]:
        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise _missing_bleak_error() from exc

        async def scan() -> list[DeviceInfo]:
            devices = await BleakScanner.discover(timeout=timeout)
            results = []
            for device in devices:
                name = device.name or ""
                self._device_cache[device.address.upper()] = device
                results.append(
                    DeviceInfo(
                        name=name,
                        address=device.address,
                        paired=None,
                        transport=DeviceTransport.BLE,
                    )
                )
            return results

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                devices = loop.run_until_complete(scan())
            finally:
                loop.close()
        except Exception as exc:
            raise RuntimeError(f"BLE scan failed: {exc}") from exc

        return devices

    def create_socket(
        self,
        pairing_hint: bool | None = None,
        ble_profile: BleTransportProfile | None = None,
        reporter: reporting.Reporter = reporting.DUMMY_REPORTER,
    ) -> SocketLike:
        return _BleakSocket(
            pairing_hint=pairing_hint,
            ble_profile=ble_profile,
            reporter=reporter,
            device_cache=self._device_cache,
        )

    def ensure_paired(self, address: str, pairing_hint: bool | None = None) -> None:
        return None
