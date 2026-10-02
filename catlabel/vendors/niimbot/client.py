import asyncio
import enum
import logging
import struct
import threading
from contextlib import suppress

from bleak import BleakClient
from PIL import Image

from ...core.resource_limits import validate_image_budget
from ...devices import get_ble_transport_profile
from ...protocol.encoding import pack_line
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


class InfoEnum(enum.IntEnum):
    DENSITY = 1
    PRINTSPEED = 2
    LABELTYPE = 3
    SOFTVERSION = 9
    BATTERY = 10
    DEVICESERIAL = 11
    HARDVERSION = 12


_STATIC_RESPONSE_CODES: dict[int, frozenset[int]] = {
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
}

_INFO_RESPONSE_CODES: dict[int, int] = {
    InfoEnum.DENSITY: 0x41,
    InfoEnum.PRINTSPEED: 0x42,
    InfoEnum.LABELTYPE: 0x43,
    InfoEnum.SOFTVERSION: 0x49,
    InfoEnum.BATTERY: 0x4A,
    InfoEnum.DEVICESERIAL: 0x4B,
    InfoEnum.HARDVERSION: 0x4C,
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
        checksum = self.type ^ len(self.data)
        for value in self.data:
            checksum ^= value
        return bytes(
            (0x55, 0x55, self.type, len(self.data), *self.data, checksum, 0xAA, 0xAA)
        )


class NiimbotClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings) -> None:
        super().__init__(device, hardware_info, printer_profile, settings)
        self.client: BleakClient | None = None
        self.notify_uuid: str | None = None
        self.write_uuid: str | None = None
        self._write_with_response = False
        self._buffer = bytearray()
        self._events: dict[int, tuple[asyncio.Event, asyncio.AbstractEventLoop]] = {}
        self._expected_responses: dict[int, frozenset[int]] = {}
        self._responses: dict[int, NiimbotPacket] = {}
        self._command_lock = asyncio.Lock()
        self._print_state_lock = threading.Lock()
        self._print_active = False
        self._print_device_error: NiimbotPacket | None = None
        self._ble_profile = get_ble_transport_profile("niimbot")

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

            packet_bytes = bytes(self._buffer[:total_length])
            del self._buffer[:total_length]

            packet = NiimbotPacket.from_bytes(packet_bytes)
            if packet is None:
                continue

            if _is_device_error(packet):
                with self._print_state_lock:
                    if self._print_active and self._print_device_error is None:
                        self._print_device_error = packet

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
        self._buffer.clear()
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
            self._events.clear()
            self._expected_responses.clear()
            self._responses.clear()
            self._finish_print()

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

        # Only scale down if the user somehow generated a label wider than the absolute
        # physical maximum of the printhead (e.g., > 120px for D11).
        if working.width > print_width_px:
            ratio = print_width_px / float(working.width)
            new_height = max(1, int(working.height * ratio))
            working = working.resize(
                (print_width_px, new_height), Image.Resampling.LANCZOS
            )

        # CRITICAL FIX: Do NOT pad to print_width_px to center it.
        # Niimbot firmware auto-centers based on the RFID tape width and SET_DIMENSION.
        # We only need to pad slightly to ensure the width is a multiple of 8 for byte packing.
        remainder = working.width % 8
        if remainder != 0:
            new_width = working.width + (8 - remainder)
            padded = Image.new("RGB", (new_width, working.height), "white")
            padded.paste(working, (0, 0))
            working = padded

        return working.convert("RGB")

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

    async def print_images(
        self,
        images: list[Image.Image],
        split_mode: bool = False,
        dither: bool = True,
    ) -> None:
        self.validate_images(images, split_mode)
        self._begin_print()
        raster_write_attempted = False
        current_stage = "print_setup"
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

            for i, image in enumerate(images):
                logger.info(f"--- Printing label {i + 1} of {len(images)} ---")

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
                prepared = self._prepare_print_image(image, print_width_px)
                raster = image_to_raster(prepared, PixelFormat.BW1, dither=dither)
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
                self._finish_print()
