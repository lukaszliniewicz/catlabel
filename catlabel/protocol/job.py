from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..raster import PixelFormat, RasterSet
from ._builders import _build_job_from_raster_set
from .commands import (
    advance_paper_cmd,
    retract_paper_cmd,
)
from .families import get_protocol_behavior
from .family import ProtocolFamily
from .types import ImageEncoding, ImagePipelineConfig

if TYPE_CHECKING:
    from typing import Any as PrinterDevice
    from ..printing.runtime.base import RuntimeController


@dataclass(frozen=True)
class ProtocolJob:
    """Printable protocol payload plus optional session runtime controller."""

    payload: bytes
    runtime_controller: RuntimeController | None = None


class PrinterProtocol:
    """Build protocol jobs for one resolved ``PrinterDevice``."""

    def __init__(self, device: PrinterDevice) -> None:
        self.device = device

    def create_runtime_controller(self) -> RuntimeController | None:
        """Create the session runtime controller required by this device, if any."""
        from ..printing.runtime.factory import runtime_controller_for_device

        return runtime_controller_for_device(self.device)

    def build_job(
        self,
        raster_set: RasterSet,
        *,
        is_text: bool,
        blackening: int = 3,
        feed_padding: int = 0,
        lsb_first: bool | None = None,
        image_pipeline: ImagePipelineConfig | None = None,
        image_encoding_override: ImageEncoding | None = None,
        pixel_format_override: PixelFormat | None = None,
    ) -> ProtocolJob:
        """Build a printable job from raster input for this device."""
        payload = self._build_payload(
            raster_set,
            is_text=is_text,
            blackening=blackening,
            feed_padding=feed_padding,
            lsb_first=lsb_first,
            image_pipeline=image_pipeline,
            image_encoding_override=image_encoding_override,
            pixel_format_override=pixel_format_override,
        )
        return ProtocolJob(
            payload=payload,
            runtime_controller=self.create_runtime_controller(),
        )

    def build_paper_motion(self, action: str) -> ProtocolJob:
        """Build a feed or retract paper-motion job for this device."""
        if action == "feed":
            payload = advance_paper_cmd(self.device.profile.dev_dpi, self.device.protocol_family)
        elif action == "retract":
            payload = retract_paper_cmd(self.device.profile.dev_dpi, self.device.protocol_family)
        else:
            raise ValueError(f"Unknown paper motion action: {action}")
        return ProtocolJob(payload=payload, runtime_controller=None)

    def resolve_image_pipeline(
        self,
        *,
        image_pipeline: ImagePipelineConfig | None = None,
        image_encoding_override: ImageEncoding | None = None,
        pixel_format_override: PixelFormat | None = None,
    ) -> ImagePipelineConfig:
        """Resolve the effective image pipeline for this job request."""
        behavior = get_protocol_behavior(self.device.protocol_family)
        if image_pipeline is not None:
            pipeline = image_pipeline
        elif self.device.protocol_family == self.device.profile.default_protocol_family:
            pipeline = self.device.image_pipeline
        else:
            pipeline = behavior.default_image_pipeline

        if image_encoding_override is not None:
            pipeline = ImagePipelineConfig(
                formats=pipeline.formats,
                encoding=image_encoding_override,
            )
        supported_formats = behavior.image_encoding_support.get(pipeline.encoding)
        if supported_formats is None:
            raise ValueError(
                f"{self.device.protocol_family.value} does not support image encoding {pipeline.encoding.value}"
            )
        if pixel_format_override is not None:
            if pixel_format_override not in supported_formats:
                raise ValueError(
                    f"{self.device.protocol_family.value} image encoding {pipeline.encoding.value} "
                    f"does not support {pixel_format_override.value}"
                )
            if pixel_format_override in pipeline.formats:
                pipeline = pipeline.with_default_format(pixel_format_override)
            else:
                pipeline = ImagePipelineConfig(
                    formats=(pixel_format_override,) + tuple(
                        value for value in pipeline.formats if value != pixel_format_override
                    ),
                    encoding=pipeline.encoding,
                )
        elif pipeline.default_format not in supported_formats:
            fallback = next((value for value in pipeline.formats if value in supported_formats), None)
            if fallback is not None:
                pipeline = pipeline.with_default_format(fallback)
            else:
                pipeline = ImagePipelineConfig(
                    formats=tuple(supported_formats) + tuple(
                        value for value in pipeline.formats if value not in supported_formats
                    ),
                    encoding=pipeline.encoding,
                )
        return pipeline

    def _resolve_lsb_first(self, override: bool | None) -> bool:
        if override is not None:
            return override
        return not self.device.profile.a4xii

    def _select_density(self, *, is_text: bool, blackening: int) -> int | None:
        return self.device.profile.select_density(
            is_text=is_text,
            blackening=blackening,
        )

    def _build_payload(
        self,
        raster_set: RasterSet,
        *,
        is_text: bool,
        blackening: int,
        feed_padding: int,
        lsb_first: bool | None,
        image_pipeline: ImagePipelineConfig | None,
        image_encoding_override: ImageEncoding | None,
        pixel_format_override: PixelFormat | None,
    ) -> bytes:
        resolved_pipeline = self.resolve_image_pipeline(
            image_pipeline=image_pipeline,
            image_encoding_override=image_encoding_override,
            pixel_format_override=pixel_format_override,
        )
        return _build_job_from_raster_set(
            raster_set=raster_set,
            is_text=is_text,
            speed=self.device.profile.select_speed(is_text=is_text),
            energy=self.device.profile.select_energy(
                is_text=is_text,
                blackening=blackening,
            ),
            density=self._select_density(is_text=is_text, blackening=blackening),
            blackening=blackening,
            lsb_first=self._resolve_lsb_first(lsb_first),
            protocol_family=self.device.protocol_family,
            feed_padding=feed_padding,
            dev_dpi=self.device.profile.dev_dpi,
            can_print_label=self.device.profile.can_print_label,
            post_print_feed_count=self.device.profile.post_print_feed_count,
            image_pipeline=resolved_pipeline,
        )
