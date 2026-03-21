from __future__ import annotations

import importlib
import unittest

from tests.helpers import install_crc8_stub
from timiniprint.protocol.family import ProtocolFamily


class ProtocolJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_crc8_stub()
        cls.commands = importlib.import_module("timiniprint.protocol.commands")
        cls.job = importlib.import_module("timiniprint.protocol.job")
        cls.types = importlib.import_module("timiniprint.protocol.types")

    def test_build_print_payload_contains_expected_sections(self) -> None:
        payload = self.job.build_print_payload(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=10,
            energy=5000,
            compress=False,
            lsb_first=True,
            protocol_family=ProtocolFamily.LEGACY,
        )
        self.assertIn(bytes([0xAF]), payload)
        self.assertIn(bytes([0xBE]), payload)
        self.assertIn(bytes([0xBD]), payload)
        self.assertIn(bytes([0xA2]), payload)

    def test_build_job_appends_final_sequence(self) -> None:
        data = self.job.build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=10,
            energy=5000,
            blackening=3,
            compress=False,
            lsb_first=True,
            protocol_family=ProtocolFamily.LEGACY,
            feed_padding=12,
            dev_dpi=203,
        )
        self.assertGreaterEqual(data.count(bytes([0xA1])), 2)
        self.assertIn(bytes([0xA3]), data)

    def test_build_from_raster_validates(self) -> None:
        raster = self.types.Raster(pixels=[1, 0, 1], width=2)
        with self.assertRaisesRegex(ValueError, "multiple of width"):
            self.job.build_job_from_raster(
                raster=raster,
                is_text=False,
                speed=10,
                energy=5000,
                blackening=3,
                compress=False,
                lsb_first=True,
                protocol_family=ProtocolFamily.LEGACY,
                feed_padding=12,
                dev_dpi=203,
            )

    def test_build_v5x_job_uses_family_specific_sequence(self) -> None:
        data = self.job.build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=10,
            energy=5000,
            blackening=3,
            compress=False,
            lsb_first=True,
            protocol_family=ProtocolFamily.V5X,
            feed_padding=12,
            dev_dpi=203,
        )
        self.assertTrue(data.startswith(bytes.fromhex("2221A70000000000")))
        self.assertIn(
            self.commands.make_packet(0xA9, bytes([0x01, 0x00]), ProtocolFamily.V5X),
            data,
        )
        self.assertIn(bytes([0x55]), data)
        self.assertTrue(data.endswith(bytes.fromhex("2221AD000100000000")))

    def test_build_v5c_job_uses_family_specific_sequence(self) -> None:
        data = self.job.build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=True,
            speed=10,
            energy=5000,
            blackening=4,
            compress=False,
            lsb_first=True,
            protocol_family=ProtocolFamily.V5C,
            feed_padding=12,
            dev_dpi=203,
        )
        self.assertTrue(data.startswith(self.commands.make_packet(0xA2, bytes([0x03, 0x01]), ProtocolFamily.V5C)))
        self.assertIn(self.commands.make_packet(0xA3, bytes([0x01]), ProtocolFamily.V5C), data)
        self.assertIn(self.commands.make_packet(0xA4, bytes([0x55]), ProtocolFamily.V5C), data)
        self.assertNotIn(bytes([0x1D, 0x76, 0x30, 0x00]), data)
        self.assertIn(self.commands.make_packet(0xA6, bytes([0x30, 0x00]), ProtocolFamily.V5C), data)
        self.assertTrue(data.endswith(self.commands.make_packet(0xA1, bytes([0x00]), ProtocolFamily.V5C)))

    def test_build_dck_job_is_not_implemented(self) -> None:
        with self.assertRaisesRegex(NotImplementedError, "DCK protocol family"):
            self.job.build_job(
                pixels=[1, 0, 1, 0, 1, 0, 1, 0],
                width=8,
                is_text=False,
                speed=10,
                energy=5000,
                blackening=3,
                compress=False,
                lsb_first=True,
                protocol_family=ProtocolFamily.DCK,
                feed_padding=12,
                dev_dpi=203,
            )


if __name__ == "__main__":
    unittest.main()
