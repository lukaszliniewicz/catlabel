import asyncio
import struct
import enum
from typing import List

from PIL import Image, ImageOps

from ..base import BasePrinterClient
from ...rendering.renderer import image_to_raster
from ...protocol.encoding import pack_line
from ...transport.bluetooth import SppBackend, DeviceInfo, DeviceTransport
from ...protocol.types import PixelFormat


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
        self.type = type_
        self.data = data

    def to_bytes(self):
        checksum = self.type ^ len(self.data)
        for i in self.data:
            checksum ^= i
        return bytes((0x55, 0x55, self.type, len(self.data), *self.data, checksum, 0xAA, 0xAA))


class NiimbotClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings):
        super().__init__(device, hardware_info, printer_profile, settings)
        self.transport = SppBackend()

    async def connect(self) -> bool:
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
                return True
            except Exception as exc:
                self.last_error = exc
                await asyncio.sleep(1.5)
        return False

    async def disconnect(self) -> None:
        await self.transport.disconnect()

    async def _send(self, req_code, data=b""):
        packet = NiimbotPacket(req_code, data)
        await self.transport.write(packet.to_bytes(), chunk_size=128, interval_ms=20)

    async def print_images(self, images: List[Image.Image], split_mode: bool = False, dither: bool = True) -> None:
        print_width_px = self.hardware_info["width_px"]
        final_images = []

        for img in images:
            if img.width > print_width_px:
                ratio = print_width_px / float(img.width)
                new_height = max(1, int(img.height * ratio))
                img = img.resize((print_width_px, new_height), Image.Resampling.LANCZOS)
            final_images.append(img)

        default_density = int(self.hardware_info.get("default_energy", 3) or 3)
        max_allowed = max(1, int(self.hardware_info.get("max_density", 5) or 5))
        raw_density = (
            self.printer_profile.energy
            if self.printer_profile and self.printer_profile.energy not in (None, 0)
            else default_density
        )
        density = max(1, min(int(raw_density), max_allowed))

        for img in final_images:
            await self._print_image(img, density=density, quantity=1, dither=dither)
            await asyncio.sleep(1.0)

    async def _print_image(self, image: Image, density: int = 3, quantity: int = 1, dither: bool = True):
        await self._send(RequestCodeEnum.SET_LABEL_DENSITY, bytes((density,)))
        await self._send(RequestCodeEnum.SET_LABEL_TYPE, bytes((1,)))
        await self._send(RequestCodeEnum.START_PRINT, b"\x01")
        await self._send(RequestCodeEnum.START_PAGE_PRINT, b"\x01")
        await self._send(RequestCodeEnum.SET_DIMENSION, struct.pack(">HH", image.height, image.width))
        await self._send(RequestCodeEnum.SET_QUANTITY, struct.pack(">H", quantity))

        img = image.convert("RGB")
        raster = image_to_raster(img, PixelFormat.BW1, dither=dither)
        packed_bytes = pack_line(raster.pixels, lsb_first=False)
        
        width_bytes = (image.width + 7) // 8
        for y in range(image.height):
            line_data = packed_bytes[y*width_bytes : (y+1)*width_bytes]
            counts = (0, 0, 0)
            header = struct.pack(">H3BB", y, *counts, 1)
            await self._send(0x85, header + line_data)

        await self._send(RequestCodeEnum.END_PAGE_PRINT, b"\x01")
        await asyncio.sleep(0.5)
        await self._send(RequestCodeEnum.END_PRINT, b"\x01")
