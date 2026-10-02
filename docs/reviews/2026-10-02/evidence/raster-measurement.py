from __future__ import annotations

import cProfile
import hashlib
import json
import pstats
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, __version__ as pillow_version
from catlabel.rendering import renderer as renderer

REPO = Path('/home/lliniewicz/Projects/catlabel')
OUT = Path('/tmp/catlabel-review-20261002/performance')


def preprocess_alpha_hoisted(img: Image.Image, gamma_value: float | None = None) -> Image.Image:
    gray = img.convert('L')
    blurred = gray.filter(ImageFilter.GaussianBlur(radius=1.0))
    gamma = renderer._auto_gray_gamma(blurred) if gamma_value is None else gamma_value
    transformed = renderer._apply_gamma(blurred, gamma)
    alpha = renderer._gray_enhance_alpha(transformed)
    enhanced = transformed.point(
        [max(0, min(255, round(value * alpha))) for value in range(256)]
    )
    equalized = ImageOps.equalize(enhanced)
    return equalized.filter(
        ImageFilter.Kernel((3, 3), [0, -1, 0, -1, 5, -1, 0, -1, 0], scale=1)
    )


def make_fixture(width: int, height: int, axis: str) -> Image.Image:
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            value = (x * 255 // (width - 1)) if axis == 'horizontal' else (y * 255 // (height - 1))
            pixels.extend((value, value, value))
    return Image.frombytes('RGB', (width, height), bytes(pixels))


def elapsed_ms(function, image: Image.Image) -> tuple[float, Image.Image]:
    start = time.perf_counter()
    output = function(image)
    return (time.perf_counter() - start) * 1000.0, output


def image_sha256(image: Image.Image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def profile_calls(function, image: Image.Image) -> dict[str, object]:
    profiler = cProfile.Profile()
    profiler.runcall(function, image)
    stats = pstats.Stats(profiler)
    renderer_calls: dict[str, int] = {}
    image_stat_calls: dict[str, int] = {}
    for (filename, _line, name), (primitive_calls, total_calls, _self, _cumulative, _callers) in stats.stats.items():
        if Path(filename).resolve() == Path(renderer.__file__).resolve():
            if name in {'_preprocess_gray_image', '_auto_gray_gamma', '_gray_enhance_alpha'}:
                renderer_calls[name] = total_calls
        if Path(filename).name == 'ImageStat.py':
            image_stat_calls[name] = total_calls
    return {
        'renderer_function_calls': renderer_calls,
        'pillow_imagestat_function_calls': image_stat_calls,
        'pillow_imagestat_init_calls': image_stat_calls.get('__init__'),
    }


def run() -> dict[str, object]:
    repo_commit = subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=REPO, check=True, text=True, capture_output=True
    ).stdout.strip()
    git_status = subprocess.run(
        ['git', 'status', '--short'], cwd=REPO, check=True, text=True, capture_output=True
    ).stdout.strip()
    cases: list[dict[str, object]] = []
    for width, height in ((384, 384), (816, 1218)):
        for axis in ('horizontal', 'vertical'):
            case_name = f'{axis}-{width}x{height}'
            image = make_fixture(width, height, axis)
            source = renderer._preprocess_gray_image
            candidate = preprocess_alpha_hoisted

            # One warm-up per method, followed by three timed calls per method.
            source(image)
            candidate(image)
            source_times: list[float] = []
            candidate_times: list[float] = []
            source_output = candidate_output = None
            for _ in range(3):
                source_ms, source_output = elapsed_ms(source, image)
                candidate_ms, candidate_output = elapsed_ms(candidate, image)
                source_times.append(source_ms)
                candidate_times.append(candidate_ms)

            source_bytes = source_output.tobytes()
            candidate_bytes = candidate_output.tobytes()
            exact_bytes_equal = source_bytes == candidate_bytes
            profile = profile_calls(source, image)

            tracemalloc.start()
            source(image)
            python_current, python_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            source_median = statistics.median(source_times)
            candidate_median = statistics.median(candidate_times)
            cases.append({
                'case': case_name,
                'input': {
                    'mode': image.mode,
                    'size': list(image.size),
                    'sha256_pixels': image_sha256(image),
                    'axis': axis,
                    'pixel_formula': 'v=x*255//(width-1)' if axis == 'horizontal' else 'v=y*255//(height-1)',
                    'rgb_pixel': '[v,v,v]',
                },
                'source': {
                    'warmups': 1,
                    'timed_samples_ms': source_times,
                    'median_ms': source_median,
                    'output_mode': source_output.mode,
                    'output_size': list(source_output.size),
                    'output_sha256_pixels': hashlib.sha256(source_bytes).hexdigest(),
                },
                'alpha_hoisted': {
                    'warmups': 1,
                    'timed_samples_ms': candidate_times,
                    'median_ms': candidate_median,
                    'output_mode': candidate_output.mode,
                    'output_size': list(candidate_output.size),
                    'output_sha256_pixels': hashlib.sha256(candidate_bytes).hexdigest(),
                },
                'median_speedup_source_over_hoisted': source_median / candidate_median,
                'exact_output_bytes_equal': exact_bytes_equal,
                'source_cprofile_calls': profile,
                'source_tracemalloc_python_current_bytes': python_current,
                'source_tracemalloc_python_peak_bytes': python_peak,
                'native_allocations_included': False,
            })
            print(f'completed {case_name}', flush=True)

    return {
        'experiment': 'source preprocess vs exact function-equivalent with _gray_enhance_alpha hoisted once before LUT',
        'provenance': {
            'repo_root': str(REPO),
            'commit': repo_commit,
            'working_tree_status_short': git_status,
            'source_file': str(Path(renderer.__file__).resolve()),
            'python_version': sys.version,
            'python_executable': sys.executable,
            'pillow_version': pillow_version,
            'cwd': str(Path.cwd()),
            'environment': {
                'PYTHONDONTWRITEBYTECODE': '1',
                'PYTHONPATH': str(REPO),
            },
        },
        'protocol': {
            'warmups_per_method_per_fixture': 1,
            'timed_samples_per_method_per_fixture': 3,
            'method_order': 'source then alpha_hoisted for warm-up and each timed round',
            'fixtures': 'RGB grayscale horizontal and vertical integer gradients at each requested size',
            'comparison': 'mode, size, direct output byte equality, and SHA256 of output pixels',
            'tracemalloc': 'one source run per fixture; Python-traced peak only; native allocations omitted',
            'cprofile': 'one source run per fixture; records _auto_gray_gamma, _gray_enhance_alpha, and Pillow ImageStat function calls',
        },
        'cases': cases,
    }


def markdown(result: dict[str, object]) -> str:
    provenance = result['provenance']
    rows = []
    for case in result['cases']:
        rows.append(
            '| {case} | {source:.3f} | {hoisted:.3f} | {speedup:.3f}x | {equal} | {calls} | {peak} |'.format(
                case=case['case'],
                source=case['source']['median_ms'],
                hoisted=case['alpha_hoisted']['median_ms'],
                speedup=case['median_speedup_source_over_hoisted'],
                equal=case['exact_output_bytes_equal'],
                calls=case['source_cprofile_calls']['renderer_function_calls'].get('_gray_enhance_alpha'),
                peak=case['source_tracemalloc_python_peak_bytes'],
            )
        )
    return '\n'.join([
        '# Grayscale preprocessing microbenchmark',
        '',
        f"Repository: `{provenance['repo_root']}` at `{provenance['commit']}`; working-tree status was `{provenance['working_tree_status_short'] or 'clean'}`.",
        f"Runtime: Python `{provenance['python_version'].split()[0]}`, Pillow `{provenance['pillow_version']}`.",
        '',
        'Source `_preprocess_gray_image` was compared with a scratch function-equivalent changing only the enhancement-alpha lookup from inside the 256-entry LUT comprehension to one call immediately before it. Blur, automatic gamma, equalize, sharpen, and all other operations call the same Pillow and renderer helpers. Each method received one warm-up followed by three timed runs; method order was source then hoisted in every round.',
        '',
        'Fixtures were RGB images whose channels share integer grayscale values: `x*255//(width-1)` for horizontal and `y*255//(height-1)` for vertical gradients, at 384×384 and 816×1218.',
        '',
        '| Fixture | Source median ms | Hoisted median ms | Speedup | Exact bytes | cProfile alpha calls | Source tracemalloc peak bytes |',
        '|---|---:|---:|---:|---|---:|---:|',
        *rows,
        '',
        'Output mode, dimensions, direct pixel-byte equality, and SHA256 were recorded for every case. cProfile recorded source helper and Pillow ImageStat call counts; the automatic-gamma ImageStat call is separate from the repeated enhancement-alpha calls. Tracemalloc ran one additional source invocation per fixture and reports Python-traced peak only; native allocations are omitted.',
        '',
        f"Exact command: `cd {provenance['cwd']} && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH={provenance['environment']['PYTHONPATH']} timeout -k 5s 175s /tmp/catlabel-review-20261002/baseline/venv/bin/python /tmp/catlabel-review-20261002/performance/measure.py`.",
        '',
    ])


if __name__ == '__main__':
    result = run()
    (OUT / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    (OUT / 'results.md').write_text(markdown(result), encoding='utf-8')
    print(f"wrote {OUT / 'results.json'} and {OUT / 'results.md'}", flush=True)
