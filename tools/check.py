"""Portable checks with an explicit, diagnostic-specific migration baseline."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCOPE = ["catlabel", "launcher.py", "tools", "tests", "typings"]
BASELINE = ROOT / "checks" / "debt.json"
AUDIT_EXCEPTIONS = ROOT / "checks" / "audit-exceptions.json"


def fingerprint(record: dict[str, Any]) -> str:
    """Positions intentionally remain exact: moving existing debt needs review."""
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def compare_debt(
    current: list[dict[str, Any]], allowed: list[dict[str, Any]]
) -> tuple[list[str], int]:
    actual = Counter(fingerprint(record) for record in current)
    previous = Counter(fingerprint(record) for record in allowed)
    additions = list((actual - previous).elements())
    resolved = sum((previous - actual).values())
    return additions, resolved


def run(command: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = str(ROOT)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        command, cwd=cwd, env=env, text=True, capture_output=True, check=False
    )


def tool_json(command: list[str], cwd: Path = ROOT) -> Any:
    result = run(command, cwd)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Checker failed: {command}\n{result.stderr}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Checker did not produce JSON: {command}\n{result.stderr or result.stdout}"
        ) from exc


def relative(path: str) -> str:
    return Path(path).resolve().relative_to(ROOT).as_posix()


def collect_static(*, typing: bool = True) -> dict[str, list[dict[str, Any]]]:
    python = sys.executable
    findings: dict[str, list[dict[str, Any]]] = {}
    findings["ruff"] = [
        {
            "path": relative(item["filename"]),
            "rule": item["code"],
            "message": item["message"],
            "line": item["location"]["row"],
            "column": item["location"]["column"],
        }
        for item in tool_json(
            [python, "-m", "ruff", "check", "--output-format=json", *SCOPE]
        )
    ]
    formatted = run([python, "-m", "ruff", "format", "--check", *SCOPE])
    if formatted.returncode not in (0, 1):
        raise RuntimeError(formatted.stderr)
    findings["format"] = []
    for line in (formatted.stdout + formatted.stderr).splitlines():
        if line.startswith("Would reformat: "):
            path = line.removeprefix("Would reformat: ")
            source = (ROOT / path).read_text(encoding="utf-8")
            findings["format"].append(
                {
                    "path": Path(path).as_posix(),
                    "sha256": hashlib.sha256(source.encode()).hexdigest(),
                }
            )
    if formatted.returncode == 1 and not findings["format"]:
        raise RuntimeError("Formatter failed without recognizable diagnostics")
    if typing:
        payload = tool_json(
            [python, "-m", "basedpyright", "--outputjson", "--project", str(ROOT)]
        )
        if "generalDiagnostics" not in payload:
            raise RuntimeError("basedpyright output lacks diagnostics")
        findings["typing"] = [
            {
                "path": relative(item["file"]),
                "rule": item.get("rule", "unknown"),
                "message": item["message"],
                "severity": item["severity"],
                "line": item["range"]["start"]["line"] + 1,
                "column": item["range"]["start"]["character"] + 1,
            }
            for item in payload["generalDiagnostics"]
        ]
    frontend = ROOT / "frontend"
    node = "node"
    frontend_types = run(
        [node, "node_modules/typescript/bin/tsc", "--project", "tsconfig.json"],
        frontend,
    )
    if frontend_types.returncode:
        raise RuntimeError(frontend_types.stdout + frontend_types.stderr)
    findings["frontend-typing"] = []
    findings["react"] = [
        {
            "path": relative(file["filePath"]),
            "rule": item["ruleId"],
            "message": item["message"],
            "severity": item["severity"],
            "line": item["line"],
            "column": item["column"],
        }
        for file in tool_json(
            [
                node,
                "node_modules/eslint/bin/eslint.js",
                "src",
                "*.config.js",
                "--format=json",
            ],
            frontend,
        )
        for item in file["messages"]
    ]
    for mode, extra in (("knip", []), ("knip-production", ["--production"])):
        payload = tool_json(
            [node, "node_modules/knip/bin/knip.js", "--reporter=json", *extra], frontend
        )
        if "issues" not in payload:
            raise RuntimeError("Knip output lacks issues")
        findings[mode] = []
        findings[mode].extend(
            {"path": path, "kind": "unused-file"} for path in payload.get("files", [])
        )
        for issue in payload["issues"]:
            for kind, entries in issue.items():
                if kind == "file":
                    continue
                for entry in entries:
                    findings[mode].append(
                        {"path": issue["file"], "kind": kind, "entry": entry}
                    )
    from tools.import_graph import build_graph

    graph = build_graph(ROOT)
    findings["python-cycles"] = [
        {"modules": modules} for modules in graph["full_cycles"]
    ]
    if graph["import_time_cycles"]:
        raise RuntimeError(f"Import-time cycles: {graph['import_time_cycles']}")
    contracts = run(["lint-imports", "--config", "pyproject.toml", "--no-cache"])
    if contracts.returncode:
        raise RuntimeError(contracts.stdout + contracts.stderr)
    findings["import-contracts"] = []
    unused_python = run([python, "-m", "vulture", *SCOPE, "--min-confidence", "80"])
    if unused_python.returncode not in (0, 3):
        raise RuntimeError(unused_python.stdout + unused_python.stderr)
    print(
        "Vulture advisory:",
        unused_python.stdout.strip() or "no candidates at confidence >=80%",
    )
    findings["frontend-cycles"] = [
        {"modules": sorted(modules)}
        for modules in tool_json(
            [
                node,
                "node_modules/madge/bin/cli.js",
                "--circular",
                "--json",
                "--extensions",
                "js,jsx,ts",
                "src",
            ],
            frontend,
        )
    ]
    return findings


def check_versions() -> None:
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for requirement in config["dependency-groups"]["dev"]:
        name, expected = requirement.split("==")
        if importlib.metadata.version(name) != expected:
            raise RuntimeError(
                f"Install requirements-dev.lock: {name} must be {expected}"
            )
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Checks require the declared Python 3.11 environment")
    node_version = run(["node", "--version"]).stdout.strip().removeprefix("v")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    npm_version = run([npm, "--version"]).stdout.strip()
    node_parts = tuple(int(part) for part in node_version.split("."))
    npm_parts = tuple(int(part) for part in npm_version.split("."))
    if node_parts < (24, 18, 0) or node_parts >= (25,):
        raise RuntimeError("Checks require Node >=24.18.0 <25")
    if npm_parts < (11, 16, 0) or npm_parts >= (12,):
        raise RuntimeError("Checks require npm >=11.16.0 <12")
    print(
        f"Environment: Python {sys.version.split()[0]}, Node {node_version}, npm {npm_version}"
    )


def collect_audits() -> dict[str, list[dict[str, Any]]]:
    payload = tool_json(
        [sys.executable, "-m", "pip_audit", "--local", "--strict", "--format=json"]
    )
    python: list[dict[str, Any]] = []
    for package in payload["dependencies"]:
        if package.get("skip_reason"):
            raise RuntimeError(f"Python audit skipped {package['name']}")
        for advisory in package["vulns"]:
            python.append(
                {
                    "package": package["name"],
                    "version": package["version"],
                    "id": advisory["id"],
                }
            )
    npm = "npm.cmd" if os.name == "nt" else "npm"
    payload = tool_json([npm, "audit", "--json"], ROOT / "frontend")
    if "vulnerabilities" not in payload or "error" in payload:
        raise RuntimeError("npm audit failed to collect advisories")
    npm_findings: list[dict[str, Any]] = []
    locked = json.loads(
        (ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8")
    )["packages"]
    for package, info in payload["vulnerabilities"].items():
        versions = sorted({locked[node]["version"] for node in info["nodes"]})
        for advisory in info["via"]:
            if isinstance(advisory, dict):
                npm_findings.append(
                    {
                        "package": package,
                        "id": advisory["source"],
                        "severity": advisory["severity"],
                        "range": advisory["range"],
                        "versions": versions,
                    }
                )
            else:
                npm_findings.append(
                    {
                        "package": package,
                        "via": advisory,
                        "versions": versions,
                        "severity": info["severity"],
                    }
                )
    return {"python-advisories": python, "npm-advisories": npm_findings}


def audit_allowances() -> dict[str, list[dict[str, Any]]]:
    allowed: dict[str, list[dict[str, Any]]] = {}
    for exception in json.loads(AUDIT_EXCEPTIONS.read_text(encoding="utf-8")):
        if (
            not exception["owner"]
            or not exception["reason"]
            or date.fromisoformat(exception["expires"]) < date.today()
        ):
            raise RuntimeError(
                "Missing rationale/owner or expired dependency exception"
            )
        allowed.setdefault(exception["tool"], []).append(exception["finding"])
    return allowed


def test_and_build(lane: str) -> bool:
    commands: list[tuple[list[str], Path]] = []
    npm = "npm.cmd" if os.name == "nt" else "npm"
    with tempfile.TemporaryDirectory(prefix="catlabel-check-") as directory:
        scratch = Path(directory)
        commands.append(
            (
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    str(ROOT / "tests"),
                    "-t",
                    str(ROOT),
                    "-v",
                ],
                scratch,
            )
        )
        commands.append(([npm, "run", "test"], ROOT / "frontend"))
        if lane == "full":
            commands.append(
                (
                    [npm, "run", "build", "--", "--outDir", str(scratch / "frontend")],
                    ROOT / "frontend",
                )
            )
        passed = True
        for command, cwd in commands:
            result = run(command, cwd)
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            passed = result.returncode == 0 and passed
        return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lane", choices=["static", "fast", "full", "audit"], default="full"
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Explicit reviewed migration only; never CI",
    )
    parser.add_argument(
        "--without-typing",
        action="store_true",
        help="Native matrix lane; Linux owns the typing gate",
    )
    parser.add_argument(
        "--report", type=Path, help="Write complete uncapped current diagnostics"
    )
    args = parser.parse_args()
    try:
        check_versions()
        generated = run([sys.executable, "-m", "tools.sync_dependencies", "--check"])
        if generated.returncode:
            raise RuntimeError(generated.stdout + generated.stderr)
        document_contract = run(
            [sys.executable, "-m", "tools.sync_document_contract", "--check"]
        )
        if document_contract.returncode:
            raise RuntimeError(document_contract.stdout + document_contract.stderr)
        public_docs = run([sys.executable, "-m", "tools.check_docs"])
        if public_docs.returncode:
            details = (public_docs.stdout + public_docs.stderr).strip()
            raise RuntimeError(details or "Public documentation check failed")
        if args.lane == "audit" and args.write_baseline:
            raise RuntimeError(
                "Audit exceptions require individual written review, not baseline capture"
            )
        current = (
            collect_audits()
            if args.lane == "audit"
            else collect_static(typing=not args.without_typing)
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(current, indent=2) + "\n", encoding="utf-8"
            )
        if args.write_baseline:
            if args.without_typing or os.environ.get("CI"):
                raise RuntimeError(
                    "Baseline writes require a complete local Linux review"
                )
            if sys.platform != "linux":
                raise RuntimeError(
                    "Capture the shared baseline in the Linux check environment"
                )
            BASELINE.parent.mkdir(parents=True, exist_ok=True)
            BASELINE.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
            print(
                "Wrote diagnostic-specific baseline; review its diff before committing."
            )
        allowed = (
            audit_allowances()
            if args.lane == "audit"
            else json.loads(BASELINE.read_text(encoding="utf-8"))
        )
        passed = True
        for tool, records in current.items():
            added, resolved = compare_debt(records, allowed.get(tool, []))
            print(
                f"{tool}: {len(records)} current, {len(added)} new, {resolved} resolved"
            )
            for record in added:
                print(record)
            passed = not added and passed
        if args.lane in ("fast", "full"):
            passed = test_and_build(args.lane) and passed
        return 0 if passed else 1
    except (
        OSError,
        RuntimeError,
        ValueError,
        importlib.metadata.PackageNotFoundError,
    ) as exc:
        print(f"Checks failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
