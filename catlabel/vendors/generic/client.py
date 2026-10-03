import asyncio
import threading
from collections.abc import Iterable, Mapping
from contextlib import closing

from fastapi import HTTPException
from PIL import Image

from ... import reporting
from ...devices import get_ble_transport_profile
from ...printing import build_raster_job, send_prepared_job
from ...printing.job_spool import ProtocolJobSpool
from ...printing.runtime.base import PreparedRuntimeContext, RuntimeController
from ...printing.runtime.factory import runtime_controller_for_device
from ...printing.runtime.session import RuntimeConnectionSession
from ...protocol.family import ProtocolFamily
from ...protocol.job import ProtocolJob
from ...protocol.types import ImageEncoding, ImagePipelineConfig, PaperMode
from ...raster import PixelFormat, RasterSet
from ...rendering.paper_layout import (
    PaperImageLayout,
    iter_prepared_paper_images,
    plan_image_layout,
)
from ...rendering.renderer import image_to_raster
from ...transport.bluetooth import DeviceInfo, SppBackend
from ...transport.bluetooth.types import DeviceTransport
from ..base import BasePrinterClient
from .models import PaperPreset, PrinterModelRegistry


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
        self._controller: RuntimeController | None = None
        self._session: RuntimeConnectionSession | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: int | None = None
        self._initialized = False

    @property
    def notify_started(self) -> bool:
        checker = getattr(self._backend, "can_receive_passively", None)
        return bool(checker()) if callable(checker) else False

    async def attach_runtime_controller(
        self, controller, *, timeout: float = 1.0
    ) -> None:
        if not self.notify_started:
            # BLE owns its runtime lifecycle; platform wrappers retain their
            # existing optional attachment route.
            await self._backend.attach_runtime_controller(controller, timeout=timeout)
            return
        if controller is not self._controller:
            controller.adopt_previous(self._controller)
            self._controller = controller
            self._initialized = False
        if self._initialized:
            return
        self._loop = asyncio.get_running_loop()
        self._loop_thread = threading.get_ident()
        session = RuntimeConnectionSession(self, reporter=reporting.DUMMY_REPORTER)
        self._session = session
        self._backend.register_notify_callback(self._handle_classic_notification)
        try:
            await controller.initialize_connection(
                session, mtu_size=self._chunk_size, timeout=timeout
            )
            await controller.after_initialize(session, timeout=timeout)
        except BaseException:
            try:
                await self.stop_runtime_controller()
            except Exception as cleanup_error:
                reporting.DUMMY_REPORTER.debug(
                    short="Runtime cleanup", detail=str(cleanup_error)
                )
            raise
        self._initialized = True

    def _handle_classic_notification(self, payload: bytes) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            raise RuntimeError("Classic runtime event loop is unavailable")
        if threading.get_ident() == self._loop_thread:
            self._dispatch_classic_notification(payload)
            return

        async def dispatch() -> None:
            self._dispatch_classic_notification(payload)

        # The reader must process flow state before evaluating reply waiters.
        # Running controllers on their owning loop also keeps their tasks safe.
        pending = asyncio.run_coroutine_threadsafe(dispatch(), loop)
        try:
            pending.result(timeout=10.0)
        except BaseException:
            pending.cancel()
            raise

    def _dispatch_classic_notification(self, payload: bytes) -> None:
        controller, session = self._controller, self._session
        if controller is not None and session is not None:
            controller.handle_notification(session, payload)

    async def stop_runtime_controller(self) -> None:
        self._backend.register_notify_callback(None)
        controller, session = self._controller, self._session
        self._controller = None
        self._session = None
        self._loop = None
        self._loop_thread = None
        self._initialized = False
        if controller is not None and session is not None:
            await controller.stop(session)

    def set_flow_paused(self, paused: bool, *, payload: bytes = b"") -> None:
        self._backend.set_flow_paused(paused, payload=payload)

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
        controller, session = self._controller, self._session
        if controller is not None and session is not None:
            controller.on_standard_send_started(session)
            data = controller.prepare_standard_payload(session, data)
            controller.track_outgoing_query_status(session, data)
        try:
            await self._backend.write(
                data,
                chunk_size=self._chunk_size,
                delay_ms=self._delay_ms,
            )
        finally:
            if controller is not None and session is not None:
                controller.on_standard_send_finished(session)

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
        self._runtime_connection: _GenericBackendConnection | None = None

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

    def _paper_image_layout(self) -> PaperImageLayout:
        preset = self._selected_paper()
        return PaperImageLayout(
            render_width_px=preset.render_width_px,
            render_height_px=preset.render_height_px,
            rotation_degrees=preset.rotation_degrees,
        )

    def validate_images(
        self,
        images: list[Image.Image],
        split_mode: bool = False,
    ) -> int:
        super().validate_images(images, split_mode)
        return len(
            plan_image_layout(images, self._paper_image_layout(), split_mode=split_mode)
        )

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
            if family is ProtocolFamily.PHOMEMO_ESC:
                # Native/custom Classic bridges differ in passive observation.
                # A connected bridge without replies must not hide a capable BLE
                # fallback, and cannot safely advance a PrintMaster page.
                for attempt in attempts:
                    try:
                        await self.backend.connect_attempts([attempt])
                        if not self.backend.can_wait_for_notification():
                            raise RuntimeError(
                                "PrintMaster transport has no completion observer"
                            )
                        return True
                    except Exception as exc:
                        self.last_error = exc
                        await self.backend.disconnect()
                await asyncio.sleep(1.5)
                continue
            try:
                await self.backend.connect_attempts(attempts)
                return True
            except Exception as exc:
                self.last_error = exc
                await self.backend.disconnect()
                await asyncio.sleep(1.5)

        return False

    async def disconnect(self) -> None:
        connection = self._runtime_connection
        self._runtime_connection = None
        try:
            if connection is not None:
                await connection.stop_runtime_controller()
        finally:
            await self.backend.disconnect()

    async def print_images(
        self,
        images: list[Image.Image],
        split_mode: bool = False,
        dither: bool = True,
    ) -> None:
        total_images = self.validate_images(images, split_mode)
        if not self.model:
            raise HTTPException(
                status_code=500, detail="Unable to resolve printer model."
            )

        selected_paper = self._selected_paper()
        with closing(
            iter_prepared_paper_images(
                images, self._paper_image_layout(), split_mode=split_mode
            )
        ) as final_images:
            await self._print_prepared_images(
                final_images,
                selected_paper,
                dither=dither,
                total_images=total_images,
            )

    async def _print_prepared_images(
        self,
        final_images: Iterable[Image.Image],
        selected_paper: PaperPreset,
        *,
        dither: bool,
        total_images: int,
    ) -> None:
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
        if protocol_family is ProtocolFamily.PHOMEMO_ESC:
            # Cat-printer global speeds have no model-backed meaning here.
            use_speed = 0
        use_blackening = 3
        if (caps.get("density") or {}).get("available"):
            density_caps = caps.get("density") or {}
            density_min = int(density_caps.get("min", 1))
            density_max = int(density_caps.get("max", 5))
            density_default = density_caps.get("default")
            density_override = (
                self.printer_profile.energy
                if self.printer_profile
                and self.printer_profile.energy is not None
                and (
                    self.printer_profile.energy != 0
                    or protocol_family
                    in {ProtocolFamily.LUCK_NORMAL, ProtocolFamily.LUCK_NORMAL_A4}
                )
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

        connection = self._runtime_connection
        if connection is None:
            connection = _GenericBackendConnection(
                self.backend,
                chunk_size=mtu,
                delay_ms=delay_ms,
            )
            self._runtime_connection = connection
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

        paper_mode = (
            PaperMode(selected_paper.paper_mode) if selected_paper.paper_mode else None
        )
        with ProtocolJobSpool() as jobs:
            for index, img in enumerate(final_images):
                is_last = index == total_images - 1
                current_feed = use_feed if is_last else 0

                try:
                    raster = image_to_raster(
                        img, pipeline_config.default_format, dither=dither
                    )
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
                        page_count=total_images,
                        left_padding_pixels=selected_paper.left_padding_px,
                        a4_sheet_max_height=selected_paper.max_height_px,
                        protocol_family=protocol_family,
                        protocol_variant=protocol_variant,
                        runtime_capabilities=runtime_context.capabilities,
                    )
                    jobs.append(job)
                finally:
                    img.close()

                del raster, raster_set, job, img

            for index, job in enumerate(jobs):
                # Completion is only needed after the final page; intermediate
                # pages keep the connection and runtime state live.
                if (
                    index < total_images - 1
                    and job.wait_for_completion
                    and protocol_family is not ProtocolFamily.PHOMEMO_ESC
                ):
                    job = ProtocolJob(payload=job.payload, steps=job.steps)
                await send_prepared_job(
                    self.model,
                    connection,
                    job,
                    timeout=1.0,
                    reporter=reporting.DUMMY_REPORTER,
                    runtime_context=runtime_context,
                )

                if (
                    index < total_images - 1
                    and protocol_family is not ProtocolFamily.PHOMEMO_ESC
                ):
                    await asyncio.sleep(1.5)
