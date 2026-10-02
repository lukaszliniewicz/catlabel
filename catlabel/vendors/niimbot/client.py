import asyncio
import enum
import logging
import struct
import threading
from contextlib import suppress
from dataclasses import dataclass

from bleak import BleakClient
from PIL import Image

from ...core.resource_limits import validate_image_budget
from ...devices import get_ble_transport_profile
from ...protocol.encoding import pack_line
from ...protocol.families.niimbot_core import (
    connect_result,
    encode_d_rows,
    frame,
    model_id,
    protocol_version,
)
from ...protocol.types import PixelFormat
from ...rendering.renderer import image_to_raster
from ..base import BasePrinterClient

# --- Configure robust logging for Niimbot ---
logger = logging.getLogger("NiimbotClient")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - [Niimbot] %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)


class RequestCodeEnum(enum.IntEnum):
    CONNECT = 0xC1
    GET_INFO = 64
    GET_RFID = 26
    HEARTBEAT = 220
    SET_LABEL_TYPE = 35
    SET_LABEL_DENSITY = 33
    SET_PRINT_SPEED = 2
    START_PRINT = 1
    END_PRINT = 243
    START_PAGE_PRINT = 3
    END_PAGE_PRINT = 227
    ALLOW_PRINT_CLEAR = 32
    SET_DIMENSION = 19
    SET_QUANTITY = 21
    GET_PRINT_STATUS = 163
    GET_STATUS_DATA = 0xA5


class InfoEnum(enum.IntEnum):
    DENSITY = 1
    PRINTSPEED = 2
    LABELTYPE = 3
    SOFTVERSION = 9
    BATTERY = 10
    DEVICESERIAL = 11
    HARDVERSION = 12
    MODEL_ID = 8


_STATIC_RESPONSE_CODES: dict[int, frozenset[int]] = {
    RequestCodeEnum.CONNECT: frozenset({0xC2}),
    RequestCodeEnum.HEARTBEAT: frozenset({0xDE, 0xDF, 0xDD, 0xD9}),
    RequestCodeEnum.SET_LABEL_TYPE: frozenset({0x33}),
    RequestCodeEnum.SET_LABEL_DENSITY: frozenset({0x31}),
    RequestCodeEnum.START_PRINT: frozenset({0x02}),
    RequestCodeEnum.END_PRINT: frozenset({0xF4}),
    RequestCodeEnum.START_PAGE_PRINT: frozenset({0x04}),
    RequestCodeEnum.END_PAGE_PRINT: frozenset({0xE4}),
    RequestCodeEnum.ALLOW_PRINT_CLEAR: frozenset({0x30}),
    RequestCodeEnum.SET_DIMENSION: frozenset({0x14}),
    RequestCodeEnum.SET_QUANTITY: frozenset({0x16}),
    RequestCodeEnum.GET_PRINT_STATUS: frozenset({0xB3}),
    RequestCodeEnum.GET_STATUS_DATA: frozenset({0xB5}),
}

_INFO_RESPONSE_CODES: dict[int, int] = {
    InfoEnum.DENSITY: 0x41,
    InfoEnum.PRINTSPEED: 0x42,
    InfoEnum.LABELTYPE: 0x43,
    InfoEnum.SOFTVERSION: 0x49,
    InfoEnum.BATTERY: 0x4A,
    InfoEnum.DEVICESERIAL: 0x4B,
    InfoEnum.HARDVERSION: 0x4C,
    InfoEnum.MODEL_ID: 0x48,
}


def _expected_response_codes(request_code: int, data: bytes) -> frozenset[int]:
    if request_code == RequestCodeEnum.GET_INFO:
        if len(data) != 1:
            raise ValueError("GET_INFO requires one supported subtype byte")
        try:
            return frozenset({_INFO_RESPONSE_CODES[data[0]]})
        except KeyError as exc:
            raise ValueError(f"Unsupported GET_INFO subtype 0x{data[0]:02x}") from exc

    try:
        return _STATIC_RESPONSE_CODES[request_code]
    except KeyError as exc:
        raise ValueError(
            f"No Niimbot response mapping for request 0x{request_code:02x}"
        ) from exc


def _is_device_error(packet: "NiimbotPacket | None") -> bool:
    return packet is not None and packet.type in {0x00, 0xDB}


def _device_error_message(packet: "NiimbotPacket", stage: str) -> str:
    if packet.type == 0x00:
        return (
            f"Printer reported unsupported feature (0x00, data={packet.data.hex()}) "
            f"during {stage}."
        )
    return (
        f"Printer returned device error (0xDB, data={packet.data.hex()}) "
        f"during {stage}."
    )


class NiimbotPrintError(RuntimeError):
    def __init__(
        self,
        stage: str,
        delivery_uncertain: bool,
        message: str | None = None,
    ) -> None:
        self.stage = stage
        self.delivery_uncertain = delivery_uncertain
        super().__init__(message or f"Niimbot print failed during {stage}.")


class NiimbotPacket:
    def __init__(self, type_: int, data: bytes) -> None:
        self.type = int(type_)
        self.data = bytes(data)

    @classmethod
    def from_bytes(cls, pkt: bytes) -> "NiimbotPacket | None":
        if len(pkt) < 7 or pkt[:2] != b"\x55\x55" or pkt[-2:] != b"\xaa\xaa":
            return None
        type_ = pkt[2]
        length = pkt[3]
        if len(pkt) != length + 7:
            return None
        data = pkt[4 : 4 + length]

        checksum = type_ ^ length
        for value in data:
            checksum ^= value

        if checksum != pkt[-3]:
            logger.warning(
                f"Packet checksum mismatch! Expected {pkt[-3]}, got {checksum}"
            )
            return None
        return cls(type_, data)

    def to_bytes(self) -> bytes:
        return frame(self.type, self.data)


@dataclass
class _PageIndexWaiter:
    event: asyncio.Event
    loop: asyncio.AbstractEventLoop
    generation: int
    receive_offset: int


class NiimbotClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings) -> None:
        super().__init__(device, hardware_info, printer_profile, settings)
        self.client: BleakClient | None = None
        self.notify_uuid: str | None = None
        self.write_uuid: str | None = None
        self._write_with_response = False
        self._buffer = bytearray()
        self._received_byte_count = 0
        self._events: dict[int, tuple[asyncio.Event, asyncio.AbstractEventLoop]] = {}
        self._expected_responses: dict[int, frozenset[int]] = {}
        self._responses: dict[int, NiimbotPacket] = {}
        self._command_lock = asyncio.Lock()
        self._print_state_lock = threading.Lock()
        self._print_active = False
        self._print_device_error: NiimbotPacket | None = None
        self._completion_waiter: _PageIndexWaiter | None = None
        self._completion_generation = 0
        self._completion_timeout = 5.0
        self._completion_poll_interval = 0.3
        self._completion_query_timeout = 1.0
        self._connect_result: int | None = None
        self._protocol_version: int | None = None
        self._model_id: int | None = None
        self._resolved_protocol_variant: str | None = None
        self._ble_profile = get_ble_transport_profile("niimbot")

    def _clear_protocol_state(self) -> None:
        self._clear_completion_state()
        self._connect_result = None
        self._protocol_version = None
        self._model_id = None
        self._resolved_protocol_variant = None

    def _clear_completion_state(self) -> None:
        self._completion_generation += 1
        self._completion_waiter = None

    def _arm_page_index_waiter(self) -> _PageIndexWaiter:
        self._completion_generation += 1
        waiter = _PageIndexWaiter(
            asyncio.Event(),
            asyncio.get_running_loop(),
            self._completion_generation,
            self._received_byte_count,
        )
        self._completion_waiter = waiter
        return waiter

    def _disarm_page_index_waiter(self, waiter: _PageIndexWaiter) -> None:
        if self._completion_waiter is waiter:
            self._completion_generation += 1
            self._completion_waiter = None

    def _publish_page_index(
        self,
        waiter: _PageIndexWaiter,
        generation: int,
        packet: NiimbotPacket,
    ) -> None:
        if (
            self._completion_waiter is not waiter
            or self._completion_generation != generation
            or waiter.generation != generation
        ):
            return
        if _is_device_error(packet):
            waiter.event.set()
            return
        if (
            packet.type == 0xE0
            and len(packet.data) >= 2
            and int.from_bytes(packet.data[:2], byteorder="big") == 1
        ):
            waiter.event.set()

    def _begin_print(self) -> None:
        with self._print_state_lock:
            self._print_device_error = None
            self._print_active = True

    def _finish_print(self) -> None:
        with self._print_state_lock:
            self._print_active = False
            self._print_device_error = None

    def _raise_for_print_device_error(self, stage: str) -> None:
        with self._print_state_lock:
            packet = self._print_device_error if self._print_active else None
        if packet is not None:
            raise RuntimeError(_device_error_message(packet, stage))

    def _publish_response(
        self,
        req_code: int,
        packet: NiimbotPacket,
        expected_event: asyncio.Event,
    ) -> None:
        event_data = self._events.get(req_code)
        if event_data is None or event_data[0] is not expected_event:
            return
        current_response = self._responses.get(req_code)
        if current_response is not None and _is_device_error(current_response):
            return
        self._responses[req_code] = packet
        expected_event.set()

    def _on_notify(self, sender, payload: bytearray) -> None:
        """Route raw Bleak notification packets back onto the waiting asyncio loop safely."""
        self._buffer.extend(payload)
        self._received_byte_count += len(payload)

        while True:
            start = self._buffer.find(b"\x55\x55")
            if start == -1:
                if self._buffer.endswith(b"\x55"):
                    self._buffer[:] = b"\x55"
                else:
                    self._buffer.clear()
                return
            if start > 0:
                del self._buffer[:start]

            if len(self._buffer) < 7:
                return

            length = self._buffer[3]
            total_length = length + 7
            if len(self._buffer) < total_length:
                return

            if self._buffer[total_length - 2 : total_length] != b"\xaa\xaa":
                del self._buffer[:2]
                continue

            # Exclude a frame that began before its page waiter was armed.
            packet_start_offset = self._received_byte_count - len(self._buffer)
            packet_bytes = bytes(self._buffer[:total_length])
            del self._buffer[:total_length]

            packet = NiimbotPacket.from_bytes(packet_bytes)
            if packet is None:
                continue

            if _is_device_error(packet):
                with self._print_state_lock:
                    if self._print_active and self._print_device_error is None:
                        self._print_device_error = packet

            if _is_device_error(packet) or packet.type == 0xE0:
                waiter = self._completion_waiter
                is_new_page_event = (
                    packet.type == 0xE0
                    and waiter is not None
                    and packet_start_offset >= waiter.receive_offset
                )
                if (
                    waiter is not None
                    and not waiter.loop.is_closed()
                    and (_is_device_error(packet) or is_new_page_event)
                ):
                    waiter.loop.call_soon_threadsafe(
                        self._publish_page_index,
                        waiter,
                        waiter.generation,
                        packet,
                    )

            matched_req_code = next(
                (
                    req_code
                    for req_code, response_codes in self._expected_responses.items()
                    if packet.type in response_codes
                ),
                None,
            )
            if _is_device_error(packet) and self._events:
                matched_req_code = next(iter(self._events))

            if matched_req_code is None:
                logger.debug(
                    f"Unsolicited packet received: type={packet.type}, data={packet.data.hex()}"
                )
                continue

            event_data = self._events.get(matched_req_code)
            if event_data is None:
                continue

            event, loop = event_data
            if loop.is_closed():
                continue

            loop.call_soon_threadsafe(
                self._publish_response,
                matched_req_code,
                packet,
                event,
            )

    async def connect(self) -> bool:
        self._clear_protocol_state()
        self._buffer.clear()
        self._received_byte_count = 0
        self._events.clear()
        self._expected_responses.clear()
        self._responses.clear()
        self._write_with_response = False

        address = self.device.address
        if hasattr(self.device, "ble_endpoint") and self.device.ble_endpoint:
            address = self.device.ble_endpoint.address

        logger.info(f"Attempting native BLE connection to {address}...")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.client = BleakClient(address)
                await self.client.connect(timeout=10.0)

                self.notify_uuid = None
                self.write_uuid = None
                self._write_with_response = False

                PREFERRED_COMBINED = ["bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"]
                PREFERRED_WRITE = ["49535343-8841-43f4-a8d4-ecbe34729bb3"]
                PREFERRED_NOTIFY = ["49535343-1e4d-4bd9-ba61-23c647249616"]

                preferred_service_uuid = (
                    self._ble_profile.preferred_service_uuid.lower()
                )
                for service in self.client.services:
                    if str(service.uuid).lower() != preferred_service_uuid:
                        continue
                    for char in service.characteristics:
                        props = {str(value).lower() for value in char.properties}
                        if self.write_uuid is None and (
                            "write" in props or "write-without-response" in props
                        ):
                            self.write_uuid = char.uuid
                        if self.notify_uuid is None and (
                            "notify" in props or "indicate" in props
                        ):
                            self.notify_uuid = char.uuid

                for service in self.client.services:
                    for char in service.characteristics:
                        uuid_str = str(char.uuid).lower()
                        if uuid_str in PREFERRED_COMBINED and not (
                            self.write_uuid and self.notify_uuid
                        ):
                            self.write_uuid = char.uuid
                            self.notify_uuid = char.uuid
                        elif uuid_str in PREFERRED_WRITE and self.write_uuid is None:
                            self.write_uuid = char.uuid
                        elif uuid_str in PREFERRED_NOTIFY and self.notify_uuid is None:
                            self.notify_uuid = char.uuid

                if not self.write_uuid or not self.notify_uuid:
                    for service in self.client.services:
                        for char in service.characteristics:
                            uuid_str = str(char.uuid).lower()
                            props = char.properties

                            # Skip the Air Patch which breaks normal communication
                            if "aca3-481c-91ec-d85e28a60318" in uuid_str:
                                continue

                            if not self.write_uuid and (
                                "write" in props or "write-without-response" in props
                            ):
                                self.write_uuid = char.uuid
                            if not self.notify_uuid and (
                                "notify" in props or "indicate" in props
                            ):
                                self.notify_uuid = char.uuid

                if not self.write_uuid or not self.notify_uuid:
                    raise RuntimeError(
                        "Could not find valid TX/RX characteristics for Niimbot."
                    )
                self._write_with_response = self._selected_write_requires_response()

                logger.debug(
                    f"Bound to RX (notify): {self.notify_uuid} | TX (write): {self.write_uuid}"
                )
                await self.client.start_notify(self.notify_uuid, self._on_notify)

                logger.info("Executing initial hardware handshake...")
                await self.send_command(RequestCodeEnum.HEARTBEAT, b"\x01", timeout=1.0)
                await self.send_command(
                    RequestCodeEnum.GET_INFO,
                    bytes([InfoEnum.DEVICESERIAL.value]),
                    timeout=1.0,
                )

                logger.info("Connected successfully.")
                return True
            except Exception as exc:
                logger.warning(f"Connection attempt {attempt + 1} failed: {exc}")
                self.last_error = exc
                if self.client and self.client.is_connected:
                    with suppress(BaseException):
                        await self.client.disconnect()
                self.client = None
                self.notify_uuid = None
                self.write_uuid = None
                self._write_with_response = False
                await asyncio.sleep(1.5)

        logger.error("All connection attempts failed.")
        return False

    async def disconnect(self) -> None:
        try:
            logger.info("Disconnecting...")
            if self.client and self.client.is_connected:
                if self.notify_uuid is not None:
                    with suppress(BaseException):
                        await self.client.stop_notify(self.notify_uuid)
                await self.client.disconnect()
        finally:
            self.client = None
            self.notify_uuid = None
            self.write_uuid = None
            self._write_with_response = False
            self._buffer.clear()
            self._received_byte_count = 0
            self._events.clear()
            self._expected_responses.clear()
            self._responses.clear()
            self._finish_print()
            self._clear_protocol_state()

    async def send_command(
        self,
        req_code: int,
        data: bytes = b"",
        timeout: float = 5.0,
    ) -> NiimbotPacket | None:
        request_code = int(req_code)
        payload = bytes(data)
        response_codes = _expected_response_codes(request_code, payload)
        packet = NiimbotPacket(request_code, payload)

        async with self._command_lock:
            loop = asyncio.get_running_loop()
            event = asyncio.Event()
            self._responses.pop(request_code, None)
            self._events[request_code] = (event, loop)
            self._expected_responses[request_code] = response_codes

            logger.debug(f"Sending cmd {request_code} (payload: {payload.hex()})")
            try:
                await self.write_raw(packet.to_bytes())
                try:
                    await asyncio.wait_for(event.wait(), timeout)
                except TimeoutError:
                    logger.warning(f"Cmd {request_code} TIMED OUT after {timeout}s.")
                    return None

                response = self._responses.pop(request_code, None)
                logger.debug(
                    f"Cmd {request_code} ACK'd. Response: "
                    f"{response.data.hex() if response else 'None'}"
                )
                return response
            finally:
                current = self._events.get(request_code)
                if current is not None and current[0] is event:
                    self._events.pop(request_code, None)
                    self._expected_responses.pop(request_code, None)

    def _selected_write_requires_response(self) -> bool:
        if self.client is None or self.write_uuid is None:
            return False

        selected_uuid = str(self.write_uuid).lower()
        for service in self.client.services:
            for characteristic in service.characteristics:
                if str(characteristic.uuid).lower() != selected_uuid:
                    continue
                properties = {
                    str(property_name).lower()
                    for property_name in characteristic.properties
                }
                return (
                    "write" in properties and "write-without-response" not in properties
                )
        return False

    async def write_raw(self, data: bytes) -> None:
        client = self.client
        write_uuid = self.write_uuid
        if not client or not client.is_connected or not write_uuid:
            raise RuntimeError("BLE client disconnected during write.")

        chunk_size = self._ble_profile.standard_chunk_cap
        delay_seconds = self._ble_profile.standard_write_delay_ms / 1000.0
        for i in range(0, len(data), chunk_size):
            chunk = data[i : i + chunk_size]
            self._raise_for_print_device_error("gatt_write")
            await client.write_gatt_char(
                write_uuid,
                chunk,
                response=self._write_with_response,
            )
            self._raise_for_print_device_error("gatt_write")
            if delay_seconds:
                await asyncio.sleep(delay_seconds)

    def _prepare_print_image(
        self, image: Image.Image, print_width_px: int
    ) -> Image.Image:
        working = image.copy()
        try:
            # Only scale down if the user somehow generated a label wider than the
            # absolute physical maximum of the printhead (e.g., > 120px for D11).
            if working.width > print_width_px:
                ratio = print_width_px / float(working.width)
                new_height = max(1, int(working.height * ratio))
                resized = working.resize(
                    (print_width_px, new_height), Image.Resampling.LANCZOS
                )
                working.close()
                working = resized

            # Firmware centers by RFID tape width; padding is only for byte packing.
            remainder = working.width % 8
            if remainder != 0:
                new_width = working.width + (8 - remainder)
                padded = Image.new("RGB", (new_width, working.height), "white")
                try:
                    padded.paste(working, (0, 0))
                except Exception:
                    padded.close()
                    raise
                working.close()
                working = padded

            converted = working.convert("RGB")
            if converted is not working:
                working.close()
            return converted
        except Exception:
            with suppress(Exception):
                working.close()
            raise

    def validate_images(
        self,
        images: list[Image.Image],
        split_mode: bool = False,
    ) -> int:
        planned_labels = super().validate_images(images, split_mode)
        print_width_px = max(1, int(self.hardware_info.get("width_px", 120) or 120))

        output_pixels = 0
        for image in images:
            if image.width > print_width_px:
                output_width = print_width_px
                output_height = max(
                    1,
                    int(image.height * print_width_px / float(image.width)),
                )
            else:
                output_width = image.width
                output_height = image.height

            padded_width = ((output_width + 7) // 8) * 8
            output_pixels = validate_image_budget(
                padded_width,
                output_height,
                output_pixels,
            )
        return planned_labels

    def _require_positive_ack(
        self,
        request_code: int,
        request_data: bytes,
        packet: NiimbotPacket | None,
        stage: str,
        delivery_uncertain: bool,
    ) -> None:
        expected_codes = _expected_response_codes(request_code, request_data)
        if packet is not None and _is_device_error(packet):
            message = _device_error_message(packet, stage)
        elif packet is None:
            message = f"Printer did not acknowledge {stage}."
        elif packet.type not in expected_codes:
            message = (
                f"Printer returned response 0x{packet.type:02x} instead of "
                f"an expected response for {stage}."
            )
        elif packet.data != b"\x01":
            message = (
                f"Printer returned an invalid {stage} response: {packet.data.hex()}."
            )
        else:
            return

        raise NiimbotPrintError(stage, delivery_uncertain, message)

    async def _send_required_ack(
        self,
        request_code: RequestCodeEnum,
        request_data: bytes,
        timeout: float,
        stage: str,
        delivery_uncertain: bool,
    ) -> None:
        self._raise_for_print_device_error(stage)
        packet = await self.send_command(request_code, request_data, timeout=timeout)
        self._raise_for_print_device_error(stage)
        self._require_positive_ack(
            request_code,
            request_data,
            packet,
            stage,
            delivery_uncertain,
        )

    async def _send_reset_command(
        self,
        request_code: RequestCodeEnum,
        stage: str,
        delivery_uncertain: bool,
    ) -> None:
        self._raise_for_print_device_error(stage)
        packet = await self.send_command(request_code, b"\x01", timeout=1.0)
        self._raise_for_print_device_error(stage)
        if packet is not None and _is_device_error(packet):
            raise NiimbotPrintError(
                stage,
                delivery_uncertain,
                _device_error_message(packet, stage),
            )

    async def _wait_for_end_page_ack(self, timeout: float = 15.0) -> None:
        logger.debug("Waiting for END_PAGE_PRINT acknowledgment...")
        await self._send_required_ack(
            RequestCodeEnum.END_PAGE_PRINT,
            b"\x01",
            timeout,
            "end_page",
            True,
        )

    def _configured_d_variant(self) -> str | None:
        variant = self.hardware_info.get("protocol_variant")
        if variant is None or variant == "":
            return None
        if isinstance(variant, str) and variant in {
            "d11_auto",
            "d11_v1",
            "d110",
        }:
            return variant
        raise NiimbotPrintError(
            "protocol_variant",
            False,
            f"Unsupported NIIMBOT protocol variant: {variant!r}.",
        )

    async def _query_model_id(self) -> None:
        try:
            packet = await self.send_command(
                RequestCodeEnum.GET_INFO,
                bytes((InfoEnum.MODEL_ID.value,)),
                timeout=1.0,
            )
        except Exception as exc:
            self._raise_for_print_device_error("protocol_probe")
            logger.warning("NIIMBOT model ID probe failed: %s", exc)
            return

        self._raise_for_print_device_error("protocol_probe")
        if packet is not None and packet.type == 0x48:
            self._model_id = model_id(packet.data)
        if self._model_id is None:
            logger.warning("NIIMBOT model ID probe returned no valid model ID.")

    async def _probe_d_variant(self, configured_variant: str) -> str:
        self._connect_result = None
        self._protocol_version = None
        self._model_id = None
        self._resolved_protocol_variant = None
        failure: str | None = None

        try:
            connect_packet = await self.send_command(
                RequestCodeEnum.CONNECT,
                b"\x01",
                timeout=1.0,
            )
        except Exception as exc:
            self._raise_for_print_device_error("protocol_probe")
            connect_packet = None
            failure = f"CONNECT query failed: {exc}"

        self._raise_for_print_device_error("protocol_probe")
        if failure is None:
            result = (
                connect_result(connect_packet.data)
                if connect_packet is not None and connect_packet.type == 0xC2
                else None
            )
            if result is None:
                failure = "CONNECT returned no recognized connect result"
            else:
                self._connect_result = result
                if result == 1:
                    self._protocol_version = 0
                elif result == 2:
                    self._protocol_version = 1
                else:
                    try:
                        status_packet = await self.send_command(
                            RequestCodeEnum.GET_STATUS_DATA,
                            b"\x01",
                            timeout=1.0,
                        )
                    except Exception as exc:
                        self._raise_for_print_device_error("protocol_probe")
                        status_packet = None
                        failure = f"status-data query failed: {exc}"

                    self._raise_for_print_device_error("protocol_probe")
                    if failure is None:
                        if (
                            status_packet is None
                            or status_packet.type != 0xB5
                            or len(status_packet.data) < 13
                        ):
                            failure = "status-data response is missing or too short"
                        else:
                            # The pinned parser maps short payloads to version 0. This
                            # local adapter requires bytes 11-12 before auto-selecting,
                            # so a truncated B5 response cannot silently choose a recipe.
                            self._protocol_version = protocol_version(
                                status_packet.data
                            )
                await self._query_model_id()

        if failure is not None:
            if configured_variant == "d11_auto":
                raise NiimbotPrintError(
                    "protocol_probe",
                    False,
                    f"Could not resolve NIIMBOT D11 protocol: {failure}.",
                )
            logger.warning(
                "NIIMBOT %s protocol probe is unverified (%s); keeping the configured variant.",
                configured_variant,
                failure,
            )
            resolved_variant = configured_variant
        elif configured_variant == "d11_auto":
            if self._protocol_version is None:
                raise NiimbotPrintError(
                    "protocol_probe",
                    False,
                    "NIIMBOT D11 protocol version is unavailable.",
                )
            resolved_variant = "d110" if self._protocol_version in (1, 2) else "d11_v1"
        else:
            resolved_variant = configured_variant

        self._resolved_protocol_variant = resolved_variant
        logger.debug(
            "NIIMBOT D probe: connect_result=%s protocol_version=%s model_id=%s configured_variant=%s resolved_variant=%s",
            self._connect_result,
            self._protocol_version,
            self._model_id,
            configured_variant,
            resolved_variant,
        )
        return resolved_variant

    async def _wait_for_page_index(
        self,
        waiter: _PageIndexWaiter,
        *,
        variant: str,
    ) -> None:
        deadline = waiter.loop.time() + self._completion_timeout
        if variant == "d11_v1":
            remaining = deadline - waiter.loop.time()
            try:
                await asyncio.wait_for(waiter.event.wait(), timeout=remaining)
            except TimeoutError as exc:
                raise NiimbotPrintError(
                    "completion",
                    True,
                    "Printer did not report D11 page completion.",
                ) from exc
            self._raise_for_print_device_error("completion")
            return

        while True:
            self._raise_for_print_device_error("completion")
            remaining = deadline - waiter.loop.time()
            if remaining <= 0:
                raise NiimbotPrintError(
                    "completion",
                    True,
                    "Printer did not report D110 page completion before the deadline.",
                )

            try:
                packet = await self.send_command(
                    RequestCodeEnum.GET_PRINT_STATUS,
                    b"\x01",
                    timeout=min(self._completion_query_timeout, remaining),
                )
            except Exception as exc:
                self._raise_for_print_device_error("completion")
                raise NiimbotPrintError(
                    "completion",
                    True,
                    f"D110 completion status query failed: {exc}",
                ) from exc

            self._raise_for_print_device_error("completion")
            if (
                packet is not None
                and packet.type == 0xB3
                and len(packet.data) >= 2
                and int.from_bytes(packet.data[:2], byteorder="big") >= 1
            ):
                return

            remaining = deadline - waiter.loop.time()
            if remaining <= 0:
                raise NiimbotPrintError(
                    "completion",
                    True,
                    "Printer did not report D110 page completion before the deadline.",
                )
            await asyncio.sleep(min(self._completion_poll_interval, remaining))

    async def _print_d_label(
        self,
        image: Image.Image,
        print_width_px: int,
        density: int,
        label_type: int,
        variant: str,
        dither: bool,
        raster_write_attempted: bool,
    ) -> bool:
        current_stage = "reset_end_print"
        prepared: Image.Image | None = None
        waiter: _PageIndexWaiter | None = None
        attempted = raster_write_attempted
        try:
            # Transaction ordering follows TiMini-Print v0.8.1's D11/D110 recipe
            # (Apache-2.0; commit f676917257b5d1f869e0f13beff03785258e2a2e).
            await self._send_reset_command(
                RequestCodeEnum.END_PRINT,
                current_stage,
                attempted,
            )
            current_stage = "reset_clear"
            await self._send_reset_command(
                RequestCodeEnum.ALLOW_PRINT_CLEAR,
                current_stage,
                attempted,
            )

            current_stage = "set_label_density"
            await self._send_required_ack(
                RequestCodeEnum.SET_LABEL_DENSITY,
                bytes((density,)),
                timeout=1.0,
                stage=current_stage,
                delivery_uncertain=attempted,
            )
            current_stage = "set_label_type"
            await self._send_required_ack(
                RequestCodeEnum.SET_LABEL_TYPE,
                bytes((label_type,)),
                timeout=1.0,
                stage=current_stage,
                delivery_uncertain=attempted,
            )
            current_stage = "start_print"
            await self._send_required_ack(
                RequestCodeEnum.START_PRINT,
                b"\x01",
                timeout=2.0,
                stage=current_stage,
                delivery_uncertain=attempted,
            )
            current_stage = "page_clear"
            await self._send_required_ack(
                RequestCodeEnum.ALLOW_PRINT_CLEAR,
                b"\x01",
                timeout=1.0,
                stage=current_stage,
                delivery_uncertain=attempted,
            )

            current_stage = "raster_prepare"
            prepared = self._prepare_print_image(image, print_width_px)
            raster = image_to_raster(prepared, PixelFormat.BW1, dither=dither)
            encoded_rows = encode_d_rows(raster)

            current_stage = "start_page_print"
            await self._send_required_ack(
                RequestCodeEnum.START_PAGE_PRINT,
                b"\x01",
                timeout=2.0,
                stage=current_stage,
                delivery_uncertain=attempted,
            )
            current_stage = "set_dimension"
            dimension_data = (
                struct.pack(">H", raster.height)
                if variant == "d11_v1"
                else struct.pack(">HH", raster.height, raster.width)
            )
            await self._send_required_ack(
                RequestCodeEnum.SET_DIMENSION,
                dimension_data,
                timeout=2.0,
                stage=current_stage,
                delivery_uncertain=attempted,
            )
            current_stage = "set_quantity"
            await self._send_required_ack(
                RequestCodeEnum.SET_QUANTITY,
                struct.pack(">H", 1),
                timeout=2.0,
                stage=current_stage,
                delivery_uncertain=attempted,
            )

            waiter = self._arm_page_index_waiter()
            logger.debug("Streaming %s NIIMBOT D row frame(s)...", len(encoded_rows))
            for encoded_row in encoded_rows:
                current_stage = "raster_write"
                self._raise_for_print_device_error(current_stage)
                attempted = True
                await self.write_raw(encoded_row)

            current_stage = "end_page"
            await self._wait_for_end_page_ack(timeout=15.0)

            current_stage = "completion"
            await self._wait_for_page_index(waiter, variant=variant)

            current_stage = "end_print"
            await self._send_required_ack(
                RequestCodeEnum.END_PRINT,
                b"\x01",
                timeout=3.0,
                stage=current_stage,
                delivery_uncertain=attempted,
            )
            return attempted
        except NiimbotPrintError as exc:
            if attempted:
                exc.delivery_uncertain = True
            raise
        except Exception as exc:
            raise NiimbotPrintError(
                current_stage,
                attempted,
                f"Print failed during {current_stage}: {exc}",
            ) from exc
        finally:
            if waiter is not None:
                self._disarm_page_index_waiter(waiter)
            if prepared is not None:
                with suppress(Exception):
                    prepared.close()

    async def print_images(
        self,
        images: list[Image.Image],
        split_mode: bool = False,
        dither: bool = True,
    ) -> None:
        configured_variant = self._configured_d_variant()
        self.validate_images(images, split_mode)
        self._begin_print()
        raster_write_attempted = False
        current_stage = "print_setup"
        d_variant: str | None = None
        try:
            logger.info(
                f"Starting batch print job for {len(images)} image(s) using independent jobs..."
            )

            default_density = int(self.hardware_info.get("default_energy", 3) or 3)
            max_allowed = max(1, int(self.hardware_info.get("max_density", 5) or 5))
            raw_density = (
                self.printer_profile.energy
                if self.printer_profile and self.printer_profile.energy not in (None, 0)
                else default_density
            )
            density = max(1, min(int(raw_density), max_allowed))

            print_width_px = max(1, int(self.hardware_info.get("width_px", 120) or 120))
            media_type_str = self.hardware_info.get("media_type", "pre-cut")
            label_type = 2 if media_type_str == "continuous" else 1

            if configured_variant is not None:
                current_stage = "protocol_probe"
                d_variant = await self._probe_d_variant(configured_variant)

            for i, image in enumerate(images):
                logger.info(f"--- Printing label {i + 1} of {len(images)} ---")

                if d_variant is not None:
                    raster_write_attempted = await self._print_d_label(
                        image,
                        print_width_px,
                        density,
                        label_type,
                        d_variant,
                        dither,
                        raster_write_attempted,
                    )
                    continue

                # FORCE STATE CLEAR before each label to avoid "Job Full" (Error 06) firmware issues
                current_stage = "reset_end_print"
                await self._send_reset_command(
                    RequestCodeEnum.END_PRINT,
                    current_stage,
                    raster_write_attempted,
                )
                current_stage = "reset_clear"
                await self._send_reset_command(
                    RequestCodeEnum.ALLOW_PRINT_CLEAR,
                    current_stage,
                    raster_write_attempted,
                )

                # Session Setup
                current_stage = "set_label_density"
                await self._send_required_ack(
                    RequestCodeEnum.SET_LABEL_DENSITY,
                    bytes([density]),
                    timeout=1.0,
                    stage=current_stage,
                    delivery_uncertain=raster_write_attempted,
                )
                current_stage = "set_label_type"
                await self._send_required_ack(
                    RequestCodeEnum.SET_LABEL_TYPE,
                    bytes([label_type]),
                    timeout=1.0,
                    stage=current_stage,
                    delivery_uncertain=raster_write_attempted,
                )

                # Start 1-page Job explicitly
                current_stage = "start_print"
                await self._send_required_ack(
                    RequestCodeEnum.START_PRINT,
                    b"\x01",
                    timeout=2.0,
                    stage=current_stage,
                    delivery_uncertain=raster_write_attempted,
                )

                current_stage = "raster_prepare"
                prepared: Image.Image | None = None
                try:
                    prepared = self._prepare_print_image(image, print_width_px)
                    raster = image_to_raster(prepared, PixelFormat.BW1, dither=dither)
                finally:
                    if prepared is not None:
                        with suppress(Exception):
                            prepared.close()
                packed_bytes = pack_line(list(raster.pixels), lsb_first=False)
                width_bytes = (raster.width + 7) // 8

                current_stage = "start_page_print"
                await self._send_required_ack(
                    RequestCodeEnum.START_PAGE_PRINT,
                    b"\x01",
                    timeout=2.0,
                    stage=current_stage,
                    delivery_uncertain=raster_write_attempted,
                )

                current_stage = "set_dimension"
                dimension_data = struct.pack(">HH", raster.height, raster.width)
                await self._send_required_ack(
                    RequestCodeEnum.SET_DIMENSION,
                    dimension_data,
                    timeout=2.0,
                    stage=current_stage,
                    delivery_uncertain=raster_write_attempted,
                )

                current_stage = "set_quantity"
                quantity_data = struct.pack(">H", 1)
                await self._send_required_ack(
                    RequestCodeEnum.SET_QUANTITY,
                    quantity_data,
                    timeout=2.0,
                    stage=current_stage,
                    delivery_uncertain=raster_write_attempted,
                )

                logger.debug(f"Streaming {raster.height} rows of raster data...")
                for y in range(raster.height):
                    line_data = packed_bytes[y * width_bytes : (y + 1) * width_bytes]
                    header = struct.pack(">HBBBB", y, 0, 0, 0, 1)
                    packet = NiimbotPacket(0x85, header + line_data)
                    current_stage = "raster_write"
                    raster_write_attempted = True
                    await self.write_raw(packet.to_bytes())

                    if y % 32 == 0:
                        await asyncio.sleep(0.01)

                logger.debug("Row streaming complete. Waiting for ACK...")
                current_stage = "end_page"
                await self._wait_for_end_page_ack(timeout=15.0)

                logger.info(f"Tearing down print session for label {i + 1}...")
                current_stage = "end_print"
                await self._send_required_ack(
                    RequestCodeEnum.END_PRINT,
                    b"\x01",
                    timeout=3.0,
                    stage=current_stage,
                    delivery_uncertain=raster_write_attempted,
                )

                if i < len(images) - 1:
                    current_stage = "between_labels"
                    logger.debug(
                        "Waiting for physical printer to finish feeding paper before next label..."
                    )
                    # This physically acts as a throttle between single-page jobs so the hardware
                    # doesn't immediately abort the second job with "06" while the print-head is still engaged.
                    await asyncio.sleep(2.5)

        except NiimbotPrintError as exc:
            if raster_write_attempted:
                exc.delivery_uncertain = True
            logger.error(f"Print job FAILED: {exc}")
            raise
        except Exception as exc:
            logger.error(f"Print job FAILED: {exc}")
            raise NiimbotPrintError(
                current_stage,
                raster_write_attempted,
                f"Print failed during {current_stage}: {exc}",
            ) from exc
        finally:
            try:
                logger.info("Cleaning up printer state...")
                try:
                    await self.send_command(
                        RequestCodeEnum.END_PRINT, b"\x01", timeout=1.0
                    )
                except Exception as cleanup_error:
                    logger.debug(
                        f"Best-effort END_PRINT cleanup failed: {cleanup_error}"
                    )
                try:
                    await asyncio.sleep(0.5)
                except Exception as cleanup_error:
                    logger.debug(f"Best-effort cleanup delay failed: {cleanup_error}")
            finally:
                self._clear_completion_state()
                self._finish_print()
