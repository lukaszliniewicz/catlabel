"""PrintMaster's ESC raster branch; compact Phomemo keeps its dedicated owner.

Recipe provenance: TiMini-Print fe603ca2ee1d21866f66f86d63ca2fc101916de8.
"""

from __future__ import annotations

from ...raster import PixelFormat
from ..family import ProtocolFamily
from ..types import ImageEncoding, ImagePipelineConfig, PaperMode
from .base import PrintJobRequest, ProtocolBehavior
from .printmaster_core import build_printmaster_page

VARIANTS = ("printmaster_m110", "printmaster_m120")


def build_job(request: PrintJobRequest) -> bytes:
    variant = request.protocol_variant
    if variant is None or variant not in VARIANTS:
        raise ValueError(f"Unsupported PrintMaster variant: {variant!r}")
    return build_printmaster_page(
        request.require_raster(PixelFormat.BW1),
        variant=variant,
        density=request.density,
        speed=request.speed or None,
    )


def advance_paper(_dpi: int, _family: ProtocolFamily, _variant: str | None) -> bytes:
    return b"\x1b\x4a\x50"


def retract_paper(_dpi: int, _family: ProtocolFamily, _variant: str | None) -> bytes:
    return b""


BEHAVIOR = ProtocolBehavior(
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1,), encoding=ImageEncoding.PHOMEMO_ESC_RASTER
    ),
    image_encoding_support={ImageEncoding.PHOMEMO_ESC_RASTER: (PixelFormat.BW1,)},
    supported_protocol_variants=VARIANTS,
    supported_paper_modes=(PaperMode.TAG,),
    advance_paper_builder=advance_paper,
    retract_paper_builder=retract_paper,
    job_builder=build_job,
)
