from __future__ import annotations

from typing import Any

from ..protocol._builders import _build_job_model_from_raster_set
from ..protocol.family import ProtocolFamily
from ..protocol.job import ProtocolJob
from ..protocol.runtime import RuntimePrintCapabilities
from ..protocol.types import ImagePipelineConfig, PageFlow, PaperMode
from ..raster import RasterSet
from .paper import apply_paper_layout_to_raster_set


def build_raster_job(
    *,
    model: Any,
    raster_set: RasterSet,
    image_pipeline: ImagePipelineConfig,
    is_text: bool,
    speed: int,
    energy: int,
    density: int | None,
    blackening: int,
    feed_padding: int,
    paper_mode: PaperMode | None,
    paper_width_pixels: int | None = None,
    left_padding_pixels: int = 0,
    a4_sheet_max_height: int | None = None,
    page_index: int = 1,
    page_count: int = 1,
    protocol_family: ProtocolFamily | str | None = None,
    protocol_variant: str | None = None,
    runtime_capabilities: RuntimePrintCapabilities | None = None,
    page_flow: PageFlow = PageFlow.PAGED,
) -> ProtocolJob:
    """Bridge a resolved printer model and raster into a stateless job."""

    raster_set = apply_paper_layout_to_raster_set(
        raster_set,
        paper_width_pixels=paper_width_pixels,
        left_padding_pixels=left_padding_pixels,
    )

    payload, steps = _build_job_model_from_raster_set(
        raster_set=raster_set,
        is_text=is_text,
        speed=speed,
        energy=energy,
        density=density,
        blackening=blackening,
        lsb_first=not model.a4xii,
        protocol_family=protocol_family or model.protocol_family,
        protocol_variant=(
            model.protocol_variant if protocol_variant is None else protocol_variant
        ),
        feed_padding=feed_padding,
        dev_dpi=model.dev_dpi,
        can_print_label=model.can_print_label,
        post_print_feed_count=model.post_print_feed_count,
        image_pipeline=image_pipeline,
        paper_mode=paper_mode,
        page_index=page_index,
        page_count=page_count,
        left_padding_pixels=left_padding_pixels,
        one_length=model.one_length,
        a4xii=model.a4xii,
        a4_sheet_max_height=a4_sheet_max_height,
        runtime_capabilities=runtime_capabilities,
        page_flow=page_flow,
    )
    return ProtocolJob(payload=payload, steps=steps, wait_for_completion=True)
