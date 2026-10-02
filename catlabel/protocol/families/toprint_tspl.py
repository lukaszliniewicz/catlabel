"""ToPrint P1 TSPL-like command dialect."""

from __future__ import annotations

from dataclasses import dataclass

from ...raster import PixelFormat, RasterBuffer
from ..plan import ProtocolPlan
from ..types import ImageEncoding, ImagePipelineConfig, PaperMode
from .base import PrintJobRequest, ProtocolBehavior
from .bitmap import pack_bw1_rows, packed_row_width_bytes

_LINE_END = b"\r\n"
_PAPER_TYPE_COMMAND = bytes([0x10, 0xFF, 0x10, 0x03])
_PAPER_CONTINUOUS_REEL = 0x01
_PAPER_NO_DRY_ADHESIVE = 0x02
_PAPER_HOLE = 0x03


@dataclass(frozen=True)
class ToPrintTsplPaperRecipe:
    media_paper_type: int
    gap_mm: float
    sensor_command: str = "GAP"
    height_extra_mm: float = 0.0
    include_speed: bool = True


def build_job(request: PrintJobRequest) -> ProtocolPlan:
    if request.protocol_variant not in (None, "p1"):
        raise ValueError(
            f"Unsupported ToPrint TSPL protocol variant: {request.protocol_variant!r}"
        )
    raster = request.require_raster(PixelFormat.BW1)
    raster.validate()
    recipe = _paper_recipe(request.paper_mode)
    height_extra_mm = recipe.height_extra_mm if request.ends_media_page else 0.0
    width_bytes = _width_bytes(raster)
    density = max(0, min(15, int(9 if request.density is None else request.density)))

    payload = bytearray(_PAPER_TYPE_COMMAND + bytes([recipe.media_paper_type]))
    payload += _command(
        "SIZE",
        (
            f"{_px_to_mm(raster.width, request.dev_dpi)} mm,"
            f"{_px_to_mm(raster.height, request.dev_dpi, extra_mm=height_extra_mm)} mm"
        ),
    )
    payload += _command("DIRECTION", "0,0")
    payload += _command(recipe.sensor_command, f"{_format_mm(recipe.gap_mm)} mm,0 mm")
    payload += _command("SET RIBBON", "OFF")
    payload += _command("DENSITY", str(density))
    payload += _command("REFERENCE", "0,0")
    if recipe.include_speed and request.speed is not None:
        payload += _command("SPEED", str(request.speed))
    payload += _command("CLS")
    payload += _command_head("BITMAP", f"0,0,{width_bytes},{raster.height},0,")
    payload += pack_bw1_rows(raster, lsb_first=False)
    payload += _LINE_END
    payload += _command("PRINT", "1,1")
    return ProtocolPlan.stream(bytes(payload))


def advance_paper_cmd(_dpi: int, _family, _variant: str | None = None) -> bytes:
    return _command("FORMFEED")


def retract_paper_cmd(_dpi: int, _family, _variant: str | None = None) -> bytes:
    return _command("BACKFEED", "40")


def _paper_recipe(paper_mode: PaperMode | None) -> ToPrintTsplPaperRecipe:
    recipes = {
        PaperMode.TAG: ToPrintTsplPaperRecipe(
            media_paper_type=_PAPER_NO_DRY_ADHESIVE,
            gap_mm=3.0,
        ),
        PaperMode.PLAIN: ToPrintTsplPaperRecipe(
            media_paper_type=_PAPER_CONTINUOUS_REEL,
            gap_mm=0.0,
            height_extra_mm=5.0,
            include_speed=False,
        ),
        PaperMode.BLACK_TAG: ToPrintTsplPaperRecipe(
            media_paper_type=_PAPER_HOLE,
            gap_mm=3.0,
            sensor_command="BLINE",
            include_speed=False,
        ),
    }
    return recipes[PaperMode.TAG if paper_mode is None else paper_mode]


def _width_bytes(raster: RasterBuffer) -> int:
    if raster.width % 8 != 0:
        raise ValueError("ToPrint TSPL bitmap jobs require width divisible by 8")
    return packed_row_width_bytes(raster.width)


def _px_to_mm(value: int, dpi: int, *, extra_mm: float = 0.0) -> str:
    return _format_mm(float(value) * 25.4 / float(dpi) + extra_mm)


def _format_mm(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _command(name: str, value: str | None = None) -> bytes:
    return _command_head(name, value) + _LINE_END


def _command_head(name: str, value: str | None = None) -> bytes:
    if value is None:
        return name.encode("ascii")
    return f"{name} {value}".encode("ascii")


BEHAVIOR = ProtocolBehavior(
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1,),
        encoding=ImageEncoding.TOPRINT_TSPL_BITMAP,
    ),
    image_encoding_support={
        ImageEncoding.TOPRINT_TSPL_BITMAP: (PixelFormat.BW1,),
    },
    supported_protocol_variants=("p1",),
    supported_paper_modes=(PaperMode.TAG, PaperMode.PLAIN, PaperMode.BLACK_TAG),
    advance_paper_builder=advance_paper_cmd,
    retract_paper_builder=retract_paper_cmd,
    job_builder=build_job,
)
