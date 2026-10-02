from __future__ import annotations

import asyncio
import unittest
from typing import Any

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

NOTIFY_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
CONTROL_UUID = "0000ffe3-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
BULK_UUID = "0000ffe4-0000-1000-8000-00805f9b34fb"


class _Characteristic:
    def __init__(self, uuid: str, properties: tuple[str, ...] = ("notify",)) -> None:
        self.uuid = uuid
        self.properties = list(properties)


class _Service:
    uuid = "0000ffe0-0000-1000-8000-00805f9b34fb"

    def __init__(self, *characteristics: _Characteristic) -> None:
        self.characteristics = list(characteristics)


class _FakeClient:
    def __init__(
        self,
        *,
        fail_start_uuid: str = "",
        start_error: BaseException | None = None,
        stop_notify_errors: dict[str, BaseException] | None = None,
        disconnect_error: BaseException | None = None,
    ) -> None:
        self.fail_start_uuid = fail_start_uuid
        self.start_error = (
            start_error
            if start_error is not None
            else RuntimeError("subscription failed")
        )
        self.stop_notify_errors = stop_notify_errors or {}
        self.disconnect_error = disconnect_error
        self.start_calls: list[str] = []
        self.stop_calls: list[str] = []
        self.disconnect_calls = 0
        self.callbacks: dict[str, Any] = {}
        self.write_calls: list[bytes] = []
        self.events: list[tuple[str, int | bytes]] = []

    async def start_notify(self, uuid: str, callback) -> None:
        self.start_calls.append(uuid)
        if uuid == self.fail_start_uuid:
            raise self.start_error
        self.callbacks[uuid] = callback

    async def stop_notify(self, uuid: str) -> None:
        self.stop_calls.append(uuid)
        if uuid in self.stop_notify_errors:
            raise self.stop_notify_errors[uuid]

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.disconnect_error is not None:
            raise self.disconnect_error

    async def write_gatt_char(self, _char: Any, data: bytes, *, response: bool) -> None:
        _ = response
        payload = bytes(data)
        self.write_calls.append(payload)
        self.events.append(("write", payload))

    def notify(self, uuid: str, payload: bytes) -> None:
        self.callbacks[uuid](uuid, payload)


class _CaptureSink(reporting.ReportSink):
    def __init__(self) -> None:
        self.messages: list[reporting.ReportMessage] = []

    def emit(self, message: reporting.ReportMessage) -> None:
        self.messages.append(message)


class _WriteController(RuntimeController):
    def __init__(self, *, fail_on_write: int | None = None) -> None:
        self.fail_on_write = fail_on_write
        self.write_sizes: list[int] = []
        self.write_timeouts: list[float] = []
        self.events: list[tuple[str, int | bytes]] = []
        self.notifications: list[bytes] = []
        self.control_notifications: list[bytes] = []
        self.stop_calls = 0
        self.stop_error: BaseException | None = None

    def handle_notification(self, session: RuntimeSessionApi, payload: bytes) -> None:
        _ = session
        self.notifications.append(bytes(payload))

    def handle_control_notification(
        self, session: RuntimeSessionApi, payload: bytes
    ) -> None:
        _ = session
        self.control_notifications.append(bytes(payload))

    async def before_write(
        self, session: RuntimeSessionApi, *, size: int, timeout: float
    ) -> None:
        _ = session
        self.write_sizes.append(size)
        self.write_timeouts.append(timeout)
        self.events.append(("before", size))
        if self.fail_on_write == len(self.write_sizes):
            raise RuntimeError("write permission rejected")

    async def stop(self, session: RuntimeSessionApi) -> None:
        _ = session
        self.stop_calls += 1
        if self.stop_error is not None:
            raise self.stop_error


def _new_session(
    profile: BleTransportProfile,
    *,
    reporter: reporting.Reporter = reporting.DUMMY_REPORTER,
) -> _BleakTransportSession:
    return _BleakTransportSession(
        transport_profile=profile,
        write_resolver=_BleWriteEndpointResolver(reporter=reporter),
        reporter=reporter,
    )


def _notification_services(
    *, ordinary_uuid: str = NOTIFY_UUID, control_uuid: str = CONTROL_UUID
) -> list[_Service]:
    return [
        _Service(
            _Characteristic(ordinary_uuid),
            _Characteristic(control_uuid),
        )
    ]


class BleWriteControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_control_and_ordinary_notifications_route_by_bound_source_uuid(
        self,
    ) -> None:
        sink = _CaptureSink()
        reporter = reporting.Reporter([sink])
        profile = BleTransportProfile(
            notify_char_uuid=NOTIFY_UUID,
            control_notify_char_uuid=CONTROL_UUID,
        )
        session = _new_session(profile, reporter=reporter)
        session.configure_endpoints(_notification_services())
        client = _FakeClient()
        socket = _BleakSocket(ble_profile=profile, reporter=reporter)
        socket._transport = session
        await session.start_notify_if_available(client, socket._handle_notification)
        await session.initialize_connection(client, mtu_size=23, timeout=0.1)
        controller = _WriteController()
        await session.attach_runtime_controller(controller, mtu_size=23, timeout=0.1)

        waiter = asyncio.create_task(
            session.wait_for_notification(
                "ordinary reply", lambda payload: payload == b"reply", timeout=1.0
            )
        )
        await asyncio.sleep(0)
        client.notify(CONTROL_UUID, b"reply")

        self.assertFalse(waiter.done())
        self.assertEqual(session._notification_history, [])
        self.assertEqual(controller.control_notifications, [b"reply"])
        self.assertEqual(controller.notifications, [])

        client.notify(NOTIFY_UUID, b"reply")
        self.assertEqual(await waiter, b"reply")
        self.assertEqual(controller.notifications, [b"reply"])
        self.assertEqual(client.start_calls, [NOTIFY_UUID, CONTROL_UUID])
        self.assertTrue(
            any(CONTROL_UUID in (message.detail or "") for message in sink.messages)
        )

        await session.stop_notify_if_started(client)
        self.assertEqual(client.stop_calls, [NOTIFY_UUID, CONTROL_UUID])

    async def test_one_subscription_when_control_and_ordinary_uuid_are_equal(
        self,
    ) -> None:
        profile = BleTransportProfile(
            notify_char_uuid=NOTIFY_UUID,
            control_notify_char_uuid=NOTIFY_UUID,
        )
        session = _new_session(profile)
        session.configure_endpoints(
            _notification_services(ordinary_uuid=NOTIFY_UUID, control_uuid=NOTIFY_UUID)
        )
        client = _FakeClient()
        socket = _BleakSocket(ble_profile=profile)
        socket._transport = session
        await session.start_notify_if_available(client, socket._handle_notification)
        controller = _WriteController()
        await session.attach_runtime_controller(controller, mtu_size=23, timeout=0.1)

        self.assertEqual(client.start_calls, [NOTIFY_UUID])
        self.assertTrue(session.can_wait_for_notification())
        client.notify(NOTIFY_UUID, b"shared")
        self.assertEqual(controller.control_notifications, [b"shared"])
        self.assertEqual(controller.notifications, [])

        await session.stop_notify_if_started(client)
        self.assertEqual(client.stop_calls, [NOTIFY_UUID])

    async def test_before_write_runs_for_each_chunk_on_standard_control_and_bulk_sends(
        self,
    ) -> None:
        client = _FakeClient()
        session = _new_session(
            BleTransportProfile(
                standard_chunk_cap=2,
                standard_write_delay_ms=0,
                bulk_write=BleBulkWriteProfile(
                    char_uuid=BULK_UUID,
                    chunk_cap=2,
                    write_delay_ms=0,
                ),
            )
        )
        session.bindings.write_char = _Characteristic(
            WRITE_UUID, ("write-without-response",)
        )
        session.bindings.bulk_write_char = _Characteristic(
            BULK_UUID, ("write-without-response",)
        )
        await session.initialize_connection(client, mtu_size=23, timeout=0.1)
        controller = _WriteController()
        client.events = controller.events
        await session.attach_runtime_controller(controller, mtu_size=23, timeout=0.1)

        self.assertTrue(await session.send_standard_payload(b"abc", timeout=1.25))
        self.assertTrue(await session.send_control_packet(b"de", timeout=2.5))
        self.assertTrue(await session.send_bulk_payload(b"fgh", timeout=3.75))

        expected = [b"ab", b"c", b"de", b"fg", b"h"]
        self.assertEqual(client.write_calls, expected)
        expected_events: list[tuple[str, int | bytes]] = []
        for payload in expected:
            expected_events.extend([("before", len(payload)), ("write", payload)])
        self.assertEqual(controller.events, expected_events)
        self.assertEqual(controller.write_timeouts, [1.25, 1.25, 2.5, 3.75, 3.75])

    async def test_legacy_duck_controller_can_omit_optional_runtime_hooks(self) -> None:
        client = _FakeClient()
        session = _new_session(BleTransportProfile(standard_write_delay_ms=0))
        session.bindings.write_char = _Characteristic(
            WRITE_UUID, ("write-without-response",)
        )
        session._runtime_controller = object()
        await session.initialize_connection(client, mtu_size=23, timeout=0.1)

        self.assertTrue(await session.send_standard_payload(b"legacy"))
        session.bindings.control_notify_char_uuid = CONTROL_UUID
        session.handle_notification(b"control", source_uuid=CONTROL_UUID)

        self.assertEqual(client.write_calls, [b"legacy"])
        self.assertEqual(session._notification_history, [])

    async def test_flow_resume_precedes_permission_hook_and_second_failure_aborts_writes(
        self,
    ) -> None:
        profile = BleTransportProfile(
            standard_chunk_cap=2,
            standard_write_delay_ms=0,
            flow_controlled_standard_write=True,
            flow_resume_timeout_s=1.0,
        )
        client = _FakeClient()
        session = _new_session(profile)
        session.bindings.write_char = _Characteristic(
            WRITE_UUID, ("write-without-response",)
        )
        await session.initialize_connection(client, mtu_size=23, timeout=0.1)
        controller = _WriteController()
        await session.attach_runtime_controller(controller, mtu_size=23, timeout=0.1)
        session.set_flow_paused(True)

        sending = asyncio.create_task(
            session.send_standard_payload(b"abcde", timeout=4.0)
        )
        await asyncio.sleep(0.02)
        self.assertEqual(controller.events, [])
        self.assertEqual(client.write_calls, [])
        session.set_flow_paused(False)
        self.assertTrue(await sending)
        self.assertEqual(controller.events[0], ("before", 2))
        self.assertEqual(client.write_calls, [b"ab", b"cd", b"e"])
        self.assertEqual(controller.write_timeouts, [4.0, 4.0, 4.0])

        failing_client = _FakeClient()
        failing_session = _new_session(
            BleTransportProfile(standard_chunk_cap=2, standard_write_delay_ms=0)
        )
        failing_session.bindings.write_char = _Characteristic(
            WRITE_UUID, ("write-without-response",)
        )
        await failing_session.initialize_connection(
            failing_client, mtu_size=23, timeout=0.1
        )
        failing_controller = _WriteController(fail_on_write=2)
        await failing_session.attach_runtime_controller(
            failing_controller, mtu_size=23, timeout=0.1
        )

        with self.assertRaisesRegex(RuntimeError, "permission rejected"):
            await failing_session.send_standard_payload(b"abcde", timeout=5.0)
        self.assertEqual(failing_client.write_calls, [b"ab"])
        self.assertEqual(failing_controller.write_timeouts, [5.0, 5.0])

    async def test_missing_declared_control_endpoint_fails_configuration(self) -> None:
        session = _new_session(
            BleTransportProfile(control_notify_char_uuid=CONTROL_UUID)
        )

        with self.assertRaisesRegex(
            RuntimeError, "control notification characteristic"
        ):
            session.configure_endpoints([_Service(_Characteristic(NOTIFY_UUID))])

        self.assertEqual(session.bindings.control_notify_char_uuid, "")

    async def test_second_subscription_failure_rolls_back_first_subscription(
        self,
    ) -> None:
        session = _new_session(
            BleTransportProfile(
                notify_char_uuid=NOTIFY_UUID,
                control_notify_char_uuid=CONTROL_UUID,
            )
        )
        session.configure_endpoints(_notification_services())
        client = _FakeClient(fail_start_uuid=CONTROL_UUID)

        with self.assertRaisesRegex(RuntimeError, "subscription failed"):
            await session.start_notify_if_available(client, lambda _uuid, _data: None)

        self.assertEqual(client.start_calls, [NOTIFY_UUID, CONTROL_UUID])
        self.assertEqual(client.stop_calls, [NOTIFY_UUID])
        self.assertFalse(session.notify_started)
        self.assertEqual(session._started_notify_uuids, [])

    async def test_subscription_failure_keeps_primary_error_when_rollback_is_cancelled(
        self,
    ) -> None:
        session = _new_session(
            BleTransportProfile(
                notify_char_uuid=NOTIFY_UUID,
                control_notify_char_uuid=CONTROL_UUID,
            )
        )
        session.configure_endpoints(_notification_services())
        start_error = RuntimeError("original subscription failure")
        rollback_error = asyncio.CancelledError("rollback cancelled")
        client = _FakeClient(
            fail_start_uuid=CONTROL_UUID,
            start_error=start_error,
            stop_notify_errors={NOTIFY_UUID: rollback_error},
        )

        with self.assertRaises(RuntimeError) as raised:
            await session.start_notify_if_available(client, lambda _uuid, _data: None)

        self.assertIs(raised.exception, start_error)
        self.assertEqual(client.stop_calls, [NOTIFY_UUID])
        self.assertFalse(session.notify_started)
        self.assertEqual(session._started_notify_uuids, [])
        self.assertEqual(session._notification_history, [])

    async def test_unsubscribe_cancellation_attempts_all_and_clears_waiters(
        self,
    ) -> None:
        profile = BleTransportProfile(
            notify_char_uuid=NOTIFY_UUID,
            control_notify_char_uuid=CONTROL_UUID,
        )
        session = _new_session(profile)
        session.configure_endpoints(_notification_services())
        cancellation = asyncio.CancelledError("unsubscribe cancelled")
        client = _FakeClient(stop_notify_errors={NOTIFY_UUID: cancellation})
        socket = _BleakSocket(ble_profile=profile)
        socket._transport = session
        await session.start_notify_if_available(client, socket._handle_notification)
        session.handle_notification(b"ordinary history")
        waiter = asyncio.create_task(
            session.wait_for_notification(
                "pending", lambda _payload: False, timeout=10.0
            )
        )
        await asyncio.sleep(0)

        with self.assertRaises(asyncio.CancelledError) as raised:
            await session.stop_notify_if_started(client)

        self.assertIs(raised.exception, cancellation)
        self.assertEqual(client.stop_calls, [NOTIFY_UUID, CONTROL_UUID])
        self.assertFalse(session.notify_started)
        self.assertEqual(session._started_notify_uuids, [])
        self.assertEqual(session._notification_history, [])
        self.assertEqual(session._notification_waiters, [])
        self.assertIsInstance(
            (await asyncio.gather(waiter, return_exceptions=True))[0],
            asyncio.CancelledError,
        )

    async def test_unsubscribe_error_does_not_skip_later_uuid_and_is_logged(
        self,
    ) -> None:
        sink = _CaptureSink()
        reporter = reporting.Reporter([sink])
        profile = BleTransportProfile(
            notify_char_uuid=NOTIFY_UUID,
            control_notify_char_uuid=CONTROL_UUID,
        )
        session = _new_session(profile, reporter=reporter)
        session.configure_endpoints(_notification_services())
        client = _FakeClient(
            stop_notify_errors={NOTIFY_UUID: RuntimeError("stop notify failed")}
        )
        socket = _BleakSocket(ble_profile=profile, reporter=reporter)
        socket._transport = session
        await session.start_notify_if_available(client, socket._handle_notification)

        await session.stop_notify_if_started(client)

        self.assertEqual(client.stop_calls, [NOTIFY_UUID, CONTROL_UUID])
        self.assertTrue(
            any(
                "failed to unsubscribe" in (message.detail or "")
                and NOTIFY_UUID in (message.detail or "")
                for message in sink.messages
            )
        )

    async def test_disconnect_runs_after_runtime_stop_error_and_preserves_it(
        self,
    ) -> None:
        for stop_error in (
            RuntimeError("runtime stop failed"),
            asyncio.CancelledError("runtime stop cancelled"),
        ):
            with self.subTest(error=type(stop_error).__name__):
                profile = BleTransportProfile(
                    notify_char_uuid=NOTIFY_UUID,
                    control_notify_char_uuid=CONTROL_UUID,
                )
                session = _new_session(profile)
                session.configure_endpoints(_notification_services())
                client = _FakeClient(
                    disconnect_error=RuntimeError("physical disconnect failed")
                )
                socket = _BleakSocket(ble_profile=profile)
                socket._client = client
                socket._transport = session
                await session.start_notify_if_available(
                    client, socket._handle_notification
                )
                controller = _WriteController()
                controller.stop_error = stop_error
                await session.attach_runtime_controller(
                    controller, mtu_size=23, timeout=0.1
                )

                with self.assertRaises(type(stop_error)) as raised:
                    await socket._safe_disconnect_async()

                self.assertIs(raised.exception, stop_error)
                self.assertEqual(client.disconnect_calls, 1)
                self.assertEqual(client.stop_calls, [NOTIFY_UUID, CONTROL_UUID])

    async def test_disconnect_cancellation_propagates_after_runtime_cleanup(
        self,
    ) -> None:
        profile = BleTransportProfile(
            notify_char_uuid=NOTIFY_UUID,
            control_notify_char_uuid=CONTROL_UUID,
        )
        session = _new_session(profile)
        session.configure_endpoints(_notification_services())
        disconnect_error = asyncio.CancelledError("disconnect cancelled")
        client = _FakeClient(disconnect_error=disconnect_error)
        socket = _BleakSocket(ble_profile=profile)
        socket._client = client
        socket._transport = session
        await session.start_notify_if_available(client, socket._handle_notification)

        with self.assertRaises(asyncio.CancelledError) as raised:
            await socket._safe_disconnect_async()

        self.assertIs(raised.exception, disconnect_error)
        self.assertEqual(client.disconnect_calls, 1)
        self.assertEqual(client.stop_calls, [NOTIFY_UUID, CONTROL_UUID])

    async def test_disconnect_exception_remains_best_effort_without_stop_error(
        self,
    ) -> None:
        client = _FakeClient(disconnect_error=RuntimeError("disconnect failed"))
        socket = _BleakSocket()
        socket._client = client

        await socket._safe_disconnect_async()

        self.assertEqual(client.disconnect_calls, 1)

    async def test_control_only_subscription_does_not_enable_reply_waits(self) -> None:
        profile = BleTransportProfile(control_notify_char_uuid=CONTROL_UUID)
        session = _new_session(profile)
        session.configure_endpoints(_notification_services())
        client = _FakeClient()
        socket = _BleakSocket(ble_profile=profile)
        socket._transport = session
        await session.start_notify_if_available(client, socket._handle_notification)

        self.assertFalse(session.notify_started)
        self.assertFalse(session.can_wait_for_notification())
        self.assertEqual(client.start_calls, [CONTROL_UUID])
        await session.stop_notify_if_started(client)
        self.assertEqual(client.stop_calls, [CONTROL_UUID])

    async def test_controller_stop_error_does_not_skip_unsubscribe_or_state_cleanup(
        self,
    ) -> None:
        profile = BleTransportProfile(
            notify_char_uuid=NOTIFY_UUID,
            control_notify_char_uuid=CONTROL_UUID,
        )
        session = _new_session(profile)
        session.configure_endpoints(_notification_services())
        client = _FakeClient(
            stop_notify_errors={
                NOTIFY_UUID: asyncio.CancelledError("unsubscribe cancelled")
            }
        )
        socket = _BleakSocket(ble_profile=profile)
        socket._transport = session
        await session.start_notify_if_available(client, socket._handle_notification)
        controller = _WriteController()
        error = RuntimeError("runtime stop failed")
        controller.stop_error = error
        await session.attach_runtime_controller(controller, mtu_size=23, timeout=0.1)
        session.handle_notification(b"keep me in ordinary history")
        waiter = asyncio.create_task(
            session.wait_for_notification(
                "never arrives", lambda _payload: False, timeout=10.0
            )
        )
        await asyncio.sleep(0)

        with self.assertRaises(RuntimeError) as raised:
            await session.stop_notify_if_started(client)
        self.assertIs(raised.exception, error)
        self.assertEqual(client.stop_calls, [NOTIFY_UUID, CONTROL_UUID])
        self.assertFalse(session.notify_started)
        self.assertEqual(session._started_notify_uuids, [])
        self.assertEqual(session._notification_history, [])
        self.assertEqual(session._notification_waiters, [])
        self.assertEqual(controller.stop_calls, 1)

        await session.stop_notify_if_started(client)
        self.assertEqual(controller.stop_calls, 1)
        self.assertEqual(client.stop_calls, [NOTIFY_UUID, CONTROL_UUID])
        self.assertIsInstance(
            (await asyncio.gather(waiter, return_exceptions=True))[0],
            asyncio.CancelledError,
        )


if __name__ == "__main__":
    unittest.main()
