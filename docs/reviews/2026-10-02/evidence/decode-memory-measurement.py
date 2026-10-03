#!/usr/bin/env python3
"""Bounded subprocess measurements for catlabel image payload decoding."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any


ROOT = Path("/home/lliniewicz/Projects/catlabel")
OUT_DIR = ROOT / "check-results/phase6-decode-memory"
SCRIPT = OUT_DIR / "measure_decode_memory.py"
PYTHON = ROOT / "check-results/runtime/check-env/bin/python"
COUNTS = (1, 20, 100)
REPETITIONS = 3
WIDTH = 384
HEIGHT = 384


def _fixture() -> tuple[bytes, str]:
    from PIL import Image

    image = Image.new("RGB", (WIDTH, HEIGHT))
    image.putdata(
        [(x % 256, y % 256, (x + y) % 256) for y in range(HEIGHT) for x in range(WIDTH)]
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image.close()
    png_bytes = buffer.getvalue()
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return png_bytes, "data:image/png;base64," + encoded


def _worker(count: int, repetition: int) -> dict[str, Any]:
    if sys.platform != "linux":
        raise RuntimeError(f"Linux required by protocol, got {sys.platform!r}")

    import catlabel.rendering.image_payload as image_payload

    png_bytes, payload = _fixture()
    encoded_part = payload.split(",", 1)[1]
    payloads = [payload] * count
    images = []
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.perf_counter()
    try:
        images = image_payload.decode_image_payloads(payloads)
        elapsed_seconds = time.perf_counter() - started
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        first_pixels = images[0].tobytes()
        last_pixels = images[-1].tobytes()
        return {
            "repetition": repetition,
            "requested_count": count,
            "image_count": len(images),
            "dimensions": [list(image.size) for image in images],
            "modes": [image.mode for image in images],
            "first_pixels_sha256": hashlib.sha256(first_pixels).hexdigest(),
            "last_pixels_sha256": hashlib.sha256(last_pixels).hexdigest(),
            "fixture_png_sha256": hashlib.sha256(png_bytes).hexdigest(),
            "fixture_png_bytes": len(png_bytes),
            "payload_bytes_per_image": len(payload.encode("ascii")),
            "base64_encoded_bytes_per_image": len(encoded_part.encode("ascii")),
            "aggregate_payload_bytes": count * len(payload.encode("ascii")),
            "aggregate_encoded_bytes": count * len(encoded_part.encode("ascii")),
            "decoded_pixel_bytes": count * WIDTH * HEIGHT * 3,
            "decode_duration_seconds": elapsed_seconds,
            "ru_maxrss_before_kib": before,
            "ru_maxrss_after_kib": after,
            "ru_maxrss_high_water_increment_kib": after - before,
            "python": sys.version,
            "pillow": __import__("PIL").__version__,
            "platform": platform.platform(),
            "machine": platform.machine(),
        }
    finally:
        for image in images:
            image.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _driver() -> int:
    environment = os.environ.copy()
    expected_env = {
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": str(ROOT / "check-results/phase6-final/tmp"),
    }
    for key, value in expected_env.items():
        environment[key] = value

    results: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    exact_worker_command = (
        f"{PYTHON} {SCRIPT} --worker COUNT REPETITION"
    )
    for count in COUNTS:
        for repetition in range(1, REPETITIONS + 1):
            command = [str(PYTHON), str(SCRIPT), "--worker", str(count), str(repetition)]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                failure = {
                    "count": count,
                    "repetition": repetition,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-4000:],
                    "stderr": completed.stderr[-8000:],
                }
                break
            try:
                results.append(json.loads(completed.stdout))
            except json.JSONDecodeError as exc:
                failure = {
                    "count": count,
                    "repetition": repetition,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-4000:],
                    "stderr": completed.stderr[-8000:],
                    "parse_error": str(exc),
                }
                break
        if failure is not None:
            break

    durations = [entry["decode_duration_seconds"] for entry in results]
    before_values = [entry["ru_maxrss_before_kib"] for entry in results]
    after_values = [entry["ru_maxrss_after_kib"] for entry in results]
    increments = [entry["ru_maxrss_high_water_increment_kib"] for entry in results]
    summary: dict[str, Any] = {
        "completed_run_count": len(results),
        "duration_seconds_range": [min(durations), max(durations)] if durations else None,
        "ru_maxrss_before_kib_range": [min(before_values), max(before_values)] if before_values else None,
        "ru_maxrss_after_kib_range": [min(after_values), max(after_values)] if after_values else None,
        "ru_maxrss_high_water_increment_kib_range": [min(increments), max(increments)] if increments else None,
    }
    measurements = {
        "protocol": {
            "counts": list(COUNTS),
            "repetitions_per_count": REPETITIONS,
            "fresh_subprocess_per_run": True,
            "fixture_dimensions": [WIDTH, HEIGHT],
            "fixture_pattern": "RGB=(x mod 256, y mod 256, (x+y) mod 256)",
            "fixture_generation": "one deterministic PNG per subprocess; reused for repeated data URLs",
            "ru_maxrss_units": "KiB on Linux",
            "ru_maxrss_interpretation": "process high-water mark before/after decode; difference is not net RSS or retained-memory delta",
            "timing_scope": "decode_image_payloads call only",
        },
        "environment": {
            "repository_root": str(ROOT),
            "parent_supplied_commit": "88c2433",
            "working_tree_status": "not inspected; prohibited by assignment",
            "python_executable": str(PYTHON),
            "driver_python": sys.version,
            "driver_platform": platform.platform(),
            "driver_machine": platform.machine(),
            "environment_overrides": expected_env,
            "worker_command_template": exact_worker_command,
            "source_sha256": {
                "catlabel/rendering/image_payload.py": _sha256(ROOT / "catlabel/rendering/image_payload.py"),
                "catlabel/core/resource_limits.py": _sha256(ROOT / "catlabel/core/resource_limits.py"),
            },
        },
        "summary": summary,
        "runs": results,
        "failure": failure,
        "limitations": [
            "ru_maxrss reports a process lifetime high-water mark, not current or net RSS.",
            "The measurement excludes driver memory and measures each decode in a fresh worker.",
            "Fixture generation and Python imports occur before the pre-decode high-water sample.",
            "Pixel-byte hashing occurs after the post-decode high-water sample.",
        ],
        "artifacts": {
            "script": str(SCRIPT),
            "measurements": str(OUT_DIR / "measurements.json"),
            "execution_log": str(OUT_DIR / "execution.log"),
        },
    }
    (OUT_DIR / "measurements.json").write_text(
        json.dumps(measurements, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    log_lines = [
        f"repository_root={ROOT}",
        "commit=88c2433 (parent supplied; git state not inspected)",
        f"python_executable={PYTHON}",
        f"python={sys.version.replace(os.linesep, ' ')}",
        f"platform={platform.platform()}",
        f"machine={platform.machine()}",
        f"pillow={results[0]['pillow'] if results else 'unavailable'}",
        f"PYTHONPATH={environment['PYTHONPATH']}",
        f"PYTHONDONTWRITEBYTECODE={environment['PYTHONDONTWRITEBYTECODE']}",
        f"TMPDIR={environment['TMPDIR']}",
        f"worker_command_template={exact_worker_command}",
        f"runs_completed={len(results)}",
        f"failure={json.dumps(failure, sort_keys=True) if failure else 'none'}",
        "note=ru_maxrss values are process high-water marks, not net RSS",
    ]
    for source_name, digest in sorted(measurements["environment"]["source_sha256"].items()):
        log_lines.append(f"source_sha256[{source_name}]={digest}")
    for digest in sorted({entry["fixture_png_sha256"] for entry in results}):
        log_lines.append(f"fixture_png_sha256={digest}")
    (OUT_DIR / "execution.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return 1 if failure else 0


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        print(json.dumps(_worker(int(sys.argv[2]), int(sys.argv[3])), sort_keys=True))
        return 0
    return _driver()


if __name__ == "__main__":
    raise SystemExit(main())
