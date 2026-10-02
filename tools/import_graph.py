"""Build a static import graph for the Python source owned by CatLabel."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

_SCOPED_DIRECTORIES = ("catlabel", "tools", "tests")
_Edge = tuple[str, str, int, bool, bool]


def _source_files(root: Path) -> list[Path]:
    paths: set[Path] = set()
    launcher = root / "launcher.py"
    if launcher.is_file():
        paths.add(launcher)

    for directory in _SCOPED_DIRECTORIES:
        scoped_root = root / directory
        if not scoped_root.is_dir():
            continue
        paths.update(
            path
            for path in scoped_root.rglob("*.py")
            if "__pycache__" not in path.parts and path.is_file()
        )
    return sorted(paths)


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    parts = (
        relative.parts[:-1]
        if path.name == "__init__.py"
        else relative.with_suffix("").parts
    )
    return ".".join(parts)


def _is_type_checking_guard(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return (
        isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
    )


def _relative_base(
    module_name: str, is_package: bool, node: ast.ImportFrom
) -> str | None:
    if not node.level:
        return node.module

    package_parts = (
        module_name.split(".") if is_package else module_name.split(".")[:-1]
    )
    parents_to_remove = node.level - 1
    if parents_to_remove >= len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - parents_to_remove]
    if node.module:
        base_parts.extend(node.module.split("."))
    return ".".join(base_parts) or None


def _dynamic_import_name(function: ast.expr) -> str | None:
    if isinstance(function, ast.Name) and function.id in {
        "__import__",
        "import_module",
    }:
        return function.id
    if isinstance(function, ast.Attribute) and function.attr == "import_module":
        return ast.unparse(function)
    return None


class _ImportCollector(ast.NodeVisitor):
    def __init__(
        self,
        module_name: str,
        is_package: bool,
        modules: set[str],
        packages: set[str],
    ) -> None:
        self.module_name = module_name
        self.is_package = is_package
        self.modules = modules
        self.packages = packages
        self.edges: set[_Edge] = set()
        self.dynamic_sites: set[str] = set()
        self.deferred = False
        self.type_only = False

    def _add_edge(self, target: str, line: int) -> None:
        if target in self.modules:
            self.edges.add(
                (self.module_name, target, line, self.deferred, self.type_only)
            )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add_edge(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = _relative_base(self.module_name, self.is_package, node)
        if base is None:
            return

        if base in self.modules and base != self.module_name:
            self._add_edge(base, node.lineno)

        if base not in self.packages:
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            self._add_edge(f"{base}.{alias.name}", node.lineno)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        old_type_only = self.type_only
        if _is_type_checking_guard(node.test):
            self.type_only = True
        for statement in node.body:
            self.visit(statement)
        self.type_only = old_type_only
        for statement in node.orelse:
            self.visit(statement)

    def _visit_function_signature(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for expression in node.decorator_list:
            self.visit(expression)
        for expression in node.args.defaults:
            self.visit(expression)
        for expression in node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.args.vararg and node.args.vararg.annotation:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation:
            self.visit(node.args.kwarg.annotation)
        if node.returns is not None:
            self.visit(node.returns)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_signature(node)
        old_deferred = self.deferred
        self.deferred = True
        for statement in node.body:
            self.visit(statement)
        self.deferred = old_deferred

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_signature(node)
        old_deferred = self.deferred
        self.deferred = True
        for statement in node.body:
            self.visit(statement)
        self.deferred = old_deferred

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expression in node.args.defaults:
            self.visit(expression)
        for expression in node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)
        old_deferred = self.deferred
        self.deferred = True
        self.visit(node.body)
        self.deferred = old_deferred

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in (*node.decorator_list, *node.bases):
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)
        for statement in node.body:
            self.visit(statement)

    def visit_Call(self, node: ast.Call) -> None:
        callee = _dynamic_import_name(node.func)
        if callee:
            timing = "deferred" if self.deferred else "eager"
            self.dynamic_sites.add(
                f"{self.module_name}:{node.lineno} ({timing} {callee})"
            )
        self.generic_visit(node)


def cyclic_components(adjacency: Mapping[str, Iterable[str]]) -> list[list[str]]:
    """Return deterministic strongly connected components that contain a cycle."""
    normalized = {node: set(targets) for node, targets in adjacency.items()}
    nodes = set(normalized)
    for targets in normalized.values():
        nodes.update(targets)

    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []
    next_index = 0

    def visit(node: str) -> None:
        nonlocal next_index
        indices[node] = next_index
        lowlinks[node] = next_index
        next_index += 1
        stack.append(node)
        on_stack.add(node)

        for target in sorted(normalized.get(node, set())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] != indices[node]:
            return

        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        component.sort()
        if len(component) > 1 or node in normalized.get(node, set()):
            components.append(component)

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return sorted(components)


def build_graph(root: str | Path) -> dict[str, Any]:
    """Parse in-scope Python files and return their deterministic import graph."""
    project_root = Path(root).resolve()
    source_paths = _source_files(project_root)
    module_paths = {_module_name(path, project_root): path for path in source_paths}
    modules = set(module_paths)
    packages = {
        name for name, path in module_paths.items() if path.name == "__init__.py"
    }
    for name in modules:
        parts = name.split(".")
        packages.update(".".join(parts[:index]) for index in range(1, len(parts)))

    edges: set[_Edge] = set()
    dynamic_sites: set[str] = set()
    for module_name, path in sorted(module_paths.items()):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        collector = _ImportCollector(
            module_name,
            path.name == "__init__.py",
            modules,
            packages,
        )
        collector.visit(tree)
        edges.update(collector.edges)
        dynamic_sites.update(collector.dynamic_sites)

    all_adjacency: dict[str, set[str]] = {name: set() for name in modules}
    import_time_adjacency: dict[str, set[str]] = {name: set() for name in modules}
    edge_records = [
        {
            "source": source,
            "target": target,
            "line": line,
            "deferred": deferred,
            "type_only": type_only,
        }
        for source, target, line, deferred, type_only in sorted(edges)
    ]
    for edge in edge_records:
        source = str(edge["source"])
        target = str(edge["target"])
        all_adjacency[source].add(target)
        if not edge["deferred"] and not edge["type_only"]:
            import_time_adjacency[source].add(target)

    limitations = [
        "Static AST analysis does not prove runtime import behavior.",
        "Dynamic imports are unresolved and do not contribute graph edges.",
        "Only imports resolving to in-scope Python modules are included as edges.",
    ]
    limitations.extend(
        f"Unresolved dynamic import call at {site}." for site in sorted(dynamic_sites)
    )

    return {
        "module_count": len(modules),
        "edge_count": len(edge_records),
        "modules": sorted(modules),
        "edges": edge_records,
        "full_cycles": cyclic_components(all_adjacency),
        "import_time_cycles": cyclic_components(import_time_adjacency),
        "limitations": limitations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root to scan (defaults to this script's repository)",
    )
    arguments = parser.parse_args(argv)
    report = build_graph(arguments.root)
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
