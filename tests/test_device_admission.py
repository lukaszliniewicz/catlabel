from __future__ import annotations

import asyncio
import unittest

from catlabel.printing.admission import (
    DeviceAdmission,
    DeviceBusyError,
    canonical_device_address,
)


class DeviceAddressCanonicalizationTests(unittest.TestCase):
    def test_mac_spellings_normalize_to_the_same_twelve_hex_digits(self) -> None:
        expected = "aabbccddeeff"
        for address in (
            "AA:BB:CC:DD:EE:FF",
            "aa-bb-cc-dd-ee-ff",
            "AABBCCDDEEFF",
            "  Aa:Bb:Cc:Dd:Ee:Ff  ",
        ):
            with self.subTest(address=address):
                self.assertEqual(canonical_device_address(address), expected)

    def test_opaque_ids_are_trimmed_and_casefolded_without_rewriting_punctuation(
        self,
    ) -> None:
        address = "  WinRT:Device/A-B  "
        canonical = canonical_device_address(address)
        self.assertEqual(canonical, "winrt:device/a-b")
        self.assertNotEqual(canonical, canonical_device_address("winrt:device/ab"))

        malformed_mac = " AA:BB-CC:DD:EE:FF "
        self.assertEqual(canonical_device_address(malformed_mac), "aa:bb-cc:dd:ee:ff")

    def test_empty_and_whitespace_addresses_are_invalid(self) -> None:
        for address in ("", " ", "\t \n"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                canonical_device_address(address)


class DeviceAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_equivalent_mac_claim_is_rejected_while_first_claim_is_held(
        self,
    ) -> None:
        admission = DeviceAdmission()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold_claim() -> None:
            async with admission.claim("AA:BB:CC:DD:EE:FF") as address:
                self.assertEqual(address, "aabbccddeeff")
                entered.set()
                await release.wait()

        holder = asyncio.create_task(hold_claim())
        await entered.wait()
        try:
            with self.assertRaises(DeviceBusyError) as raised:
                await asyncio.wait_for(
                    self._claim_once(admission, "aa-bb-cc-dd-ee-ff"), timeout=1.0
                )
            self.assertEqual(raised.exception.address, "aabbccddeeff")
        finally:
            release.set()
            await holder

    async def test_unrelated_printer_can_be_claimed_while_one_is_held(self) -> None:
        admission = DeviceAdmission()
        async with (
            admission.claim("AA:BB:CC:DD:EE:FF") as first,
            admission.claim("11:22:33:44:55:66") as second,
        ):
            self.assertEqual(first, "aabbccddeeff")
            self.assertEqual(second, "112233445566")

    async def test_opaque_ids_remain_distinct_claims(self) -> None:
        admission = DeviceAdmission()
        async with (
            admission.claim("WinRT:Device/A-B") as first,
            admission.claim("winrt:device/ab") as second,
        ):
            self.assertEqual(first, "winrt:device/a-b")
            self.assertEqual(second, "winrt:device/ab")

    async def test_claim_can_be_reused_after_normal_and_error_exit(self) -> None:
        admission = DeviceAdmission()
        async with admission.claim("serial://printer-1") as address:
            self.assertEqual(address, "serial://printer-1")
        async with admission.claim("serial://printer-1"):
            pass

        with self.assertRaisesRegex(RuntimeError, "job failed"):
            async with admission.claim("serial://printer-1"):
                raise RuntimeError("job failed")
        async with admission.claim("serial://printer-1"):
            pass

    async def test_claim_is_released_after_cancellation(self) -> None:
        admission = DeviceAdmission()
        entered = asyncio.Event()
        never = asyncio.Event()

        async def cancelled_claim() -> None:
            async with admission.claim("serial://printer-2"):
                entered.set()
                await never.wait()

        task = asyncio.create_task(cancelled_claim())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        async with admission.claim("serial://printer-2") as address:
            self.assertEqual(address, "serial://printer-2")

    async def test_empty_claim_address_raises_value_error(self) -> None:
        admission = DeviceAdmission()
        with self.assertRaises(ValueError):
            async with admission.claim(" \t "):
                self.fail("empty address must not be claimed")

    @staticmethod
    async def _claim_once(admission: DeviceAdmission, address: str) -> str:
        async with admission.claim(address) as normalized:
            return normalized


if __name__ == "__main__":
    unittest.main()
