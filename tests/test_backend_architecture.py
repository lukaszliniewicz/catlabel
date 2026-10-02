from __future__ import annotations

import ast
import unittest
from pathlib import Path

from catlabel.devices import get_ble_transport_profile
from catlabel.protocol import ProtocolFamily, ProtocolJob, ProtocolStep

ROOT = Path(__file__).resolve().parents[1]


def _imports_under(path: Path) -> set[str]:
    imports: set[str] = set()
    for source_path in path.rglob("*.py"):
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path)
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


class BackendArchitectureTests(unittest.TestCase):
    def test_protocol_does_not_depend_on_live_printing_or_transport(self) -> None:
        imports = _imports_under(ROOT / "catlabel" / "protocol")
        self.assertFalse(any("printing" in name for name in imports))
        self.assertFalse(any("transport" in name for name in imports))

    def test_transport_does_not_select_printing_runtime(self) -> None:
        imports = _imports_under(ROOT / "catlabel" / "transport")
        self.assertFalse(any("printing.runtime" in name for name in imports))

    def test_transport_does_not_parse_protocol_packets(self) -> None:
        imports = _imports_under(ROOT / "catlabel" / "transport")
        self.assertFalse(any("protocol" in name for name in imports))

    def test_protocol_job_is_stateless_and_validates_steps(self) -> None:
        step = ProtocolStep.send("data", b"abc")
        job = ProtocolJob(steps=(step,), wait_for_completion=True)
        self.assertEqual(job.payload, b"abc")
        self.assertFalse(hasattr(job, "runtime_controller"))
        with self.assertRaisesRegex(ValueError, "does not match"):
            ProtocolJob(payload=b"wrong", steps=(step,))

    def test_device_layer_owns_ble_policy(self) -> None:
        profile = get_ble_transport_profile(ProtocolFamily.V5X)
        self.assertIsNotNone(profile)
        if profile is None:
            self.fail("V5X should have a BLE transport profile")
        self.assertEqual(profile.standard_chunk_cap, 20)
        self.assertEqual(profile.standard_write_delay_ms, 50)
        self.assertEqual(profile.write_without_response_payload_reserve, 5)
        bulk_write = profile.bulk_write
        self.assertIsNotNone(bulk_write)
        if bulk_write is None:
            self.fail("V5X should have a bulk-write profile")
        self.assertEqual(bulk_write.chunk_cap, 180)
        self.assertEqual(bulk_write.write_delay_ms, 30)
        self.assertTrue(bulk_write.flow_controlled)

        v5g = get_ble_transport_profile(ProtocolFamily.V5G)
        self.assertEqual(v5g.standard_chunk_cap, 448)
        self.assertEqual(v5g.standard_write_delay_ms, 30)
        self.assertEqual(v5g.write_without_response_payload_reserve, 5)

        phomemo = get_ble_transport_profile("phomemo_esc")
        self.assertEqual(phomemo.standard_chunk_cap, 128)
        self.assertEqual(phomemo.standard_write_delay_ms, 20)
        self.assertTrue(
            phomemo.preferred_write_char_uuid.endswith(
                "ff02-0000-1000-8000-00805f9b34fb"
            )
        )

        niimbot = get_ble_transport_profile("niimbot")
        self.assertEqual(niimbot.standard_chunk_cap, 20)
        self.assertEqual(niimbot.standard_write_delay_ms, 10)
        self.assertEqual(
            niimbot.preferred_service_uuid,
            "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
        )


if __name__ == "__main__":
    unittest.main()
