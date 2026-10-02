"""Source v0.7.3 profiles retain ToPrint identity after the dialect split."""

import copy
import unittest

from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.types import ImageEncoding
from catlabel.vendors.generic.models import (
    PrinterModelRegistry,
    _normalize_legacy_toprint_profile,
)


class LegacyToPrintProfileTests(unittest.TestCase):
    def test_exact_legacy_profile_normalization_is_nonmutating_and_idempotent(
        self,
    ) -> None:
        for key, old, new, suffix in (
            ("toprint_tspl_p1", "eleph_tspl", "toprint_tspl", "bitmap"),
            ("toprint_hprt_esc_zl1", "eleph_hprt_esc", "toprint_hprt_esc", "raster"),
        ):
            with self.subTest(key=key):
                raw = {
                    "profile_key": key,
                    "protocol_default": {"type": old, "packets_type": "p1"},
                    "default_image_pipeline": {
                        "encoding": f"{old}_{suffix}",
                        "formats": ["bw1"],
                    },
                }
                saved = copy.deepcopy(raw)
                normalized = _normalize_legacy_toprint_profile(raw)
                self.assertEqual(raw, saved)
                self.assertEqual(normalized["protocol_default"]["type"], new)
                self.assertEqual(
                    normalized["default_image_pipeline"]["encoding"], f"{new}_{suffix}"
                )
                self.assertEqual(
                    _normalize_legacy_toprint_profile(normalized), normalized
                )
                unrelated = {**raw, "profile_key": "eleph_tspl_p1"}
                self.assertIs(_normalize_legacy_toprint_profile(unrelated), unrelated)

    def test_shipped_catalog_resolves_toprint_without_changing_raw_provenance(
        self,
    ) -> None:
        registry = PrinterModelRegistry.load()
        for name, family, encoding in (
            (
                "toprint_tspl_p1",
                ProtocolFamily.TOPRINT_TSPL,
                ImageEncoding.TOPRINT_TSPL_BITMAP,
            ),
            (
                "toprint_hprt_esc_zl1",
                ProtocolFamily.TOPRINT_HPRT_ESC,
                ImageEncoding.TOPRINT_HPRT_ESC_RASTER,
            ),
        ):
            with self.subTest(name=name):
                model = registry.get(name)
                if model is None:
                    self.fail(f"expected known ToPrint profile for {name}")
                self.assertIs(model.protocol_family, family)
                self.assertIs(model.image_pipeline.encoding, encoding)
