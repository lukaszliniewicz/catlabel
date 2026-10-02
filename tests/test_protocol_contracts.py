from __future__ import annotations

import unittest
from unittest.mock import patch

from catlabel.protocol import _builders
from catlabel.protocol.encoding import pack_line
from catlabel.protocol.families import get_protocol_definition
from catlabel.protocol.family import ProtocolCommandSet, ProtocolFamily
from catlabel.protocol.plan import ProtocolPlan
from catlabel.protocol.steps import ProtocolReplyExpectation, ProtocolStep
from catlabel.raster import RasterBuffer, RasterSet


class PackLineSequenceTests(unittest.TestCase):
    def test_tuple_and_list_inputs_match_for_partial_final_byte(self) -> None:
        pixels = (1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 1)

        self.assertEqual(pack_line(pixels, lsb_first=True), b"\x2d\x07")
        self.assertEqual(pack_line(list(pixels), lsb_first=True), b"\x2d\x07")
        self.assertEqual(pack_line(pixels, lsb_first=False), b"\xb4\xe0")
        self.assertEqual(pack_line(list(pixels), lsb_first=False), b"\xb4\xe0")


class ProtocolSpecDefinitionTests(unittest.TestCase):
    def test_family_specs_match_the_legacy_registry_definitions(self) -> None:
        expected = {
            ProtocolFamily.LEGACY: (b"\x51\x78", ProtocolCommandSet.LEGACY),
            ProtocolFamily.LEGACY_PREFIXED: (
                b"\x12\x51\x78",
                ProtocolCommandSet.LEGACY,
            ),
            ProtocolFamily.LUCK_NORMAL: (None, ProtocolCommandSet.LUCK_NORMAL),
            ProtocolFamily.LUCK_NORMAL_A4: (None, ProtocolCommandSet.LUCK_NORMAL),
            ProtocolFamily.V5G: (b"\x51\x78", ProtocolCommandSet.V5G),
            ProtocolFamily.V5X: (b"\x22\x21", ProtocolCommandSet.V5X),
            ProtocolFamily.V5C: (b"\x56\x88", ProtocolCommandSet.V5C),
            ProtocolFamily.DCK: (b"\x55\xaa", ProtocolCommandSet.DCK),
            ProtocolFamily.ELEPH_HPRT_ESC: (
                None,
                ProtocolCommandSet.ELEPH_HPRT_ESC,
            ),
            ProtocolFamily.ELEPH_TSPL: (None, ProtocolCommandSet.ELEPH_TSPL),
            ProtocolFamily.TOPRINT_HPRT_ESC: (
                None,
                ProtocolCommandSet.TOPRINT_HPRT_ESC,
            ),
            ProtocolFamily.TOPRINT_TSPL: (None, ProtocolCommandSet.TOPRINT_TSPL),
            ProtocolFamily.YK_ASTRA_P1: (None, ProtocolCommandSet.YK_ASTRA_P1),
            ProtocolFamily.INSTAPRINT_CORE: (
                None,
                ProtocolCommandSet.INSTAPRINT_CORE,
            ),
            ProtocolFamily.FUNNY_LX: (None, ProtocolCommandSet.FUNNY_LX),
        }

        self.assertEqual(set(expected), set(ProtocolFamily))
        for family, (prefix, command_set) in expected.items():
            with self.subTest(family=family):
                spec = family.spec
                self.assertEqual(spec.packet_prefix, prefix)
                self.assertIs(spec.command_set, command_set)
                self.assertEqual(str(family), f"ProtocolFamily.{family.name}")
                self.assertEqual(
                    str(command_set),
                    f"ProtocolCommandSet.{command_set.name}",
                )
                self.assertIs(get_protocol_definition(family).spec, spec)


class ByteOnlyPrintHelperTests(unittest.TestCase):
    def test_family_plan_without_steps_returns_its_byte_payload(self) -> None:
        plan = ProtocolPlan.stream(b"legacy payload")

        with (
            patch.object(_builders, "_build_request", return_value=object()),
            patch.object(_builders, "_build_family_job", return_value=plan),
        ):
            result = _builders._build_print_payload_from_raster_set(
                raster_set=RasterSet.from_single(RasterBuffer(pixels=[0] * 8, width=8)),
                is_text=False,
                speed=1,
                energy=1,
                lsb_first=False,
                protocol_family=ProtocolFamily.LEGACY,
            )

        self.assertEqual(result, b"legacy payload")

    def test_interactive_family_plan_is_rejected(self) -> None:
        plan = ProtocolPlan.sequence(
            (ProtocolStep.query("status", b"\x01", expect=ProtocolReplyExpectation.OK),)
        )

        with (
            patch.object(_builders, "_build_request", return_value=object()),
            patch.object(_builders, "_build_family_job", return_value=plan),
            self.assertRaisesRegex(
                ValueError,
                "^Interactive protocol plans require the printing layer\\.$",
            ),
        ):
            _builders._build_print_payload_from_raster_set(
                raster_set=RasterSet.from_single(RasterBuffer(pixels=[0] * 8, width=8)),
                is_text=False,
                speed=1,
                energy=1,
                lsb_first=False,
                protocol_family=ProtocolFamily.LEGACY,
            )


if __name__ == "__main__":
    unittest.main()
