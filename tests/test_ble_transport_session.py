from __future__ import annotations

import asyncio
import unittest

from catlabel import reporting
from catlabel.devices import BleTransportProfile
from catlabel.printing.runtime.tiny import TinyRuntimeController
from catlabel.printing.runtime.yk_astra_p1 import AstraP1RuntimeController
from catlabel.protocol.families.yk_common import pack_yk_frame
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


class _StaleMtuCharacteristic(_Characteristic):
    max_write_without_response_size = 20


class _SmallerMtuCharacteristic(_Characteristic):
    max_write_without_response_size = 100


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


class _RecordingClient:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    async def write_gatt_char(
        self, _char: object, data: bytes, *, response: bool
    ) -> None:
        _ = response
        self.writes.append(bytes(data))


class BleTransportSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_s001_completion_uses_live_fragment_decoder_before_waiters(
        self,
    ) -> None:
        session = _BleakTransportSession(
            transport_profile=BleTransportProfile(prefer_generic_notify=True),
            write_resolver=_BleWriteEndpointResolver(reporter=reporting.DUMMY_REPORTER),
            reporter=reporting.DUMMY_REPORTER,
        )
        session.notify_started = True
        controller = AstraP1RuntimeController()
        await session.attach_runtime_controller(controller, mtu_size=20, timeout=0.1)
        controller.on_standard_send_started(session)
        task = asyncio.create_task(controller.wait_for_completion(session, timeout=0.1))
        printing = pack_yk_frame(0x81, bytes.fromhex("0000080009000264"))
        idle = pack_yk_frame(0x81, bytes.fromhex("0000000009000264"))
        try:
            await asyncio.sleep(0)
            session.handle_notification(printing[:7])
            session.handle_notification(printing[7:] + idle[:5])
            self.assertFalse(task.done())
            session.handle_notification(idle[5:])
            await asyncio.wait_for(task, timeout=1.0)
            self.assertEqual(controller.debug_snapshot()["completion_count"], 1)
            self.assertFalse(controller.debug_snapshot()["finished"])
            controller.on_standard_send_started(session)
            self.assertFalse(controller._completion_reply(printing + idle))
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await controller.stop(session)

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

    def test_verified_payload_ignores_stale_default_and_applies_reserve(self) -> None:
        self.assertEqual(
            _BleakTransportSession._effective_mtu_payload(
                _StaleMtuCharacteristic(),
                245,
                response=False,
                reserve=5,
                verified_payload=245,
            ),
            240,
        )

    def test_unverified_payload_keeps_reported_characteristic_limit(self) -> None:
        self.assertEqual(
            _BleakTransportSession._effective_mtu_payload(
                _StaleMtuCharacteristic(),
                245,
                response=False,
                reserve=5,
            ),
            15,
        )

    def test_verified_payload_honors_a_smaller_characteristic_limit(self) -> None:
        self.assertEqual(
            _BleakTransportSession._effective_mtu_payload(
                _SmallerMtuCharacteristic(),
                245,
                response=False,
                reserve=5,
                verified_payload=245,
            ),
            95,
        )

    def test_unverified_public_limit_can_exceed_default_fallback(self) -> None:
        self.assertEqual(
            _BleakTransportSession._effective_mtu_payload(
                _SmallerMtuCharacteristic(),
                20,
                response=False,
                reserve=5,
            ),
            95,
        )

    def test_response_write_keeps_fallback_even_with_verified_payload(self) -> None:
        self.assertEqual(
            _BleakTransportSession._effective_mtu_payload(
                _StaleMtuCharacteristic(),
                245,
                response=True,
                reserve=5,
                verified_payload=245,
            ),
            245,
        )

    async def test_actual_verified_chunks_stay_within_mtu_and_profile_cap(self) -> None:
        profile = BleTransportProfile(
            standard_chunk_cap=448,
            standard_write_delay_ms=0,
            write_without_response_payload_reserve=5,
        )
        session = _BleakTransportSession(
            transport_profile=profile,
            write_resolver=_BleWriteEndpointResolver(reporter=reporting.DUMMY_REPORTER),
            reporter=reporting.DUMMY_REPORTER,
        )
        session.bindings.write_char = _StaleMtuCharacteristic()
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        client = _RecordingClient()
        await session.initialize_connection(
            client,
            mtu_size=245,
            timeout=0.1,
            verified_payload=245,
        )

        await session.send_standard_payload(b"x" * 721)

        self.assertEqual([len(chunk) for chunk in client.writes], [240, 240, 240, 1])
        self.assertTrue(all(len(chunk) <= 245 for chunk in client.writes))
        self.assertTrue(
            all(len(chunk) <= profile.standard_chunk_cap for chunk in client.writes)
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
