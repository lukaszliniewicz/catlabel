import asyncio
from typing import List

from fastapi import HTTPException
from PIL import Image

from ..base import BasePrinterClient
from ...devices import DeviceResolver, PrinterModelRegistry
from ...protocol.job import build_job_from_raster
from ...rendering.renderer import image_to_raster
from ...transport.bluetooth import SppBackend


class GenericClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings):
        super().__init__(device, hardware_info, printer_profile, settings)
        self.backend = SppBackend()
        self.registry = PrinterModelRegistry.load()
        self.resolver = DeviceResolver(self.registry)
        self.model = (
            getattr(device, "model", None)
            or self.registry.detect_from_device_name(
                getattr(device, "name", ""),
                getattr(device, "address", None),
            )
            or self.registry.get(str(hardware_info.get("model_id") or ""))
        )

    async def connect(self) -> bool:
        attempts = self.resolver.build_connection_attempts(self.device)
        if not attempts:
            raise HTTPException(status_code=500, detail="No valid connection endpoints found.")

        max_retries = 3
        self.last_error = None

        for _ in range(max_retries):
            try:
                await self.backend.connect_attempts(attempts)
                return True
            except Exception as exc:
                self.last_error = exc
                await asyncio.sleep(1.5)

        return False

    async def disconnect(self) -> None:
        await self.backend.disconnect()

    async def print_images(self, images: List[Image.Image], split_mode: bool = False) -> None:
        if not self.model:
            raise HTTPException(
                status_code=500,
                detail="Unable to resolve printer model for generic vendor pipeline.",
            )

        print_width_px = self.hardware_info["width_px"]
        final_images = []

        for img in images:
            if split_mode and img.width > print_width_px:
                for x in range(0, img.width, print_width_px):
                    strip = img.crop((x, 0, min(x + print_width_px, img.width), img.height))
                    if strip.width < print_width_px:
                        padded = Image.new("RGB", (print_width_px, strip.height), "white")
                        padded.paste(strip, (0, 0))
                        strip = padded
                    final_images.append(strip)
            else:
                if img.width != print_width_px:
                    if img.width < print_width_px:
                        padded = Image.new("RGB", (print_width_px, img.height), "white")
                        offset_x = (print_width_px - img.width) // 2
                        padded.paste(img, (offset_x, 0))
                        img = padded
                    else:
                        ratio = print_width_px / float(img.width)
                        new_height = max(1, int(img.height * ratio))
                        img = img.resize((print_width_px, new_height), Image.Resampling.LANCZOS)
                final_images.append(img)

        pipeline_config = self.model.image_pipeline

        hardware_default_speed = int(
            self.hardware_info.get("default_speed", getattr(self.model, "img_print_speed", 0)) or 0
        )
        hardware_default_energy = int(
            self.hardware_info.get(
                "default_energy",
                getattr(self.model, "moderation_energy", 5000) or 5000,
            )
            or 5000
        )
        min_allowed_energy = max(1, int(self.hardware_info.get("min_energy", 1) or 1))
        max_allowed_energy = max(
            min_allowed_energy,
            int(self.hardware_info.get("max_energy", hardware_default_energy) or hardware_default_energy),
        )
        max_allowed_speed = max(
            1,
            int(self.hardware_info.get("max_speed", max(hardware_default_speed, 1)) or max(hardware_default_speed, 1)),
        )

        resolved_speed = (
            self.printer_profile.speed
            if self.printer_profile and self.printer_profile.speed not in (None, 0)
            else (self.settings.speed if self.settings.speed > 0 else hardware_default_speed)
        )
        resolved_energy = (
            self.printer_profile.energy
            if self.printer_profile and self.printer_profile.energy not in (None, 0)
            else (self.settings.energy if self.settings.energy > 0 else hardware_default_energy)
        )

        use_speed = max(0, min(int(resolved_speed or 0), max_allowed_speed))
        use_energy = max(
            min_allowed_energy,
            min(int(resolved_energy or hardware_default_energy), max_allowed_energy),
        )
        use_feed = (
            self.printer_profile.feed_lines
            if self.printer_profile and self.printer_profile.feed_lines is not None
            else self.settings.feed_lines
        )

        jobs = []
        total_images = len(final_images)
        for index, img in enumerate(final_images):
            is_last = index == total_images - 1
            current_feed = use_feed if is_last else 0

            raster = image_to_raster(img, pipeline_config.default_format, dither=True)
            job = build_job_from_raster(
                raster=raster,
                is_text=False,
                speed=use_speed,
                energy=use_energy,
                blackening=3,
                lsb_first=not self.model.a4xii,
                protocol_family=self.model.protocol_family,
                feed_padding=current_feed,
                dev_dpi=self.model.dev_dpi,
                can_print_label=self.model.can_print_label,
                image_pipeline=pipeline_config,
            )
            jobs.append(job)

        interval = getattr(self.model, "interval_ms", 0)
        for index, job in enumerate(jobs):
            await self.backend.write(job, chunk_size=128, interval_ms=interval)
            if index < len(jobs) - 1:
                if (index + 1) % 3 == 0:
                    await asyncio.sleep(2.0)
                else:
                    await asyncio.sleep(0.3)
