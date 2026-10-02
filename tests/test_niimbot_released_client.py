from __future__ import annotations

import asyncio
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from catlabel.protocol.families import niimbot_core as codec
from catlabel.raster import RasterBuffer
from catlabel.vendors.niimbot.client import (
    InfoEnum,
    NiimbotClient,
    NiimbotPacket,
    NiimbotPrintError,
    RequestCodeEnum,
)

_ACK_RESPONSES = {
    RequestCodeEnum.HEARTBEAT: 0xDE,
    RequestCodeEnum.SET_LABEL_TYPE: 0x33,
    RequestCodeEnum.SET_LABEL_DENSITY: 0x31,
    RequestCodeEnum.START_PRINT: 0x02,
    RequestCodeEnum.END_PRINT: 0xF4,
    RequestCodeEnum.START_PAGE_PRINT: 0x04,
    RequestCodeEnum.END_PAGE_PRINT: 0xE4,
    RequestCodeEnum.ALLOW_PRINT_CLEAR: 0x30,
    RequestCodeEnum.SET_DIMENSION: 0x14,
    RequestCodeEnum.SET_QUANTITY: 0x16,
}
_REAL_SLEEP = asyncio.sleep


def _frame(type_: int, data: bytes = b"\x01") -> bytes:
    return NiimbotPacket(type_, data).to_bytes()


def _status_payload(version: int) -> bytes:
    payload = bytearray(13)
    encoded = {3: (2, 4), 4: (3, 0), 5: (3, 2)}[version]
    payload[11], payload[12] = encoded
    return bytes(payload)


def _client(variant: str | None = None, *, width: int = 96) -> NiimbotClient:
    hardware_info: dict[str, object] = {
        "width_px": width,
        "default_energy": 3,
        "max_density": 5,
    }
    if variant is not None:
        hardware_info["protocol_variant"] = variant
    return NiimbotClient(
        SimpleNamespace(address="AA:BB:CC:DD:EE:FF"),
        hardware_info,
        SimpleNamespace(energy=3),
        None,
    )


async def _test_sleep(delay: float) -> None:
    # Keep BLE pacing and poll deadlines realistic, but omit cleanup and legacy
    # inter-label throttles from focused unit tests.
    if delay < 0.1:
        await _REAL_SLEEP(delay)


class NiimbotReleasedClientTests(unittest.IsolatedAsyncioTestCase):
    async def _run_print(
        self,
        client: NiimbotClient,
        raster: RasterBuffer,
        *,
        image_size: tuple[int, int] = (96, 1),
        connect_payload: bytes = b"\x01",
        status_payload: bytes | None = None,
        model_payload: bytes | None = b"\x12\x34",
        completion_page: bytes = b"\x00\x01",
        completion_at: str = "row",
        response_overrides: dict[tuple[int, int], NiimbotPacket | None] | None = None,
        before_write=None,
        status_replies: tuple[bytes | None, ...] = (b"\x00\x01",),
    ) -> tuple[list[tuple[int, bytes, float]], list[bytes]]:
        calls: list[tuple[int, bytes, float]] = []
        writes: list[bytes] = []
        counts: Counter[int] = Counter()
        overrides = response_overrides or {}

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            payload = bytes(data)
            calls.append((code, payload, timeout))
            counts[code] += 1
            if (code, counts[code]) in overrides:
                return overrides[(code, counts[code])]
            if code == RequestCodeEnum.CONNECT:
                return NiimbotPacket(0xC2, connect_payload)
            if code == RequestCodeEnum.GET_INFO:
                if payload == bytes((InfoEnum.MODEL_ID.value,)):
                    if model_payload is None:
                        return None
                    return NiimbotPacket(0x48, model_payload)
                return NiimbotPacket(0x4B, b"\x01")
            if code == RequestCodeEnum.GET_STATUS_DATA:
                if status_payload is None:
                    return None
                return NiimbotPacket(0xB5, status_payload)
            if code == RequestCodeEnum.GET_PRINT_STATUS:
                index = counts[code] - 1
                status = status_replies[min(index, len(status_replies) - 1)]
                return None if status is None else NiimbotPacket(0xB3, status)
            response = _ACK_RESPONSES.get(RequestCodeEnum(code))
            if response is None:
                raise AssertionError(f"unexpected NIIMBOT request 0x{code:02x}")

            if code == RequestCodeEnum.END_PAGE_PRINT and completion_at == "page_end":
                page = _frame(0xE0, completion_page)
                trailer = _frame(0xE4, b"\x01")
                client._on_notify(None, bytearray(page[:3]))
                client._on_notify(None, bytearray(page[3:] + trailer))
            return NiimbotPacket(response, b"\x01")

        async def fake_write(data: bytes) -> None:
            writes.append(bytes(data))
            if before_write is not None:
                await before_write(bytes(data), len(writes))
            elif completion_at == "row" and len(writes) == 1:
                client._on_notify(None, bytearray(_frame(0xE0, completion_page)))

        source = Image.new("RGB", image_size, "white")
        try:
            with (
                patch.object(client, "send_command", new=fake_send),
                patch.object(client, "write_raw", new=fake_write),
                patch(
                    "catlabel.vendors.niimbot.client.image_to_raster",
                    return_value=raster,
                ),
                patch(
                    "catlabel.vendors.niimbot.client.asyncio.sleep",
                    new=_test_sleep,
                ),
            ):
                await client.print_images([source], dither=False)
        finally:
            source.close()
        return calls, writes

    async def test_connect_request_uses_transport_marker_and_packet_parser_stays_plain(
        self,
    ) -> None:
        request = NiimbotPacket(RequestCodeEnum.CONNECT, b"\x01")
        self.assertEqual(request.to_bytes(), bytes.fromhex("035555c10101c1aaaa"))
        parsed = NiimbotPacket.from_bytes(_frame(0xC2, b"\x01"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual((parsed.type, parsed.data), (0xC2, b"\x01"))
        self.assertEqual(
            _ACK_RESPONSES[RequestCodeEnum.SET_DIMENSION],
            0x14,
        )

    async def test_auto_probe_connect_results_select_dimension_shape_and_model_query(
        self,
    ) -> None:
        cases = (
            (b"\x01", None, 0, "d11_v1", b"\x00\x01"),
            (b"\x02", None, 1, "d110", bytes.fromhex("00010060")),
            (b"\x03", _status_payload(3), 3, "d11_v1", b"\x00\x01"),
            (b"\x03", _status_payload(4), 4, "d11_v1", b"\x00\x01"),
            (b"\x03", _status_payload(5), 5, "d11_v1", b"\x00\x01"),
        )
        for connect_payload, status_payload, version, variant, dimension in cases:
            with self.subTest(connect=connect_payload, version=version):
                client = _client("d11_auto")
                raster = RasterBuffer([1] * 96, width=96)
                calls, _writes = await self._run_print(
                    client,
                    raster,
                    connect_payload=connect_payload,
                    status_payload=status_payload,
                )
                self.assertEqual(client._protocol_version, version)
                self.assertEqual(client._resolved_protocol_variant, variant)
                self.assertIn(
                    (int(RequestCodeEnum.SET_DIMENSION), dimension),
                    [(code, data) for code, data, _timeout in calls],
                )
                self.assertIn(
                    (int(RequestCodeEnum.GET_INFO), b"\x08"),
                    [(code, data) for code, data, _timeout in calls],
                )
                self.assertLess(
                    [code for code, _data, _timeout in calls].index(
                        RequestCodeEnum.CONNECT
                    ),
                    [code for code, _data, _timeout in calls].index(
                        RequestCodeEnum.SET_LABEL_DENSITY
                    ),
                )

    async def test_auto_probe_protocol_version_two_selects_d110(self) -> None:
        client = _client("d11_auto")
        with patch(
            "catlabel.vendors.niimbot.client.protocol_version",
            return_value=2,
        ):
            calls, _writes = await self._run_print(
                client,
                RasterBuffer([0] * 96, width=96),
                connect_payload=b"\x03",
                status_payload=_status_payload(3),
            )
        self.assertEqual(client._protocol_version, 2)
        self.assertEqual(client._resolved_protocol_variant, "d110")
        self.assertIn(
            (int(RequestCodeEnum.SET_DIMENSION), bytes.fromhex("00010060")),
            [(code, data) for code, data, _timeout in calls],
        )

    async def test_missing_model_id_is_debug_only(self) -> None:
        client = _client("d11_auto")
        with patch("catlabel.vendors.niimbot.client.logger.warning") as warning:
            calls, _writes = await self._run_print(
                client,
                RasterBuffer([0] * 96, width=96),
                model_payload=None,
            )
        self.assertEqual(client._resolved_protocol_variant, "d11_v1")
        self.assertIsNone(client._model_id)
        self.assertTrue(warning.called)
        self.assertIn(
            (int(RequestCodeEnum.GET_INFO), b"\x08"),
            [(code, data) for code, data, _timeout in calls],
        )

    async def test_auto_probe_rejects_missing_negative_and_truncated_replies_before_print(
        self,
    ) -> None:
        cases = (
            (None, None, "missing CONNECT"),
            (NiimbotPacket(0xC2, b""), None, "empty CONNECT"),
            (NiimbotPacket(0xC2, b"\x00"), None, "negative CONNECT"),
            (NiimbotPacket(0xC2, b"\x04"), None, "unknown CONNECT"),
            (NiimbotPacket(0xC2, b"\x03"), None, "missing B5"),
            (
                NiimbotPacket(0xC2, b"\x03"),
                NiimbotPacket(0xB5, b"\x00" * 12),
                "short B5",
            ),
        )
        for connect_reply, status_reply, name in cases:
            with self.subTest(case=name):
                client = _client("d11_auto")
                calls: list[tuple[int, bytes, float]] = []
                writes: list[bytes] = []

                async def fake_send(
                    req_code,
                    data=b"",
                    timeout=5.0,
                    *,
                    call_log=calls,
                    c_reply=connect_reply,
                    s_reply=status_reply,
                ):
                    code = int(req_code)
                    call_log.append((code, bytes(data), timeout))
                    if code == RequestCodeEnum.CONNECT:
                        return c_reply
                    if code == RequestCodeEnum.GET_INFO:
                        return NiimbotPacket(0x48, b"\x12\x34")
                    if code == RequestCodeEnum.GET_STATUS_DATA:
                        return s_reply
                    return NiimbotPacket(0xF4, b"\x01")

                async def fake_write(data: bytes, *, sent=writes) -> None:
                    sent.append(data)

                with (
                    patch.object(client, "send_command", new=fake_send),
                    patch.object(client, "write_raw", new=fake_write),
                    patch(
                        "catlabel.vendors.niimbot.client.image_to_raster",
                        return_value=RasterBuffer([0] * 96, width=96),
                    ),
                    patch(
                        "catlabel.vendors.niimbot.client.asyncio.sleep",
                        new=_test_sleep,
                    ),
                    self.assertRaises(NiimbotPrintError) as raised,
                ):
                    await client.print_images([Image.new("RGB", (96, 1), "white")])

                self.assertEqual(raised.exception.stage, "protocol_probe")
                self.assertFalse(raised.exception.delivery_uncertain)
                self.assertEqual(writes, [])
                codes = [code for code, _data, _timeout in calls]
                self.assertFalse(
                    set(codes)
                    & {
                        RequestCodeEnum.SET_LABEL_DENSITY,
                        RequestCodeEnum.SET_LABEL_TYPE,
                        RequestCodeEnum.START_PRINT,
                        RequestCodeEnum.START_PAGE_PRINT,
                        RequestCodeEnum.SET_DIMENSION,
                        RequestCodeEnum.SET_QUANTITY,
                        RequestCodeEnum.ALLOW_PRINT_CLEAR,
                    }
                )
                self.assertEqual(codes[-1], RequestCodeEnum.END_PRINT)

    async def test_explicit_variant_keeps_recipe_when_connect_probe_is_missing(
        self,
    ) -> None:
        client = _client("d11_v1")
        with patch("catlabel.vendors.niimbot.client.logger.warning") as warning:
            calls, _writes = await self._run_print(
                client,
                RasterBuffer([0] * 96, width=96),
                response_overrides={(RequestCodeEnum.CONNECT, 1): None},
            )
        self.assertEqual(client._resolved_protocol_variant, "d11_v1")
        self.assertIsNone(client._connect_result)
        self.assertTrue(
            any("unverified" in str(call) for call in warning.call_args_list)
        )
        self.assertIn(
            (int(RequestCodeEnum.SET_DIMENSION), b"\x00\x01"),
            [(code, data) for code, data, _timeout in calls],
        )

    async def test_explicit_variant_keeps_recipe_when_status_probe_is_short(
        self,
    ) -> None:
        client = _client("d11_v1")
        with patch("catlabel.vendors.niimbot.client.logger.warning") as warning:
            calls, _writes = await self._run_print(
                client,
                RasterBuffer([0] * 96, width=96),
                connect_payload=b"\x03",
                status_payload=b"\x00" * 12,
            )
        self.assertEqual(client._resolved_protocol_variant, "d11_v1")
        self.assertIsNone(client._protocol_version)
        self.assertTrue(
            any("unverified" in str(call) for call in warning.call_args_list)
        )
        self.assertIn(
            (int(RequestCodeEnum.GET_STATUS_DATA), b"\x01"),
            [(code, data) for code, data, _timeout in calls],
        )

    async def test_unknown_variant_fails_before_any_transport_or_raster(self) -> None:
        client = _client("d11_maybe")
        source = Image.new("RGB", (96, 1), "white")
        with self.assertRaises(NiimbotPrintError) as raised:
            await client.print_images([source])
        self.assertEqual(raised.exception.stage, "protocol_variant")
        self.assertFalse(raised.exception.delivery_uncertain)
        self.assertEqual(source.getpixel((0, 0)), (255, 255, 255))
        source.close()

    async def test_probe_fields_reset_on_connect_and_disconnect(self) -> None:
        client = _client("d11_v1")
        client._connect_result = 3
        client._protocol_version = 5
        client._model_id = 0x1234
        client._resolved_protocol_variant = "d110"
        client._arm_page_index_waiter()
        write_characteristic = SimpleNamespace(
            uuid="write-char",
            properties=["write"],
        )
        notify_characteristic = SimpleNamespace(
            uuid="notify-char",
            properties=["notify"],
        )
        fake_ble_client = SimpleNamespace(
            services=[
                SimpleNamespace(
                    uuid="unpreferred-service",
                    characteristics=[write_characteristic, notify_characteristic],
                )
            ],
            is_connected=True,
            connect=AsyncMock(),
            start_notify=AsyncMock(),
            stop_notify=AsyncMock(),
            disconnect=AsyncMock(),
        )
        with (
            patch(
                "catlabel.vendors.niimbot.client.BleakClient",
                return_value=fake_ble_client,
            ),
            patch.object(client, "send_command", new=AsyncMock(return_value=None)),
            patch("catlabel.vendors.niimbot.client.asyncio.sleep", new=_test_sleep),
        ):
            self.assertTrue(await client.connect())

        self.assertIsNone(client._completion_waiter)
        self.assertIsNone(client._connect_result)
        self.assertIsNone(client._protocol_version)
        self.assertIsNone(client._model_id)
        self.assertIsNone(client._resolved_protocol_variant)

        client._connect_result = 3
        client._protocol_version = 5
        client._model_id = 0x1234
        client._resolved_protocol_variant = "d110"
        client._arm_page_index_waiter()
        await client.disconnect()
        self.assertIsNone(client._completion_waiter)
        self.assertIsNone(client._connect_result)
        self.assertIsNone(client._protocol_version)
        self.assertIsNone(client._model_id)
        self.assertIsNone(client._resolved_protocol_variant)

    async def test_required_clear_follows_start_and_precedes_page_start(self) -> None:
        client = _client("d11_v1")
        calls, _writes = await self._run_print(
            client,
            RasterBuffer([0] * 96, width=96),
            connect_payload=b"\x01",
        )
        commands = [(code, data) for code, data, _timeout in calls]
        start = commands.index((RequestCodeEnum.START_PRINT, b"\x01"))
        page_start = commands.index((RequestCodeEnum.START_PAGE_PRINT, b"\x01"))
        clears = [
            index
            for index, item in enumerate(commands)
            if item == (RequestCodeEnum.ALLOW_PRINT_CLEAR, b"\x01")
        ]
        self.assertEqual(len(clears), 2)
        self.assertLess(start, clears[1])
        self.assertLess(clears[1], page_start)
        self.assertEqual(
            commands[start + 1], (RequestCodeEnum.ALLOW_PRINT_CLEAR, b"\x01")
        )

    async def test_dense_96_pixel_row_matches_released_wire_literal(self) -> None:
        client = _client("d11_v1")
        _calls, writes = await self._run_print(
            client,
            RasterBuffer([1] * 96, width=96),
        )
        self.assertEqual(
            writes,
            [bytes.fromhex("55558512000020202001ffffffffffffffffffffffffb6aaaa")],
        )

    async def test_empty_sparse_and_repeated_rows_use_coalesced_row_frames(
        self,
    ) -> None:
        sparse_indexes = {0, 7, 8, 31, 32, 95}
        sparse = [int(index in sparse_indexes) for index in range(96)]
        raster = RasterBuffer([0] * 192 + sparse + sparse, width=96)
        client = _client("d11_v1")
        _calls, writes = await self._run_print(client, raster)
        self.assertEqual(tuple(writes), codec.encode_d_rows(raster))
        self.assertEqual([frame[2] for frame in writes], [0x84, 0x83])
        empty_row = NiimbotPacket.from_bytes(writes[0])
        sparse_row = NiimbotPacket.from_bytes(writes[1])
        self.assertIsNotNone(empty_row)
        self.assertIsNotNone(sparse_row)
        if empty_row is None or sparse_row is None:
            self.fail("codec emitted an invalid NIIMBOT row packet")
        self.assertEqual(empty_row.data, b"\x00\x00\x02")
        self.assertEqual(sparse_row.data[5], 2)

    async def test_d11_page_event_can_arrive_fragmented_before_end_page_ack(
        self,
    ) -> None:
        client = _client("d11_v1")
        calls, writes = await self._run_print(
            client,
            RasterBuffer([0] * 96, width=96),
            completion_at="page_end",
        )
        self.assertEqual(len(writes), 1)
        commands = [code for code, _data, _timeout in calls]
        self.assertLess(
            commands.index(RequestCodeEnum.END_PAGE_PRINT),
            commands.index(
                RequestCodeEnum.END_PRINT,
                commands.index(RequestCodeEnum.END_PAGE_PRINT) + 1,
            ),
        )

    async def test_page_completion_ignores_prearm_wrong_page_and_stale_callbacks(
        self,
    ) -> None:
        client = _client("d11_v1")
        client._begin_print()
        page_one = _frame(0xE0, b"\x00\x01")
        client._on_notify(None, bytearray(page_one))
        await _REAL_SLEEP(0)
        waiter = client._arm_page_index_waiter()
        for payload in (b"", b"\x00", b"\x00\x00", b"\x00\x02"):
            client._on_notify(None, bytearray(_frame(0xE0, payload)))
        await _REAL_SLEEP(0)
        self.assertFalse(waiter.event.is_set())

        client._on_notify(None, bytearray(page_one[:3]))
        client._on_notify(None, bytearray(page_one[3:] + _frame(0xC6, b"\x01")))
        await asyncio.wait_for(waiter.event.wait(), timeout=0.1)

        old_waiter = waiter
        client._on_notify(None, bytearray(page_one))
        client._disarm_page_index_waiter(old_waiter)
        new_waiter = client._arm_page_index_waiter()
        await _REAL_SLEEP(0)
        self.assertFalse(new_waiter.event.is_set())
        client._clear_completion_state()
        client._finish_print()

    async def test_prearm_fragmented_page_event_cannot_complete_new_waiter(
        self,
    ) -> None:
        client = _client("d11_v1")
        client._begin_print()
        page_one = _frame(0xE0, b"\x00\x01")
        client._on_notify(None, bytearray(page_one[:7]))
        waiter = client._arm_page_index_waiter()

        client._on_notify(None, bytearray(page_one[7:]))
        await _REAL_SLEEP(0)

        self.assertFalse(waiter.event.is_set())
        self.assertEqual(client._received_byte_count, len(page_one))
        client._clear_completion_state()
        client._finish_print()

    async def test_fresh_event_after_prearm_fragment_tail_completes_waiter(
        self,
    ) -> None:
        client = _client("d11_v1")
        client._begin_print()
        old_page = _frame(0xE0, b"\x00\x01")
        fresh_page = _frame(0xE0, b"\x00\x01")
        client._on_notify(None, bytearray(old_page[:7]))
        waiter = client._arm_page_index_waiter()

        # The old frame's tail and a complete new frame may share one notify.
        client._on_notify(None, bytearray(old_page[7:] + fresh_page))
        await asyncio.wait_for(waiter.event.wait(), timeout=0.1)
        client._clear_completion_state()
        client._finish_print()

    async def test_prearm_fragmented_device_error_still_wakes_and_fails(self) -> None:
        client = _client("d11_v1")
        client._begin_print()
        error = _frame(0xDB, b"\x06")
        client._on_notify(None, bytearray(error[:7]))
        waiter = client._arm_page_index_waiter()

        client._on_notify(None, bytearray(error[7:]))
        await asyncio.wait_for(waiter.event.wait(), timeout=0.1)
        with self.assertRaisesRegex(RuntimeError, "device error"):
            client._raise_for_print_device_error("completion")
        client._clear_completion_state()
        client._finish_print()

    async def test_prearm_fragment_during_quantity_ack_does_not_end_print(self) -> None:
        client = _client("d11_v1")
        client._completion_timeout = 0.002
        raster = RasterBuffer([0] * 96, width=96)
        page_one = _frame(0xE0, b"\x00\x01")
        calls: list[tuple[int, bytes, float]] = []
        writes: list[bytes] = []

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            payload = bytes(data)
            calls.append((code, payload, timeout))
            if code == RequestCodeEnum.CONNECT:
                return NiimbotPacket(0xC2, b"\x01")
            if code == RequestCodeEnum.GET_INFO:
                return NiimbotPacket(0x48, b"\x12\x34")
            if code == RequestCodeEnum.SET_QUANTITY:
                # The ACK and old page-event prefix share one notification;
                # print_images arms only after this call returns.
                quantity_ack = _frame(0x16, b"\x01")
                client._on_notify(None, bytearray(quantity_ack + page_one[:7]))
            response = _ACK_RESPONSES[RequestCodeEnum(code)]
            return NiimbotPacket(response, b"\x01")

        async def fake_write(data: bytes) -> None:
            writes.append(bytes(data))
            # Finish only the pre-arm frame; the printer reports no fresh event.
            client._on_notify(None, bytearray(page_one[7:]))

        source = Image.new("RGB", (96, 1), "white")
        try:
            with (
                patch.object(client, "send_command", new=fake_send),
                patch.object(client, "write_raw", new=fake_write),
                patch(
                    "catlabel.vendors.niimbot.client.image_to_raster",
                    return_value=raster,
                ),
                patch(
                    "catlabel.vendors.niimbot.client.asyncio.sleep",
                    new=_test_sleep,
                ),
                self.assertRaises(NiimbotPrintError) as raised,
            ):
                await client.print_images([source])
        finally:
            source.close()

        self.assertEqual(raised.exception.stage, "completion")
        self.assertTrue(raised.exception.delivery_uncertain)
        self.assertEqual(len(writes), 1)
        self.assertNotIn(
            (RequestCodeEnum.END_PRINT, b"\x01", 3.0),
            calls,
            "required END_PRINT must wait for a fresh completion event",
        )

    async def test_device_error_wakes_active_completion_waiter_and_sticky_error_wins(
        self,
    ) -> None:
        client = _client("d11_v1")
        client._begin_print()
        waiter = client._arm_page_index_waiter()
        client._on_notify(None, bytearray(_frame(0xDB, b"\x06")))
        await asyncio.wait_for(waiter.event.wait(), timeout=0.1)
        with self.assertRaisesRegex(RuntimeError, "device error"):
            client._raise_for_print_device_error("completion")
        client._clear_completion_state()
        client._finish_print()

    async def test_missing_completion_and_negative_end_page_ack_never_replay_rows(
        self,
    ) -> None:
        for bad_end_page in (False, True):
            with self.subTest(bad_end_page=bad_end_page):
                client = _client("d11_v1")
                client._completion_timeout = 0.002
                raster = RasterBuffer([0] * 96, width=96)
                calls: list[tuple[int, bytes, float]] = []
                writes: list[bytes] = []
                counts: Counter[int] = Counter()

                async def fake_send(
                    req_code,
                    data=b"",
                    timeout=5.0,
                    *,
                    call_log=calls,
                    call_counts=counts,
                    end_page_is_bad=bad_end_page,
                ):
                    code = int(req_code)
                    call_log.append((code, bytes(data), timeout))
                    call_counts[code] += 1
                    if code == RequestCodeEnum.CONNECT:
                        return NiimbotPacket(0xC2, b"\x01")
                    if code == RequestCodeEnum.GET_INFO:
                        return NiimbotPacket(0x48, b"\x12\x34")
                    if code == RequestCodeEnum.END_PAGE_PRINT and end_page_is_bad:
                        return NiimbotPacket(0xE4, b"\x00")
                    response = _ACK_RESPONSES.get(RequestCodeEnum(code))
                    if response is None:
                        raise AssertionError(code)
                    return NiimbotPacket(response, b"\x01")

                async def fake_write(data: bytes, *, sent=writes) -> None:
                    sent.append(data)

                with (
                    patch.object(client, "send_command", new=fake_send),
                    patch.object(client, "write_raw", new=fake_write),
                    patch(
                        "catlabel.vendors.niimbot.client.image_to_raster",
                        return_value=raster,
                    ),
                    patch(
                        "catlabel.vendors.niimbot.client.asyncio.sleep",
                        new=_test_sleep,
                    ),
                    self.assertRaises(NiimbotPrintError) as raised,
                ):
                    await client.print_images([Image.new("RGB", (96, 1), "white")])

                if bad_end_page:
                    self.assertEqual(raised.exception.stage, "end_page")
                else:
                    self.assertEqual(raised.exception.stage, "completion")
                self.assertTrue(raised.exception.delivery_uncertain)
                self.assertEqual(len(writes), 1)
                self.assertEqual(counts[RequestCodeEnum.START_PRINT], 1)

    async def test_device_error_arriving_during_completion_fails_without_replay(
        self,
    ) -> None:
        client = _client("d11_v1")
        raster = RasterBuffer([0] * 96, width=96)
        calls: list[tuple[int, bytes, float]] = []
        writes: list[bytes] = []

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls.append((code, bytes(data), timeout))
            if code == RequestCodeEnum.CONNECT:
                return NiimbotPacket(0xC2, b"\x01")
            if code == RequestCodeEnum.GET_INFO:
                return NiimbotPacket(0x48, b"\x12\x34")
            if code == RequestCodeEnum.END_PAGE_PRINT:
                asyncio.get_running_loop().call_soon(
                    client._on_notify,
                    None,
                    bytearray(_frame(0xDB, b"\x06")),
                )
            response = _ACK_RESPONSES[RequestCodeEnum(code)]
            return NiimbotPacket(response, b"\x01")

        async def fake_write(data: bytes) -> None:
            writes.append(data)

        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fake_write),
            patch(
                "catlabel.vendors.niimbot.client.image_to_raster",
                return_value=raster,
            ),
            patch("catlabel.vendors.niimbot.client.asyncio.sleep", new=_test_sleep),
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await client.print_images([Image.new("RGB", (96, 1), "white")])

        self.assertEqual(raised.exception.stage, "completion")
        self.assertTrue(raised.exception.delivery_uncertain)
        self.assertEqual(len(writes), 1)

    async def test_sticky_device_error_stops_later_encoded_rows(self) -> None:
        client = _client("d11_v1")
        pixels = [0] * 96 + [1] * 96
        raster = RasterBuffer(pixels, width=96)
        writes: list[bytes] = []

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            if code == RequestCodeEnum.CONNECT:
                return NiimbotPacket(0xC2, b"\x01")
            if code == RequestCodeEnum.GET_INFO:
                return NiimbotPacket(0x48, b"\x12\x34")
            return NiimbotPacket(_ACK_RESPONSES[RequestCodeEnum(code)], b"\x01")

        async def fail_after_first_row(data: bytes) -> None:
            writes.append(data)
            if len(writes) == 1:
                client._on_notify(None, bytearray(_frame(0xDB, b"\x06")))

        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fail_after_first_row),
            patch(
                "catlabel.vendors.niimbot.client.image_to_raster",
                return_value=raster,
            ),
            patch("catlabel.vendors.niimbot.client.asyncio.sleep", new=_test_sleep),
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await client.print_images([Image.new("RGB", (96, 2), "white")])
        self.assertEqual(raised.exception.stage, "raster_write")
        self.assertTrue(raised.exception.delivery_uncertain)
        self.assertEqual(len(writes), 1)

    async def test_d110_status_poll_zero_then_one_and_respects_query_deadline(
        self,
    ) -> None:
        client = _client("d110")
        calls, writes = await self._run_print(
            client,
            RasterBuffer([0] * 96, width=96),
            connect_payload=b"\x02",
            status_replies=(b"\x00\x00", b"\x00\x01"),
        )
        poll_calls = [
            (data, timeout)
            for code, data, timeout in calls
            if code == RequestCodeEnum.GET_PRINT_STATUS
        ]
        self.assertEqual(poll_calls[0][0], b"\x01")
        self.assertEqual(poll_calls[1][0], b"\x01")
        self.assertTrue(all(0 < timeout <= 1.0 for _data, timeout in poll_calls))
        self.assertEqual(len(poll_calls), 2)
        self.assertEqual(len(writes), 1)

        timed_client = _client("d110")
        timed_client._completion_timeout = 0.004
        calls2: list[tuple[int, bytes, float]] = []
        writes2: list[bytes] = []

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls2.append((code, bytes(data), timeout))
            if code == RequestCodeEnum.CONNECT:
                return NiimbotPacket(0xC2, b"\x02")
            if code == RequestCodeEnum.GET_INFO:
                return NiimbotPacket(0x48, b"\x12\x34")
            if code == RequestCodeEnum.GET_PRINT_STATUS:
                return NiimbotPacket(0xB3, b"\x00\x00")
            return NiimbotPacket(_ACK_RESPONSES[RequestCodeEnum(code)], b"\x01")

        async def fake_write(data: bytes) -> None:
            writes2.append(data)

        with (
            patch.object(timed_client, "send_command", new=fake_send),
            patch.object(timed_client, "write_raw", new=fake_write),
            patch(
                "catlabel.vendors.niimbot.client.image_to_raster",
                return_value=RasterBuffer([0] * 96, width=96),
            ),
            patch("catlabel.vendors.niimbot.client.asyncio.sleep", new=_test_sleep),
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await timed_client.print_images([Image.new("RGB", (96, 1), "white")])
        self.assertEqual(raised.exception.stage, "completion")
        self.assertTrue(raised.exception.delivery_uncertain)
        self.assertGreaterEqual(
            sum(code == RequestCodeEnum.GET_PRINT_STATUS for code, _data, _ in calls2),
            1,
        )
        self.assertEqual(len(writes2), 1)

    async def test_two_d_labels_advance_on_completion_without_legacy_throttle(
        self,
    ) -> None:
        client = _client("d11_v1")
        raster = RasterBuffer([0] * 96, width=96)
        calls: list[tuple[int, bytes, float]] = []
        writes: list[bytes] = []
        delays: list[float] = []
        counts: Counter[int] = Counter()

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls.append((code, bytes(data), timeout))
            counts[code] += 1
            if code == RequestCodeEnum.CONNECT:
                return NiimbotPacket(0xC2, b"\x01")
            if code == RequestCodeEnum.GET_INFO:
                return NiimbotPacket(0x48, b"\x12\x34")
            return NiimbotPacket(_ACK_RESPONSES[RequestCodeEnum(code)], b"\x01")

        async def fake_write(data: bytes) -> None:
            writes.append(data)
            client._on_notify(None, bytearray(_frame(0xE0, b"\x00\x01")))

        async def record_sleep(delay: float) -> None:
            delays.append(delay)
            if delay < 0.1:
                await _REAL_SLEEP(delay)

        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=fake_write),
            patch(
                "catlabel.vendors.niimbot.client.image_to_raster",
                return_value=raster,
            ),
            patch(
                "catlabel.vendors.niimbot.client.asyncio.sleep",
                new=record_sleep,
            ),
        ):
            await client.print_images(
                [
                    Image.new("RGB", (96, 1), "white"),
                    Image.new("RGB", (96, 1), "white"),
                ]
            )

        self.assertEqual(len(writes), 2)
        end_pages = [
            index
            for index, (code, _data, _timeout) in enumerate(calls)
            if code == RequestCodeEnum.END_PAGE_PRINT
        ]
        page_starts = [
            index
            for index, (code, _data, _timeout) in enumerate(calls)
            if code == RequestCodeEnum.START_PAGE_PRINT
        ]
        self.assertEqual((len(end_pages), len(page_starts)), (2, 2))
        self.assertLess(end_pages[0], page_starts[1])
        self.assertNotIn(2.5, delays)

    async def test_d110_positive_status_ends_page_and_f3_follows_completion(
        self,
    ) -> None:
        client = _client("d110")
        calls, _writes = await self._run_print(
            client,
            RasterBuffer([0] * 96, width=96),
            connect_payload=b"\x02",
        )
        codes = [code for code, _data, _timeout in calls]
        end_page = codes.index(RequestCodeEnum.END_PAGE_PRINT)
        poll = codes.index(RequestCodeEnum.GET_PRINT_STATUS)
        end_print_after_completion = codes.index(
            RequestCodeEnum.END_PRINT,
            end_page + 1,
        )
        self.assertLess(end_page, poll)
        self.assertLess(poll, end_print_after_completion)

    async def test_prepared_image_is_closed_without_closing_caller_image(self) -> None:
        client = _client("d11_v1")
        prepared = Image.new("RGB", (96, 1), "white")
        source = Image.new("RGB", (96, 1), "white")
        with (
            patch.object(client, "_prepare_print_image", return_value=prepared),
            patch(
                "catlabel.vendors.niimbot.client.image_to_raster",
                return_value=RasterBuffer([0] * 96, width=96),
            ),
            patch.object(client, "send_command", new=self._success_send),
            patch.object(client, "write_raw", new=self._completion_write(client)),
            patch("catlabel.vendors.niimbot.client.asyncio.sleep", new=_test_sleep),
            patch.object(prepared, "close", wraps=prepared.close) as close,
        ):
            await client.print_images([source])
            close.assert_called_once()
        self.assertEqual(source.getpixel((0, 0)), (255, 255, 255))
        source.close()

    async def _success_send(self, req_code, data=b"", timeout=5.0):
        code = int(req_code)
        if code == RequestCodeEnum.CONNECT:
            return NiimbotPacket(0xC2, b"\x01")
        if code == RequestCodeEnum.GET_INFO:
            return NiimbotPacket(0x48, b"\x12\x34")
        return NiimbotPacket(_ACK_RESPONSES[RequestCodeEnum(code)], b"\x01")

    def _completion_write(self, client: NiimbotClient):
        async def write(data: bytes) -> None:
            client._on_notify(None, bytearray(_frame(0xE0, b"\x00\x01")))

        return write

    async def test_prepared_image_closes_on_encoder_error_and_caller_image_survives(
        self,
    ) -> None:
        client = _client("d11_v1")
        prepared = Image.new("RGB", (96, 1), "white")
        source = Image.new("RGB", (96, 1), "white")
        with (
            patch.object(client, "_prepare_print_image", return_value=prepared),
            patch(
                "catlabel.vendors.niimbot.client.image_to_raster",
                return_value=RasterBuffer([0] * 96, width=96),
            ),
            patch.object(client, "send_command", new=self._success_send),
            patch(
                "catlabel.vendors.niimbot.client.encode_d_rows",
                side_effect=ValueError("bad raster"),
            ),
            patch("catlabel.vendors.niimbot.client.asyncio.sleep", new=_test_sleep),
            patch.object(prepared, "close", wraps=prepared.close) as close,
            self.assertRaises(NiimbotPrintError) as raised,
        ):
            await client.print_images([source])
        close.assert_called_once()
        self.assertEqual(raised.exception.stage, "raster_prepare")
        self.assertFalse(raised.exception.delivery_uncertain)
        self.assertEqual(source.getpixel((0, 0)), (255, 255, 255))
        source.close()

    async def test_cancellation_during_raster_does_not_replay_or_mask_cleanup(
        self,
    ) -> None:
        client = _client("d11_v1")
        raster = RasterBuffer([0] * 96, width=96)
        calls: list[int] = []
        writes: list[bytes] = []

        async def fake_send(req_code, data=b"", timeout=5.0):
            code = int(req_code)
            calls.append(code)
            if code == RequestCodeEnum.CONNECT:
                return NiimbotPacket(0xC2, b"\x01")
            if code == RequestCodeEnum.GET_INFO:
                return NiimbotPacket(0x48, b"\x12\x34")
            return NiimbotPacket(_ACK_RESPONSES[RequestCodeEnum(code)], b"\x01")

        async def cancel_after_attempt(data: bytes) -> None:
            writes.append(data)
            raise asyncio.CancelledError

        source = Image.new("RGB", (96, 1), "white")
        with (
            patch.object(client, "send_command", new=fake_send),
            patch.object(client, "write_raw", new=cancel_after_attempt),
            patch(
                "catlabel.vendors.niimbot.client.image_to_raster",
                return_value=raster,
            ),
            patch("catlabel.vendors.niimbot.client.asyncio.sleep", new=_test_sleep),
            self.assertRaises(asyncio.CancelledError),
        ):
            await client.print_images([source])
        self.assertEqual(len(writes), 1)
        self.assertEqual(calls.count(RequestCodeEnum.CONNECT), 1)
        self.assertEqual(calls[-1], RequestCodeEnum.END_PRINT)
        self.assertIsNone(client._completion_waiter)
        self.assertEqual(source.getpixel((0, 0)), (255, 255, 255))
        source.close()
