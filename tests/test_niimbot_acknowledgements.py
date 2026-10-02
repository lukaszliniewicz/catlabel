from __future__ import annotations

import asyncio
import unittest
from collections import Counter
from types import SimpleNamespace
from typing import cast
from unittest.mock import ANY, AsyncMock, patch

from bleak import BleakClient
from bleak.exc import BleakError
from PIL import Image

from catlabel.vendors.niimbot.client import (
    InfoEnum,
    NiimbotClient,
    NiimbotPacket,
    NiimbotPrintError,
    RequestCodeEnum,
)

_RESPONSE_CODES = {
    RequestCodeEnum.SET_LABEL_TYPE: 0x33,
    RequestCodeEnum.SET_LABEL_DENSITY: 0x31,
    RequestCodeEnum.START_PRINT: 0x02,
    RequestCodeEnum.END_PRINT: 0xF4,
    RequestCodeEnum.START_PAGE_PRINT: 0x04,
    RequestCodeEnum.END_PAGE_PRINT: 0xE4,
    RequestCodeEnum.ALLOW_PRINT_CLEAR: 0x30,
    RequestCodeEnum.SET_DIMENSION: 0x14,
    RequestCodeEnum.SET_QUANTITY: 0x16,
    RequestCodeEnum.GET_PRINT_STATUS: 0xB3,
}
_INFO_RESPONSE_CODES = {
    InfoEnum.DENSITY: 0x41,
    InfoEnum.PRINTSPEED: 0x42,
    InfoEnum.LABELTYPE: 0x43,
    InfoEnum.SOFTVERSION: 0x49,
    InfoEnum.BATTERY: 0x4A,
    InfoEnum.DEVICESERIAL: 0x4B,
    InfoEnum.HARDVERSION: 0x4C,
}

_REQUIRED_SETUP = (
    (RequestCodeEnum.SET_LABEL_DENSITY, "set_label_density"),
    (RequestCodeEnum.SET_LABEL_TYPE, "set_label_type"),
    (RequestCodeEnum.START_PRINT, "start_print"),
    (RequestCodeEnum.START_PAGE_PRINT, "start_page_print"),
    (RequestCodeEnum.SET_DIMENSION, "set_dimension"),
    (RequestCodeEnum.SET_QUANTITY, "set_quantity"),
)


def _frame(type_: int, data: bytes = b"\x01") -> bytes:
    return NiimbotPacket(type_, data).to_bytes()


def _client() -> NiimbotClient:
    return NiimbotClient(
        SimpleNamespace(address="AA:BB:CC:DD:EE:FF"),
        {"width_px": 8, "default_energy": 3, "max_density": 5},
        SimpleNamespace(energy=3),
        None,
    )


def _positive_response(request_code: int, data: bytes) -> NiimbotPacket:
    if request_code == RequestCodeEnum.GET_INFO:
        response_code = _INFO_RESPONSE_CODES[InfoEnum(data[0])]
    elif request_code == RequestCodeEnum.HEARTBEAT:
        response_code = 0xDE
    else:
        response_code = _RESPONSE_CODES[RequestCodeEnum(request_code)]
    return NiimbotPacket(response_code, b"\x01")


async def _no_sleep(_delay: float) -> None:
    return None


class NiimbotNotificationRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_and_coalesced_frames_require_exact_response_code(
        self,
    ) -> None:
        client = _client()
        write_started = asyncio.Event()

        async def fake_write_raw(_data: bytes) -> None:
            write_started.set()
            for wrong_code in (0x21, 0x22, 0xE0, 0xD3, 0xC6):
                client._on_notify(None, bytearray(_frame(wrong_code)))

        with patch.object(client, "write_raw", new=fake_write_raw):
            command = asyncio.create_task(
                client.send_command(
                    RequestCodeEnum.SET_LABEL_DENSITY, b"\x03", timeout=1.0
                )
            )
            await write_started.wait()
            await asyncio.sleep(0.01)
            self.assertFalse(
                command.done(), "wrong or unsolicited response woke the waiter"
            )

            expected_and_unsolicited = _frame(0x31, b"\x01") + _frame(0xC6, b"\x00")
            client._on_notify(None, bytearray(expected_and_unsolicited[:3]))
            client._on_notify(None, bytearray(expected_and_unsolicited[3:]))
            response = await command

        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual((response.type, response.data), (0x31, b"\x01"))

    async def test_parser_handles_one_byte_fragments_and_invalid_frames(self) -> None:
        client = _client()
        write_started = asyncio.Event()

        async def fake_write_raw(_data: bytes) -> None:
            write_started.set()

        with patch.object(client, "write_raw", new=fake_write_raw):
            command = asyncio.create_task(
                client.send_command(RequestCodeEnum.START_PRINT, b"\x01", timeout=1.0)
            )
            await write_started.wait()

            bad_checksum = bytearray(_frame(0x02))
            bad_checksum[-3] ^= 0x01
            bad_trailer = bytearray(_frame(0x02))
            bad_trailer[-1] = 0x00
            client._on_notify(None, bad_checksum)
            client._on_notify(None, bad_trailer)
            self.assertLessEqual(len(client._buffer), 1)
            await asyncio.sleep(0.01)
            self.assertFalse(command.done(), "an invalid packet woke the waiter")

            client._on_notify(None, bytearray(b"\x44" * 4096 + b"\x55"))
            self.assertEqual(client._buffer, b"\x55")
            client._on_notify(None, bytearray(b"\x44"))
            self.assertFalse(client._buffer)
            for value in _frame(0x02):
                client._on_notify(None, bytearray([value]))
            response = await command

        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual((response.type, response.data), (0x02, b"\x01"))

    async def test_error_response_frames_wake_active_waiter(self) -> None:
        for error_packet in (
            NiimbotPacket(0xDB, b"\x00"),
            NiimbotPacket(0xDB, b"\x06"),
            NiimbotPacket(0xDB, b""),
            NiimbotPacket(0x00, b""),
            NiimbotPacket(0x00, b"\x01"),
        ):
            client = _client()

            async def fake_write_raw(
                _data: bytes,
                *,
                response_packet=error_packet,
                notify_client=client,
            ) -> None:
                notify_client._on_notify(
                    None,
                    bytearray(_frame(response_packet.type, response_packet.data)),
                )

            with patch.object(client, "write_raw", new=fake_write_raw):
                response = await client.send_command(
                    RequestCodeEnum.START_PRINT, b"\x01", timeout=1.0
                )

            self.assertIsNotNone(response)
            assert response is not None
            self.assertEqual(
                (response.type, response.data),
                (error_packet.type, error_packet.data),
            )

    async def test_coalesced_device_error_takes_precedence_in_either_order(
        self,
    ) -> None:
        error_packet = _frame(0xDB, b"\x06")
        positive_ack = _frame(0x02, b"\x01")
        for frames in (error_packet + positive_ack, positive_ack + error_packet):
            client = _client()

            async def fake_write_raw(
                _data: bytes,
                *,
                notifications=frames,
                notify_client=client,
            ) -> None:
                notify_client._on_notify(None, bytearray(notifications))

            with patch.object(client, "write_raw", new=fake_write_raw):
                response = await client.send_command(
                    RequestCodeEnum.START_PRINT, b"\x01", timeout=1.0
                )

            self.assertIsNotNone(response)
            assert response is not None
            self.assertEqual((response.type, response.data), (0xDB, b"\x06"))

    async def test_commands_are_serialized_until_each_response_arrives(self) -> None:
        client = _client()
        writes: list[int] = []
        first_written = asyncio.Event()
        second_written = asyncio.Event()

        async def fake_write_raw(data: bytes) -> None:
            packet = NiimbotPacket.from_bytes(data)
            self.assertIsNotNone(packet)
            assert packet is not None
            writes.append(packet.type)
            (first_written if len(writes) == 1 else second_written).set()

        with patch.object(client, "write_raw", new=fake_write_raw):
            first = asyncio.create_task(
                client.send_command(RequestCodeEnum.START_PRINT, b"\x01", timeout=1.0)
            )
            await first_written.wait()
            second = asyncio.create_task(
                client.send_command(
                    RequestCodeEnum.START_PAGE_PRINT, b"\x01", timeout=1.0
                )
            )
            await asyncio.sleep(0.01)
            self.assertEqual(writes, [RequestCodeEnum.START_PRINT])

            client._on_notify(None, bytearray(_frame(0x02)))
            first_response = await first
            await second_written.wait()
            self.assertEqual(
                writes, [RequestCodeEnum.START_PRINT, RequestCodeEnum.START_PAGE_PRINT]
            )
            client._on_notify(None, bytearray(_frame(0x04)))
            second_response = await second

        assert first_response is not None
        assert second_response is not None
        self.assertEqual(first_response.type, 0x02)
        self.assertEqual(second_response.type, 0x04)

    async def test_info_subtypes_route_by_their_response_code(self) -> None:
        for subtype, response_code in _INFO_RESPONSE_CODES.items():
            client = _client()

            async def fake_write_raw(
                _data: bytes,
                *,
                expected_response=response_code,
                notify_client=client,
            ) -> None:
                notify_client._on_notify(None, bytearray(_frame(expected_response)))

            with patch.object(client, "write_raw", new=fake_write_raw):
                response = await client.send_command(
                    RequestCodeEnum.GET_INFO, bytes([subtype])
                )

            self.assertIsNotNone(response)
            assert response is not None
            self.assertEqual(response.type, response_code)

    async def test_heartbeat_accepts_only_its_defined_response_codes(self) -> None:
        for response_code in (0xDE, 0xDF, 0xDD, 0xD9):
            client = _client()

            async def fake_write_raw(
                _data: bytes,
                *,
                expected_response=response_code,
                notify_client=client,
            ) -> None:
                notify_client._on_notify(None, bytearray(_frame(expected_response)))

            with patch.object(client, "write_raw", new=fake_write_raw):
                response = await client.send_command(RequestCodeEnum.HEARTBEAT, b"\x01")

            self.assertIsNotNone(response)
            assert response is not None
            self.assertEqual(response.type, response_code)

    async def test_unsupported_requests_and_info_payloads_raise_value_error(
        self,
    ) -> None:
        client = _client()
        write_raw = AsyncMock()

        with patch.object(client, "write_raw", new=write_raw):
            with self.assertRaises(ValueError):
                await client.send_command(RequestCodeEnum.GET_RFID)
            with self.assertRaises(ValueError):
                await client.send_command(RequestCodeEnum.GET_INFO)
            for invalid_payload in (
                b"\x00",
                b"\x04",
                b"\x05",
                b"\x10",
                b"\x01\x02",
            ):
                with (
                    self.subTest(payload=invalid_payload),
                    self.assertRaises(ValueError),
                ):
                    await client.send_command(RequestCodeEnum.GET_INFO, invalid_payload)

        write_raw.assert_not_awaited()

    async def test_selected_write_mode_matches_final_characteristic_properties(
        self,
    ) -> None:
        for properties, expected in (
            (["write"], True),
            (["write-without-response"], False),
            (["write", "write-without-response"], False),
        ):
            client = _client()
            characteristic = SimpleNamespace(uuid="write-char", properties=properties)
            service = SimpleNamespace(characteristics=[characteristic])
            client.client = cast(
                BleakClient, SimpleNamespace(services=[service], is_connected=True)
            )
            client.write_uuid = "write-char"

            with self.subTest(properties=properties):
                self.assertEqual(client._selected_write_requires_response(), expected)

    async def test_connect_sets_mode_from_the_selected_characteristic(self) -> None:
        client = _client()
        write_characteristic = SimpleNamespace(uuid="write-char", properties=["write"])
        notify_characteristic = SimpleNamespace(
            uuid="notify-char", properties=["notify"]
        )
        services = [
            SimpleNamespace(
                uuid="unpreferred-service",
                characteristics=[write_characteristic, notify_characteristic],
            )
        ]
        fake_ble_client = SimpleNamespace(
            services=services,
            is_connected=True,
            connect=AsyncMock(),
            start_notify=AsyncMock(),
            disconnect=AsyncMock(),
        )
        handshake = AsyncMock(return_value=None)

        with (
            patch(
                "catlabel.vendors.niimbot.client.BleakClient",
                return_value=fake_ble_client,
            ),
            patch.object(client, "send_command", new=handshake),
            patch("catlabel.vendors.niimbot.client.asyncio.sleep", new=_no_sleep),
        ):
            self.assertTrue(await client.connect())

        self.assertEqual(client.write_uuid, "write-char")
        self.assertEqual(client.notify_uuid, "notify-char")
        self.assertTrue(client._write_with_response)
        fake_ble_client.connect.assert_awaited_once_with(timeout=10.0)
        fake_ble_client.start_notify.assert_awaited_once()
        self.assertEqual(handshake.await_count, 2)

    async def test_bleak_write_error_is_not_replayed(self) -> None:
        client = _client()
        gatt_write = AsyncMock(side_effect=BleakError("write failed"))
        client.client = cast(
            BleakClient,
            SimpleNamespace(is_connected=True, write_gatt_char=gatt_write),
        )
        client.write_uuid = "write-char"
        client._write_with_response = False

        with (
            patch("catlabel.vendors.niimbot.client.asyncio.sleep", new=_no_sleep),
            self.assertRaisesRegex(BleakError, "write failed"),
        ):
            await client.write_raw(b"raster")

        gatt_write.assert_awaited_once_with("write-char", b"raster", response=False)

    async def test_disconnect_clears_print_error_state(self) -> None:
        client = _client()
        client._print_active = True
        client._print_device_error = NiimbotPacket(0xDB, b"\x06")

        await client.disconnect()

        self.assertFalse(client._print_active)
        self.assertIsNone(client._print_device_error)

    async def test_timeout_returns_none_and_write_errors_propagate(self) -> None:
        client = _client()

        async def silent_write(_data: bytes) -> None:
            return None

        with patch.object(client, "write_raw", new=silent_write):
            result = await client.send_command(
                RequestCodeEnum.START_PRINT, b"\x01", timeout=0.001
            )
        self.assertIsNone(result)

        async def failed_write(_data: bytes) -> None:
            raise OSError("BLE write failed")

        with (
            patch.object(client, "write_raw", new=failed_write),
            self.assertRaisesRegex(OSError, "BLE write failed"),
        ):
            await client.send_command(RequestCodeEnum.START_PRINT, b"\x01", timeout=1.0)


class NiimbotPrintAcknowledgementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        logger_patch = patch("catlabel.vendors.niimbot.client.logger")
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

    def _patch_raster_and_delays(self):
        raster = SimpleNamespace(width=8, height=1, pixels=[0, 1, 0, 1, 0, 1, 0, 1])
        return (
            patch(
                "catlabel.vendors.niimbot.client.image_to_raster", return_value=raster
            ),
            patch("catlabel.vendors.niimbot.client.asyncio.sleep", new=_no_sleep),
        )

    async def test_each_setup_command_rejects_non_positive_or_malformed_ack(
        self,
    ) -> None:
        invalid_responses: tuple[NiimbotPacket | None, ...] = (
            None,
            NiimbotPacket(0x31, b""),
            NiimbotPacket(0x31, b"\x00"),
            NiimbotPacket(0x31, b"\x02"),
            NiimbotPacket(0x31, b"\x01\x00"),
            NiimbotPacket(0x30, b"\x01"),
        )

        for request_code, expected_stage in _REQUIRED_SETUP:
            expected_response = _RESPONSE_CODES[request_code]
            for invalid_response in invalid_responses:
                response = invalid_response
                if response is not None and response.type == 0x31:
                    response = NiimbotPacket(expected_response, response.data)
                elif response is not None and response.type == 0x30:
                    response = NiimbotPacket(expected_response ^ 0x01, response.data)

                client = _client()
                calls: Counter[int] = Counter()
                writes: list[bytes] = []

                async def fake_send(
                    req_code,
                    _data=b"",
                    timeout=5.0,
                    *,
                    failing_code=request_code,
                    failing_response=response,
                    call_counts=calls,
                ):
                    code = int(req_code)
                    call_counts[code] += 1
                    if code in (
                        RequestCodeEnum.END_PRINT,
                        RequestCodeEnum.ALLOW_PRINT_CLEAR,
                    ):
                        return None
                    if code == failing_code:
                        return failing_response
                    return _positive_response(code, _data)

                async def fake_write_raw(data: bytes, *, sent=writes) -> None:
                    sent.append(data)

                raster_patch, sleep_patch = self._patch_raster_and_delays()
                with (
                    patch.object(client, "send_command", new=fake_send),
                    patch.object(client, "write_raw", new=fake_write_raw),
                    raster_patch,
                    sleep_patch,
                    self.assertRaises(NiimbotPrintError) as raised,
                ):
                    await client.print_images([Image.new("RGB", (8, 1), "white")])

                self.assertEqual(raised.exception.stage, expected_stage)
                self.assertFalse(raised.exception.delivery_uncertain)
                self.assertEqual(
                    writes, [], f"raster was sent after invalid {expected_stage} reply"
                )

    async def test_device_error_from_compatibility_reset_aborts_before_raster(
        self,
    ) -> None:
        error_packets = (
            NiimbotPacket(0xDB, b"\x00"),
            NiimbotPacket(0xDB, b"\x06"),
            NiimbotPacket(0xDB, b""),
            NiimbotPacket(0x00, b""),
            NiimbotPacket(0x00, b"\x01"),
        )
        reset_commands = (
            (RequestCodeEnum.END_PRINT, "reset_end_print"),
            (RequestCodeEnum.ALLOW_PRINT_CLEAR, "reset_clear"),
        )
        for failing_request, expected_stage in reset_commands:
            for error_packet in error_packets:
                with self.subTest(
                    request=failing_request,
                    error_type=error_packet.type,
                    error_data=error_packet.data,
                ):
                    client = _client()
                    calls: Counter[int] = Counter()
                    writes: list[bytes] = []

                    async def fake_send(
                        req_code,
                        _data=b"",
                        timeout=5.0,
                        *,
                        failing_code=failing_request,
                        response_packet=error_packet,
                        call_counts=calls,
                    ):
                        code = int(req_code)
                        call_counts[code] += 1
                        if code == failing_code and call_counts[code] == 1:
                            return response_packet
                        return None

                    async def fake_write_raw(data: bytes, *, sent=writes) -> None:
                        sent.append(data)

                    raster_patch, sleep_patch = self._patch_raster_and_delays()
                    with (
                        patch.object(client, "send_command", new=fake_send),
                        patch.object(client, "write_raw", new=fake_write_raw),
                        raster_patch,
                        sleep_patch,
                        self.assertRaises(NiimbotPrintError) as raised,
                    ):
                        await client.print_images([Image.new("RGB", (8, 1), "white")])

                    self.assertEqual(raised.exception.stage, expected_stage)
                    self.assertFalse(raised.exception.delivery_uncertain)
                    self.assertEqual(writes, [])

    async def test_end_page_uncertainty_sends_once_and_aborts_remaining_labels(
        self,
    ) -> None:
        client = _client()
        calls: Counter[int] = Counter()
        writes: list[bytes] = []

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls[code] += 1
            if code in (RequestCodeEnum.END_PRINT, RequestCodeEnum.ALLOW_PRINT_CLEAR):
                return None
            if code == RequestCodeEnum.END_PAGE_PRINT:
                self.assertEqual(timeout, 15.0)
                return None
            return _positive_response(code, data)

        async def fake_write_raw(data: bytes) -> None:
            writes.append(data)

        raster_patch, sleep_patch = self._patch_raster_and_delays()
        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fake_write_raw),
            raster_patch,
            sleep_patch,
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await client.print_images(
                [Image.new("RGB", (8, 1), "white"), Image.new("RGB", (8, 1), "white")]
            )

        self.assertEqual(raised.exception.stage, "end_page")
        self.assertTrue(raised.exception.delivery_uncertain)
        self.assertEqual(calls[RequestCodeEnum.END_PAGE_PRINT], 1)
        self.assertEqual(calls[RequestCodeEnum.START_PRINT], 1)
        self.assertEqual(len(writes), 1)

    async def test_end_print_uncertainty_aborts_remaining_labels(self) -> None:
        client = _client()
        calls: Counter[int] = Counter()
        writes: list[bytes] = []

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls[code] += 1
            if code == RequestCodeEnum.END_PRINT:
                return None
            if code == RequestCodeEnum.ALLOW_PRINT_CLEAR:
                return None
            return _positive_response(code, data)

        async def fake_write_raw(data: bytes) -> None:
            writes.append(data)

        raster_patch, sleep_patch = self._patch_raster_and_delays()
        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fake_write_raw),
            raster_patch,
            sleep_patch,
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await client.print_images(
                [Image.new("RGB", (8, 1), "white"), Image.new("RGB", (8, 1), "white")]
            )

        self.assertEqual(raised.exception.stage, "end_print")
        self.assertTrue(raised.exception.delivery_uncertain)
        self.assertEqual(calls[RequestCodeEnum.START_PRINT], 1)
        self.assertEqual(calls[RequestCodeEnum.END_PAGE_PRINT], 1)
        self.assertEqual(len(writes), 1)

    async def test_later_label_reset_error_keeps_batch_uncertain(self) -> None:
        client = _client()
        calls: Counter[int] = Counter()
        writes: list[bytes] = []

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls[code] += 1
            if code == RequestCodeEnum.END_PRINT:
                if calls[code] == 2:
                    return _positive_response(code, data)
                if calls[code] == 3:
                    return NiimbotPacket(0xDB, b"\x00")
                return None
            if code == RequestCodeEnum.ALLOW_PRINT_CLEAR:
                return None
            return _positive_response(code, data)

        async def fake_write_raw(data: bytes) -> None:
            writes.append(data)

        raster_patch, sleep_patch = self._patch_raster_and_delays()
        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fake_write_raw),
            raster_patch,
            sleep_patch,
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await client.print_images(
                [Image.new("RGB", (8, 1), "white"), Image.new("RGB", (8, 1), "white")]
            )

        self.assertEqual(raised.exception.stage, "reset_end_print")
        self.assertTrue(raised.exception.delivery_uncertain)
        self.assertEqual(calls[RequestCodeEnum.START_PRINT], 1)
        self.assertEqual(len(writes), 1)

    async def test_successful_single_label_requires_all_acks(self) -> None:
        client = _client()
        calls: Counter[int] = Counter()
        writes: list[bytes] = []

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls[code] += 1
            if code == RequestCodeEnum.END_PRINT and calls[code] == 1:
                return None
            if code == RequestCodeEnum.ALLOW_PRINT_CLEAR:
                return None
            return _positive_response(code, data)

        async def fake_write_raw(data: bytes) -> None:
            writes.append(data)

        raster_patch, sleep_patch = self._patch_raster_and_delays()
        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fake_write_raw),
            raster_patch,
            sleep_patch,
        ):
            result = await client.print_images([Image.new("RGB", (8, 1), "white")])

        self.assertIsNone(result)
        for request_code, _stage in _REQUIRED_SETUP:
            self.assertEqual(calls[request_code], 1)
        self.assertEqual(calls[RequestCodeEnum.END_PAGE_PRINT], 1)
        self.assertEqual(calls[RequestCodeEnum.END_PRINT], 3)
        self.assertEqual(len(writes), 1)
        self.assertFalse(client._print_active)
        self.assertIsNone(client._print_device_error)

    async def test_unsolicited_device_error_during_raster_stops_batch(self) -> None:
        client = _client()
        calls: Counter[int] = Counter()
        gatt_writes: list[tuple[str, bytes, bool]] = []
        gatt_write_count = 0

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls[code] += 1
            if code == RequestCodeEnum.END_PRINT and calls[code] == 1:
                return None
            if code == RequestCodeEnum.ALLOW_PRINT_CLEAR:
                return None
            return _positive_response(code, data)

        async def fake_gatt_write(
            uuid: str, data: bytes, *, response: bool = False
        ) -> None:
            nonlocal gatt_write_count
            gatt_write_count += 1
            gatt_writes.append((uuid, data, response))
            if gatt_write_count == 1:
                self.assertFalse(client._events)
                client._on_notify(None, bytearray(_frame(0xDB, b"\x06")))

        client.client = cast(
            BleakClient,
            SimpleNamespace(
                is_connected=True,
                write_gatt_char=AsyncMock(side_effect=fake_gatt_write),
            ),
        )
        client.write_uuid = "write-char"
        client._write_with_response = False
        raster = SimpleNamespace(
            width=8,
            height=2,
            pixels=[0, 1, 0, 1, 0, 1, 0, 1] * 2,
        )
        raster_patch = patch(
            "catlabel.vendors.niimbot.client.image_to_raster", return_value=raster
        )
        sleep_patch = patch(
            "catlabel.vendors.niimbot.client.asyncio.sleep", new=_no_sleep
        )
        with (
            patch.object(client, "send_command", new=fake_send),
            raster_patch,
            sleep_patch,
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await client.print_images(
                [
                    Image.new("RGB", (8, 2), "white"),
                    Image.new("RGB", (8, 2), "white"),
                ]
            )

        self.assertEqual(raised.exception.stage, "raster_write")
        self.assertTrue(raised.exception.delivery_uncertain)
        self.assertEqual(len(gatt_writes), 1)
        self.assertEqual(calls[RequestCodeEnum.START_PRINT], 1)
        self.assertEqual(calls[RequestCodeEnum.END_PAGE_PRINT], 0)
        self.assertFalse(client._print_active)
        self.assertIsNone(client._print_device_error)

    async def test_positive_setup_ack_does_not_clear_pending_device_error(self) -> None:
        client = _client()
        calls: Counter[int] = Counter()
        writes: list[bytes] = []

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls[code] += 1
            if code == RequestCodeEnum.SET_LABEL_DENSITY:
                client._on_notify(None, bytearray(_frame(0xDB, b"\x06")))
                return _positive_response(code, data)
            if code in (RequestCodeEnum.END_PRINT, RequestCodeEnum.ALLOW_PRINT_CLEAR):
                return None
            return _positive_response(code, data)

        async def fake_write_raw(data: bytes) -> None:
            writes.append(data)

        raster_patch, sleep_patch = self._patch_raster_and_delays()
        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fake_write_raw),
            raster_patch,
            sleep_patch,
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await client.print_images([Image.new("RGB", (8, 1), "white")])

        self.assertEqual(raised.exception.stage, "set_label_density")
        self.assertFalse(raised.exception.delivery_uncertain)
        self.assertEqual(writes, [])
        self.assertFalse(client._print_active)
        self.assertIsNone(client._print_device_error)

    async def test_error_outside_print_does_not_poison_next_job(self) -> None:
        client = _client()
        client._on_notify(None, bytearray(_frame(0xDB, b"\x06")))
        self.assertIsNone(client._print_device_error)

        calls: Counter[int] = Counter()

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls[code] += 1
            if code == RequestCodeEnum.END_PRINT and calls[code] == 1:
                return None
            if code == RequestCodeEnum.ALLOW_PRINT_CLEAR:
                return None
            return _positive_response(code, data)

        async def fake_write_raw(_data: bytes) -> None:
            return None

        raster_patch, sleep_patch = self._patch_raster_and_delays()
        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fake_write_raw),
            raster_patch,
            sleep_patch,
        ):
            result = await client.print_images([Image.new("RGB", (8, 1), "white")])

        self.assertIsNone(result)
        self.assertEqual(calls[RequestCodeEnum.END_PAGE_PRINT], 1)
        self.assertFalse(client._print_active)
        self.assertIsNone(client._print_device_error)

    async def test_cancellation_clears_active_print_state(self) -> None:
        client = _client()
        end_page_started = asyncio.Event()

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            if code in (RequestCodeEnum.END_PRINT, RequestCodeEnum.ALLOW_PRINT_CLEAR):
                return None
            return _positive_response(code, data)

        async def fake_write_raw(_data: bytes) -> None:
            return None

        async def block_end_page(*, timeout: float = 15.0) -> None:
            end_page_started.set()
            await asyncio.Event().wait()

        raster_patch, sleep_patch = self._patch_raster_and_delays()
        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fake_write_raw),
            patch.object(client, "_wait_for_end_page_ack", new=block_end_page),
            raster_patch,
            sleep_patch,
        ):
            print_task = asyncio.create_task(
                client.print_images([Image.new("RGB", (8, 1), "white")])
            )
            await end_page_started.wait()
            self.assertTrue(client._print_active)
            print_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await print_task

        self.assertFalse(client._print_active)
        self.assertIsNone(client._print_device_error)

    async def test_raster_write_failure_is_uncertain_and_cleanup_does_not_mask_it(
        self,
    ) -> None:
        client = _client()
        calls: Counter[int] = Counter()
        gatt_write = AsyncMock(side_effect=BleakError("raster write failed"))
        client.client = cast(
            BleakClient,
            SimpleNamespace(is_connected=True, write_gatt_char=gatt_write),
        )
        client.write_uuid = "write-char"
        client._write_with_response = False

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls[code] += 1
            if code == RequestCodeEnum.END_PRINT:
                if calls[code] == 1:
                    return None
                raise OSError("cleanup failed")
            if code == RequestCodeEnum.ALLOW_PRINT_CLEAR:
                return None
            return _positive_response(code, data)

        raster_patch, sleep_patch = self._patch_raster_and_delays()
        with (
            patch.object(client, "send_command", new=fake_send),
            raster_patch,
            sleep_patch,
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await client.print_images([Image.new("RGB", (8, 1), "white")])

        self.assertEqual(raised.exception.stage, "raster_write")
        self.assertTrue(raised.exception.delivery_uncertain)
        self.assertEqual(calls[RequestCodeEnum.END_PRINT], 2)
        gatt_write.assert_awaited_once_with("write-char", ANY, response=False)
        self.assertFalse(client._print_active)
        self.assertIsNone(client._print_device_error)

    async def test_wait_for_end_page_rejects_missing_malformed_and_wrong_responses_once(
        self,
    ) -> None:
        invalid_packets: tuple[NiimbotPacket | None, ...] = (
            None,
            NiimbotPacket(0xE4, b""),
            NiimbotPacket(0xE4, b"\x00"),
            NiimbotPacket(0xE4, b"\x02"),
            NiimbotPacket(0xE4, b"\x01\x00"),
            NiimbotPacket(0xE5, b"\x01"),
        )

        for packet in invalid_packets:
            client = _client()
            calls: list[tuple[int, bytes, float]] = []

            async def fake_send(
                req_code,
                data=b"",
                timeout=5.0,
                *,
                response_packet=packet,
                call_log=calls,
            ):
                call_log.append((int(req_code), data, timeout))
                return response_packet

            with (
                patch.object(client, "send_command", new=fake_send),
                self.assertRaises(NiimbotPrintError) as raised,
            ):
                await client._wait_for_end_page_ack(timeout=0.75)

            self.assertEqual(raised.exception.stage, "end_page")
            self.assertTrue(raised.exception.delivery_uncertain)
            self.assertEqual(calls, [(RequestCodeEnum.END_PAGE_PRINT, b"\x01", 0.75)])

    async def test_existing_print_error_is_not_wrapped(self) -> None:
        client = _client()
        calls: Counter[int] = Counter()
        sentinel = NiimbotPrintError("end_page", True, "original error")

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls[code] += 1
            if code in (RequestCodeEnum.END_PRINT, RequestCodeEnum.ALLOW_PRINT_CLEAR):
                return None
            return _positive_response(code, data)

        async def fake_write_raw(_data: bytes) -> None:
            return None

        async def failed_wait(*, timeout: float = 15.0) -> None:
            raise sentinel

        raster_patch, sleep_patch = self._patch_raster_and_delays()
        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fake_write_raw),
            patch.object(client, "_wait_for_end_page_ack", new=failed_wait),
            raster_patch,
            sleep_patch,
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await client.print_images([Image.new("RGB", (8, 1), "white")])

        self.assertIs(raised.exception, sentinel)
        self.assertTrue(raised.exception.delivery_uncertain)


if __name__ == "__main__":
    unittest.main()
