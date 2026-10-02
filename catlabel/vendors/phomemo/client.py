import asyncio

from PIL import Image, ImageOps

from ...core.resource_limits import validate_image_budget
from ...devices import get_ble_transport_profile
from ...protocol.encoding import pack_line
from ...raster import PixelFormat
from ...rendering.renderer import image_to_raster
from ...transport.bluetooth import DeviceInfo, DeviceTransport, SppBackend
from ..base import BasePrinterClient
from .protocol import (
    CMD,
    D_CMD,
    M02_CMD,
    M04_CMD,
    M110_CMD,
    P12_CMD,
    TSPL,
    density_to_heat_time,
)

_BASE_DPI = 203


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
                ble_profile=get_ble_transport_profile("phomemo_esc"),
            )
        ]

        max_retries = 3
        for _ in range(max_retries):
            try:
                await self.transport.connect_attempts(attempts)
                return True
            except Exception as exc:
                self.last_error = exc
                await self.transport.disconnect()
                await asyncio.sleep(1.5)
        return False

    async def disconnect(self) -> None:
        await self.transport.disconnect()

    async def _send(self, data: bytes) -> None:
        await self.transport.write(data, chunk_size=128, interval_ms=20)

    @staticmethod
    def _dpi_scaled_size(width: int, height: int, dpi: int) -> tuple[int, int]:
        if dpi <= _BASE_DPI:
            return width, height
        scale_factor = dpi / float(_BASE_DPI)
        return (
            max(1, int(round(width * scale_factor))),
            max(1, int(round(height * scale_factor))),
        )

    @staticmethod
    def _head_scaled_size(
        width: int,
        height: int,
        print_width_px: int,
    ) -> tuple[int, int]:
        ratio = print_width_px / float(width)
        return print_width_px, max(1, int(round(height * ratio)))

    @staticmethod
    def _rotates_for_protocol(protocol: str) -> bool:
        return "tspl" not in protocol and (
            "p12" in protocol or protocol.split("_")[-1] == "d"
        )

    def validate_images(
        self,
        images: list[Image.Image],
        split_mode: bool = False,
    ) -> int:
        planned_labels = super().validate_images(images, split_mode)
        protocol = str(self.hardware_info.get("protocol_family", "legacy")).lower()
        print_width_px = int(self.hardware_info.get("width_px", 384) or 384)
        dpi = int(self.hardware_info.get("dpi", _BASE_DPI) or _BASE_DPI)
        rotates = self._rotates_for_protocol(protocol)

        dpi_pixels = 0
        output_pixels = 0
        rotated_pixels = 0
        for image in images:
            dpi_width, dpi_height = self._dpi_scaled_size(
                image.width,
                image.height,
                dpi,
            )
            dpi_pixels = validate_image_budget(dpi_width, dpi_height, dpi_pixels)

            output_width = dpi_width
            output_height = dpi_height
            if output_width > print_width_px and not split_mode:
                output_width, output_height = self._head_scaled_size(
                    output_width,
                    output_height,
                    print_width_px,
                )
            output_pixels = validate_image_budget(
                output_width,
                output_height,
                output_pixels,
            )
            if rotates:
                rotated_pixels = validate_image_budget(
                    output_height,
                    output_width,
                    rotated_pixels,
                )

        return planned_labels

    def _render_to_raster(
        self,
        img: Image.Image,
        rotate_cw: bool = False,
        invert: bool = False,
        dither: bool = True,
    ) -> tuple[bytes, int, int]:
        if rotate_cw:
            img = img.rotate(-90, expand=True)
        if invert:
            img = ImageOps.invert(img.convert("L"))
        raster = image_to_raster(img, PixelFormat.BW1, dither=dither)
        width_bytes = (raster.width + 7) // 8
        packed_rows = [
            pack_line(
                list(raster.pixels[row * raster.width : (row + 1) * raster.width]),
                lsb_first=False,
            )
            for row in range(raster.height)
        ]
        return b"".join(packed_rows), width_bytes, raster.height

    async def print_images(
        self, images: list[Image.Image], split_mode: bool = False, dither: bool = True
    ) -> None:
        self.validate_images(images, split_mode)
        protocol = str(self.hardware_info.get("protocol_family", "legacy")).lower()

        hardware_default_energy = int(self.hardware_info.get("default_energy", 6) or 6)
        resolved_energy = (
            self.printer_profile.energy
            if self.printer_profile and self.printer_profile.energy not in (None, 0)
            else (
                self.settings.energy
                if getattr(self.settings, "energy", 0) > 0
                else hardware_default_energy
            )
        )

        hardware_default_feed = int(self.hardware_info.get("default_feed", 32) or 32)
        resolved_feed = (
            self.printer_profile.feed_lines
            if self.printer_profile and self.printer_profile.feed_lines is not None
            else (
                self.settings.feed_lines
                if getattr(self.settings, "feed_lines", None) is not None
                else hardware_default_feed
            )
        )

        density = max(1, min(int(resolved_energy or hardware_default_energy), 8))
        feed = max(0, int(resolved_feed or hardware_default_feed))

        print_width_px = int(self.hardware_info.get("width_px", 384) or 384)
        dpi = int(self.hardware_info.get("dpi", _BASE_DPI) or _BASE_DPI)
        width_bytes = max(1, print_width_px // 8)

        for img in images:
            working_image = img.copy()

            if dpi > _BASE_DPI:
                scaled_width, scaled_height = self._dpi_scaled_size(
                    working_image.width,
                    working_image.height,
                    dpi,
                )
                working_image = working_image.resize(
                    (scaled_width, scaled_height),
                    Image.Resampling.LANCZOS,
                )

            if working_image.width > print_width_px and not split_mode:
                scaled_width, scaled_height = self._head_scaled_size(
                    working_image.width,
                    working_image.height,
                    print_width_px,
                )
                working_image = working_image.resize(
                    (scaled_width, scaled_height),
                    Image.Resampling.LANCZOS,
                )

            if "tspl" in protocol:
                await self._print_tspl(
                    working_image, width_bytes, density, dither=False
                )
            elif "p12" in protocol:
                await self._print_p12(working_image, dither=dither)
            elif protocol.split("_")[-1] == "d":
                await self._print_d_series(working_image, density, dither=dither)
            elif "m02" in protocol:
                await self._print_m02(
                    working_image, width_bytes, density, dither=dither
                )
            elif "m04" in protocol:
                await self._print_m04(
                    working_image, width_bytes, density, feed, dither=dither
                )
            elif "m110" in protocol:
                await self._print_m110(
                    working_image, width_bytes, density, dither=dither
                )
            else:
                await self._print_m_series(
                    working_image, width_bytes, density, feed, dither=dither
                )

    async def _print_m_series(
        self,
        img: Image.Image,
        width_bytes: int,
        density: int,
        feed: int,
        dither: bool = True,
    ) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(
            img, dither=dither
        )
        await self._send(CMD.INIT)
        await asyncio.sleep(0.1)
        await self._send(CMD.HEAT_SETTINGS(7, density_to_heat_time(density), 2))
        await asyncio.sleep(0.05)
        await self._send(CMD.RASTER_HEADER(packed_width_bytes, height_lines))
        await self._send(raster_data)
        await asyncio.sleep(0.3)
        await self._send(CMD.FEED(feed))
        await asyncio.sleep(0.5)

    async def _print_m02(
        self, img: Image.Image, width_bytes: int, density: int, dither: bool = True
    ) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(
            img, dither=dither
        )
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

    async def _print_m04(
        self,
        img: Image.Image,
        width_bytes: int,
        density: int,
        feed: int,
        dither: bool = True,
    ) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(
            img, dither=dither
        )
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

    async def _print_m110(
        self, img: Image.Image, width_bytes: int, density: int, dither: bool = True
    ) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(
            img, dither=dither
        )
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

    async def _print_d_series(
        self, img: Image.Image, density: int, dither: bool = True
    ) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(
            img, rotate_cw=True, dither=dither
        )

        await self._send(CMD.HEAT_SETTINGS(7, density_to_heat_time(density), 2))
        await asyncio.sleep(0.05)
        await self._send(D_CMD.HEADER(packed_width_bytes, height_lines))
        await self._send(raster_data)
        await asyncio.sleep(0.1)
        await self._send(D_CMD.END)

    async def _print_p12(self, img: Image.Image, dither: bool = True) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(
            img, rotate_cw=True, dither=dither
        )

        for packet in P12_CMD.INIT_SEQUENCE:
            await self._send(packet)
            await asyncio.sleep(0.1)

        await self._send(P12_CMD.HEADER(packed_width_bytes, height_lines))
        await self._send(raster_data)
        await asyncio.sleep(0.1)
        await self._send(P12_CMD.FEED)
        await asyncio.sleep(0.05)
        await self._send(P12_CMD.FEED)

    async def _print_tspl(
        self, img: Image.Image, width_bytes: int, density: int, dither: bool = True
    ) -> None:
        raster_data, packed_width_bytes, height_lines = self._render_to_raster(
            img, invert=True, dither=dither
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
        await self._send(raster_data)
        await self._send(b"\r\n")
        await asyncio.sleep(0.05)
        await self._send(TSPL.PRINT(1))
        await asyncio.sleep(0.05)
        await self._send(TSPL.END)
