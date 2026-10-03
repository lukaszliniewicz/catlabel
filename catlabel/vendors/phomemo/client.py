import asyncio
from collections.abc import Iterator
from contextlib import ExitStack

from PIL import Image, ImageOps

from ...core.resource_limits import (
    MAX_PRINT_JOBS,
    ResourceLimitError,
    validate_image_budget,
)
from ...devices import get_ble_transport_profile
from ...printing.job_spool import ProtocolJobSpool
from ...protocol.encoding import pack_line
from ...protocol.families.phomemo_esc_core import (
    build_released_page,
    plan_released_raster_size,
)
from ...protocol.job import ProtocolJob
from ...protocol.types import PaperMode
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
        variant = self._released_variant()
        if variant is not None:
            plan_released_raster_size(1, 1, variant=variant)

        address = self.device.address
        ble_endpoint = getattr(self.device, "ble_endpoint", None)
        if ble_endpoint:
            address = ble_endpoint.address

        name = getattr(self.device, "name", "Phomemo Printer")
        paired = getattr(self.device, "paired", None)
        ble_attempt = DeviceInfo(
            name=name,
            address=address,
            paired=paired,
            transport=DeviceTransport.BLE,
            ble_profile=get_ble_transport_profile("phomemo_esc"),
        )
        if variant is None:
            attempts = [ble_attempt]
        else:
            classic_endpoint = getattr(self.device, "classic_endpoint", None)
            classic_address = (
                classic_endpoint.address if classic_endpoint else self.device.address
            )
            attempts = [
                DeviceInfo(
                    name=name,
                    address=classic_address,
                    paired=paired,
                    transport=DeviceTransport.CLASSIC,
                ),
                ble_attempt,
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
        variant = self._released_variant()
        if variant is not None:
            return self._validate_released_images(images, split_mode, variant)

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

    def _released_variant(self) -> str | None:
        value = self.hardware_info.get("protocol_variant")
        if value is None or value == "":
            return None
        return str(value)

    def _released_paper_mode(self) -> PaperMode | None:
        value = getattr(self.printer_profile, "paper_mode", None)
        if value is None:
            return None
        if isinstance(value, PaperMode):
            return value
        aliases = {
            "continuous": PaperMode.PLAIN,
            "pre-cut": PaperMode.TAG,
        }
        text = str(value)
        if text in aliases:
            return aliases[text]
        return PaperMode(text)

    @staticmethod
    def _released_job_count(width: int, head_width: int, split_mode: bool) -> int:
        if split_mode and width > head_width:
            return (width + head_width - 1) // head_width
        return 1

    def _released_job_sizes(
        self,
        width: int,
        height: int,
        head_width: int,
        split_mode: bool,
    ) -> Iterator[tuple[int, int]]:
        if width > head_width:
            if split_mode:
                for left in range(0, width, head_width):
                    yield min(head_width, width - left), height
                return
            yield self._head_scaled_size(width, height, head_width)
            return
        yield width, height

    def _validate_released_images(
        self,
        images: list[Image.Image],
        split_mode: bool,
        variant: str,
    ) -> int:
        head_width = int(self.hardware_info.get("width_px", 384) or 384)
        paper_mode: PaperMode | None = None
        paper_mode_resolved = False
        planned_jobs = 0
        normalized_pixels = 0
        padded_pixels = 0

        for image in images:
            if image.width > head_width and split_mode:
                first_width, first_height = head_width, image.height
            elif image.width > head_width:
                first_width, first_height = self._head_scaled_size(
                    image.width,
                    image.height,
                    head_width,
                )
            else:
                first_width, first_height = image.width, image.height

            # Validate the variant before counting or preparing any image jobs.
            plan_released_raster_size(
                first_width,
                first_height,
                variant=variant,
            )

            if not paper_mode_resolved:
                paper_mode = self._released_paper_mode()
                paper_mode_resolved = True

            image_jobs = self._released_job_count(
                image.width,
                head_width,
                split_mode,
            )
            planned_jobs += image_jobs
            if planned_jobs > MAX_PRINT_JOBS:
                raise ResourceLimitError(
                    f"Print requires more than {MAX_PRINT_JOBS} physical jobs."
                )

            for width, height in self._released_job_sizes(
                image.width,
                image.height,
                head_width,
                split_mode,
            ):
                normalized_pixels = validate_image_budget(
                    width,
                    height,
                    normalized_pixels,
                )
                padded_width, padded_height = plan_released_raster_size(
                    width,
                    height,
                    variant=variant,
                    paper_mode=paper_mode,
                )
                padded_pixels = validate_image_budget(
                    padded_width,
                    padded_height,
                    padded_pixels,
                )

        return planned_jobs

    def _render_to_raster(
        self,
        img: Image.Image,
        rotate_cw: bool = False,
        invert: bool = False,
        dither: bool = True,
    ) -> tuple[bytes, int, int]:
        with ExitStack() as owned_images:
            if rotate_cw:
                img = img.rotate(-90, expand=True)
                owned_images.callback(img.close)
            if invert:
                grayscale_image = img.convert("L")
                owned_images.callback(grayscale_image.close)
                img = ImageOps.invert(grayscale_image)
                owned_images.callback(img.close)
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
        variant = self._released_variant()
        if variant is not None:
            await self._print_released_images(
                images,
                split_mode=split_mode,
                dither=dither,
                variant=variant,
            )
            return

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
            try:
                if dpi > _BASE_DPI:
                    scaled_width, scaled_height = self._dpi_scaled_size(
                        working_image.width,
                        working_image.height,
                        dpi,
                    )
                    previous_image = working_image
                    working_image = previous_image.resize(
                        (scaled_width, scaled_height),
                        Image.Resampling.LANCZOS,
                    )
                    previous_image.close()

                if working_image.width > print_width_px and not split_mode:
                    scaled_width, scaled_height = self._head_scaled_size(
                        working_image.width,
                        working_image.height,
                        print_width_px,
                    )
                    previous_image = working_image
                    working_image = previous_image.resize(
                        (scaled_width, scaled_height),
                        Image.Resampling.LANCZOS,
                    )
                    previous_image.close()

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
            finally:
                working_image.close()

    async def _print_released_images(
        self,
        images: list[Image.Image],
        *,
        split_mode: bool,
        dither: bool,
        variant: str,
    ) -> None:
        head_width = int(self.hardware_info.get("width_px", 384) or 384)
        paper_mode = self._released_paper_mode()

        default_density = 4 if variant == "m02x" else 2
        hardware_density = self.hardware_info.get("default_energy")
        if hardware_density in (None, 0):
            hardware_density = default_density
        profile_density = getattr(self.printer_profile, "energy", None)
        density = int(
            hardware_density if profile_density in (None, 0) else profile_density
        )

        hardware_feed = self.hardware_info.get("default_feed")
        if hardware_feed is None:
            hardware_feed = 0
        profile_feed = getattr(self.printer_profile, "feed_lines", None)
        feed_count = int(hardware_feed if profile_feed is None else profile_feed)

        total_jobs = sum(
            self._released_job_count(image.width, head_width, split_mode)
            for image in images
        )
        page_index = 0

        with ProtocolJobSpool() as spool:
            for image in images:
                working_image = image.copy()
                try:
                    if working_image.width > head_width and not split_mode:
                        scaled_width, scaled_height = self._head_scaled_size(
                            working_image.width,
                            working_image.height,
                            head_width,
                        )
                        resized_image = working_image.resize(
                            (scaled_width, scaled_height),
                            Image.Resampling.LANCZOS,
                        )
                        previous_image = working_image
                        working_image = resized_image
                        previous_image.close()

                    if split_mode and working_image.width > head_width:
                        for left in range(0, working_image.width, head_width):
                            right = min(left + head_width, working_image.width)
                            segment = working_image.crop(
                                (left, 0, right, working_image.height)
                            )
                            try:
                                spool.append(
                                    ProtocolJob(
                                        payload=self._build_released_job(
                                            segment,
                                            variant=variant,
                                            paper_mode=paper_mode,
                                            density=density,
                                            feed_count=feed_count,
                                            is_first_page=page_index == 0,
                                            is_last_page=page_index == total_jobs - 1,
                                            dither=dither,
                                        )
                                    )
                                )
                                page_index += 1
                            finally:
                                segment.close()
                    else:
                        spool.append(
                            ProtocolJob(
                                payload=self._build_released_job(
                                    working_image,
                                    variant=variant,
                                    paper_mode=paper_mode,
                                    density=density,
                                    feed_count=feed_count,
                                    is_first_page=page_index == 0,
                                    is_last_page=page_index == total_jobs - 1,
                                    dither=dither,
                                )
                            )
                        )
                        page_index += 1
                finally:
                    working_image.close()

            await self._send_spooled_pages(spool)

    async def _send_spooled_pages(self, spool: ProtocolJobSpool) -> None:
        chunk_size = 64 * 1024
        buffer = bytearray()

        for job in spool:
            payload = job.payload
            offset = 0
            while offset < len(payload):
                count = min(chunk_size - len(buffer), len(payload) - offset)
                buffer.extend(payload[offset : offset + count])
                offset += count
                if len(buffer) == chunk_size:
                    await self._send(bytes(buffer))
                    buffer.clear()

        if buffer:
            await self._send(bytes(buffer))

    @staticmethod
    def _build_released_job(
        image: Image.Image,
        *,
        variant: str,
        paper_mode: PaperMode | None,
        density: int,
        feed_count: int,
        is_first_page: bool,
        is_last_page: bool,
        dither: bool,
    ) -> bytes:
        raster = image_to_raster(image, PixelFormat.BW1, dither=dither)
        return build_released_page(
            raster,
            variant=variant,
            density=density,
            paper_mode=paper_mode,
            is_first_page=is_first_page,
            is_last_page=is_last_page,
            ends_media_page=True,
            post_print_feed_count=feed_count,
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
