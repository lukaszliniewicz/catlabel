from __future__ import annotations

from typing import Any

from ..raster import PixelFormat, RasterSet
from ._builders import _build_job_model_from_raster_set
from .commands import advance_paper_cmd, retract_paper_cmd
from .families import get_protocol_behavior
from .runtime import RuntimePrintCapabilities
from .steps import ProtocolStep
from .types import ImageEncoding, ImagePipelineConfig, PaperMode


class ProtocolJob:
    """Stateless payload and execution policy, independent of a live session."""

    def __init__(
        self,
        payload: bytes | None = None,
        *,
        steps: tuple[ProtocolStep, ...] = (),
        wait_for_completion: bool = False,
    ) -> None:
        normalized_steps = tuple(steps)
        steps_payload = b"".join(
            step.data for step in normalized_steps if step.include_in_payload
        )
        if payload is None:
            normalized_payload = steps_payload
        else:
            normalized_payload = bytes(payload)
            if normalized_steps and normalized_payload != steps_payload:
                raise ValueError(
                    "Protocol job payload does not match included protocol steps"
                )
        self.payload = normalized_payload
        self.steps = normalized_steps
        self.wait_for_completion = bool(wait_for_completion)


class PrinterProtocol:
    """Build stateless protocol jobs for one resolved printer device."""

    def __init__(self, device: Any) -> None:
        self.device = device

    def build_job(
        self,
        raster_set: RasterSet,
        *,
        is_text: bool,
        blackening: int = 3,
        feed_padding: int = 0,
        paper_mode: PaperMode | None = None,
        lsb_first: bool | None = None,
        image_pipeline: ImagePipelineConfig | None = None,
        image_encoding_override: ImageEncoding | None = None,
        pixel_format_override: PixelFormat | None = None,
        page_index: int = 1,
        page_count: int = 1,
        runtime_capabilities: RuntimePrintCapabilities | None = None,
    ) -> ProtocolJob:
        pipeline = self.resolve_image_pipeline(
            image_pipeline=image_pipeline,
            image_encoding_override=image_encoding_override,
            pixel_format_override=pixel_format_override,
        )
        profile = self.device.profile
        payload, steps = _build_job_model_from_raster_set(
            raster_set=raster_set,
            is_text=is_text,
            speed=profile.select_speed(is_text=is_text),
            energy=profile.select_energy(is_text=is_text, blackening=blackening),
            density=profile.select_density(is_text=is_text, blackening=blackening),
            blackening=blackening,
            lsb_first=lsb_first if lsb_first is not None else not profile.a4xii,
            protocol_family=self.device.protocol_family,
            protocol_variant=getattr(self.device, "protocol_variant", None),
            feed_padding=feed_padding,
            dev_dpi=profile.dev_dpi,
            can_print_label=profile.can_print_label,
            post_print_feed_count=profile.post_print_feed_count,
            image_pipeline=pipeline,
            paper_mode=paper_mode,
            page_index=page_index,
            page_count=page_count,
            one_length=getattr(profile, "one_length", 0),
            a4xii=bool(getattr(profile, "a4xii", False)),
            runtime_capabilities=runtime_capabilities,
        )
        return ProtocolJob(payload=payload, steps=steps, wait_for_completion=True)

    def build_paper_motion(self, action: str) -> ProtocolJob:
        if action == "feed":
            payload = advance_paper_cmd(
                self.device.profile.dev_dpi,
                self.device.protocol_family,
                getattr(self.device, "protocol_variant", None),
            )
        elif action == "retract":
            payload = retract_paper_cmd(
                self.device.profile.dev_dpi,
                self.device.protocol_family,
                getattr(self.device, "protocol_variant", None),
            )
        else:
            raise ValueError(f"Unknown paper motion action: {action}")
        return ProtocolJob(payload=payload)

    def resolve_image_pipeline(
        self,
        *,
        image_pipeline: ImagePipelineConfig | None = None,
        image_encoding_override: ImageEncoding | None = None,
        pixel_format_override: PixelFormat | None = None,
    ) -> ImagePipelineConfig:
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
        supported = behavior.image_encoding_support.get(pipeline.encoding)
        if supported is None:
            raise ValueError(
                f"{self.device.protocol_family.value} does not support image encoding "
                f"{pipeline.encoding.value}"
            )
        if pixel_format_override is not None:
            if pixel_format_override not in supported:
                raise ValueError(
                    f"{self.device.protocol_family.value} image encoding {pipeline.encoding.value} "
                    f"does not support {pixel_format_override.value}"
                )
            if pixel_format_override in pipeline.formats:
                pipeline = pipeline.with_default_format(pixel_format_override)
            else:
                pipeline = ImagePipelineConfig(
                    formats=(pixel_format_override,)
                    + tuple(
                        value
                        for value in pipeline.formats
                        if value != pixel_format_override
                    ),
                    encoding=pipeline.encoding,
                )
        elif pipeline.default_format not in supported:
            fallback = next(
                (value for value in pipeline.formats if value in supported),
                supported[0],
            )
            if fallback in pipeline.formats:
                pipeline = pipeline.with_default_format(fallback)
            else:
                pipeline = ImagePipelineConfig(
                    formats=(fallback,)
                    + tuple(value for value in pipeline.formats if value != fallback),
                    encoding=pipeline.encoding,
                )
        return pipeline

    def supported_paper_modes(self) -> tuple[PaperMode, ...]:
        behavior = get_protocol_behavior(self.device.protocol_family)
        if behavior.supported_paper_modes_resolver is not None:
            return behavior.supported_paper_modes_resolver(
                getattr(self.device, "protocol_variant", None)
            )
        return behavior.supported_paper_modes
