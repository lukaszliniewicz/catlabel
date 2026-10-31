from __future__ import annotations

import asyncio
import sys
import unittest
from types import ModuleType
from typing import Any
from unittest.mock import patch

from catlabel import reporting
from catlabel.devices import BleBulkWriteProfile, BleTransportProfile
from catlabel.printing.runtime.base import RuntimeController, RuntimeSessionApi
from catlabel.transport.bluetooth.adapters.bleak_adapter import _BleakSocket
from catlabel.transport.bluetooth.adapters.bleak_adapter_endpoint_resolver import (
    _BleWriteEndpointResolver,
)
from catlabel.transport.bluetooth.adapters.bleak_adapter_transport import (
    _BleakTransportSession,
)

SERVICE = "0000ae30-0000-1000-8000-00805f9b34fb"
WRITE = "0000ae01-0000-1000-8000-00805f9b34fb"
NOTIFY = "0000ae02-0000-1000-8000-00805f9b34fb"
BULK = "0000ae03-0000-1000-8000-00805f9b34fb"
CONTROL = "0000ae04-0000-1000-8000-00805f9b34fb"


class _Characteristic:
    def __init__(self, uuid: str, handle: int, *properties: str) -> None:
        self.uuid = uuid
        self.handle = handle
        self.properties = properties
        self.max_write_without_response_size = 20


class _Service:
    def __init__(self, uuid: str, *characteristics: _Characteristic) -> None:
        self.uuid = uuid
        self.characteristics = list(characteristics)


def _complete(
    offset: int = 0, *, write_properties: str = "write-without-response"
) -> _Service:
    return _Service(
        SERVICE,
        _Characteristic(WRITE, offset + 1, write_properties),
        _Characteristic(NOTIFY, offset + 2, "notify"),
        _Characteristic(BULK, offset + 3, "write-without-response"),
    )


def _profile(**kwargs: Any) -> BleTransportProfile:
    return BleTransportProfile(
        preferred_service_uuid=SERVICE,
        preferred_write_char_uuid=WRITE,
        notify_char_uuid=NOTIFY,
        bulk_write=BleBulkWriteProfile(char_uuid=BULK, write_delay_ms=0),
        standard_write_delay_ms=0,
        **kwargs,
    )


def _session(
    profile: BleTransportProfile, services: list[_Service]
) -> _BleakTransportSession:
    session = _BleakTransportSession(
        profile, _BleWriteEndpointResolver(), reporting.DUMMY_REPORTER
    )
    session.configure_endpoints(services)
    return session


class _Client:
    def __init__(self, services: list[_Service]) -> None:
        self.services = services
        self.mtu_size = 23
        self.started: list[_Characteristic] = []
        self.stopped: list[_Characteristic] = []
        self.callbacks: dict[_Characteristic, Any] = {}
        self.writes: list[_Characteristic] = []
        self.fail_start: _Characteristic | None = None
        self.fail_stop: _Characteristic | None = None

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def start_notify(self, endpoint: _Characteristic, callback: Any) -> None:
        self.started.append(endpoint)
        if endpoint is self.fail_start:
            raise RuntimeError("primary subscription failure")
        self.callbacks[endpoint] = callback

    async def stop_notify(self, endpoint: _Characteristic) -> None:
        self.stopped.append(endpoint)
        if endpoint is self.fail_stop:
            raise asyncio.CancelledError("unsubscribe cancelled")

    async def write_gatt_char(
        self, endpoint: _Characteristic, _data: bytes, *, response: bool
    ) -> None:
        self.writes.append(endpoint)


class _Controller(RuntimeController):
    def __init__(self) -> None:
        self.ordinary: list[bytes] = []
        self.control: list[bytes] = []

    def handle_notification(self, session: RuntimeSessionApi, payload: bytes) -> None:
        self.ordinary.append(payload)

    def handle_control_notification(
        self, session: RuntimeSessionApi, payload: bytes
    ) -> None:
        self.control.append(payload)


class BleGattLayoutSelectionTests(unittest.TestCase):
    def test_complete_duplicate_service_wins_over_incomplete_instance(self) -> None:
        incomplete = _Service(
            SERVICE, _Characteristic(WRITE, 1, "write-without-response")
        )
        complete = _complete(20)
        session = _session(_profile(), [incomplete, complete])
        self.assertIs(session.bindings.write_char, complete.characteristics[0])
        self.assertIs(session.bindings.notify_char, complete.characteristics[1])
        self.assertIs(session.bindings.bulk_write_char, complete.characteristics[2])

    def test_multiple_complete_services_keep_existing_write_scoring(self) -> None:
        write = _complete(write_properties="write")
        wnr = _complete(20)
        session = _session(_profile(), [write, wnr])
        self.assertIs(session.bindings.write_char, wnr.characteristics[0])
        self.assertIs(session.bindings.notify_char, wnr.characteristics[1])

    def test_explicit_service_and_write_must_both_match(self) -> None:
        resolver = _BleWriteEndpointResolver()
        for services in (
            [_Service(SERVICE, _Characteristic("wrong-write", 1, "write"))],
            [_Service("wrong-service", _Characteristic(WRITE, 1, "write"))],
        ):
            with self.subTest(services=services):
                self.assertIsNone(resolver.resolve(services, profile=_profile()))

    def test_required_notify_or_bulk_cannot_come_from_another_service(self) -> None:
        for missing_index in (1, 2):
            with self.subTest(missing_index=missing_index):
                selected = _complete()
                missing = selected.characteristics.pop(missing_index)
                other = _Service(SERVICE, missing)
                with self.assertRaisesRegex(RuntimeError, "not found"):
                    _session(_profile(), [selected, other])

    def test_required_endpoints_must_have_correct_properties(self) -> None:
        for index in (1, 2):
            with self.subTest(index=index):
                service = _complete()
                service.characteristics[index].properties = ("read",)
                with self.assertRaisesRegex(RuntimeError, "required properties"):
                    _session(_profile(), [service])

    def test_ambiguous_explicit_notify_within_selected_service_fails(self) -> None:
        service = _complete()
        service.characteristics.append(_Characteristic(NOTIFY, 99, "notify"))
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            _session(_profile(), [service])

    def test_generic_optional_notify_is_limited_to_selected_write_service(self) -> None:
        write = _Characteristic("custom-write", 1, "write-without-response")
        elsewhere = _Characteristic(NOTIFY, 12, "notify")
        selected = _Service("custom-service", write)
        session = _session(
            BleTransportProfile(prefer_generic_notify=True),
            [selected, _Service("other", elsewhere)],
        )
        self.assertIs(session.bindings.write_char, write)
        self.assertIsNone(session.bindings.notify_char)
        local = _Characteristic("custom-notify", 2, "indicate")
        selected.characteristics.append(local)
        session = _session(
            BleTransportProfile(prefer_generic_notify=True),
            [selected, _Service("other", elsewhere)],
        )
        self.assertIs(session.bindings.notify_char, local)

    def test_separate_control_endpoint_must_be_unambiguous(self) -> None:
        service = _complete()
        control = _Characteristic(CONTROL, 40, "notify")
        session = _session(
            _profile(control_notify_char_uuid=CONTROL),
            [service, _Service("control-service", control)],
        )
        self.assertIs(session.bindings.control_notify_char, control)
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            _session(
                _profile(control_notify_char_uuid=CONTROL),
                [
                    service,
                    _Service("control-service", control),
                    _Service(
                        "duplicate-control", _Characteristic(CONTROL, 50, "notify")
                    ),
                ],
            )

    def test_missing_layout_fails_before_subscriptions_or_writes(self) -> None:
        service = _complete()
        service.characteristics.pop()
        client = _Client([service])
        module = ModuleType("bleak")
        module.__dict__["BleakClient"] = lambda _target: client

        class Socket(_BleakSocket):
            async def _resolve_client_target(self, address: str) -> str:
                return address

        socket = Socket(ble_profile=_profile())
        socket._timeout = 0.05
        socket._cleanup_timeout = 0.02
        with (
            patch.dict(sys.modules, {"bleak": module}),
            self.assertRaisesRegex(RuntimeError, "bulk write"),
        ):
            socket.connect(("fake", 0))
        self.assertEqual(client.started, [])
        self.assertEqual(client.writes, [])
        self.assertIsNone(socket._loop)


class BleGattEndpointObjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_subscribe_and_unsubscribe_use_selected_objects(self) -> None:
        selected = _complete()
        unselected = _complete(20)
        control = _Characteristic(CONTROL, 40, "notify")
        services = [selected, unselected, _Service("control", control)]
        session = _session(_profile(control_notify_char_uuid=CONTROL), services)
        socket = _BleakSocket()
        socket._transport = session
        client = _Client(services)
        controller = _Controller()
        await session.start_notify_if_available(client, socket._handle_notification)
        await session.initialize_connection(client, mtu_size=20, timeout=0.05)
        await session.attach_runtime_controller(controller, mtu_size=20, timeout=0.05)
        self.assertEqual(client.started, [selected.characteristics[1], control])
        self.assertTrue(await session.send_standard_payload(b"a"))
        self.assertTrue(await session.send_bulk_payload(b"b"))
        self.assertEqual(
            client.writes, [selected.characteristics[0], selected.characteristics[2]]
        )
        # Bleak's sender argument cannot redirect a selected channel's callback.
        client.callbacks[selected.characteristics[1]](
            unselected.characteristics[1], b"ordinary"
        )
        client.callbacks[control](selected.characteristics[1], b"control")
        session.handle_notification(
            b"unselected", source_uuid=NOTIFY, source=unselected.characteristics[1]
        )
        self.assertEqual(controller.ordinary, [b"ordinary"])
        self.assertEqual(controller.control, [b"control"])
        await session.stop_notify_if_started(client)
        self.assertEqual(client.stopped, client.started)

    async def test_shared_physical_ordinary_and_control_endpoint_subscribes_once(
        self,
    ) -> None:
        service = _complete()
        session = _session(_profile(control_notify_char_uuid=NOTIFY), [service])
        self.assertIs(
            session.bindings.notify_char, session.bindings.control_notify_char
        )
        client = _Client([service])
        await session.start_notify_if_available(client, lambda _source, _data: None)
        await session.stop_notify_if_started(client)
        self.assertEqual(client.started, [service.characteristics[1]])
        self.assertEqual(client.stopped, client.started)

    async def test_equal_uuid_distinct_selected_objects_do_not_deduplicate_or_cross_route(
        self,
    ) -> None:
        service = _complete()
        session = _session(_profile(), [service])
        control = _Characteristic(NOTIFY, 99, "notify")
        session.bindings.control_notify_char = control
        session.bindings.control_notify_char_uuid = NOTIFY
        client = _Client([service])
        socket = _BleakSocket()
        socket._transport = session
        controller = _Controller()
        await session.start_notify_if_available(client, socket._handle_notification)
        await session.attach_runtime_controller(controller, mtu_size=20, timeout=0.05)
        self.assertEqual(client.started, [service.characteristics[1], control])
        client.callbacks[service.characteristics[1]](control, b"ordinary")
        client.callbacks[control](service.characteristics[1], b"control")
        self.assertEqual(controller.ordinary, [b"ordinary"])
        self.assertEqual(controller.control, [b"control"])
        await session.stop_notify_if_started(client)
        self.assertEqual(client.stopped, client.started)

    async def test_failed_subscription_rollback_retains_actual_endpoint_for_retry(
        self,
    ) -> None:
        service = _complete()
        control = _Characteristic(CONTROL, 40, "notify")
        services = [service, _Service("control", control)]
        session = _session(_profile(control_notify_char_uuid=CONTROL), services)
        client = _Client(services)
        client.fail_start = control
        client.fail_stop = service.characteristics[1]
        with self.assertRaisesRegex(RuntimeError, "primary subscription failure"):
            await session.start_notify_if_available(client, lambda _source, _data: None)
        self.assertEqual(
            session._started_notify_endpoints, [service.characteristics[1]]
        )
        client.fail_stop = None
        await session.stop_notify_if_started(client)
        self.assertEqual(
            client.stopped, [service.characteristics[1], service.characteristics[1]]
        )
        self.assertEqual(session._started_notify_endpoints, [])


if __name__ == "__main__":
    unittest.main()
