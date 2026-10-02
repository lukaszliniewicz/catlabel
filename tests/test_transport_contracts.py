from __future__ import annotations

import unittest
from collections.abc import Callable

from catlabel import reporting
from catlabel.devices import BleTransportProfile
from catlabel.printing.runtime.session import RuntimeConnectionSession
from catlabel.transport.bluetooth.adapters.bleak_adapter import _BleakSocket
from catlabel.transport.bluetooth.adapters.bleak_adapter_endpoint_resolver import (
    _BleWriteEndpointResolver,
)
from catlabel.transport.bluetooth.adapters.bleak_adapter_transport import (
    _BleakTransportSession,
)
from catlabel.transport.bluetooth.backend import (
    SppBackend,
    _recv_until_match_or_timeout,
    _send_all,
)
from catlabel.transport.bluetooth.types import DeviceTransport


class _SyncControlConnection:
    def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        return bool(packet) and timeout > 0


class _MalformedResponseConnection:
    def can_send_control_packet_wait_notification(self) -> bool:
        return True

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float,
        reply_complete: Callable[[bytes], bool] | None = None,
    ) -> object:
        return "not bytes"

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> object:
        return bytearray(b"not bytes")

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool = True,
    ) -> object:
        return memoryview(b"not bytes")


class _SendSocket:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.calls: list[bytes] = []

    def send(self, payload: bytes) -> object:
        self.calls.append(payload)
        return self.results.pop(0)


class _ReceiveSocket:
    def __init__(self, chunk: object) -> None:
        self.chunk = chunk
        self.timeout: float | None = 0.75

    def gettimeout(self) -> float | None:
        return self.timeout

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = timeout

    def recv(self, _size: int) -> object:
        return self.chunk


class _BleResponseSocket:
    def __init__(self, response: object) -> None:
        self.response = response

    def query_control_packet(self, *_args: object, **_kwargs: object) -> object:
        return self.response

    def wait_for_notification(self, *_args: object, **_kwargs: object) -> object:
        return self.response

    def send_control_packet_wait_notification(
        self, *_args: object, **_kwargs: object
    ) -> object:
        return self.response


class _NotifyCharacteristic:
    uuid = "notify-characteristic"


class _SyncNotifyClient:
    def start_notify(self, _uuid: str, _callback: Callable[..., None]) -> None:
        return None


class _SyncPairClient:
    def pair(self) -> bool:
        return True


def _connected_ble_backend(sock: object) -> SppBackend:
    backend = SppBackend()
    backend._sock = sock
    backend._connected = True
    backend._transport = DeviceTransport.BLE
    return backend


class RuntimeSessionContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_synchronous_dynamic_operation_is_rejected(self) -> None:
        session = RuntimeConnectionSession(
            _SyncControlConnection(), reporter=reporting.DUMMY_REPORTER
        )

        with self.assertRaisesRegex(TypeError, "send_control_packet.*awaitable"):
            await session.send_control_packet(b"command")

    async def test_optional_methods_preserve_missing_capability_results(self) -> None:
        session = RuntimeConnectionSession(object(), reporter=reporting.DUMMY_REPORTER)

        self.assertFalse(await session.send_control_packet(b"command"))
        self.assertIsNone(await session.query_control_packet(b"query"))
        self.assertIsNone(
            await session.wait_for_notification(
                "optional", lambda _payload: True, timeout=0.01, required=False
            )
        )
        self.assertIsNone(
            await session.send_control_packet_wait_notification(
                b"query",
                label="optional",
                match=lambda _payload: True,
                timeout=0.01,
                required=False,
            )
        )
        self.assertFalse(await session.send_bulk_payload(b"payload"))
        await session.attach_runtime_controller(object(), timeout=0.01)

        with self.assertRaisesRegex(RuntimeError, "notification waits"):
            await session.wait_for_notification(
                "required", lambda _payload: True, timeout=0.01
            )
        with self.assertRaisesRegex(RuntimeError, "notification queries"):
            await session.send_control_packet_wait_notification(
                b"query",
                label="required",
                match=lambda _payload: True,
                timeout=0.01,
            )
        with self.assertRaisesRegex(RuntimeError, "standard payload sends"):
            await session.send_standard_payload(b"payload")

    async def test_malformed_async_byte_responses_are_rejected(self) -> None:
        session = RuntimeConnectionSession(
            _MalformedResponseConnection(), reporter=reporting.DUMMY_REPORTER
        )

        with self.assertRaisesRegex(TypeError, "query_control_packet"):
            await session.query_control_packet(b"query")
        with self.assertRaisesRegex(TypeError, "wait_for_notification"):
            await session.wait_for_notification(
                "wait", lambda _payload: True, timeout=0.01
            )
        with self.assertRaisesRegex(TypeError, "send_control_packet_wait_notification"):
            await session.send_control_packet_wait_notification(
                b"query",
                label="query",
                match=lambda _payload: True,
                timeout=0.01,
            )


class BluetoothBoundaryContractTests(unittest.IsolatedAsyncioTestCase):
    def test_device_transport_keeps_legacy_string_representation(self) -> None:
        self.assertEqual(str(DeviceTransport.BLE), "DeviceTransport.BLE")
        self.assertEqual(DeviceTransport.BLE.value, "ble")

    async def test_nonawaitable_ble_start_notify_is_rejected(self) -> None:
        transport = _BleakTransportSession(
            transport_profile=BleTransportProfile(prefer_generic_notify=True),
            write_resolver=_BleWriteEndpointResolver(reporter=reporting.DUMMY_REPORTER),
            reporter=reporting.DUMMY_REPORTER,
        )
        transport.bindings.notify_char = _NotifyCharacteristic()
        transport.bindings.notify_char_uuid = _NotifyCharacteristic.uuid

        with self.assertRaisesRegex(TypeError, "start_notify.*awaitable"):
            await transport.start_notify_if_available(
                _SyncNotifyClient(), lambda _sender, _data: None
            )
        self.assertFalse(transport.notify_started)

    async def test_nonawaitable_ble_pair_is_reported(self) -> None:
        socket = _BleakSocket()
        socket._client = _SyncPairClient()

        with self.assertRaisesRegex(RuntimeError, "BLE pairing failed") as raised:
            await socket._pair_if_supported()

        self.assertIsInstance(raised.exception.__cause__, TypeError)

    async def test_ble_backend_rejects_malformed_dynamic_byte_responses(self) -> None:
        backend = _connected_ble_backend(_BleResponseSocket("not bytes"))

        with self.assertRaisesRegex(TypeError, "query_control_packet"):
            backend._query_control_packet_blocking(b"query", 0.1)
        with self.assertRaisesRegex(TypeError, "wait_for_notification"):
            backend._wait_for_notification_blocking(
                "wait", lambda _payload: True, 0.1, True
            )
        with self.assertRaisesRegex(TypeError, "send_control_packet_wait_notification"):
            backend._send_control_packet_wait_notification_blocking(
                b"query", "query", lambda _payload: True, 0.1, True
            )

    def test_partial_send_rejects_invalid_progress(self) -> None:
        for result in (None, 0, -1, 4):
            with (
                self.subTest(result=result),
                self.assertRaisesRegex(RuntimeError, "Bluetooth send failed"),
            ):
                _send_all(_SendSocket([result]), b"abc")

    def test_partial_send_accepts_valid_progress_counts(self) -> None:
        sock = _SendSocket([1, 2])

        _send_all(sock, b"abc")

        self.assertEqual(sock.calls, [b"abc", b"bc"])

    def test_malformed_receive_chunks_fail_and_restore_timeout(self) -> None:
        for chunk in (None, "not bytes", bytearray(b"x"), memoryview(b"x")):
            with self.subTest(chunk_type=type(chunk).__name__):
                sock = _ReceiveSocket(chunk)

                with self.assertRaisesRegex(TypeError, "Bluetooth recv"):
                    _recv_until_match_or_timeout(sock, timeout=0.1)

                self.assertEqual(sock.timeout, 0.75)


if __name__ == "__main__":
    unittest.main()
