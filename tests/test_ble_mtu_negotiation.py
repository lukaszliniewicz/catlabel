from __future__ import annotations

import asyncio
import sys
import unittest
from types import ModuleType
from typing import Any
from unittest.mock import patch

import catlabel.transport.bluetooth.adapters.bleak_adapter as adapter_module
from catlabel.devices import BleTransportProfile, get_ble_transport_profile
from catlabel.transport.bluetooth.adapters.bleak_adapter import _BleakSocket
from catlabel.transport.bluetooth.adapters.bleak_adapter_transport import (
    _BleakTransportSession,
)


class _WriteCharacteristic:
    uuid = "0000ffe1-0000-1000-8000-00805f9b34fb"
    properties = ["write-without-response"]
    max_write_without_response_size = 20


class _NotifyCharacteristic:
    uuid = "0000ffe2-0000-1000-8000-00805f9b34fb"
    properties = ["notify"]


class _Service:
    uuid = "0000ffe0-0000-1000-8000-00805f9b34fb"

    def __init__(self) -> None:
        self.characteristics = [_WriteCharacteristic(), _NotifyCharacteristic()]


class _FakeBlueZBackend:
    __module__ = "bleak.backends.bluezdbus.client"

    def __init__(
        self,
        client: _FakeBleakClient,
        events: list[object],
        *,
        error: BaseException | None = None,
        delay: float = 0.0,
        negotiated_mtu: Any = 248,
    ) -> None:
        self.client = client
        self.events = events
        self.error = error
        self.delay = delay
        self.negotiated_mtu = negotiated_mtu
        self.calls = 0

    async def _acquire_mtu(self) -> None:
        self.calls += 1
        self.events.append("mtu")
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        self.client.mtu_size = self.negotiated_mtu


class _OtherBackend(_FakeBlueZBackend):
    __module__ = "bleak.backends.bluezdbus_fake.client"


class _MissingBlueZBackend:
    __module__ = "bleak.backends.bluezdbus.client"


class _FakeBleakClient:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self._backend: Any = None
        self.mtu_size = 23
        self.services = [_Service()]

    async def connect(self) -> None:
        self.events.append("connect")

    async def disconnect(self) -> None:
        self.events.append("disconnect")

    async def start_notify(self, _uuid: str, _callback: Any) -> None:
        self.events.append("notify")

    async def stop_notify(self, _uuid: str) -> None:
        self.events.append("stop_notify")

    async def write_gatt_char(self, _char: Any, data: bytes, *, response: bool) -> None:
        self.events.append(("write", bytes(data), response))


class _TestSocket(_BleakSocket):
    async def _resolve_client_target(self, address: str) -> str:
        return address


class _WritingRuntime:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def adopt_previous(self, _previous: Any) -> None:
        return None

    async def initialize_connection(
        self,
        session: _BleakTransportSession,
        *,
        mtu_size: int,
        timeout: float,
    ) -> None:
        _ = mtu_size, timeout
        self.events.append("runtime_initialize")
        await session.send_control_packet(b"x" * 500)

    async def after_initialize(
        self,
        _session: _BleakTransportSession,
        *,
        timeout: float,
    ) -> None:
        _ = timeout

    async def stop(self, _session: _BleakTransportSession) -> None:
        return None


def _fake_bleak_module(client: _FakeBleakClient) -> ModuleType:
    module = ModuleType("bleak")
    module.__dict__["BleakClient"] = lambda _target: client
    return module


def _fake_client(
    events: list[object],
    backend_kind: str,
    *,
    error: BaseException | None = None,
    delay: float = 0.0,
) -> tuple[_FakeBleakClient, _FakeBlueZBackend | _MissingBlueZBackend]:
    client = _FakeBleakClient(events)
    if backend_kind == "missing":
        backend: _FakeBlueZBackend | _MissingBlueZBackend = _MissingBlueZBackend()
    elif backend_kind == "other":
        backend = _OtherBackend(client, events, error=error, delay=delay)
    else:
        backend = _FakeBlueZBackend(client, events, error=error, delay=delay)
    client._backend = backend
    return client, backend


class BleMtuNegotiationTests(unittest.IsolatedAsyncioTestCase):
    async def test_v5g_alone_opts_into_bluez_mtu_acquisition(self) -> None:
        self.assertTrue(get_ble_transport_profile("v5g").acquire_bluez_mtu)
        self.assertFalse(get_ble_transport_profile("v5c").acquire_bluez_mtu)
        self.assertFalse(BleTransportProfile().acquire_bluez_mtu)

    async def test_successful_acquisition_precedes_notifications_and_runtime_writes(
        self,
    ) -> None:
        events: list[object] = []
        client, backend = _fake_client(events, "bluez")
        socket = _TestSocket(ble_profile=get_ble_transport_profile("v5g"))
        socket.settimeout(30.0)
        observed_timeouts: list[float | None] = []
        original_wait_for = asyncio.wait_for

        async def capture_wait_for(awaitable: Any, timeout: float | None = None) -> Any:
            observed_timeouts.append(timeout)
            return await original_wait_for(awaitable, timeout=timeout)

        with (
            patch.dict(sys.modules, {"bleak": _fake_bleak_module(client)}),
            patch.object(adapter_module.sys, "platform", "linux"),
            patch.object(
                adapter_module.asyncio,
                "wait_for",
                new=capture_wait_for,
            ),
        ):
            await socket._connect_async("fake-printer")
            await socket._transport.attach_runtime_controller(
                _WritingRuntime(events),
                mtu_size=socket._mtu_size,
                timeout=socket._timeout,
            )

        assert isinstance(backend, _FakeBlueZBackend)
        self.assertEqual(backend.calls, 1)
        self.assertEqual(observed_timeouts, [5.0])
        self.assertEqual(socket._mtu_size, 245)
        self.assertEqual(socket._transport._verified_payload, 245)
        self.assertLess(events.index("mtu"), events.index("notify"))
        self.assertLess(events.index("notify"), events.index("runtime_initialize"))
        runtime_chunks = [
            event[1]
            for event in events
            if isinstance(event, tuple)
            and len(event) > 1
            and isinstance(event[1], bytes)
        ]
        self.assertEqual([len(chunk) for chunk in runtime_chunks], [240, 240, 20])
        self.assertTrue(all(len(chunk) <= 245 for chunk in runtime_chunks))
        self.assertTrue(all(len(chunk) <= 448 for chunk in runtime_chunks))

    async def test_deadline_uses_smaller_socket_timeout_when_configured(self) -> None:
        events: list[object] = []
        client, _backend = _fake_client(events, "bluez")
        socket = _TestSocket(ble_profile=get_ble_transport_profile("v5g"))
        socket.settimeout(0.25)
        observed_timeouts: list[float | None] = []
        original_wait_for = asyncio.wait_for

        async def capture_wait_for(awaitable: Any, timeout: float | None = None) -> Any:
            observed_timeouts.append(timeout)
            return await original_wait_for(awaitable, timeout=timeout)

        with (
            patch.dict(sys.modules, {"bleak": _fake_bleak_module(client)}),
            patch.object(adapter_module.sys, "platform", "linux"),
            patch.object(
                adapter_module.asyncio,
                "wait_for",
                new=capture_wait_for,
            ),
        ):
            await socket._connect_async("fake-printer")

        self.assertEqual(observed_timeouts, [0.25])

    async def test_invalid_public_mtu_is_not_marked_verified(self) -> None:
        for invalid_mtu in (23, 518, "248"):
            with self.subTest(mtu=invalid_mtu):
                events: list[object] = []
                client, backend = _fake_client(events, "bluez")
                assert isinstance(backend, _FakeBlueZBackend)
                backend.negotiated_mtu = invalid_mtu
                socket = _TestSocket(ble_profile=get_ble_transport_profile("v5g"))
                with (
                    patch.dict(sys.modules, {"bleak": _fake_bleak_module(client)}),
                    patch.object(adapter_module.sys, "platform", "linux"),
                ):
                    await socket._connect_async("fake-printer")

                self.assertIsNone(socket._transport._verified_payload)
                self.assertEqual(
                    _BleakTransportSession._effective_mtu_payload(
                        _WriteCharacteristic(),
                        socket._mtu_size,
                        response=False,
                        reserve=5,
                    ),
                    15,
                )

    async def test_inapplicable_failed_and_timed_out_negotiation_keep_public_limit(
        self,
    ) -> None:
        scenarios = (
            ("failed", "linux", True, "bluez", RuntimeError("dbus failed"), 10.0, 1),
            ("missing", "linux", True, "missing", None, 10.0, 0),
            ("non-linux", "darwin", True, "bluez", None, 10.0, 0),
            ("non-bluez", "linux", True, "other", None, 10.0, 0),
            ("disabled", "linux", False, "bluez", None, 10.0, 0),
            ("nonpositive-timeout", "linux", True, "bluez", None, 0.0, 0),
            ("timeout", "linux", True, "bluez", None, 0.02, 1),
        )
        for name, platform, enabled, backend_kind, error, timeout, calls in scenarios:
            with self.subTest(scenario=name):
                events: list[object] = []
                delay = 0.1 if name == "timeout" else 0.0
                client, backend = _fake_client(
                    events,
                    backend_kind,
                    error=error,
                    delay=delay,
                )
                profile = (
                    get_ble_transport_profile("v5g")
                    if enabled
                    else BleTransportProfile(write_without_response_payload_reserve=5)
                )
                socket = _TestSocket(ble_profile=profile)
                socket.settimeout(timeout)
                with (
                    patch.dict(sys.modules, {"bleak": _fake_bleak_module(client)}),
                    patch.object(adapter_module.sys, "platform", platform),
                ):
                    await socket._connect_async("fake-printer")

                self.assertEqual(events.count("mtu"), calls)
                self.assertIsNone(socket._transport._verified_payload)
                self.assertEqual(socket._mtu_size, 20)
                self.assertEqual(
                    _BleakTransportSession._effective_mtu_payload(
                        _WriteCharacteristic(),
                        socket._mtu_size,
                        response=False,
                        reserve=5,
                    ),
                    15,
                )


class BleMtuCancellationCleanupTests(unittest.TestCase):
    def test_cancellation_propagates_through_connect_and_cleans_up_socket(self) -> None:
        events: list[object] = []
        client, _backend = _fake_client(
            events,
            "bluez",
            error=asyncio.CancelledError("MTU acquisition cancelled"),
        )
        socket = _TestSocket(ble_profile=get_ble_transport_profile("v5g"))

        with (
            patch.dict(sys.modules, {"bleak": _fake_bleak_module(client)}),
            patch.object(adapter_module.sys, "platform", "linux"),
            self.assertRaises(asyncio.CancelledError),
        ):
            socket.connect(("fake-printer", 0))

        self.assertIn("disconnect", events)
        self.assertFalse(socket._connected)
        self.assertIsNone(socket._client)
        self.assertIsNone(socket._loop)


if __name__ == "__main__":
    unittest.main()
