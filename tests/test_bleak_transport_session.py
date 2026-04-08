from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from tests.helpers import build_capture_reporter
from timiniprint.protocol.families import get_protocol_behavior, split_prefixed_bulk_stream
from timiniprint.protocol.family import ProtocolFamily
from timiniprint.protocol.families.v5x import (
    V5X_CONNECT_INIT_PACKET,
    V5X_FINALIZE_PACKET,
    V5X_GET_SERIAL_PACKET,
    V5X_NOTIFY_GET_SERIAL_ACK,
    V5X_NOTIFY_IDLE_GET_SERIAL,
    V5X_NOTIFY_START_PRINT_OK,
    V5X_NOTIFY_START_READY,
    V5X_NOTIFY_TRIGGER_STATUS_POLL,
    V5X_STATUS_POLL_PACKET,
)
from timiniprint.protocol.families.v5c import V5C_CONNECT_INIT_PACKET, V5C_QUERY_STATUS_PACKET
from timiniprint.protocol.packet import crc8_value, make_packet
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

    def _make_session_with_sink(self, family: ProtocolFamily):
        reporter, sink = build_capture_reporter()
        resolver = _BleWriteEndpointResolver(reporter=reporter)
        transport = get_protocol_behavior(family).transport
        session = _BleakTransportSession(family, transport, resolver, reporter)
        client = _Client([])
        return session, client, sink

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

    def test_initialize_connection_sends_family_init_packets(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5X)
        cmd = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = cmd
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = cmd.uuid

        async def run() -> None:
            await session.initialize_connection(
                client,
                mtu_size=180,
                timeout=0.2,
                write_delay_ms=0,
            )

        asyncio.run(run())

        self.assertEqual(client.calls, [(cmd.uuid, V5X_CONNECT_INIT_PACKET, False)])

    def test_initialize_connection_waits_for_family_settle_delay(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5X)
        cmd = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = cmd
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = cmd.uuid
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        async def run() -> None:
            with patch(
                "timiniprint.transport.bluetooth.adapters.bleak_adapter_transport.asyncio.sleep",
                new=fake_sleep,
            ), patch.object(session, "_write_chunks", new=AsyncMock()) as write_chunks:
                await session.initialize_connection(
                    client,
                    mtu_size=180,
                    timeout=0.2,
                    write_delay_ms=0,
                )
                write_chunks.assert_awaited_once()

        asyncio.run(run())

        self.assertIn(0.2, sleep_calls)

    def test_initialize_connection_sends_v5c_init_packet(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5C)
        cmd = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = cmd
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = cmd.uuid

        async def run() -> None:
            await session.initialize_connection(
                client,
                mtu_size=180,
                timeout=0.2,
                write_delay_ms=0,
            )

        asyncio.run(run())

        self.assertEqual(client.calls, [(cmd.uuid, V5C_CONNECT_INIT_PACKET, False)])

    def test_initialize_connection_waits_for_v5c_settle_delay(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5C)
        cmd = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = cmd
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = cmd.uuid
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        async def run() -> None:
            with patch(
                "timiniprint.transport.bluetooth.adapters.bleak_adapter_transport.asyncio.sleep",
                new=fake_sleep,
            ), patch.object(session, "_write_chunks", new=AsyncMock()) as write_chunks:
                await session.initialize_connection(
                    client,
                    mtu_size=180,
                    timeout=0.2,
                    write_delay_ms=0,
                )
                write_chunks.assert_awaited_once()

        asyncio.run(run())

        self.assertIn(0.6, sleep_calls)

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
            V5X_GET_SERIAL_PACKET
            + bytes.fromhex("2221A20001005D94FF")
            + bytes.fromhex("2221A9000600010030010000EBFF")
            + (b"\xAA\x55" * 16)
            + V5X_FINALIZE_PACKET
        )

        async def run() -> None:
            async def notify() -> None:
                while len(client.calls) < 1:
                    await asyncio.sleep(0.001)
                session.handle_notification(V5X_NOTIFY_GET_SERIAL_ACK)
                session.handle_notification(V5X_NOTIFY_START_READY)
                while len(client.calls) < 3:
                    await asyncio.sleep(0.001)
                session.handle_notification(V5X_NOTIFY_START_PRINT_OK)

            task = asyncio.create_task(notify())
            await session.send(
                client,
                data,
                mtu_size=180,
                timeout=0.2,
                write_delay_ms=0,
                bulk_write_delay_ms=0,
            )
            await task

        asyncio.run(run())

        self.assertEqual(client.calls[0][0], cmd.uuid)
        self.assertEqual(client.calls[1][0], cmd.uuid)
        self.assertEqual(client.calls[2][0], cmd.uuid)
        self.assertEqual(client.calls[3][0], bulk.uuid)
        self.assertEqual(client.calls[4][0], cmd.uuid)

    def test_v5x_skips_redundant_density_command_on_same_connection(self) -> None:
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
            V5X_GET_SERIAL_PACKET
            + bytes.fromhex("2221A20001005D94FF")
            + bytes.fromhex("2221A9000600010030010000EBFF")
            + (b"\xAA\x55" * 8)
            + V5X_FINALIZE_PACKET
        )

        async def run_once() -> None:
            async def notify() -> None:
                while len(client.calls) < 1:
                    await asyncio.sleep(0.001)
                session.handle_notification(V5X_NOTIFY_GET_SERIAL_ACK)
                session.handle_notification(V5X_NOTIFY_START_READY)
                while True:
                    if client.calls and client.calls[-1][1].startswith(bytes.fromhex("2221A900")):
                        break
                    await asyncio.sleep(0.001)
                session.handle_notification(V5X_NOTIFY_START_PRINT_OK)

            task = asyncio.create_task(notify())
            await session.send(
                client,
                data,
                mtu_size=180,
                timeout=0.2,
                write_delay_ms=0,
                bulk_write_delay_ms=0,
            )
            await task

        asyncio.run(run_once())
        first_job_calls = list(client.calls)
        client.calls.clear()
        asyncio.run(run_once())

        self.assertEqual(
            [call[1] for call in first_job_calls[:3]],
            [
                V5X_GET_SERIAL_PACKET,
                bytes.fromhex("2221A20001005D94FF"),
                bytes.fromhex("2221A9000600010030010000EBFF"),
            ],
        )
        self.assertEqual(
            [call[1] for call in client.calls[:2]],
            [
                V5X_GET_SERIAL_PACKET,
                bytes.fromhex("2221A9000600010030010000EBFF"),
            ],
        )

    def test_v5x_notifications_update_session_state(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)

        session.handle_notification(
            make_packet(0xA7, bytes.fromhex("112233445566"), ProtocolFamily.V5X)
        )
        session.handle_notification(make_packet(0xB0, bytes([0x01]), ProtocolFamily.V5X))
        session.handle_notification(
            make_packet(0xB1, b"FW1.0.22", ProtocolFamily.V5X)
        )
        session.handle_notification(
            make_packet(0xA1, bytes([0x01, 0x00, 0x00, 0x63, 0x1E, 0x00, 0x00, 0x00]), ProtocolFamily.V5X)
        )
        session.handle_notification(make_packet(0xA9, bytes([0x00]), ProtocolFamily.V5X))

        self.assertEqual(session._v5x_state.device_serial, "112233445566")
        self.assertTrue(session._v5x_state.serial_valid)
        self.assertEqual(session._v5x_state.last_a7_payload, bytes.fromhex("112233445566"))
        self.assertEqual(session._v5x_state.print_head_type, "gaoya")
        self.assertEqual(session._v5x_state.firmware_version, "FW1.0.22")
        self.assertTrue(session._v5x_state.connect_info_received)
        self.assertEqual(session._v5x_state.last_a9_status, 0x00)
        self.assertEqual(session._v5x_state.task_state, 0x01)
        self.assertEqual(session._v5x_state.task_state_name, "printing")
        self.assertEqual(session._v5x_state.battery_level, 99)
        self.assertEqual(session._v5x_state.temperature_c, 30)
        self.assertEqual(session._v5x_state.error_group, 0x00)
        self.assertEqual(session._v5x_state.error_code, 0x00)
        self.assertEqual(session._v5x_state.compatibility.mode, "auth")

    def test_v5x_framed_a9_status_uses_payload_byte_not_crc(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)

        session.handle_notification(make_packet(0xA9, bytes([0x03]), ProtocolFamily.V5X))

        self.assertEqual(session._v5x_state.last_a9_status, 0x03)

    def test_v5x_invalid_serial_is_marked_invalid(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)

        session.handle_notification(
            make_packet(0xA7, bytes.fromhex("FFFFFFFFFFFF"), ProtocolFamily.V5X)
        )

        self.assertEqual(session._v5x_state.device_serial, "ffffffffffff")
        self.assertFalse(session._v5x_state.serial_valid)
        self.assertEqual(session._v5x_state.compatibility.mode, "get_sn")

    def test_v5x_builds_compat_request_for_auth_mode(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)

        session.handle_notification(
            make_packet(0xA7, bytes.fromhex("112233445566"), ProtocolFamily.V5X)
        )

        request = session.build_v5x_compat_request(
            ble_name="JK01",
            ble_address="48:0F:57:49:1D:3A",
        )

        self.assertEqual(
            request,
            {
                "mode": "auth",
                "ble_name": "JK01",
                "ble_address": "48:0F:57:49:1D:3A",
                "ble_sn": "112233445566",
                "ble_model": "V5X",
            },
        )

    def test_v5x_builds_compat_request_for_get_sn_mode(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)

        session.handle_notification(
            make_packet(0xA7, bytes.fromhex("FFFFFFFFFFFF"), ProtocolFamily.V5X)
        )

        request = session.build_v5x_compat_request(
            ble_name="JK01",
            ble_address="48:0F:57:49:1D:3A",
            ble_model="JK01",
        )

        self.assertEqual(
            request,
            {
                "mode": "get_sn",
                "ble_name": "JK01",
                "ble_address": "48:0F:57:49:1D:3A",
                "ble_sn": "ffffffffffff",
                "ble_model": "JK01",
            },
        )

    def test_v5x_compat_result_is_non_blocking_and_warns_on_rejection(self) -> None:
        session, _, sink = self._make_session_with_sink(ProtocolFamily.V5X)

        session.handle_notification(
            make_packet(0xA7, bytes.fromhex("112233445566"), ProtocolFamily.V5X)
        )
        session.apply_v5x_compat_result(mode="auth", result_code=-2)

        self.assertTrue(session._v5x_state.compatibility.checked)
        self.assertFalse(session._v5x_state.compatibility.confirmed)
        self.assertEqual(session._v5x_state.compatibility.last_result_code, -2)
        warnings = [msg for msg in sink.messages if msg.level == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].short, "V5X compatibility check failed")

    def test_v5x_compat_result_keeps_backend_write_cmd(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)

        session.handle_notification(
            make_packet(0xA7, bytes.fromhex("FFFFFFFFFFFF"), ProtocolFamily.V5X)
        )
        session.apply_v5x_compat_result(
            mode="get_sn",
            result_code=1,
            write_cmd=bytes.fromhex("2221A70000000000"),
        )

        self.assertTrue(session._v5x_state.compatibility.checked)
        self.assertTrue(session._v5x_state.compatibility.confirmed)
        self.assertEqual(session._v5x_state.compatibility.last_result_code, 1)
        self.assertEqual(
            session._v5x_state.compatibility.backend_write_cmd,
            bytes.fromhex("2221A70000000000"),
        )

    def test_v5x_status_poll_ack_is_tracked(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)

        session.handle_notification(make_packet(0xA3, bytes([0x00]), ProtocolFamily.V5X))

        self.assertTrue(session._v5x_state.status_poll_ack_seen)

    def test_v5x_ab_status_is_tracked(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)

        session.handle_notification(make_packet(0xAB, bytes([0x11]), ProtocolFamily.V5X))

        self.assertEqual(session._v5x_state.last_ab_status, 0x11)

    def test_v5x_error_status_warns_once_per_signature(self) -> None:
        session, _, sink = self._make_session_with_sink(ProtocolFamily.V5X)

        error_packet = make_packet(
            0xA1,
            bytes([0x01, 0x00, 0x00, 0x50, 0x1E, 0x00, 0x02, 0x09]),
            ProtocolFamily.V5X,
        )
        session.handle_notification(error_packet)
        session.handle_notification(error_packet)

        warnings = [msg for msg in sink.messages if msg.level == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].short, "V5X printer reported an error status")
        self.assertIn("Task=printing", warnings[0].detail)
        self.assertIn("error_group=0x02", warnings[0].detail)
        self.assertIn("error_code=0x09", warnings[0].detail)

    def test_v5x_b3_warns_without_blocking_session(self) -> None:
        session, _, sink = self._make_session_with_sink(ProtocolFamily.V5X)

        session.handle_notification(make_packet(0xB3, bytes([0x01]), ProtocolFamily.V5X))
        session.handle_notification(make_packet(0xB3, bytes([0x01]), ProtocolFamily.V5X))

        self.assertTrue(session._v5x_state.mxw_sign_requested)
        warnings = [msg for msg in sink.messages if msg.level == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].short, "V5X printer requested an additional signing step")

    def test_v5x_density_is_adjusted_using_session_state_and_coverage(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)
        session.handle_notification(make_packet(0xB0, bytes([0x01]), ProtocolFamily.V5X))
        session.handle_notification(
            make_packet(
                0xA1,
                bytes([0x01, 0x00, 0x00, 0x63, 0x41, 0x00, 0x00, 0x00]),
                ProtocolFamily.V5X,
            )
        )

        split = split_prefixed_bulk_stream(
            bytes.fromhex("2221A20001005D94FF")
            + bytes.fromhex("2221A9000600010030010000EBFF")
            + (b"\xAA\x55" * 16)
            + V5X_FINALIZE_PACKET,
            ProtocolFamily.V5X,
            get_protocol_behavior(ProtocolFamily.V5X).transport.split_tail_packets,
        )
        context = session._build_v5x_job_context(split)
        self.assertIsNotNone(context)

        adjusted = session._adjust_v5x_density_payload(bytes([0x5D]), context)

        self.assertEqual(adjusted, bytes([0x05]))

    def test_v5x_start_delay_prefers_gaoya_high_coverage_rule(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)
        session._v5x_state.print_head_type = "gaoya"
        split = split_prefixed_bulk_stream(
            bytes.fromhex("2221A9000600010030010000EBFF")
            + (b"\xAA\x55" * 16)
            + V5X_FINALIZE_PACKET,
            ProtocolFamily.V5X,
            get_protocol_behavior(ProtocolFamily.V5X).transport.split_tail_packets,
        )
        context = session._build_v5x_job_context(split)
        self.assertIsNotNone(context)

        delay_ms = session._compute_v5x_start_delay_ms(context, density_updated=True)

        self.assertEqual(delay_ms, 200)

    def test_v5x_start_delay_uses_short_density_settle_for_lower_coverage(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)
        session._v5x_state.print_head_type = "diya"
        split = split_prefixed_bulk_stream(
            bytes.fromhex("2221A9000600010030010000EBFF")
            + (b"\x80" * 8)
            + V5X_FINALIZE_PACKET,
            ProtocolFamily.V5X,
            get_protocol_behavior(ProtocolFamily.V5X).transport.split_tail_packets,
        )
        context = session._build_v5x_job_context(split)
        self.assertIsNotNone(context)

        delay_ms = session._compute_v5x_start_delay_ms(context, density_updated=True)

        self.assertEqual(delay_ms, 60)

    def test_v5x_gray_job_context_recognizes_len2_start_packet(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5X)
        height_bytes = bytes([0x01, 0x00])
        split = split_prefixed_bulk_stream(
            (bytes.fromhex("2221A9000200") + height_bytes + bytes([crc8_value(height_bytes), 0xFF]))
            + bytes.fromhex("FEDCBA98")
            + V5X_FINALIZE_PACKET,
            ProtocolFamily.V5X,
            get_protocol_behavior(ProtocolFamily.V5X).transport.split_tail_packets,
        )

        context = session._build_v5x_job_context(split)

        self.assertIsNotNone(context)
        self.assertTrue(context.is_gray)
        self.assertEqual(context.coverage_ratio, 0.0)

    def test_v5x_b2_notification_schedules_status_poll(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5X)
        cmd = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = cmd
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = cmd.uuid
        session._client = client

        async def run() -> None:
            session.handle_notification(V5X_NOTIFY_TRIGGER_STATUS_POLL)
            await asyncio.sleep(0.75)

        asyncio.run(run())

        self.assertEqual(client.calls, [(cmd.uuid, V5X_STATUS_POLL_PACKET, False)])

    def test_v5x_a6_notification_requests_serial_when_idle(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5X)
        cmd = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = cmd
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = cmd.uuid
        session._client = client

        async def run() -> None:
            session.handle_notification(V5X_NOTIFY_IDLE_GET_SERIAL)
            await asyncio.sleep(0.05)

        asyncio.run(run())

        self.assertEqual(client.calls, [(cmd.uuid, V5X_GET_SERIAL_PACKET, False)])

    def test_v5x_timeout_clears_pending_handshake_state(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5X)
        cmd = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        bulk = _Char("0000ae03-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = cmd
        session.bindings.bulk_write_char = bulk
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = cmd.uuid
        session.bindings.bulk_write_char_uuid = bulk.uuid

        data = V5X_GET_SERIAL_PACKET + (b"\xAA\x55" * 8) + V5X_FINALIZE_PACKET

        async def run() -> None:
            with self.assertRaises(TimeoutError):
                await session.send(
                    client,
                    data,
                    mtu_size=180,
                    timeout=0.01,
                    write_delay_ms=0,
                    bulk_write_delay_ms=0,
                )

        asyncio.run(run())

        self.assertEqual(session._command_ack_events, {})
        self.assertIsNone(session._start_ready_event)

    def test_v5x_nonzero_a9_status_fails_immediately(self) -> None:
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
            V5X_GET_SERIAL_PACKET
            + bytes.fromhex("2221A9000600010030010000EBFF")
            + (b"\xAA\x55" * 8)
            + V5X_FINALIZE_PACKET
        )

        async def run() -> None:
            async def notify() -> None:
                while len(client.calls) < 1:
                    await asyncio.sleep(0.001)
                session.handle_notification(V5X_NOTIFY_GET_SERIAL_ACK)
                session.handle_notification(V5X_NOTIFY_START_READY)
                while len(client.calls) < 2:
                    await asyncio.sleep(0.001)
                session.handle_notification(make_packet(0xA9, bytes([0x03]), ProtocolFamily.V5X))

            task = asyncio.create_task(notify())
            with self.assertRaisesRegex(RuntimeError, "status=0x03"):
                await session.send(
                    client,
                    data,
                    mtu_size=180,
                    timeout=0.2,
                    write_delay_ms=0,
                    bulk_write_delay_ms=0,
                )
            await task

        asyncio.run(run())

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

    def test_v5c_standard_send_arms_query_status_when_query_packet_is_present(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5C)
        write_char = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = write_char
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = write_char.uuid

        async def run() -> None:
            await session.send(
                client,
                b"AB" + V5C_QUERY_STATUS_PACKET,
                mtu_size=180,
                timeout=0.2,
                write_delay_ms=0,
                bulk_write_delay_ms=0,
            )

        asyncio.run(run())

        self.assertTrue(session._v5c_state.query_status_in_flight)

    def test_v5c_notifications_update_session_state(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5C)

        session.handle_notification(make_packet(0xA1, bytes([0x80]), ProtocolFamily.V5C))
        session.handle_notification(make_packet(0xAA, (800).to_bytes(2, "little"), ProtocolFamily.V5C))
        session.handle_notification(
            make_packet(0xA9, bytes.fromhex("1122334455667788"), ProtocolFamily.V5C)
        )

        self.assertEqual(session._v5c_state.status_code, 0x80)
        self.assertEqual(session._v5c_state.status_name, "printing")
        self.assertFalse(session._v5c_state.is_charging)
        self.assertFalse(session._v5c_state.print_complete_seen)
        self.assertEqual(session._v5c_state.max_print_height, 800)
        self.assertEqual(session._v5c_state.device_serial, "1122334455667788")
        self.assertTrue(session._v5c_state.serial_valid)
        self.assertEqual(
            session._v5c_state.last_auth_payload,
            bytes.fromhex("1122334455667788"),
        )
        self.assertEqual(session._v5c_state.compatibility.mode, "auth")
        self.assertEqual(session._v5c_state.compatibility.last_trigger_opcode, 0xA9)

    def test_v5c_invalid_serial_switches_to_get_sn_mode(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5C)

        session.handle_notification(
            make_packet(0xA9, bytes.fromhex("0000000000000000"), ProtocolFamily.V5C)
        )

        self.assertEqual(session._v5c_state.device_serial, "0000000000000000")
        self.assertFalse(session._v5c_state.serial_valid)
        self.assertEqual(session._v5c_state.compatibility.mode, "get_sn")
        self.assertEqual(session._v5c_state.compatibility.last_trigger_opcode, 0xA9)

    def test_v5c_builds_compat_request(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5C)

        self.assertIsNone(
            session.build_v5c_compat_request(
                ble_name="YTB01",
                ble_address="48:0F:57:49:1D:3A",
            )
        )

        session.handle_notification(
            make_packet(0xA9, bytes.fromhex("1122334455667788"), ProtocolFamily.V5C)
        )

        request = session.build_v5c_compat_request(
            ble_name="YTB01",
            ble_address="48:0F:57:49:1D:3A",
        )

        self.assertEqual(
            request,
            {
                "mode": "auth",
                "ble_name": "YTB01",
                "ble_address": "48:0F:57:49:1D:3A",
                "ble_sn": "1122334455667788",
                "ble_model": "V5C",
            },
        )
        self.assertTrue(session._v5c_state.compatibility.request_pending)

    def test_v5c_a8_builds_to_auth_request_from_full_packet(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5C)

        packet = make_packet(0xA8, bytes.fromhex("1122334455667788"), ProtocolFamily.V5C)
        session.handle_notification(packet)

        request = session.build_v5c_compat_request(
            ble_name="YTB01",
            ble_address="48:0F:57:49:1D:3A",
        )

        self.assertEqual(
            request,
            {
                "mode": "to_auth",
                "ble_name": "YTB01",
                "ble_address": "48:0F:57:49:1D:3A",
                "ble_sn": packet.hex(),
                "ble_model": "V5C",
            },
        )
        self.assertEqual(session._v5c_state.compatibility.last_trigger_opcode, 0xA8)
        self.assertIsNone(session._v5c_state.serial_valid)
        self.assertTrue(session._v5c_state.compatibility.request_pending)

    def test_v5c_compat_result_is_non_blocking_and_warns_on_rejection(self) -> None:
        session, _, sink = self._make_session_with_sink(ProtocolFamily.V5C)

        session.handle_notification(
            make_packet(0xA9, bytes.fromhex("1122334455667788"), ProtocolFamily.V5C)
        )
        session.apply_v5c_compat_result(mode="auth", result_code=-2)

        self.assertTrue(session._v5c_state.compatibility.checked)
        self.assertFalse(session._v5c_state.compatibility.confirmed)
        self.assertEqual(session._v5c_state.compatibility.last_result_code, -2)
        self.assertFalse(session._v5c_state.compatibility.request_pending)
        self.assertIsNone(
            session.build_v5c_compat_request(
                ble_name="YTB01",
                ble_address="48:0F:57:49:1D:3A",
            )
        )
        warnings = [msg for msg in sink.messages if msg.level == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].short, "V5C compatibility check failed")

    def test_v5c_error_status_warns_once_per_status_code(self) -> None:
        session, _, sink = self._make_session_with_sink(ProtocolFamily.V5C)

        error_packet = make_packet(0xA1, bytes([0x04]), ProtocolFamily.V5C)
        session.handle_notification(error_packet)
        session.handle_notification(error_packet)

        warnings = [msg for msg in sink.messages if msg.level == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].short, "V5C printer reported an overheat state")
        self.assertIn("status=0x04", warnings[0].detail)
        self.assertEqual(session._v5c_state.status_name, "overheat")

    def test_v5c_attention_status_warns_and_uses_grouped_name(self) -> None:
        session, _, sink = self._make_session_with_sink(ProtocolFamily.V5C)

        packet = make_packet(0xA1, bytes([0x01]), ProtocolFamily.V5C)
        session.handle_notification(packet)
        session.handle_notification(packet)

        warnings = [msg for msg in sink.messages if msg.level == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].short, "V5C printer reported an attention state")
        self.assertIn("status=0x01", warnings[0].detail)
        self.assertEqual(session._v5c_state.status_name, "attention")

    def test_v5c_normal_status_clears_previous_error_state(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5C)

        session.handle_notification(make_packet(0xA1, bytes([0x04]), ProtocolFamily.V5C))
        session.handle_notification(make_packet(0xA1, bytes([0x00]), ProtocolFamily.V5C))

        self.assertIsNone(session._v5c_state.last_error_status)
        self.assertEqual(session._v5c_state.status_name, "normal")

    def test_v5c_low_power_status_warns_once_per_status_code(self) -> None:
        session, _, sink = self._make_session_with_sink(ProtocolFamily.V5C)

        packet = make_packet(0xA1, bytes([0x08]), ProtocolFamily.V5C)
        session.handle_notification(packet)
        session.handle_notification(packet)

        warnings = [msg for msg in sink.messages if msg.level == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].short, "V5C printer reported a low-power state")
        self.assertIn("status=0x08", warnings[0].detail)
        self.assertEqual(session._v5c_state.status_name, "low_power")

    def test_v5c_charging_status_sets_charging_flag(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5C)

        session.handle_notification(make_packet(0xA1, bytes([0x10]), ProtocolFamily.V5C))

        self.assertEqual(session._v5c_state.status_name, "charging")
        self.assertTrue(session._v5c_state.is_charging)
        self.assertIsNone(session._v5c_state.last_error_status)

    def test_v5c_return_to_normal_marks_print_complete_after_printing(self) -> None:
        session, _ = self._make_session(ProtocolFamily.V5C)

        session.handle_notification(make_packet(0xA1, bytes([0x80]), ProtocolFamily.V5C))
        session.handle_notification(make_packet(0xA1, bytes([0x00]), ProtocolFamily.V5C))

        self.assertEqual(session._v5c_state.status_name, "normal")
        self.assertTrue(session._v5c_state.print_complete_seen)
        self.assertFalse(session._v5c_state.is_charging)

    def test_v5c_query_status_ack_does_not_mark_print_complete(self) -> None:
        session, client = self._make_session(ProtocolFamily.V5C)
        write_char = _Char("0000ae01-0000-1000-8000-00805f9b34fb", ["write-without-response"])
        session.bindings.write_char = write_char
        session.bindings.write_selection_strategy = "preferred_uuid"
        session.bindings.write_response_preference = False
        session.bindings.write_char_uuid = write_char.uuid
        session._v5c_state.status_code = 0x80
        session._v5c_state.status_name = "printing"

        async def run() -> None:
            await session.send(
                client,
                V5C_QUERY_STATUS_PACKET,
                mtu_size=180,
                timeout=0.2,
                write_delay_ms=0,
                bulk_write_delay_ms=0,
            )

        asyncio.run(run())
        session.handle_notification(make_packet(0xA1, bytes([0x00]), ProtocolFamily.V5C))

        self.assertFalse(session._v5c_state.query_status_in_flight)
        self.assertFalse(session._v5c_state.print_complete_seen)


if __name__ == "__main__":
    unittest.main()
