# Development checks and static debt policy

Use Python 3.11.15 and Node 24.18.0 (`.node-version`), with npm 11.16.0. The five-platform Pixi runtime lock is separate from the universal CI/development lock. Native acceptance is recorded separately from lock resolution.

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

`pyproject.toml` owns application requirements and optional AI/headless/launcher dependencies. `python -m tools.sync_dependencies --check` rejects divergent pip/Pixi manifests. `--write` explicitly regenerates `requirements.txt`, `requirements-ai.txt`, `launcher-requirements.txt` and `pixi.toml`. The generator maps platform bridges to win-64/osx-64/osx-arm64 targets and resolves common dependencies across all five declared platforms. Overlapping normalized requirements are rejected.

`requirements-dev.lock` pins the checker-only environment; `requirements-check.lock` includes app, launcher, optional renderer and check dependencies for reproducible CI. Neither replaces the runtime lock. Refresh deliberately:

```sh
uv pip compile --group dev --python-version 3.11 --universal --generate-hashes --output-file requirements-dev.lock
uv pip compile pyproject.toml --extra launcher --extra headless --extra ai --group dev --python-version 3.11 --universal --generate-hashes --output-file requirements-check.lock
```

Review the resolved changes and audit/test them. Pin checker versions in the dev group. Use `pixi lock --manifest-path pixi.toml --check --dry-run` to verify existing runtime-lock consistency without promotion. Node dependencies/checkers are pinned through `frontend/package-lock.json`; no `npx latest` is used by the runner.

## Temporary debt, without hiding new failures

`checks/debt.json` contains individual current diagnostics, not a total-count allowance. Path, rule, message, severity and exact location are retained where supplied. Identical duplicate findings are counted. Removing an old error cannot pay for an unrelated new one. Moving existing debt intentionally requires reviewing the baseline diff; line drift is not automatically forgiven. Formatter debt includes source hashes, so editing an unformatted file requires cleaning it. Cycle allowances name the complete existing SCC membership.

The uncapped `--report` output always includes existing debt. `--write-baseline` is a deliberate local Linux migration operation and is rejected in CI; it is not the default check. New tooling is strict-typed and may not acquire baseline entries. After a coherent cleanup, remove resolved entries and review every added/moved entry before committing. Phase 2 eliminates the migration baseline rather than keeping it forever. Broad disabled rules/ignored source paths are not an acceptable fix.

Ruff targets Python 3.11 with `E4,E7,E9,F,I,UP,B,SIM,C4`; line-length E501 is excluded. Application, launcher, tool, test and maintained `.pyi` source are linted/formatted and type-checked. basedpyright uses standard mode for existing code and strict mode for the named check/domain contracts in `pyproject.toml`. The headless import is included in the locked check environment.

The Windows-only `winsdk` dependency has a pinned-wheel-derived, licensed structural subset under `typings/winsdk`. This checks used SDK signatures on Linux without pretending the native extension can run there. Only `reportMissingModuleSource` is disabled in `windows_winrt.py`: its stub-only runtime source is intentionally unavailable in this environment. Missing imports and type errors remain enabled. This is a documented platform policy, not a source-debt allowance. The Windows CI test calls the real SDK import helper; fake-SDK tests cover the selector overload and nullable device. Wheel/version changes require refreshing the subset and its provenance. Native Windows execution remains unverified until the corresponding CI/install checks run. [Basedpyright documents the distinction and scoped diagnostic configuration](https://docs.basedpyright.com/v1.40.1/configuration/comments/).

Knip includes JavaScript/JSX/TypeScript/CSS source and config entry points, excludes generated dist through its project scope, and marks production entry/project patterns explicitly. CSS imports are checked after the Tailwind 4 migration; generated output needs no redundant ignore. Tests are excluded only from production analysis. Madge resolves JS/JSX/TypeScript imports. The deterministic Python graph distinguishes function-local/type-only edges from eager edges and reports unresolved dynamic imports. No new eager cycle is allowed. Import Linter also checks indirect paths. Device transfer policy consumes stable string identifiers without importing protocol implementations; the temporary device-policy → family-ID exception has been removed. The API context service and protocol specification ownership remove both former full-graph cycles.

`checks/audit-exceptions.json` requires an exact advisory/package/version scope, owner, rationale and expiry. New findings and expired exceptions fail, including on the same package. Baseline capture cannot create advisory exceptions. The initial three Vitest exceptions, due 16 October 2026, were removed after the tested Vitest 5 migration and a clean advisory refresh. The current exception list is empty.

The GitHub workflow runs shared checks/tests/builds on Linux, Windows and macOS and preserves uncapped reports. It is configured locally; do not claim hosted CI passed until actual runs are inspected.

Current acceptance availability (user-confirmed): Linux only. Windows and macOS validation is best effort; successful lock resolution, script/interface checks and configured CI are evidence about those artifacts, not proof of a native install or print. Unavailable native runs are recorded without blocking local implementation.

TypeScript 5.9.3 checks `src/domain/**/*.ts` and `src/utils/**/*.ts` strictly with no emit, unused declarations, implicit returns or unchecked indexed access. This gate is always enabled, including native lanes that omit the Linux-owned Python typing check. Compiler diagnostics cannot acquire debt allowances. The remaining JavaScript/JSX is outside this typing scope; a typed serializer does not validate its callers. Expand the checked boundary deliberately as decomposition proceeds. TypeScript 7 is deferred until the installed analysis tools declare compatible peer ranges.

TypeScript source is also covered by the pinned typescript-eslint 8.71.0
`recommendedTypeChecked` rules, scoped to `src/**/*.ts` with project service.
Unknown response bodies must be narrowed before access; unsafe assignments and
unhandled promises are checked. The existing React/Hooks policy applies to JS/JSX.
Both scopes run through the same ESLint command; there is no ignored-TypeScript
success. [Official flat-config setup](https://typescript-eslint.io/getting-started/).

The typed JSON request boundary includes response body consumption and validation
in its deadline and preserves caller cancellation. Raw `apiFetch` returns at
successful headers; callers that consume a body should use `apiJson` to keep that
consumption inside the deadline. These checks cover the boundary contracts, not
whole-app JavaScript typing.

## Maintenance ownership and review cadence

The CatLabel repository maintainer owns dependency selection, accepted exceptions,
upstream scope and release decisions. The author of a change owns its focused checks
and receipt; the integrating maintainer owns the combined gate and exact shipped
artifact. A delegated test or review does not transfer acceptance ownership.

| When | Owner | Required action and recorded result |
| --- | --- | --- |
| Every change | Change author and integrating maintainer | Run the static gate and relevant tests; run the full lane for integration. Keep all ten diagnostic categories at zero. Review every suppression, ignored path and boundary change. |
| Weekly during active development | Repository maintainer | Run the live advisory lane against the resolved environment. Review actionable security patches; retain the uncapped report, resolved versions and disposition. Next review: 10 October 2026. |
| Monthly | Repository maintainer | Review upstream releases and the pinned parity ledger, dependency minors/majors, compatibility deferrals and outstanding acceptance gaps. Publish a dated debt report. Next review: 3 November 2026. |
| Before a release | Integrating maintainer | Verify source/lock/checker identity, exact built frontend, install/update/rollback evidence, and changed protocol-family fixtures. Distinguish physical/native/provider evidence from fixtures. |

The cadence is a manual maintenance policy. No reminder or recurring automation has
been scheduled. Missing future reports are not represented as already completed.

A monthly debt report records the source commit, environment/checker versions, all
uncapped static/advisory counts, remaining exceptions with owners and expiry,
upstream tag/SHA and adopted/deferred deltas, dependency decisions and new evidence.
Compare diagnostic fingerprints, not just totals. The historical review baseline
is immutable; a green new tool/configuration does not retroactively change it.
Vulture remains advisory: context-manager parameters such as `exc_type` are part of
the Python protocol and are not removable dead code merely because their names are
unused. Record reviewed advisory candidates rather than adding meaningless reads.

Current compatibility deferrals have concrete reconsideration triggers:

- ESLint10: reconsider when the installed React plugin declares compatible peers,
  or after a deliberately tested replacement of that rule surface. Owner: repository
  maintainer. Review by 3 November2026; do not force an incompatible dependency tree.
- TypeScript7: reconsider when the installed analysis tool peers support it and the
  domain/API fixtures pass. Owner: repository maintainer. Review by 3 November2026.
- Windows/macOS native installs and transports: best effort until native runners
  are available. Owner: repository maintainer. Reassess availability monthly; keep
  portable script/lock evidence separate from native execution.
- Physical PD01 and Niimbot checks: confirm the actual Niimbot model before choosing
  its hardware recipe; record model/firmware/media/transport and visible output.
  Owner: repository maintainer. No automatic enablement follows from a calendar date.

These are compatibility/acceptance deferrals, not advisory exemptions. The advisory
exception list is currently empty. Any future advisory exemption needs its exact
package/version/advisory, rationale, owner, expiry and review receipt; the check gate
rejects an expired exemption or an unrelated replacement finding.

Each release receipt must include the source commit and dirty-state disposition,
resolved lock/checker hashes and versions, commands and test outcomes including
skips, static and live advisory reports, inspected frontend file manifest/digest,
installation/update/rollback scope, relevant fixture hashes, and actual hardware or
provider receipts when performed. Unavailable checks remain explicitly unverified.
Never replace an accepted artifact with an uninspected rebuild during promotion.
