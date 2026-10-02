"""Eleph/ToPrint HPRT ESC command dialect."""

from __future__ import annotations

from dataclasses import dataclass

from ...raster import PixelFormat, RasterBuffer
from ..plan import ProtocolPlan
from ..steps import ProtocolStep
from ..types import ImageEncoding, ImagePipelineConfig, PaperMode
from .base import PrintJobRequest, ProtocolBehavior
from .bitmap import pack_bw1_rows, packed_row_width_bytes

_MEDIA_TYPE_CMD = bytes([0x10, 0xFF, 0x10, 0x03])
_ENABLE_CMD = bytes([0x10, 0xFF, 0xFE, 0x01])
_WAKEUP_CMD = bytes(12)
_LOCATION_CENTER_CMD = bytes([0x1B, 0x61, 0x01])
_IMAGE_CMD = bytes([0x1D, 0x76, 0x30])
_POSITION_CMD = bytes([0x1D, 0x0C])
_STOP_JOB_CMD = bytes([0x10, 0xFF, 0xFE, 0x45])
_THICKNESS_CMD = bytes([0x10, 0xFF, 0x10, 0x00])
_FEED_DOTS_CMD = bytes([0x1B, 0x4A])
_RETRACT_DOTS_CMD = bytes([0x10, 0xFF, 0x81])
_MANUAL_PAPER_MOTION_DOTS = 80

_MEDIA_CONTINUOUS_REEL = 0x01
_MEDIA_NO_DRY_ADHESIVE = 0x02
_MEDIA_HOLE_PAPER = 0x03


@dataclass(frozen=True)
class ElephHprtEscPaperRecipe:
    media_paper_type: int


@dataclass(frozen=True)
class ElephHprtEscRecipe:
    protocol_variant: str
    paper_recipes: dict[PaperMode, ElephHprtEscPaperRecipe]
    default_paper_mode: PaperMode = PaperMode.TAG
    default_thickness: int = 1

    def build_steps(self, request: PrintJobRequest) -> tuple[ProtocolStep, ...]:
        if request.protocol_variant not in (None, self.protocol_variant):
            raise ValueError(
                f"Unsupported Eleph HPRT ESC protocol variant: {request.protocol_variant}"
            )
        raster = request.require_raster(PixelFormat.BW1)
        recipe = self._paper_recipe(request.paper_mode)
        thickness = _thickness(request.density, default=self.default_thickness)
        return (
            ProtocolStep.send(
                "hprt-media-type",
                _MEDIA_TYPE_CMD + bytes([recipe.media_paper_type]),
            ),
            ProtocolStep.send(
                "hprt-esc-job",
                _esc_job(
                    raster,
                    thickness=thickness,
                    ends_media_page=request.ends_media_page,
                ),
            ),
        )

    def _paper_recipe(self, paper_mode: PaperMode | None) -> ElephHprtEscPaperRecipe:
        resolved = self.default_paper_mode if paper_mode is None else paper_mode
        return self.paper_recipes[resolved]


def build_job(request: PrintJobRequest) -> ProtocolPlan:
    recipe = ElephHprtEscRecipe(
        protocol_variant="zl1",
        paper_recipes={
            PaperMode.TAG: ElephHprtEscPaperRecipe(_MEDIA_NO_DRY_ADHESIVE),
            PaperMode.PLAIN: ElephHprtEscPaperRecipe(_MEDIA_CONTINUOUS_REEL),
            PaperMode.BLACK_TAG: ElephHprtEscPaperRecipe(_MEDIA_HOLE_PAPER),
        },
    )
    return ProtocolPlan.sequence(recipe.build_steps(request))


def advance_paper_cmd(_dpi: int, _family, _variant: str | None = None) -> bytes:
    return _FEED_DOTS_CMD + bytes([_MANUAL_PAPER_MOTION_DOTS])


def retract_paper_cmd(_dpi: int, _family, _variant: str | None = None) -> bytes:
    return _RETRACT_DOTS_CMD + bytes([_MANUAL_PAPER_MOTION_DOTS])


def _esc_job(
    raster: RasterBuffer,
    *,
    thickness: int,
    ends_media_page: bool = True,
) -> bytes:
    job = _ENABLE_CMD + _WAKEUP_CMD + _LOCATION_CENTER_CMD + _image_cmd(raster)
    if ends_media_page:
        job += _POSITION_CMD
    return job + _STOP_JOB_CMD + _THICKNESS_CMD + bytes([thickness])


def _image_cmd(raster: RasterBuffer) -> bytes:
    raster.validate()
    width_bytes = packed_row_width_bytes(raster.width)
    height = raster.height
    return (
        _IMAGE_CMD
        + bytes(
            [
                0,
                width_bytes & 0xFF,
                (width_bytes >> 8) & 0xFF,
                height & 0xFF,
                (height >> 8) & 0xFF,
            ]
        )
        + pack_bw1_rows(raster, lsb_first=False)
    )


def _thickness(value: int | None, *, default: int) -> int:
    return max(0, min(255, int(default if value is None else value)))


BEHAVIOR = ProtocolBehavior(
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1,),
        encoding=ImageEncoding.ELEPH_HPRT_ESC_RASTER,
    ),
    image_encoding_support={
        ImageEncoding.ELEPH_HPRT_ESC_RASTER: (PixelFormat.BW1,),
    },
    supported_protocol_variants=("zl1",),
    supported_paper_modes=(PaperMode.TAG, PaperMode.PLAIN, PaperMode.BLACK_TAG),
    advance_paper_builder=advance_paper_cmd,
    retract_paper_builder=retract_paper_cmd,
    job_builder=build_job,
)
