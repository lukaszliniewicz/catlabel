"""Transport policy accepts enum strings without depending on protocol implementation."""

import unittest

from catlabel.devices import get_ble_transport_profile
from catlabel.protocol.family import ProtocolFamily


class BlePolicyTests(unittest.TestCase):
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
