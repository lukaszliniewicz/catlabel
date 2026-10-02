"""Transport policy accepts enum strings without depending on protocol implementation."""

import unittest

from catlabel.devices import get_ble_transport_profile
from catlabel.protocol.family import ProtocolFamily


class BlePolicyTests(unittest.TestCase):
    def test_released_tiny_flow_and_separate_eleph_toprint_policies(self) -> None:
        tiny = get_ble_transport_profile("legacy")
        self.assertEqual(tiny, get_ble_transport_profile("legacy_prefixed"))
        self.assertTrue(tiny.prefer_generic_notify)
        self.assertTrue(tiny.flow_controlled_standard_write)
        self.assertEqual(tiny.flow_resume_timeout_s, 600.0)
        eleph = get_ble_transport_profile("eleph_tspl")
        toprint = get_ble_transport_profile("toprint_tspl")
        self.assertEqual(
            (eleph.standard_chunk_cap, eleph.standard_write_delay_ms), (20, 30)
        )
        self.assertEqual(
            (toprint.standard_chunk_cap, toprint.standard_write_delay_ms), (180, 10)
        )
        self.assertEqual(
            eleph.preferred_write_char_uuid, "00002af1-0000-1000-8000-00805f9b34fb"
        )
        self.assertEqual(toprint.preferred_write_char_uuid, "")
        self.assertTrue(get_ble_transport_profile("phomemo_esc").prefer_generic_notify)

    def test_string_and_protocol_enum_identifiers_select_the_same_policy(self) -> None:
        for family in ProtocolFamily:
            with self.subTest(family=family):
                self.assertEqual(
                    get_ble_transport_profile(family),
                    get_ble_transport_profile(family.value),
                )

    def test_absent_identifier_uses_legacy_and_unknown_uses_conservative_defaults(
        self,
    ) -> None:
        self.assertEqual(
            get_ble_transport_profile(None), get_ble_transport_profile("legacy")
        )
        self.assertEqual(get_ble_transport_profile(None).standard_chunk_cap, 512)
        self.assertEqual(get_ble_transport_profile("unknown").standard_chunk_cap, 20)
        self.assertEqual(
            get_ble_transport_profile(" V5X "), get_ble_transport_profile("v5x")
        )
