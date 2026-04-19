from __future__ import annotations

from ...raster import PixelFormat
from ..types import ImageEncoding, ImagePipelineConfig
from .base import BleTransportProfile, ProtocolBehavior

TRANSPORT = BleTransportProfile(
    standard_chunk_cap=180,
    standard_write_delay_ms=10,
)

BEHAVIOR = ProtocolBehavior(
    transport=TRANSPORT,
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1,),
        encoding=ImageEncoding.LEGACY_RAW,
    ),
    image_encoding_support={
        ImageEncoding.LEGACY_RAW: (PixelFormat.BW1,),
        ImageEncoding.LEGACY_RLE: (PixelFormat.BW1,),
    },
)
