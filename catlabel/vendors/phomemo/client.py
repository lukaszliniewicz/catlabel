import asyncio
from typing import List

from fastapi import HTTPException
from PIL import Image

from ..base import BasePrinterClient
from .protocol import CMD, D_CMD, M02_CMD, M04_CMD, M110_CMD, P12_CMD, TSPL, density_to_heat_time
from .raster import render_to_raster

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # pragma: no cover - optional runtime dependency
    BleakClient = None
    BleakScanner = None


class PhomemoClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings):
        super().__init__(device, hardware_info, printer_profile, settings)
        self.ble_client = None
        self.write_uuid = None
        self.write_uuids = [
            "0000ff02-0000-1000-8000-00805f9b34fb",
            "0000ae01-0000-1000-8000-00805f9b34fb",
            "49535343-8841-43f4-a8d4-ecbe34729bb3",
            "0000ffe1-0000-1000-8000-00805f9b34fb",
        ]

    async def connect(self) -> bool:
        if BleakClient is None or BleakScanner is None:
            raise HTTPException(
                status_code=501,
                detail="Phomemo printing requires the 'bleak' package to be installed.",
            )

        address = self.device.address
        if hasattr(self.device, "ble_endpoint") and self.device.ble_endpoint:
            address = self.device.ble_endpoint.address

        scanned_device = await BleakScanner.find_device_by_address(address, timeout=5.0)
        self.ble_client = BleakClient(scanned_device if scanned_device else address)

        try:
            await self.ble_client.connect()
            services = getattr(self.ble_client, "services", None)
            if not services:
                get_services = getattr(self.ble_client, "get_services", None)
                if callable(get_services):
                    services = await get_services()

            if not services:
                raise RuntimeError("No BLE services found on the Phomemo printer.")

            for service in services:
                for char in service.characteristics:
                    char_uuid = str(char.uuid).lower()
                    props = {str(prop).lower() for prop in char.properties}
                    if char_uuid in self.write_uuids and (
                        "write" in props or "write-without-response" in props
                    ):
                        self.write_uuid = char.uuid
                        return True

            for service in services:
                for char in service.characteristics:
                    props = {str(prop).lower() for prop in char.properties}
                    if "write" in props or "write-without-response" in props:
                        self.write_uuid = char.uuid
                        return True

            raise RuntimeError("No writable BLE characteristic found for the Phomemo printer.")
        except Exception as exc:
            self.last_error = exc
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        if self.ble_client and self.ble_client.is_connected:
            await self.ble_client.disconnect()

    async def _send(self, data: bytes) -> None:
        if not self.ble_client or not self.ble_client.is_connected:
            raise RuntimeError("Printer disconnected during print job.")
        await self.ble_client.write_gatt_char(self.write_uuid, data)

    async def print_images(self, images: List[Image.Image], split_mode: bool = False) -> None:
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
                await self._print_tspl(working_image, width_bytes, density)
            elif "p12" in protocol:
                await self._print_p12(working_image)
            elif protocol.split("_")[-1] == "d":
                await self._print_d_series(working_image, density)
            elif "m02" in protocol:
                await self._print_m02(working_image, width_bytes, density)
            elif "m04" in protocol:
                await self._print_m04(working_image, width_bytes, density, feed)
            elif "m110" in protocol:
                await self._print_m110(working_image, width_bytes, density)
            else:
                await self._print_m_series(working_image, width_bytes, density, feed)

    async def _print_m_series(
        self,
        img: Image.Image,
        width_bytes: int,
        density: int,
        feed: int,
    ) -> None:
        raster_data, packed_width_bytes, height_lines = render_to_raster(img, width_bytes)

        await self._send(CMD.INIT)
        await asyncio.sleep(0.1)
        await self._send(CMD.HEAT_SETTINGS(7, density_to_heat_time(density), 2))
        await asyncio.sleep(0.05)
        await self._send(CMD.RASTER_HEADER(packed_width_bytes, height_lines))
        await self._send_chunked(raster_data, 128, 0.02)
        await asyncio.sleep(0.3)
        await self._send(CMD.FEED(feed))
        await asyncio.sleep(0.5)

    async def _print_m02(self, img: Image.Image, width_bytes: int, density: int) -> None:
        raster_data, packed_width_bytes, height_lines = render_to_raster(img, width_bytes)

        await self._send(M02_CMD.PREFIX)
        await asyncio.sleep(0.05)
        await self._send(CMD.INIT)
        await asyncio.sleep(0.1)
        await self._send(CMD.HEAT_SETTINGS(7, density_to_heat_time(density), 2))
        await asyncio.sleep(0.05)
        await self._send(CMD.RASTER_HEADER(packed_width_bytes, height_lines))
        await self._send_chunked(raster_data, 128, 0.02)
        await asyncio.sleep(0.3)
        await self._send(CMD.FEED(8))
        await asyncio.sleep(0.5)

    async def _print_m04(
        self,
        img: Image.Image,
        width_bytes: int,
        density: int,
        feed: int,
    ) -> None:
        raster_data, packed_width_bytes, height_lines = render_to_raster(img, width_bytes)
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
        await self._send_chunked(raster_data, 256, 0.02)
        await asyncio.sleep(0.3)

        feed_count = max(1, round(feed / 16))
        for _ in range(feed_count):
            await self._send(M04_CMD.FEED)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

    async def _print_m110(self, img: Image.Image, width_bytes: int, density: int) -> None:
        raster_data, packed_width_bytes, height_lines = render_to_raster(img, width_bytes)
        m110_density = round(5 + density * 1.25)

        await self._send(M110_CMD.SPEED(5))
        await asyncio.sleep(0.05)
        await self._send(M110_CMD.DENSITY(m110_density))
        await asyncio.sleep(0.05)
        await self._send(M110_CMD.MEDIA_TYPE(10))
        await asyncio.sleep(0.05)
        await self._send(CMD.RASTER_HEADER(packed_width_bytes, height_lines))
        await self._send_chunked(raster_data, 128, 0.02)
        await asyncio.sleep(0.3)
        await self._send(M110_CMD.FOOTER)
        await asyncio.sleep(0.5)

    async def _print_d_series(self, img: Image.Image, density: int) -> None:
        raster_data, packed_width_bytes, height_lines = render_to_raster(
            img,
            0,
            rotate_cw=True,
        )

        await self._send(CMD.HEAT_SETTINGS(7, density_to_heat_time(density), 2))
        await asyncio.sleep(0.05)
        await self._send(D_CMD.HEADER(packed_width_bytes, height_lines))
        await self._send_chunked(raster_data, 128, 0.02)
        await asyncio.sleep(0.1)
        await self._send(D_CMD.END)

    async def _print_p12(self, img: Image.Image) -> None:
        raster_data, packed_width_bytes, height_lines = render_to_raster(
            img,
            0,
            rotate_cw=True,
        )

        for packet in P12_CMD.INIT_SEQUENCE:
            await self._send(packet)
            await asyncio.sleep(0.1)

        await self._send(P12_CMD.HEADER(packed_width_bytes, height_lines))
        await self._send_chunked(raster_data, 128, 0.02)
        await asyncio.sleep(0.1)
        await self._send(P12_CMD.FEED)
        await asyncio.sleep(0.05)
        await self._send(P12_CMD.FEED)

    async def _print_tspl(self, img: Image.Image, width_bytes: int, density: int) -> None:
        raster_data, packed_width_bytes, height_lines = render_to_raster(
            img,
            width_bytes,
            invert=True,
        )

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
        await self._send_chunked(raster_data, 512, 0.01)
        await self._send(b"\r\n")
        await asyncio.sleep(0.05)
        await self._send(TSPL.PRINT(1))
        await asyncio.sleep(0.05)
        await self._send(TSPL.END)

    async def _send_chunked(self, data: bytes, chunk_size: int, delay: float) -> None:
        for index in range(0, len(data), chunk_size):
            chunk = data[index:index + chunk_size]
            await self._send(chunk)
            await asyncio.sleep(delay)
