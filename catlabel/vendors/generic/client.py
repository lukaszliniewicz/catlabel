import asyncio
from typing import List

from fastapi import HTTPException
from PIL import Image

from ..base import BasePrinterClient
from .models import PrinterModelRegistry
from ...rendering.renderer import image_to_raster
from ...transport.bluetooth import DeviceInfo, SppBackend
from ...transport.bluetooth.types import DeviceTransport

try:
    from ...protocol._builders import _build_job_from_raster_set
except Exception:  # pragma: no cover
    _build_job_from_raster_set = None

try:
    from ...protocol.types import RasterSet
except Exception:  # pragma: no cover
    RasterSet = None

try:
    from ...protocol.job import build_job_from_raster
except Exception:  # pragma: no cover
    build_job_from_raster = None


def _resolve_runtime_controller(model):
    protocol_family = getattr(model, "protocol_family", None)
    if protocol_family is None:
        return None

    family_val = protocol_family.value if hasattr(protocol_family, "value") else str(protocol_family)
    try:
        if family_val == "v5g":
            from ...printing.runtime.v5g import V5GRuntimeController

            return V5GRuntimeController(
                helper_kind=getattr(model, "runtime_variant", None),
                density_profile_key=getattr(model, "runtime_density_profile_key", None),
                density_profile=None,
            )
        if family_val == "v5x":
            from ...printing.runtime.v5x import V5XRuntimeController

            return V5XRuntimeController()
        if family_val == "v5c":
            from ...printing.runtime.v5c import V5CRuntimeController

            return V5CRuntimeController()
    except Exception:
        return None

    return None


def _build_job_bytes(model, raster, feed_padding: int, image_pipeline, speed: int, energy: int) -> bytes:
    common_kwargs = dict(
        is_text=False,
        speed=speed,
        energy=energy,
        blackening=3,
        lsb_first=not model.a4xii,
        protocol_family=model.protocol_family,
        feed_padding=feed_padding,
        dev_dpi=model.dev_dpi,
        can_print_label=model.can_print_label,
        image_pipeline=image_pipeline,
    )

    if _build_job_from_raster_set is not None and RasterSet is not None and hasattr(RasterSet, "from_single"):
        raster_set = RasterSet.from_single(raster)
        try:
            return _build_job_from_raster_set(
                raster_set=raster_set,
                density=None,
                post_print_feed_count=2,
                **common_kwargs,
            )
        except TypeError:
            try:
                return _build_job_from_raster_set(
                    raster_set=raster_set,
                    density=None,
                    **common_kwargs,
                )
            except TypeError:
                return _build_job_from_raster_set(
                    raster_set=raster_set,
                    **common_kwargs,
                )

    if build_job_from_raster is None:
        raise RuntimeError("Generic print job builder is unavailable")

    return build_job_from_raster(
        raster=raster,
        **common_kwargs,
    )


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

    async def print_images(self, images: List[Image.Image], split_mode: bool = False, dither: bool = True) -> None:
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
        runtime_controller = _resolve_runtime_controller(self.model)

        jobs = []
        total_images = len(final_images)
        for index, img in enumerate(final_images):
            is_last = index == total_images - 1
            current_feed = use_feed if is_last else 0

            raster = image_to_raster(img, pipeline_config.default_format, dither=dither)
            job_bytes = _build_job_bytes(
                self.model,
                raster,
                feed_padding=current_feed,
                image_pipeline=pipeline_config,
                speed=use_speed,
                energy=use_energy,
            )
            jobs.append(job_bytes)

        delay_ms = getattr(self.model, "delay_ms", getattr(self.model, "interval_ms", 0))
        for index, job_bytes in enumerate(jobs):
            await self.backend.write(
                job_bytes,
                chunk_size=128,
                delay_ms=delay_ms,
                runtime_controller=runtime_controller,
            )
            if index < len(jobs) - 1:
                if (index + 1) % 3 == 0:
                    await asyncio.sleep(2.0)
                else:
                    await asyncio.sleep(0.3)
