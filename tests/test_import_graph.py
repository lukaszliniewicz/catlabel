from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tools.import_graph import build_graph, cyclic_components

ROOT = Path(__file__).resolve().parents[1]


def _write_sources(root: Path, sources: dict[str, str]) -> None:
    for relative_path, content in sources.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _find_edge(report: dict[str, Any], source: str, target: str) -> dict[str, Any]:
    return next(
        edge
        for edge in report["edges"]
        if edge["source"] == source and edge["target"] == target
    )


class ImportGraphTests(unittest.TestCase):
    def test_resolves_relative_and_from_package_submodule_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_sources(
                root,
                {
                    "catlabel/__init__.py": "",
                    "catlabel/relative_user.py": "from . import relative_target\n",
                    "catlabel/relative_target.py": "",
                    "catlabel/package_user.py": "from catlabel import package_target\n",
                    "catlabel/package_target.py": "",
                },
            )

            report = build_graph(root)

        self.assertEqual(
            _find_edge(report, "catlabel.relative_user", "catlabel.relative_target")[
                "type_only"
            ],
            False,
        )
        self.assertEqual(
            _find_edge(report, "catlabel.package_user", "catlabel.package_target")[
                "deferred"
            ],
            False,
        )
        self.assertIn("catlabel", report["modules"])

    def test_reports_full_cycle_and_excludes_function_body_import_from_eager_cycles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_sources(
                root,
                {
                    "catlabel/__init__.py": "",
                    "catlabel/a.py": "def load_later():\n    import catlabel.b\n",
                    "catlabel/b.py": "import catlabel.a\n",
                },
            )

            report = build_graph(root)

        self.assertEqual(report["full_cycles"], [["catlabel.a", "catlabel.b"]])
        self.assertEqual(report["import_time_cycles"], [])
        self.assertTrue(_find_edge(report, "catlabel.a", "catlabel.b")["deferred"])
        self.assertFalse(_find_edge(report, "catlabel.b", "catlabel.a")["deferred"])

    def test_reports_eager_cycle_and_type_checking_body_separately_from_else(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_sources(
                root,
                {
                    "catlabel/__init__.py": "",
                    "catlabel/a.py": "import catlabel.b\n",
                    "catlabel/b.py": "import catlabel.a\n",
                    "catlabel/type_user.py": (
                        "from typing import TYPE_CHECKING\n"
                        "if TYPE_CHECKING:\n"
                        "    import catlabel.type_dependency\n"
                        "else:\n"
                        "    import catlabel.runtime_dependency\n"
                    ),
                    "catlabel/type_dependency.py": "",
                    "catlabel/runtime_dependency.py": "",
                    "catlabel/qualified_user.py": (
                        "import typing\n"
                        "if typing.TYPE_CHECKING:\n"
                        "    import catlabel.qualified_type_dependency\n"
                        "else:\n"
                        "    import catlabel.qualified_runtime_dependency\n"
                    ),
                    "catlabel/qualified_type_dependency.py": "",
                    "catlabel/qualified_runtime_dependency.py": "",
                },
            )

            report = build_graph(root)

        self.assertEqual(report["full_cycles"], [["catlabel.a", "catlabel.b"]])
        self.assertEqual(report["import_time_cycles"], [["catlabel.a", "catlabel.b"]])
        type_edge = _find_edge(report, "catlabel.type_user", "catlabel.type_dependency")
        self.assertTrue(type_edge["type_only"])
        self.assertFalse(type_edge["deferred"])
        runtime_edge = _find_edge(
            report, "catlabel.type_user", "catlabel.runtime_dependency"
        )
        self.assertFalse(runtime_edge["type_only"])
        self.assertFalse(runtime_edge["deferred"])
        qualified_edge = _find_edge(
            report,
            "catlabel.qualified_user",
            "catlabel.qualified_type_dependency",
        )
        self.assertTrue(qualified_edge["type_only"])

    def test_substring_in_unrelated_guard_does_not_mark_import_type_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_sources(
                root,
                {
                    "catlabel/__init__.py": "",
                    "catlabel/user.py": (
                        "if has_TYPE_CHECKING_mode:\n    import catlabel.dependency\n"
                    ),
                    "catlabel/dependency.py": "",
                },
            )

            report = build_graph(root)

        edge = _find_edge(report, "catlabel.user", "catlabel.dependency")
        self.assertFalse(edge["type_only"])
        self.assertFalse(edge["deferred"])

    def test_unresolved_dynamic_imports_are_reported_without_becoming_edges(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_sources(
                root,
                {
                    "catlabel/__init__.py": "",
                    "catlabel/user.py": (
                        "import importlib\n"
                        "def eager_default(value=importlib.import_module('catlabel.target')):\n"
                        "    importlib.import_module('catlabel.target')\n"
                    ),
                    "catlabel/target.py": "",
                },
            )

            report = build_graph(root)

        self.assertEqual(report["edge_count"], 0)
        self.assertTrue(
            any(
                "Unresolved dynamic import call at catlabel.user:2" in item
                and "eager" in item
                for item in report["limitations"]
            )
        )
        self.assertTrue(
            any(
                "Unresolved dynamic import call at catlabel.user:3" in item
                and "deferred" in item
                for item in report["limitations"]
            )
        )
        self.assertTrue(
            any(
                "Dynamic imports are unresolved" in item
                for item in report["limitations"]
            )
        )

    def test_cyclic_components_are_sorted_and_include_self_cycles(self) -> None:
        adjacency = {
            "z": ["z"],
            "c": ["a"],
            "a": ["b"],
            "b": ["c"],
            "leaf": [],
        }

        self.assertEqual(
            cyclic_components(adjacency),
            [["a", "b", "c"], ["z"]],
        )

    def test_cli_emits_json_for_requested_root_without_creating_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_sources(
                root,
                {
                    "catlabel/__init__.py": "",
                    "catlabel/leaf.py": "",
                },
            )
            before = sorted(path.relative_to(root) for path in root.rglob("*"))

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "import_graph.py"),
                    "--root",
                    str(root),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            after = sorted(path.relative_to(root) for path in root.rglob("*"))

        report = json.loads(result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertEqual(before, after)
        self.assertEqual(report["module_count"], 2)
        self.assertEqual(report["modules"], ["catlabel", "catlabel.leaf"])
        self.assertEqual(
            set(report),
            {
                "module_count",
                "edge_count",
                "modules",
                "edges",
                "full_cycles",
                "import_time_cycles",
                "limitations",
            },
        )


if __name__ == "__main__":
    unittest.main()
