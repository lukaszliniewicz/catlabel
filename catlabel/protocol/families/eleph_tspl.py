"""Released Eleph-label P1 TSPL command dialect."""

from __future__ import annotations

from ...raster import PixelFormat, RasterBuffer
from ..plan import ProtocolPlan
from ..types import ImageEncoding, ImagePipelineConfig, PaperMode
from .base import PrintJobRequest, ProtocolBehavior
from .bitmap import pack_bw1_rows, packed_row_width_bytes

_LINE_END = b"\r\n"


def build_job(request: PrintJobRequest) -> ProtocolPlan:
    if request.protocol_variant not in (None, "p1"):
        raise ValueError(
            f"Unsupported Eleph-label TSPL protocol variant: {request.protocol_variant}"
        )
    raster = request.require_raster(PixelFormat.BW1)
    raster.validate()
    width_bytes = _width_bytes(raster)

    payload = bytearray(
        _command(
            "SIZE",
            f"{_px_to_whole_mm(raster.width, request.dev_dpi)} mm,"
            f"{_px_to_whole_mm(raster.height, request.dev_dpi)} mm",
        )
    )
    payload += _command("GAP", "2 mm,0 mm")
    payload += _command("DIRECTION", "0")
    payload += _command("CLS")
    bitmap = pack_bw1_rows(raster, lsb_first=False)
    payload += _command_head("BITMAP", f"0,0,{width_bytes},{raster.height},0,")
    payload += bytes(value ^ 0xFF for value in bitmap)
    payload += _LINE_END
    payload += _command("PRINT", "1,1")
    return ProtocolPlan.stream(bytes(payload))


def advance_paper_cmd(_dpi: int, _family, _variant: str | None = None) -> bytes:
    return _command("FORMFEED")


def retract_paper_cmd(_dpi: int, _family, _variant: str | None = None) -> bytes:
    return _command("BACKFEED", "40")


def _width_bytes(raster: RasterBuffer) -> int:
    if raster.width % 8 != 0:
        raise ValueError("Eleph TSPL bitmap jobs require width divisible by 8")
    return packed_row_width_bytes(raster.width)


def _px_to_whole_mm(value: int, dpi: int) -> int:
    return int(float(value) * 25.4 / float(dpi))


def _command(name: str, value: str | None = None) -> bytes:
    return _command_head(name, value) + _LINE_END


def _command_head(name: str, value: str | None = None) -> bytes:
    if value is None:
        return name.encode("ascii")
    return f"{name} {value}".encode("ascii")


BEHAVIOR = ProtocolBehavior(
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1,),
        encoding=ImageEncoding.ELEPH_TSPL_BITMAP,
    ),
    image_encoding_support={
        ImageEncoding.ELEPH_TSPL_BITMAP: (PixelFormat.BW1,),
    },
    supported_protocol_variants=("p1",),
    supported_paper_modes=(PaperMode.TAG,),
    advance_paper_builder=advance_paper_cmd,
    retract_paper_builder=retract_paper_cmd,
    job_builder=build_job,
)
