# Development checks and static debt policy

Use Python 3.11.15 and Node 24.18.0 (`.node-version`), with npm 11.16.0. The application runtime's existing Windows Pixi lock remains separate from the universal CI/development lock until the native-installation phase is accepted.

Create an isolated environment and install the **hash-locked** check dependencies:

```sh
python -m pip install uv==0.11.29
uv venv --python 3.11 .venv
uv pip sync --python .venv/bin/python --require-hashes requirements-check.lock
cd frontend
npm ci
cd ..
.venv/bin/python -m tools.check --lane full --report check-results/static.json
```

On Windows use `.venv\Scripts\python.exe` for the environment's interpreter. Linux owns the current shared typing baseline. The Windows/macOS CI lanes run `--without-typing` explicitly; the Windows SDK runtime imports are checked by a Windows-only unit test. Native execution and hardware acceptance remain separate. No check is silently skipped. Native CI results and clean native installation are separate from the Linux results recorded here.

`--lane static` runs Ruff, formatter, basedpyright, full React Hooks rules/config lint, both Knip modes, Python/frontend cycle detection and Import Linter contracts. Vulture >=80% remains an advisory report. `--lane fast` adds backend/frontend unit tests. `--lane full` adds a production build in a temporary directory. Tests also use a temporary cwd; they must not require a pre-existing user database. The runner leaves tracked frontend artifacts unchanged.

`--lane audit --report check-results/audit.json` audits the installed resolved Python environment and frontend lock tree against live advisory metadata. Any dependency collection failure, skipped Python package, missing tool or malformed output fails the check. Advisory execution is distinct from a zero-advisory result. The current audit gate is Linux-only; native resolved audits remain acceptance work. No paid provider calls or physical prints belong in these lanes.

Hardware/integration acceptance requires named device, firmware, OS, transport, media, source/build identity, observed physical outcome and timeout/retry evidence. It must be recorded separately; a fake-device unit pass is not a hardware receipt. Browser integration acceptance is parent-owned and specified in the [maintenance plan](reviews/2026-10-02/plan.md).

## Canonical dependencies and locks

`pyproject.toml` owns application requirements and optional headless/launcher dependencies. `python -m tools.sync_dependencies --check` rejects divergent pip/Pixi manifests. `--write` explicitly regenerates `requirements.txt`, `launcher-requirements.txt` and `pixi.toml`. It currently supports the established win-64 Pixi runtime only; adding native platforms belongs to phase 4.

`requirements-dev.lock` pins the checker-only environment; `requirements-check.lock` includes app, launcher, optional renderer and check dependencies for reproducible CI. Neither replaces the accepted Windows runtime lock. Refresh deliberately:

```sh
uv pip compile --group dev --python-version 3.11 --universal --generate-hashes --output-file requirements-dev.lock
uv pip compile pyproject.toml --extra launcher --extra headless --group dev --python-version 3.11 --universal --generate-hashes --output-file requirements-check.lock
```

Review the resolved changes and audit/test them. Pin checker versions in the dev group. Use `pixi lock --manifest-path pixi.toml --check --dry-run` to verify existing runtime-lock consistency without promotion. Node dependencies/checkers are pinned through `frontend/package-lock.json`; no `npx latest` is used by the runner.

## Temporary debt, without hiding new failures

`checks/debt.json` contains individual current diagnostics, not a total-count allowance. Path, rule, message, severity and exact location are retained where supplied. Identical duplicate findings are counted. Removing an old error cannot pay for an unrelated new one. Moving existing debt intentionally requires reviewing the baseline diff; line drift is not automatically forgiven. Formatter debt includes source hashes, so editing an unformatted file requires cleaning it. Cycle allowances name the complete existing SCC membership.

The uncapped `--report` output always includes existing debt. `--write-baseline` is a deliberate local Linux migration operation and is rejected in CI; it is not the default check. New tooling is strict-typed and may not acquire baseline entries. After a coherent cleanup, remove resolved entries and review every added/moved entry before committing. Phase 2 eliminates the migration baseline rather than keeping it forever. Broad disabled rules/ignored source paths are not an acceptable fix.

Ruff targets Python 3.11 with `E4,E7,E9,F,I,UP,B,SIM,C4`; line-length E501 is excluded. Application, launcher, tool, test and maintained `.pyi` source are linted/formatted and type-checked. basedpyright uses standard mode for existing code and strict mode for the named check/domain contracts in `pyproject.toml`. The headless import is included in the locked check environment.

The Windows-only `winsdk` dependency has a pinned-wheel-derived, licensed structural subset under `typings/winsdk`. This checks used SDK signatures on Linux without pretending the native extension can run there. Only `reportMissingModuleSource` is disabled in `windows_winrt.py`: its stub-only runtime source is intentionally unavailable in this environment. Missing imports and type errors remain enabled. This is a documented platform policy, not a source-debt allowance. The Windows CI test calls the real SDK import helper; fake-SDK tests cover the selector overload and nullable device. Wheel/version changes require refreshing the subset and its provenance. Native Windows execution remains unverified until the corresponding CI/install checks run. [Basedpyright documents the distinction and scoped diagnostic configuration](https://docs.basedpyright.com/v1.40.1/configuration/comments/).

Knip includes source/config entry points, excludes generated dist, and marks production entry/project patterns explicitly. Tests are excluded only from production analysis. Madge resolves JS/JSX imports. The deterministic Python graph distinguishes function-local/type-only edges from eager edges and reports unresolved dynamic imports. No new eager cycle is allowed. Import Linter also checks indirect paths. Device transfer policy consumes stable string identifiers without importing protocol implementations; the temporary device-policy → family-ID exception has been removed. The API context service and protocol specification ownership remove both former full-graph cycles.

`checks/audit-exceptions.json` requires an exact advisory/package/version scope, owner, rationale and expiry. New findings and expired exceptions fail, including on the same package. Baseline capture cannot create advisory exceptions. Current exceptions are migration debt, not a claim that vulnerable versions are safe; prompt patches and the tested Vitest migration must remove them. Their initial deadline is 16 October 2026.

The GitHub workflow runs shared checks/tests/builds on Linux, Windows and macOS and preserves uncapped reports. It is configured locally; do not claim hosted CI passed until actual runs are inspected.
