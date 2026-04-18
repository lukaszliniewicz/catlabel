import asyncio
from typing import List
from fastapi import HTTPException
from PIL import Image

from ..base import BasePrinterClient
from .models import PrinterModelRegistry

from ...protocol._builders import _build_job_from_raster_set
from ...rendering.renderer import image_to_raster
from ...transport.bluetooth import DeviceInfo, SppBackend
from ...transport.bluetooth.types import DeviceTransport
from ...raster import RasterSet

class GenericClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings):
        super().__init__(device, hardware_info, printer_profile, settings)
        self.backend = SppBackend()
        self.registry = PrinterModelRegistry.load()
        
        self.model = (
            getattr(device, "model", None)
            or self.registry.detect_from_device_name(
                getattr(device, "name", ""),
                getattr(device, "address", None),
            )
            or self.registry.get(str(hardware_info.get("model_id") or ""))
        )
        
        if not self.model:
            self.model = self.registry.get("GT01")

    async def connect(self) -> bool:
        attempts = []
        prefer_spp = getattr(self.model, "use_spp", False)
        ordered = [DeviceTransport.CLASSIC, DeviceTransport.BLE] if prefer_spp else [DeviceTransport.BLE, DeviceTransport.CLASSIC]

        for transport in ordered:
            attempts.append(
                DeviceInfo(
                    name=getattr(self.device, "name", "Unknown"),
                    address=self.device.address,
                    paired=getattr(self.device, "paired", None),
                    transport=transport,
                    protocol_family=self.model.protocol_family if self.model else None,
                )
            )

        if not attempts:
            raise HTTPException(status_code=500, detail="No valid connection endpoints found.")

        self.last_error = None
        for _ in range(3):
            try:
                await self.backend.connect_attempts(attempts)
                return True
            except Exception as exc:
                self.last_error = exc
                await self.backend.disconnect()
                await asyncio.sleep(1.5)

        return False

    async def disconnect(self) -> None:
        await self.backend.disconnect()

    async def print_images(self, images: List[Image.Image], split_mode: bool = False, dither: bool = True) -> None:
        if not self.model:
            raise HTTPException(status_code=500, detail="Unable to resolve printer model.")

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

        hardware_default_speed = int(self.hardware_info.get("default_speed", getattr(self.model, "img_print_speed", 0)) or 0)
        hardware_default_energy = int(self.hardware_info.get("default_energy", getattr(self.model, "moderation_energy", 5000) or 5000) or 5000)
        min_allowed_energy = max(1, int(self.hardware_info.get("min_energy", 1) or 1))
        max_allowed_energy = max(min_allowed_energy, int(self.hardware_info.get("max_energy", hardware_default_energy) or hardware_default_energy))
        max_allowed_speed = max(1, int(self.hardware_info.get("max_speed", max(hardware_default_speed, 1)) or max(hardware_default_speed, 1)))

        resolved_speed = self.printer_profile.speed if self.printer_profile and self.printer_profile.speed not in (None, 0) else (self.settings.speed if self.settings.speed > 0 else hardware_default_speed)
        resolved_energy = self.printer_profile.energy if self.printer_profile and self.printer_profile.energy not in (None, 0) else (self.settings.energy if self.settings.energy > 0 else hardware_default_energy)

        use_speed = max(0, min(int(resolved_speed or 0), max_allowed_speed))
        use_energy = max(min_allowed_energy, min(int(resolved_energy or hardware_default_energy), max_allowed_energy))
        use_feed = self.printer_profile.feed_lines if self.printer_profile and self.printer_profile.feed_lines is not None else self.settings.feed_lines

        runtime_controller = None
        if hasattr(self.model, "protocol_family"):
            family_val = self.model.protocol_family.value if hasattr(self.model.protocol_family, "value") else str(self.model.protocol_family)
            
            if family_val == "v5g":
                from ...printing.runtime.v5g import V5GRuntimeController
                runtime_controller = V5GRuntimeController(
                    helper_kind=getattr(self.model, "runtime_variant", None),
                    density_profile_key=getattr(self.model, "runtime_density_profile_key", None),
                    density_profile=None 
                )
            elif family_val == "v5x":
                from ...printing.runtime.v5x import V5XRuntimeController
                runtime_controller = V5XRuntimeController()
            elif family_val == "v5c":
                from ...printing.runtime.v5c import V5CRuntimeController
                runtime_controller = V5CRuntimeController()

        jobs = []
        total_images = len(final_images)
        for index, img in enumerate(final_images):
            is_last = index == total_images - 1
            current_feed = use_feed if is_last else 0

            raster = image_to_raster(img, pipeline_config.default_format, dither=dither)
            raster_set = RasterSet.from_single(raster)
            
            job_bytes = _build_job_from_raster_set(
                raster_set=raster_set,
                is_text=False,
                speed=use_speed,
                energy=use_energy,
                density=None,
                blackening=3,
                lsb_first=not self.model.a4xii,
                protocol_family=self.model.protocol_family,
                feed_padding=current_feed,
                dev_dpi=self.model.dev_dpi,
                can_print_label=self.model.can_print_label,
                post_print_feed_count=2,
                image_pipeline=pipeline_config,
            )
            jobs.append(job_bytes)

        delay_ms = getattr(self.model, "interval_ms", getattr(self.model, "delay_ms", 0))
        for index, job_bytes in enumerate(jobs):
            await self.backend.write(job_bytes, chunk_size=128, interval_ms=delay_ms)

            if index < len(jobs) - 1:
                await asyncio.sleep(0.05)
