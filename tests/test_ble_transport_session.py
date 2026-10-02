from __future__ import annotations

import asyncio
import unittest

from catlabel import reporting
from catlabel.devices import BleTransportProfile
from catlabel.printing.runtime.tiny import TinyRuntimeController
from catlabel.transport.bluetooth.adapters.bleak_adapter_endpoint_resolver import (
    _BleWriteEndpointResolver,
)
from catlabel.transport.bluetooth.adapters.bleak_adapter_transport import (
    _BleakTransportSession,
)


class _Characteristic:
    uuid = "0000ffe1-0000-1000-8000-00805f9b34fb"
    properties = ["write-without-response"]
    max_write_without_response_size = 23


class _NotifyCharacteristic:
    uuid = "0000ffe2-0000-1000-8000-00805f9b34fb"
    properties = ["notify"]


class _Service:
    uuid = "0000ffe0-0000-1000-8000-00805f9b34fb"

    def __init__(self, *characteristics) -> None:
        self.characteristics = list(characteristics)


class _ImmediateReplyClient:
    def __init__(self, session: _BleakTransportSession, reply: bytes) -> None:
        self.session = session
        self.reply = reply
        self.writes: list[bytes] = []

    async def write_gatt_char(self, char, data, *, response: bool) -> None:
        self.writes.append(bytes(data))
        self.session.handle_notification(self.reply)


class BleTransportSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_tiny_notifications_pause_actual_ble_chunk_writes(self) -> None:
        session = _BleakTransportSession(
            transport_profile=BleTransportProfile(
                flow_controlled_standard_write=True,
                flow_resume_timeout_s=1.0,
                standard_chunk_cap=5,
                standard_write_delay_ms=0,
            ),
            write_resolver=_BleWriteEndpointResolver(reporter=reporting.DUMMY_REPORTER),
            reporter=reporting.DUMMY_REPORTER,
        )
        session.bindings.write_char = _Characteristic()
        session.bindings.write_char_uuid = _Characteristic.uuid
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        resume = bytes.fromhex("5178AE0101000000FF")
        client = _ImmediateReplyClient(session, resume)
        await session.initialize_connection(client, mtu_size=5, timeout=0.1)
        await session.attach_runtime_controller(
            TinyRuntimeController(), mtu_size=5, timeout=0.1
        )
        pause = bytes.fromhex("5178AE0101001070FF")
        session.handle_notification(pause[:4])
        session.handle_notification(pause[4:])
        task = asyncio.create_task(session.send_standard_payload(b"abcdefghij"))
        try:
            await asyncio.sleep(0)
            self.assertEqual(client.writes, [])
            self.assertFalse(session.flow_can_write)
            session.handle_notification(resume)
            self.assertTrue(await task)
            self.assertEqual(client.writes, [b"abcde", b"fghij"])
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await session.stop_notify_if_started(client)

    async def test_flow_resume_budget_is_independent_of_command_timeout(self) -> None:
        session = _BleakTransportSession(
            transport_profile=BleTransportProfile(flow_resume_timeout_s=1.0),
            write_resolver=_BleWriteEndpointResolver(reporter=reporting.DUMMY_REPORTER),
            reporter=reporting.DUMMY_REPORTER,
        )
        session.set_flow_paused(True)

        async def resume() -> None:
            await asyncio.sleep(0.01)
            session.set_flow_paused(False)

        task = asyncio.create_task(resume())
        try:
            await session._wait_for_flow(timeout=0.0)
            self.assertTrue(session.flow_can_write)
        finally:
            await task

    async def test_flow_pause_still_has_a_finite_failure_budget(self) -> None:
        session = _BleakTransportSession(
            transport_profile=BleTransportProfile(flow_resume_timeout_s=0.0),
            write_resolver=_BleWriteEndpointResolver(reporter=reporting.DUMMY_REPORTER),
            reporter=reporting.DUMMY_REPORTER,
        )
        session.set_flow_paused(True)
        with self.assertRaisesRegex(TimeoutError, "flow-control resume"):
            await session._wait_for_flow(timeout=100.0)

    def test_generic_notify_profile_binds_notify_characteristic(self) -> None:
        session = _BleakTransportSession(
            transport_profile=BleTransportProfile(prefer_generic_notify=True),
            write_resolver=_BleWriteEndpointResolver(reporter=reporting.DUMMY_REPORTER),
            reporter=reporting.DUMMY_REPORTER,
        )
        notify_char = _NotifyCharacteristic()

        session.configure_endpoints([_Service(_Characteristic(), notify_char)])

        self.assertIs(session.bindings.notify_char, notify_char)
        self.assertEqual(session.bindings.notify_char_uuid, notify_char.uuid)

    def test_write_without_response_reserve_reduces_reported_payload(self) -> None:
        self.assertEqual(
            _BleakTransportSession._effective_mtu_payload(
                _Characteristic(),
                180,
                response=False,
                reserve=5,
            ),
            18,
        )

    async def test_atomic_query_registers_waiter_before_write(self) -> None:
        session = _BleakTransportSession(
            transport_profile=BleTransportProfile(),
            write_resolver=_BleWriteEndpointResolver(reporter=reporting.DUMMY_REPORTER),
            reporter=reporting.DUMMY_REPORTER,
        )
        session.bindings.write_char = _Characteristic()
        session.bindings.write_char_uuid = _Characteristic.uuid
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.notify_started = True
        client = _ImmediateReplyClient(session, b"reply")
        await session.initialize_connection(client, mtu_size=180, timeout=0.1)

        reply = await session.send_control_packet_wait_notification(
            b"query",
            label="immediate reply",
            match=lambda payload: payload == b"reply",
            timeout=0.1,
        )

        self.assertEqual(reply, b"reply")
        self.assertEqual(client.writes, [b"query"])


if __name__ == "__main__":
    unittest.main()
