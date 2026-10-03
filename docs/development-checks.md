# Development checks

Use Python 3.11 and the Node version in `.node-version`; install npm at the version
specified in `frontend/package.json`. The runtime's five-platform Pixi lock and
the universal CI/development dependency lock serve different purposes.

## Setup and commands

```sh
python -m pip install uv==0.11.29
uv venv --python 3.11 .venv
uv pip sync --python .venv/bin/python --require-hashes requirements-check.lock
cd frontend
npm ci
cd ..
.venv/bin/python -m tools.check --lane full --report check-results/static.json
```

On Windows, use `.venv\Scripts\python.exe`. Run results belong under ignored
`check-results/`, rather than in public documentation.

| Lane | Checks |
| --- | --- |
| `static` | Public-document visibility/links; generated dependency and document/edit-schema drift; Ruff, formatting, basedpyright, frontend TypeScript, React lint, both Knip modes, Python/frontend cycles and Import Linter contracts. |
| `fast` | Static checks plus backend and frontend unit tests. |
| `full` | The fast lane plus a production frontend build in a temporary directory. |
| `audit` | Installed Python and locked frontend dependencies against current advisory metadata. |

Vulture findings at 80% confidence or higher are advisory. Context-manager
parameters required by Python's protocol are not removable dead code merely
because their names are unused.

The runner does not replace committed frontend assets. Backend tests use a
temporary working directory and must not depend on a user's database. Paid
provider calls and physical prints belong in explicit integration checks.

Linux runs the shared Python typing gate. Windows/macOS CI explicitly use
`--without-typing`; the Windows-only SDK import test runs on Windows. Frontend
TypeScript checks remain enabled everywhere. A configured workflow or resolved
platform lock does not establish a successful native installation or print.

## Dependencies and generated contracts

`pyproject.toml` owns application, optional AI/headless/MCP/launcher and check
requirements. `python -m tools.sync_dependencies --check` rejects divergent
pip/Pixi manifests; `--write` deliberately regenerates them.

The backend document/edit models generate checked-in JSON schemas and frontend
contract types. Run `python -m tools.sync_document_contract --check` to detect
drift, or `--write` after an intentional model change.

Refresh the hash-locked checker and complete development environments explicitly:

```sh
uv pip compile --group dev --python-version 3.11 --universal --generate-hashes --output-file requirements-dev.lock
uv pip compile pyproject.toml --extra launcher --extra headless --extra ai --extra mcp --group dev --python-version 3.11 --universal --generate-hashes --output-file requirements-check.lock
```

Review, audit and test the resulting versions. Use `pixi lock --check --dry-run`
to check the runtime lock without promoting another resolution. Frontend tools
and dependencies come from `frontend/package-lock.json`; the gate does not invoke
unversioned latest tools.

## Static policy

The expected source/check diagnostic baseline is empty. `checks/debt.json` stores
individual diagnostic fingerprints if a reviewed migration needs temporary debt;
it cannot grant an allowance by total count. Removing one error cannot pay for
another. Formatting debt includes source hashes, and cycle entries identify the
complete component membership. Broad disabled rules or ignored source paths are
not acceptable fixes.

`--write-baseline` is an explicit local Linux migration operation, rejected in CI.
Review every changed allowance and remove resolved entries. New tooling and strict
contracts must not acquire baseline allowances.

Ruff checks the maintained Python, tests and stubs for Python 3.11. basedpyright
uses standard mode generally and strict mode for the contracts named in
`pyproject.toml`. The licensed `typings/winsdk` subset checks the used SDK shapes
on Linux; it does not emulate the Windows runtime. Scoped missing-runtime-source
policy is documented in the bridge, while missing imports and type errors remain
checked.

React lint covers Hooks rules. Knip checks development and production usage;
Madge checks frontend cycles. The Python graph distinguishes eager, function-local
and type-only imports; Import Linter enforces layer ownership. TypeScript strictly
checks the domain and API utilities; remaining JavaScript/JSX is outside that
compiler's scope.

Advisory collection failures, skipped packages and malformed tool output fail the
audit. `checks/audit-exceptions.json` requires exact advisory/package/version
scope, rationale, owner and expiry. Expired or unrelated exceptions fail; baseline
capture cannot create advisory exceptions.

## Public docs and releases

Keep stable user guidance, contributor contracts and upstream attribution public.
Keep dated plans, implementation ledgers, test logs, receipts and screenshots in
ignored internal locations. `python -m tools.check_docs` rejects tracked private
paths and public Markdown links to private, missing or untracked files.

Before release, inspect the exact source, locks, frontend files, installation and
update/rollback behavior. Protocol fixtures and fake devices do not establish
physical output. Record hardware/firmware/OS/media and observed outcomes privately,
and label unavailable native or provider checks clearly. Preserve an accepted
artifact during publication rather than replacing it with an uninspected rebuild.
