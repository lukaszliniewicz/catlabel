import asyncio
import enum
import struct
from typing import Dict, List, Optional, Tuple

from PIL import Image

from ..base import BasePrinterClient
from ...protocol.encoding import pack_line
from ...protocol.types import PixelFormat
from ...rendering.renderer import image_to_raster
from ...transport.bluetooth import DeviceInfo, DeviceTransport, SppBackend


class RequestCodeEnum(enum.IntEnum):
    GET_INFO = 64
    GET_RFID = 26
    HEARTBEAT = 220
    SET_LABEL_TYPE = 35
    SET_LABEL_DENSITY = 33
    START_PRINT = 1
    END_PRINT = 243
    START_PAGE_PRINT = 3
    END_PAGE_PRINT = 227
    ALLOW_PRINT_CLEAR = 32
    SET_DIMENSION = 19
    SET_QUANTITY = 21
    GET_PRINT_STATUS = 163


class NiimbotPacket:
    def __init__(self, type_, data):
        self.type = int(type_)
        self.data = bytes(data)

    @classmethod
    def from_bytes(cls, pkt: bytes) -> Optional["NiimbotPacket"]:
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
            return None
        return cls(type_, data)

    def to_bytes(self) -> bytes:
        checksum = self.type ^ len(self.data)
        for value in self.data:
            checksum ^= value
        return bytes((0x55, 0x55, self.type, len(self.data), *self.data, checksum, 0xAA, 0xAA))


class NiimbotClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings):
        super().__init__(device, hardware_info, printer_profile, settings)
        self.transport = SppBackend()
        self._buffer = bytearray()
        self._events: Dict[int, Tuple[asyncio.Event, asyncio.AbstractEventLoop]] = {}
        self._responses: Dict[int, NiimbotPacket] = {}

    def _publish_response(self, req_code: int, packet: NiimbotPacket) -> None:
        self._responses[req_code] = packet
        event_data = self._events.get(req_code)
        if event_data is None:
            return
        event, _loop = event_data
        event.set()

    def _on_notify(self, payload: bytes) -> None:
        """Route Bleak notification packets back onto the waiting asyncio loop safely."""
        self._buffer.extend(payload)

        while True:
            start = self._buffer.find(b"\x55\x55")
            if start == -1:
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

            # SMART RESPONSE ROUTING (Safely ignore unsolicited status/heartbeats)
            matched_req_code = None
            if packet.type in self._events:
                matched_req_code = packet.type
            elif (packet.type - 1) in self._events:
                # Catch the +1 response offset (e.g. sent 33, received 34)
                matched_req_code = packet.type - 1
            elif len(self._events) == 1 and packet.type not in (220, 163):
                # Fallback: if exactly 1 command is waiting, assume this is its response.
                matched_req_code = list(self._events.keys())[0]

            if matched_req_code is None:
                self._responses[packet.type] = packet
                continue

            event_data = self._events.get(matched_req_code)
            if event_data is None:
                self._responses[matched_req_code] = packet
                continue

            _event, loop = event_data
            if loop.is_closed():
                self._responses[matched_req_code] = packet
                continue

            loop.call_soon_threadsafe(self._publish_response, matched_req_code, packet)

    async def connect(self) -> bool:
        self._buffer.clear()
        self._events.clear()
        self._responses.clear()

        address = self.device.address
        if hasattr(self.device, "ble_endpoint") and self.device.ble_endpoint:
            address = self.device.ble_endpoint.address

        attempts = [
            DeviceInfo(
                name=getattr(self.device, "name", "Niimbot Printer"),
                address=address,
                paired=getattr(self.device, "paired", None),
                transport=DeviceTransport.BLE,
                protocol_family=None,
            )
        ]

        max_retries = 3
        for _ in range(max_retries):
            try:
                await self.transport.connect_attempts(attempts)
                if hasattr(self.transport, "register_notify_callback"):
                    self.transport.register_notify_callback(self._on_notify)
                
                # HANDSHAKE: Wake up the printer/RFID scanner immediately
                await self.send_command(RequestCodeEnum.GET_INFO, bytes([1]), timeout=2.0)
                return True
            except Exception as exc:
                self.last_error = exc
                await asyncio.sleep(1.5)
        return False

    async def disconnect(self) -> None:
        try:
            await self.transport.disconnect()
        finally:
            self._buffer.clear()
            self._events.clear()
            self._responses.clear()

    async def send_command(self, req_code, data=b"", timeout=5.0):
        request_code = int(req_code)
        packet = NiimbotPacket(request_code, data)
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        self._responses.pop(request_code, None)
        self._events[request_code] = (event, loop)

        try:
            await self.transport.write(packet.to_bytes(), chunk_size=128, interval_ms=0)
            await asyncio.wait_for(event.wait(), timeout)
            return self._responses.pop(request_code, None)
        except (asyncio.TimeoutError, Exception):
            return None
        finally:
            current = self._events.get(request_code)
            if current is not None and current[0] is event:
                self._events.pop(request_code, None)

    async def write_raw(self, data: bytes) -> None:
        await self.transport.write(data, chunk_size=128, interval_ms=0)

    def _prepare_print_image(self, image: Image.Image, print_width_px: int) -> Image.Image:
        # Prevent 90 degree rotation squash: CatLabel's frontend natively rotates landscapes to portrait for the print head.
        working = image.copy()

        if working.width > print_width_px:
            ratio = print_width_px / float(working.width)
            new_height = max(1, int(working.height * ratio))
            working = working.resize((print_width_px, new_height), Image.Resampling.LANCZOS)

        if working.width < print_width_px:
            padded = Image.new("RGB", (print_width_px, working.height), "white")
            offset = (print_width_px - working.width) // 2
            padded.paste(working, (offset, 0))
            working = padded

        return working.convert("RGB")

    async def _wait_for_end_page_ack(self, timeout: float = 15.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            packet = await self.send_command(RequestCodeEnum.END_PAGE_PRINT, b"\x01", timeout=2.0)
            if packet and len(packet.data) > 0 and packet.data[0] == 1:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("Timed out waiting for Niimbot END_PAGE_PRINT acknowledgement")
            await asyncio.sleep(0.1)

    async def _wait_for_page_complete(self, expected_page: int, timeout: float = 60.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            status_pkt = await self.send_command(RequestCodeEnum.GET_PRINT_STATUS, b"\x01", timeout=2.0)
            if status_pkt and len(status_pkt.data) >= 2:
                page = struct.unpack(">H", status_pkt.data[:2])[0]
                if page >= expected_page:
                    return
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("Timed out waiting for Niimbot physical print completion.")
            await asyncio.sleep(0.5)

    async def print_images(self, images: List[Image.Image], split_mode: bool = False, dither: bool = True) -> None:
        # Density calculations
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

        try:
            # Session Setup
            await self.send_command(RequestCodeEnum.SET_LABEL_DENSITY, bytes([density]), timeout=1.0)
            await self.send_command(RequestCodeEnum.SET_LABEL_TYPE, bytes([label_type]), timeout=1.0)
            await self.send_command(RequestCodeEnum.START_PRINT, b"\x01", timeout=2.0)

            for image in images:
                prepared = self._prepare_print_image(image, print_width_px)
                raster = image_to_raster(prepared, PixelFormat.BW1, dither=dither)
                packed_bytes = pack_line(raster.pixels, lsb_first=False)
                width_bytes = (raster.width + 7) // 8

                await self.send_command(RequestCodeEnum.START_PAGE_PRINT, b"\x01", timeout=2.0)
                await self.send_command(
                    RequestCodeEnum.SET_DIMENSION,
                    struct.pack(">HH", raster.height, raster.width),
                    timeout=2.0
                )
                await self.send_command(RequestCodeEnum.SET_QUANTITY, struct.pack(">H", 1), timeout=2.0)

                for y in range(raster.height):
                    line_data = packed_bytes[y * width_bytes : (y + 1) * width_bytes]
                    header = struct.pack(">HBBBB", y, 0, 0, 0, 1)
                    packet = NiimbotPacket(0x85, header + line_data)
                    await self.write_raw(packet.to_bytes())
                    await asyncio.sleep(0.01) # Yield to event loop slightly to prevent BLE underruns

                await self._wait_for_end_page_ack(timeout=15.0)

            # Wait for physical completion (Dynamically scaled based on pages)
            await self._wait_for_page_complete(expected_page=len(images), timeout=max(30.0, len(images) * 15.0))

        except Exception as e:
            print(f"Niimbot Print Pipeline Error: {e}")
            raise
        finally:
            # ALWAYS gracefully close the print pipeline even on error so printer doesn't freeze
            await self.send_command(RequestCodeEnum.END_PRINT, b"\x01", timeout=2.0)
            await asyncio.sleep(0.5)