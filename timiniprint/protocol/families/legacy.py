from __future__ import annotations

from ..types import ImageEncoding, ImagePipelineConfig, PixelFormat
from .base import ProtocolBehavior


BEHAVIOR = ProtocolBehavior(
    default_image_pipeline=ImagePipelineConfig(
        formats=(PixelFormat.BW1,),
        encoding=ImageEncoding.LEGACY_RAW,
    ),
    image_encoding_support={
        ImageEncoding.LEGACY_RAW: (PixelFormat.BW1,),
        ImageEncoding.LEGACY_RLE: (PixelFormat.BW1,),
    },
)
