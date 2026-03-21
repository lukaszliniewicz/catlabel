from __future__ import annotations

import asyncio
import unittest

from tests.helpers import build_capture_reporter
from timiniprint.protocol.families import get_protocol_behavior
from timiniprint.protocol.family import ProtocolFamily
from timiniprint.transport.bluetooth.adapters.bleak_adapter_endpoint_resolver import (
    _BleWriteEndpointResolver,
)
from timiniprint.transport.bluetooth.adapters.bleak_adapter_transport import (
    _BleakTransportSession,
)


class _Char:
    def __init__(self, uuid: str, properties):
        self.uuid = uuid
        self.properties = properties


class _Svc:
    def __init__(self, uuid: str, chars):
        self.uuid = uuid
        self.characteristics = chars


class _Client:
    def __init__(self, services):
        self.services = services
        self.calls = []
        self.notify_callbacks = {}
        self.stop_notify_calls = []

    async def write_gatt_char(self, char, chunk, response=True):
        self.calls.append((char.uuid, bytes(chunk), response))

    async def start_notify(self, char_uuid, callback):
        self.notify_callbacks[char_uuid] = callback

    async def stop_notify(self, char_uuid):
        self.stop_notify_calls.append(char_uuid)
        self.notify_callbacks.pop(char_uuid, None)


class BleakTransportSessionTests(unittest.TestCase):
    def _make_session(self, family: ProtocolFamily) -> tuple[_BleakTransportSession, _Client]:
        reporter, _ = build_capture_reporter()
        resolver = _BleWriteEndpointResolver(reporter=reporter)
        transport = get_protocol_behavior(family).transport
        session = _BleakTransportSession(family, transport, resolver, reporter)
        client = _Client([])
        return session, client

    def test_configure_endpoints_prefers_profile_service_uuid(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)
        preferred = _Char("0000ae03-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        fallback = _Char("0000ae03-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        notify = _Char("0000ae02-0000-1000-8000-00805f9b34fb", ["notify"])
        services = [
            _Svc("11111111-0000-1000-8000-00805f9b34fb", [fallback]),
            _Svc("0000ae30-0000-1000-8000-00805f9b34fb", [preferred, notify]),
        ]

        session.configure_endpoints(services)

        self.assertIs(session.bindings.bulk_write_char, preferred)
        self.assertIs(session.bindings.notify_char, notify)

    def test_start_and_stop_notify_use_bound_notify_characteristic(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5X)
        notify = _Char("0000ae02-0000-1000-8000-00805f9b34fb", ["notify"])
        session.bindings.notify_char = notify
        session.bindings.notify_char_uuid = notify.uuid

        async def run() -> None:
            await session.start_notify_if_available(client, lambda *_args: None)
            await session.stop_notify_if_started(client)

        asyncio.run(run())

        self.assertEqual(list(client.notify_callbacks.keys()), [])
        self.assertEqual(client.stop_notify_calls, [notify.uuid])
        self.assertFalse(session.notify_started)

    def test_send_split_routes_commands_bulk_and_trailing_packets(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5X)
        cmd = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        bulk = _Char("0000ae03-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = cmd
        session.bindings.bulk_write_char = bulk
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = cmd.uuid
        session.bindings.bulk_write_char_uuid = bulk.uuid

        data = (
            bytes.fromhex("2221A70000000000")
            + bytes.fromhex("2221A9000200010000FF")
            + (b"\xAA\x55" * 16)
            + bytes.fromhex("2221AD000100000000")
        )

        asyncio.run(
            session.send(
                client,
                data,
                mtu_size=180,
                timeout=0.2,
                write_delay_ms=0,
                bulk_write_delay_ms=0,
            )
        )

        self.assertEqual(client.calls[0][0], cmd.uuid)
        self.assertEqual(client.calls[1][0], cmd.uuid)
        self.assertEqual(client.calls[2][0], bulk.uuid)
        self.assertEqual(client.calls[3][0], cmd.uuid)

    def test_flow_controlled_standard_send_waits_for_resume(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5C)
        write_char = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = write_char
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = write_char.uuid
        session.flow_can_write = False

        async def run() -> None:
            async def resume() -> None:
                await asyncio.sleep(0.02)
                session.handle_notification(bytes.fromhex("5688A70101000000FF"))

            task = asyncio.create_task(resume())
            await session.send(
                client,
                b"ABC",
                mtu_size=180,
                timeout=0.2,
                write_delay_ms=0,
                bulk_write_delay_ms=0,
            )
            await task

        asyncio.run(run())

        self.assertEqual(client.calls, [(write_char.uuid, b"ABC", False)])
        self.assertTrue(session.flow_can_write)


if __name__ == "__main__":
    unittest.main()
