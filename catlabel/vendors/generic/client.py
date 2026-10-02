import asyncio
from collections.abc import Mapping

from fastapi import HTTPException
from PIL import Image

from ... import reporting
from ...core.resource_limits import (
    MAX_PRINT_JOBS,
    ResourceLimitError,
    validate_image_budget,
)
from ...devices import get_ble_transport_profile
from ...printing import build_raster_job, send_prepared_job
from ...printing.runtime.base import PreparedRuntimeContext
from ...printing.runtime.factory import runtime_controller_for_device
from ...printing.runtime.session import RuntimeConnectionSession
from ...protocol.family import ProtocolFamily
from ...protocol.job import ProtocolJob
from ...protocol.types import ImageEncoding, ImagePipelineConfig, PaperMode
from ...raster import PixelFormat, RasterSet
from ...rendering.renderer import image_to_raster
from ...transport.bluetooth import DeviceInfo, SppBackend
from ...transport.bluetooth.types import DeviceTransport
from ..base import BasePrinterClient
from .models import PrinterModelRegistry


def _image_density_levels(model) -> Mapping[str, object] | None:
    density = getattr(model, "runtime_density", None) or getattr(
        model, "profile_density", None
    )
    if not isinstance(density, Mapping):
        return None
    image = density.get("image")
    return image if isinstance(image, Mapping) else None


def _blackening_level_for_density(
    density: int,
    levels: Mapping[str, object] | None,
) -> int:
    """Map a raw V5G density override back to upstream's five levels."""

    if levels is None:
        low, middle, high = 50, 100, 150
    else:
        low = _density_level_value(levels, "low", 50)
        middle = _density_level_value(levels, "middle", low)
        high = _density_level_value(levels, "high", middle)

    value = int(density)
    if value == middle:
        return 3
    if value < middle:
        return 1 if value <= low else 2
    return 5 if value >= high else 4


def _density_level_value(
    levels: Mapping[str, object],
    name: str,
    default: int,
) -> int:
    value = levels.get(name, default)
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        raise ValueError(
            f"Invalid image density level {name!r}: expected a numeric value"
        )
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid image density level {name!r}: {value!r} is not an integer"
        ) from exc


def _energy_for_blackening_level(model, level: int, default: int) -> int:
    if level <= 2:
        return int(getattr(model, "thin_energy", default) or default)
    if level >= 4:
        return int(getattr(model, "deepen_energy", default) or default)
    return int(getattr(model, "moderation_energy", default) or default)


class _GenericBackendConnection:
    """Expose SppBackend through the printing runtime connection contract."""

    def __init__(self, backend: SppBackend, *, chunk_size: int, delay_ms: int) -> None:
        self._backend = backend
        self._chunk_size = chunk_size
        self._delay_ms = delay_ms

    async def attach_runtime_controller(
        self, controller, *, timeout: float = 1.0
    ) -> None:
        await self._backend.attach_runtime_controller(controller, timeout=timeout)

    def can_send_control_packet(self) -> bool:
        checker = getattr(self._backend, "can_send_control_packet", None)
        return bool(checker()) if callable(checker) else False

    def can_send_bulk_payload(self) -> bool:
        checker = getattr(self._backend, "can_send_bulk_payload", None)
        return bool(checker()) if callable(checker) else False

    def can_query_control_packet(self) -> bool:
        checker = getattr(self._backend, "can_query_control_packet", None)
        return bool(checker()) if callable(checker) else False

    def can_wait_for_notification(self) -> bool:
        checker = getattr(self._backend, "can_wait_for_notification", None)
        return bool(checker()) if callable(checker) else False

    def can_send_control_packet_wait_notification(self) -> bool:
        checker = getattr(
            self._backend, "can_send_control_packet_wait_notification", None
        )
        return bool(checker()) if callable(checker) else False

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        return await self._backend.send_control_packet(packet, timeout=timeout)

    async def send_bulk_payload(self, data: bytes, *, timeout: float = 1.0) -> bool:
        return await self._backend.send_bulk_payload(data, timeout=timeout)

    async def query_control_packet(self, packet: bytes, **kwargs):
        return await self._backend.query_control_packet(packet, **kwargs)

    async def wait_for_notification(self, label, match, **kwargs):
        return await self._backend.wait_for_notification(label, match, **kwargs)

    async def send_control_packet_wait_notification(self, packet: bytes, **kwargs):
        return await self._backend.send_control_packet_wait_notification(
            packet, **kwargs
        )

    async def send_standard_payload(self, data: bytes) -> None:
        await self._backend.write(
            data,
            chunk_size=self._chunk_size,
            delay_ms=self._delay_ms,
        )

    async def send(self, job: ProtocolJob) -> None:
        if job.steps:
            raise RuntimeError(
                "Interactive jobs must be executed by the printing layer"
            )
        await self.send_standard_payload(job.payload)


class GenericClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings):
        super().__init__(device, hardware_info, printer_profile, settings)
        self.backend = SppBackend()
        self.registry = PrinterModelRegistry.load()
        self.model_match = None
        if not getattr(device, "model", None):
            self.model_match = self.registry.detect_with_origin(
                getattr(device, "name", ""),
                getattr(device, "address", None),
            )

        self.model = (
            getattr(device, "model", None)
            or (self.model_match.model if self.model_match else None)
            or self.registry.get(str(hardware_info.get("model_id") or ""))
        )

        if not self.model:
            self.model = self.registry.get("GT01")
        self._runtime_context = PreparedRuntimeContext()

    def _effective_protocol_family(self):
        if self.model_match is not None:
            return self.model_match.protocol_family
        value = self.hardware_info.get("protocol_family") or getattr(
            self.model, "protocol_family", None
        )
        try:
            return ProtocolFamily.from_value(value)
        except Exception:
            return getattr(self.model, "protocol_family", ProtocolFamily.LEGACY)

    def _effective_protocol_variant(self):
        if self.model_match is not None and self.model_match.protocol_variant:
            return self.model_match.protocol_variant
        return self.hardware_info.get("protocol_variant") or getattr(
            self.model, "protocol_variant", None
        )

    def _effective_image_pipeline(self):
        if self.model is None:
            raise HTTPException(
                status_code=500, detail="Unable to resolve printer model."
            )
        if self.model_match is not None and self.model_match.image_pipeline is not None:
            return self.model_match.image_pipeline
        return self.model.image_pipeline

    def _selected_paper(self):
        if not self.model:
            raise HTTPException(
                status_code=500, detail="Unable to resolve printer model."
            )

        requested_paper_mode = getattr(self.printer_profile, "paper_mode", None)
        return next(
            (
                preset
                for preset in self.model.paper_presets
                if requested_paper_mode and preset.paper_mode == requested_paper_mode
            ),
            self.model.paper_preset(),
        )

    def validate_images(
        self,
        images: list[Image.Image],
        split_mode: bool = False,
    ) -> int:
        super().validate_images(images, split_mode)
        selected_paper = self._selected_paper()
        print_width_px = selected_paper.render_width_px
        validate_image_budget(print_width_px, 1)

        planned_labels = 0
        output_pixels = 0
        for image in images:
            if split_mode and image.width > print_width_px:
                label_count = (image.width + print_width_px - 1) // print_width_px
                output_width = print_width_px
                output_height = image.height
            elif image.width < print_width_px:
                label_count = 1
                output_width = print_width_px
                output_height = image.height
            elif image.width > print_width_px:
                label_count = 1
                output_width = print_width_px
                output_height = max(
                    1,
                    int(image.height * print_width_px / float(image.width)),
                )
            else:
                label_count = 1
                output_width = image.width
                output_height = image.height

            planned_labels += label_count
            if planned_labels > MAX_PRINT_JOBS:
                raise ResourceLimitError(
                    f"Print requires more than {MAX_PRINT_JOBS} label jobs."
                )
            for _ in range(label_count):
                output_pixels = validate_image_budget(
                    output_width,
                    output_height,
                    output_pixels,
                )
        return planned_labels

    async def connect(self) -> bool:
        attempts = []
        prefer_spp = getattr(self.model, "use_spp", False)
        family = self._effective_protocol_family()
        variant = self._effective_protocol_variant()
        if family.value == "funny_lx":
            # Funny LX cannot operate without its BLE notification endpoint.
            ordered = [DeviceTransport.BLE]
        elif family is ProtocolFamily.LUCK_NORMAL and variant in {
            "lujiang_normal",
            "lujiang_normal_h",
        }:
            # Lujiang request/reply is socket based; the BLE adapter has no
            # read characteristic for these models.
            ordered = [DeviceTransport.CLASSIC]
        else:
            ordered = (
                [DeviceTransport.CLASSIC, DeviceTransport.BLE]
                if prefer_spp
                else [DeviceTransport.BLE, DeviceTransport.CLASSIC]
            )

        for transport in ordered:
            attempts.append(
                DeviceInfo(
                    name=getattr(self.device, "name", "Unknown"),
                    address=self.device.address,
                    paired=getattr(self.device, "paired", None),
                    transport=transport,
                    ble_profile=(
                        get_ble_transport_profile(self._effective_protocol_family())
                        if self.model
                        else None
                    ),
                )
            )

        if not attempts:
            raise HTTPException(
                status_code=500, detail="No valid connection endpoints found."
            )

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

    async def print_images(
        self,
        images: list[Image.Image],
        split_mode: bool = False,
        dither: bool = True,
    ) -> None:
        self.validate_images(images, split_mode)
        if not self.model:
            raise HTTPException(
                status_code=500, detail="Unable to resolve printer model."
            )

        selected_paper = self._selected_paper()
        print_width_px = selected_paper.render_width_px
        final_images = []

        for img in images:
            if split_mode and img.width > print_width_px:
                for x in range(0, img.width, print_width_px):
                    strip = img.crop(
                        (x, 0, min(x + print_width_px, img.width), img.height)
                    )
                    if strip.width < print_width_px:
                        padded = Image.new(
                            "RGB", (print_width_px, strip.height), "white"
                        )
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
                        img = img.resize(
                            (print_width_px, new_height), Image.Resampling.LANCZOS
                        )
                final_images.append(img)

        pipeline_config = self._effective_image_pipeline()
        protocol_family = self._effective_protocol_family()
        protocol_variant = self._effective_protocol_variant()

        hardware_default_speed = int(
            self.hardware_info.get(
                "default_speed", getattr(self.model, "img_print_speed", 0)
            )
            or 0
        )
        hardware_default_energy = int(
            self.hardware_info.get(
                "default_energy", getattr(self.model, "moderation_energy", 5000) or 5000
            )
            or 5000
        )
        caps = self.hardware_info.get("capabilities") or {}
        min_allowed_energy = max(1, int(self.hardware_info.get("min_energy", 1) or 1))
        max_allowed_energy = max(
            min_allowed_energy,
            int(
                self.hardware_info.get("max_energy", hardware_default_energy)
                or hardware_default_energy
            ),
        )
        max_allowed_speed = max(
            1,
            int(
                self.hardware_info.get("max_speed", max(hardware_default_speed, 1))
                or max(hardware_default_speed, 1)
            ),
        )

        resolved_speed = (
            self.printer_profile.speed
            if self.printer_profile and self.printer_profile.speed not in (None, 0)
            else (
                self.settings.speed
                if self.settings.speed > 0
                else hardware_default_speed
            )
        )
        resolved_energy = (
            self.printer_profile.energy
            if self.printer_profile and self.printer_profile.energy not in (None, 0)
            else (
                self.settings.energy
                if self.settings.energy > 0
                else hardware_default_energy
            )
        )

        use_speed = max(0, min(int(resolved_speed or 0), max_allowed_speed))
        use_blackening = 3
        if (caps.get("density") or {}).get("available"):
            density_caps = caps.get("density") or {}
            density_min = int(density_caps.get("min", 1))
            density_max = int(density_caps.get("max", 5))
            density_default = density_caps.get("default")
            density_override = (
                self.printer_profile.energy
                if self.printer_profile and self.printer_profile.energy not in (None, 0)
                else None
            )
            density_value = (
                density_override if density_override is not None else density_default
            )
            use_density = (
                None
                if density_value is None
                else max(density_min, min(int(density_value), density_max))
            )
            use_energy = hardware_default_energy
            if protocol_family is ProtocolFamily.V5G and use_density is not None:
                use_blackening = _blackening_level_for_density(
                    use_density,
                    _image_density_levels(self.model),
                )
                use_energy = _energy_for_blackening_level(
                    self.model,
                    use_blackening,
                    hardware_default_energy,
                )
                use_energy = max(
                    min_allowed_energy, min(use_energy, max_allowed_energy)
                )
            elif use_density is not None:
                use_blackening = use_density
        else:
            use_density = None
            use_energy = max(
                min_allowed_energy,
                min(
                    int(resolved_energy or hardware_default_energy), max_allowed_energy
                ),
            )
        use_feed = (
            self.printer_profile.feed_lines
            if self.printer_profile and self.printer_profile.feed_lines is not None
            else self.settings.feed_lines
        )

        delay_ms = getattr(
            self.model, "interval_ms", getattr(self.model, "delay_ms", 4)
        )
        try:
            delay_ms = int(delay_ms or 4)
        except (TypeError, ValueError):
            delay_ms = 4

        try:
            mtu = int(getattr(self.model, "img_mtu", 128) or 128)
        except (TypeError, ValueError):
            mtu = 128
        if mtu <= 0:
            mtu = 128

        runtime_controller = runtime_controller_for_device(
            self.model,
            protocol_family=protocol_family,
            bluetooth_address=getattr(self.device, "address", ""),
        )

        connection = _GenericBackendConnection(
            self.backend,
            chunk_size=mtu,
            delay_ms=delay_ms,
        )
        runtime_context = PreparedRuntimeContext(runtime_controller=runtime_controller)
        if runtime_controller is not None:
            runtime_session = RuntimeConnectionSession(
                connection,
                reporter=reporting.DUMMY_REPORTER,
            )
            await runtime_session.attach_runtime_controller(
                runtime_controller, timeout=1.0
            )
            await runtime_controller.probe_capabilities(runtime_session, timeout=1.0)
            runtime_context = PreparedRuntimeContext(
                runtime_controller=runtime_controller,
                capabilities=runtime_controller.runtime_capabilities(),
            )
        self._runtime_context = runtime_context
        if (
            runtime_context.capabilities is not None
            and runtime_context.capabilities.supports_gray is False
            and pipeline_config.encoding is ImageEncoding.LUCK_NORMAL_GRAY
        ):
            pipeline_config = ImagePipelineConfig(
                formats=(PixelFormat.BW1,),
                encoding=ImageEncoding.LUCK_NORMAL_RAW,
            )

        jobs = []
        total_images = len(final_images)
        paper_mode = (
            PaperMode(selected_paper.paper_mode) if selected_paper.paper_mode else None
        )
        total_pages = len(final_images)
        for index, img in enumerate(final_images):
            is_last = index == total_images - 1
            current_feed = use_feed if is_last else 0

            raster = image_to_raster(img, pipeline_config.default_format, dither=dither)
            raster_set = RasterSet.from_single(raster)

            job = build_raster_job(
                model=self.model,
                raster_set=raster_set,
                is_text=False,
                speed=use_speed,
                energy=use_energy,
                density=use_density,
                blackening=use_blackening,
                feed_padding=current_feed,
                image_pipeline=pipeline_config,
                paper_mode=paper_mode,
                paper_width_pixels=selected_paper.paper_width_px,
                page_index=index + 1,
                page_count=total_pages,
                left_padding_pixels=selected_paper.left_padding_px,
                a4_sheet_max_height=selected_paper.max_height_px,
                protocol_family=protocol_family,
                protocol_variant=protocol_variant,
                runtime_capabilities=runtime_context.capabilities,
            )
            jobs.append(job)

        for index, job in enumerate(jobs):
            # Completion is only needed after the final page; intermediate
            # pages keep the connection and runtime state live.
            if index < len(jobs) - 1 and job.wait_for_completion:
                job = ProtocolJob(payload=job.payload, steps=job.steps)
            await send_prepared_job(
                self.model,
                connection,
                job,
                timeout=1.0,
                reporter=reporting.DUMMY_REPORTER,
                runtime_context=runtime_context,
            )

            if index < len(jobs) - 1:
                await asyncio.sleep(1.5)
