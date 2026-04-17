import asyncio
from typing import List

from fastapi import HTTPException
from PIL import Image, ImageOps

from ..base import BasePrinterClient
from .protocol import CMD, D_CMD, M02_CMD, M04_CMD, M110_CMD, P12_CMD, TSPL, density_to_heat_time
from ...rendering.renderer import image_to_raster
from ...protocol.encoding import pack_line
from ...transport.bluetooth import SppBackend, DeviceInfo, DeviceTransport
from ...protocol.types import PixelFormat


class PhomemoClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings):
        super().__init__(device, hardware_info, printer_profile, settings)
        self.transport = SppBackend()

    async def connect(self) -> bool:
        address = self.device.address
        if hasattr(self.device, "ble_endpoint") and self.device.ble_endpoint:
            address = self.device.ble_endpoint.address
            
        attempts = [
            DeviceInfo(
                name=getattr(self.device, "name", "Phomemo Printer"),
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

    async def _send(self, data: bytes) -> None:
        await self.transport.write(data, chunk_size=128, interval_ms=20)

    def _render_to_raster(self, img, rotate_cw=False, invert=False, dither=True):
        if rotate_cw:
            img = img.rotate(-90, expand=True)
        if invert:
            img = ImageOps.invert(img.convert("L"))
        raster = image_to_raster(img, PixelFormat.BW1, dither=dither)
        packed_bytes = pack_line(raster.pixels, lsb_first=False)
        return packed_bytes, (raster.width + 7) // 8, raster.height

    async def print_images(self, images: List[Image.Image], split_mode: bool = False, dither: bool = True) -> None:
        protocol = str(self.hardware_info.get("protocol_family", "legacy")).lower()
        density = int(
            self.printer_profile.energy
            if self.printer_profile and self.printer_profile.energy not in (None, 0)
            else 6
        )
        feed = int(
            self.printer_profile.feed_lines
            if self.printer_profile and self.printer_profile.feed_lines is not None
            else 32
        )

        print_width_px = int(self.hardware_info.get("width_px", 384) or 384)
        width_bytes = max(1, print_width_px // 8)

        for img in images:
            working_image = img
            if working_image.width > print_width_px and not split_mode:
                ratio = print_width_px / float(working_image.width)
                new_height = max(1, int(working_image.height * ratio))
                working_image = working_image.resize(
                    (print_width_px, new_height),
                    Image.Resampling.LANCZOS,
                )

            if "tspl" in protocol:
                await self._print_tspl(working_image, width_bytes, density, dither=dither)
            elif "p12" in protocol:
                await self._print_p12(working_image, dither=dither)
            elif protocol.split("_")[-1] == "d":
                await self._print_d_series(working_image, density, dither=dither)
            elif "m02" in protocol:
                await self._print_m02(working_image, width_bytes, density, dither=dither)
            elif "m04" in protocol:
                await self._print_m04(working_image, width_bytes, density, feed, dither=dither)
            elif "m110" in protocol:
                await self._print_m110(working_image, width_bytes, density, dither=dither)
            else:
                await self._print_m_series(working_image, width_bytes, density, feed, dither=dither)

    async def _print_m_series(self, img: Image.Image, width_bytes: int, density: int, feed: int, dither: bool = True) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(img, dither=dither)
        await self._send(CMD.INIT)
        await asyncio.sleep(0.1)
        await self._send(CMD.HEAT_SETTINGS(7, density_to_heat_time(density), 2))
        await asyncio.sleep(0.05)
        await self._send(CMD.RASTER_HEADER(packed_width_bytes, height_lines))
        await self._send(raster_data)
        await asyncio.sleep(0.3)
        await self._send(CMD.FEED(feed))
        await asyncio.sleep(0.5)

    async def _print_m02(self, img: Image.Image, width_bytes: int, density: int, dither: bool = True) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(img, dither=dither)
        await self._send(M02_CMD.PREFIX)
        await asyncio.sleep(0.05)
        await self._send(CMD.INIT)
        await asyncio.sleep(0.1)
        await self._send(CMD.HEAT_SETTINGS(7, density_to_heat_time(density), 2))
        await asyncio.sleep(0.05)
        await self._send(CMD.RASTER_HEADER(packed_width_bytes, height_lines))
        await self._send(raster_data)
        await asyncio.sleep(0.3)
        await self._send(CMD.FEED(8))
        await asyncio.sleep(0.5)

    async def _print_m04(self, img: Image.Image, width_bytes: int, density: int, feed: int, dither: bool = True) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(img, dither=dither)
        m04_density = round((density / 8) * 15)
        m04_heat = round(100 + (density - 1) * 50 / 3)

        await self._send(M04_CMD.DENSITY(m04_density))
        await asyncio.sleep(0.05)
        await self._send(M04_CMD.HEAT(m04_heat))
        await asyncio.sleep(0.05)
        await self._send(M04_CMD.INIT)
        await asyncio.sleep(0.05)
        await self._send(M04_CMD.COMPRESSION(0x00))
        await asyncio.sleep(0.05)
        await self._send(M04_CMD.RASTER_HEADER(packed_width_bytes, height_lines))
        await self._send(raster_data)
        await asyncio.sleep(0.3)

        feed_count = max(1, round(feed / 16))
        for _ in range(feed_count):
            await self._send(M04_CMD.FEED)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

    async def _print_m110(self, img: Image.Image, width_bytes: int, density: int, dither: bool = True) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(img, dither=dither)
        m110_density = round(5 + density * 1.25)

        await self._send(M110_CMD.SPEED(5))
        await asyncio.sleep(0.05)
        await self._send(M110_CMD.DENSITY(m110_density))
        await asyncio.sleep(0.05)
        await self._send(M110_CMD.MEDIA_TYPE(10))
        await asyncio.sleep(0.05)
        await self._send(CMD.RASTER_HEADER(packed_width_bytes, height_lines))
        await self._send(raster_data)
        await asyncio.sleep(0.3)
        await self._send(M110_CMD.FOOTER)
        await asyncio.sleep(0.5)

    async def _print_d_series(self, img: Image.Image, density: int, dither: bool = True) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(img, rotate_cw=True, dither=dither)

        await self._send(CMD.HEAT_SETTINGS(7, density_to_heat_time(density), 2))
        await asyncio.sleep(0.05)
        await self._send(D_CMD.HEADER(packed_width_bytes, height_lines))
        await self._send(raster_data)
        await asyncio.sleep(0.1)
        await self._send(D_CMD.END)

    async def _print_p12(self, img: Image.Image, dither: bool = True) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(img, rotate_cw=True, dither=dither)

        for packet in P12_CMD.INIT_SEQUENCE:
            await self._send(packet)
            await asyncio.sleep(0.1)

        await self._send(P12_CMD.HEADER(packed_width_bytes, height_lines))
        await self._send(raster_data)
        await asyncio.sleep(0.1)
        await self._send(P12_CMD.FEED)
        await asyncio.sleep(0.05)
        await self._send(P12_CMD.FEED)

    async def _print_tspl(self, img: Image.Image, width_bytes: int, density: int, dither: bool = True) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(img, invert=True, dither=dither)

        label_w_mm = round(packed_width_bytes * 8 / 8)
        label_h_mm = round(height_lines / 8)
        tspl_density = round((density / 8) * 15)

        await self._send(TSPL.SIZE(label_w_mm, label_h_mm))
        await asyncio.sleep(0.05)
        await self._send(TSPL.GAP(3))
        await asyncio.sleep(0.05)
        await self._send(TSPL.OFFSET)
        await asyncio.sleep(0.05)
        await self._send(TSPL.DENSITY(tspl_density))
        await asyncio.sleep(0.05)
        await self._send(TSPL.SPEED(4))
        await asyncio.sleep(0.05)
        await self._send(TSPL.DIRECTION(0))
        await asyncio.sleep(0.05)
        await self._send(TSPL.CLS)
        await asyncio.sleep(0.05)
        await self._send(TSPL.BITMAP_HEADER(0, 0, packed_width_bytes, height_lines))
        await self._send(raster_data)
        await self._send(b"\r\n")
        await asyncio.sleep(0.05)
        await self._send(TSPL.PRINT(1))
        await asyncio.sleep(0.05)
        await self._send(TSPL.END)
