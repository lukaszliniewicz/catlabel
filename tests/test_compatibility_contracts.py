"""Compatibility witnesses for type/lint modernization at public boundaries."""

import unittest
from enum import Enum
from types import SimpleNamespace

from catlabel.protocol.family import ProtocolCommandSet, ProtocolFamily
from catlabel.protocol.steps import ProtocolReplyExpectation, ProtocolStepOperation
from catlabel.protocol.types import ImageEncoding, PaperMode
from catlabel.raster import PixelFormat
from catlabel.transport.bluetooth.types import DeviceTransport
from catlabel.vendors.utils import extract_raw_hardware_info, find_model_in_registry


class CompatibilityContracts(unittest.TestCase):
    def test_modern_string_enums_preserve_legacy_formatting(self) -> None:
        for enum_class in (
            ProtocolFamily,
            ProtocolCommandSet,
            ProtocolStepOperation,
            ProtocolReplyExpectation,
            ImageEncoding,
            PaperMode,
            PixelFormat,
            DeviceTransport,
        ):
            for value in enum_class:
                expected = f"{enum_class.__name__}.{value.name}"
                with self.subTest(enum=enum_class.__name__, member=value.name):
                    self.assertEqual(str(value), expected)
                    self.assertEqual(f"{value}", expected)
                    for spec in ("", ">28", "^32", ".10"):
                        self.assertEqual(format(value, spec), format(expected, spec))

    def test_non_protocol_enum_still_exports_its_value(self) -> None:
        class ExternalFamily(Enum):
            LEGACY = "legacy"

        model = SimpleNamespace(protocol_family=ExternalFamily.LEGACY)
        self.assertEqual(extract_raw_hardware_info(model)["protocol_family"], "legacy")

    def test_registry_accepts_legacy_sequence_protocol(self) -> None:
        model = SimpleNamespace(model_no="EXAMPLE", head_name="Example")

        class LegacySequence:
            def __getitem__(self, index: int) -> object:
                if index == 0:
                    return model
                raise IndexError(index)

        registry = SimpleNamespace(models=LegacySequence())
        self.assertIs(find_model_in_registry(registry, "EXAMPLE"), model)
