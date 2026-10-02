# Grayscale preprocessing microbenchmark

Repository: `/home/lliniewicz/Projects/catlabel` at `c193e93d82b13724196aa29b22d52055fd112406`; working-tree status was `clean`.
Runtime: Python `3.11.15`, Pillow `12.3.0`.

Source `_preprocess_gray_image` was compared with a scratch function-equivalent changing only the enhancement-alpha lookup from inside the 256-entry LUT comprehension to one call immediately before it. Blur, automatic gamma, equalize, sharpen, and all other operations call the same Pillow and renderer helpers. Each method received one warm-up followed by three timed runs; method order was source then hoisted in every round.

Fixtures were RGB images whose channels share integer grayscale values: `x*255//(width-1)` for horizontal and `y*255//(height-1)` for vertical gradients, at 384×384 and 816×1218.

| Fixture | Source median ms | Hoisted median ms | Speedup | Exact bytes | cProfile alpha calls | Source tracemalloc peak bytes |
|---|---:|---:|---:|---|---:|---:|
| horizontal-384x384 | 44.623 | 3.919 | 11.385x | True | 256 | 17128 |
| vertical-384x384 | 78.918 | 5.110 | 15.442x | True | 256 | 17128 |
| horizontal-816x1218 | 196.848 | 25.067 | 7.853x | True | 256 | 17128 |
| vertical-816x1218 | 405.596 | 25.848 | 15.692x | True | 256 | 17128 |

Output mode, dimensions, direct pixel-byte equality, and SHA256 were recorded for every case. cProfile recorded source helper and Pillow ImageStat call counts; the automatic-gamma ImageStat call is separate from the repeated enhancement-alpha calls. Tracemalloc ran one additional source invocation per fixture and reports Python-traced peak only; native allocations are omitted.

Exact command: `cd /tmp/catlabel-review-20261002/performance && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/lliniewicz/Projects/catlabel timeout -k 5s 175s /tmp/catlabel-review-20261002/baseline/venv/bin/python /tmp/catlabel-review-20261002/performance/measure.py`.
