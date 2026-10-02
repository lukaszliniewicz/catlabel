"""ToPrint ZL1 HPRT ESC dialect using the shared stateless encoder."""

from __future__ import annotations

from ...raster import PixelFormat
from ..plan import ProtocolPlan
from ..types import ImageEncoding, ImagePipelineConfig, PaperMode
from .base import PrintJobRequest, ProtocolBehavior
from .eleph_hprt_esc import (
    advance_paper_cmd as advance_paper_cmd,
)
from .eleph_hprt_esc import (
    build_job as _build_eleph_hprt_job,
)
from .eleph_hprt_esc import (
    retract_paper_cmd as retract_paper_cmd,
)


def build_job(request: PrintJobRequest) -> ProtocolPlan:
    if request.protocol_variant not in (None, "zl1"):
        raise ValueError(
            f"Unsupported ToPrint HPRT ESC protocol variant: {request.protocol_variant!r}"
        )
    return _build_eleph_hprt_job(request)


BEHAVIOR = ProtocolBehavior(
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1,),
        encoding=ImageEncoding.TOPRINT_HPRT_ESC_RASTER,
    ),
    image_encoding_support={
        ImageEncoding.TOPRINT_HPRT_ESC_RASTER: (PixelFormat.BW1,),
    },
    supported_protocol_variants=("zl1",),
    supported_paper_modes=(PaperMode.TAG, PaperMode.PLAIN, PaperMode.BLACK_TAG),
    advance_paper_builder=advance_paper_cmd,
    retract_paper_builder=retract_paper_cmd,
    job_builder=build_job,
)
