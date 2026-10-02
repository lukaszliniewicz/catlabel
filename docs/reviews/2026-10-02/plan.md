# CatLabel maintenance and modernization plan

This is a proposed plan based on the [2 October review](README.md), [baseline](baseline.md) and [dependency inventory](dependencies.md). Implement in small reviewable changes, retain project-data recovery copies, and isolate dependency upgrades from behavioral refactors. Complete each phase's acceptance before promoting the affected release.

## Phase sequence

| Phase | Scope | Completion gate |
| --- | --- | --- |
| 0 | Reproducible checks and test isolation | One documented developer/CI check route; tools/config pinned; baseline captured without hiding failures |
| 1 | Immediate backend and printer correctness | Wrong classification, key exposure, overlapping sessions, input limits and row packing covered by focused regression tests |
| 2 | Dedicated debt elimination and maintenance | Default Ruff/format, curated Python typing, full React rules and Knip reach their agreed zero-debt gates; targeted import cycles removed |
| 3 | Released TiMini-Print synchronization | v0.8.1 catalog/schema/protocol/runtime parity ledger, fixtures and explicit hardware evidence for changed families |
| 4 | Installation and dependency migrations | Locked native installation/upgrade/repair matrix and separately accepted dependency bundles |
| 5 | Frontend decomposition and UX | Stable editor contracts, responsive/keyboard acceptance, truthful readiness/save states and recoverable drafts |
| 6 | Measured performance and backend lifecycle | Correct render readiness, bounded memory, renderer ownership and measured editor/job performance |
| 7 | Ongoing maintenance | Ratchets remain green, stale exceptions disappear, dependency/upstream checks have owners |

Phase 1 safety/correctness fixes can proceed as soon as phase 0 produces reproducible tests. Small patched dependency updates may accompany phase 1 in a separate change. Major upgrades must wait for the relevant tests and peer/engine compatibility; hardware coverage may keep a new family deferred rather than block unrelated work.

Implementation scope clarification: the user has Linux available and requested best effort for Windows/macOS. Validate their locks, bootstrap branches and portable interfaces, label native execution unverified, and do not block local implementation on unavailable native systems. Physical printer receipts remain separate from source/fixture parity; see the current [implementation ledger](../../maintenance-progress.md) and [upstream parity ledger](../../upstream-parity.md).

## Phase 0 Reproduce the baseline and introduce check policy

Add `pyproject.toml` for Ruff/basedpyright configuration and a locked development feature/environment. Preserve Python 3.11 initially. Use the tested Node 24 toolchain with a recorded version and `npm ci`; define a supported engine floor compatible with the selected tooling. Resolve a single authoritative dependency declaration, with generated compatibility requirements rather than manually divergent copies. Add CI on Linux, Windows and macOS for platform-relevant code; native installation tests belong to phase 4.

Make backend tests hermetic: create their own schema/data directory, never rely on a pre-existing project database, and fix the Windows path assertion to test platform-appropriate behavior. Add linting for launcher/tools/config scripts, not only app modules. Introduce a portable `check` command and distinct fast, integration and hardware lanes. Frontend's existing `npm run check` remains the starting point.

| Surface | Proposed gate | Initial migration handling |
| --- | --- | --- |
| Python lint | Ruff `E4,E7,E9,F,I,UP,B,SIM,C4`, Python 3.11 target; select additional rules only for demonstrated value | Fix 36 default findings first; preserve compatibility re-exports explicitly. Audit import/syntax autofixes. Do not gate on E501's 652 prose/line-length findings. |
| Python format | `ruff format --check catlabel launcher.py tools tests` | One isolated formatting change for 83 files; no behavioral edits in it. |
| Python typing | basedpyright `standard` for all application/launcher/tool/test code; strict for new or newly extracted typed domain/protocol contracts | Commit a diagnostic-specific baseline for reviewed existing source debt, plus an uncapped report. Missing optional/platform modules require correct feature/platform environments or maintained stubs, not project-wide suppression. Ratchet down to zero. |
| React correctness | Full installed Hooks recommended preset, retaining `exhaustive-deps` as error; scoped React Refresh rule | Review 19 diagnostics individually. External-resource effects remain where needed; no blanket disabling of effect rules. |
| JS/TS typing | Incremental checked JSDoc or TypeScript at document, API, printer capability and store interfaces | Avoid enabling noisy whole-app `checkJs` and calling the result policy. Establish named included modules, then expand the checked boundary with decomposition. |
| Frontend dead code | Pinned Knip, configured entry `src/main.jsx` and tests; source/config project scope; production and full modes | Exclude generated dist from analysis; resolve the two unused-export candidates. Track lazy imports and configuration plugin entry points. No broad ignore lists. |
| Python dead code | Vulture >=80% as advisory; corroborate before removal | Zero candidates is not proof of no dead code. Preserve API decorators, registries and platform bridges. |
| Import boundaries | Import Linter contracts plus a deterministic import/SCC report; frontend import-cycle check with JSX/TS resolution | Preserve zero import-time cycles; reject new unreviewed full-graph SCCs and reduce main↔AI/protocol aggregation coupling. Distinguish deferred/type-only edges. Add tests for stateless protocol and transport ownership. |
| Dependency hygiene | npm audit, Python pip-audit or OSV against resolved per-platform environments, lock consistency and peer checks | Classify runtime/dev exposure and advisory trigger conditions. Reject new unreviewed high/critical findings; exceptions need exact advisory, rationale, owner and expiry. |

Pin the checker versions and record their commands, scope and environment. Missing checks fail CI rather than silently skip. Check only appropriate native modules on each OS and separately test compatibility of shared interfaces. New baseline entries, ignored paths and disabled rules require explicit review. A frozen fingerprint/rule budget must prevent trading one old error for an unrelated new error; a total-count threshold alone is insufficient.

Acceptance: 67 backend tests pass in a fresh disposable test environment on their supported platforms; 21 existing frontend tests remain green; current lint/build remain green; expanded checks produce repeatable diagnostics and CI rejects a deliberately introduced new error. No application data are touched.

## Phase 1 Repair concrete correctness and local operation

1. Narrow vendor matching and enforce specific-name precedence. Own `vendors/phomemo/manifest.py`, `vendors/registry.py` and generic detection interactions. Test D80/D100, unsupported D1/D2, M02PRO/M02 PRO, actual D30 names, ambiguous names, prefixes/MAC rules and the unknown sentinel. A dedicated vendor must not bypass an unsupported or conflicting classification silently.
2. Default the server to loopback. Keep LAN operation an explicit configured mode with authentication; restrict origins and protect state-changing local endpoints from cross-origin requests. Make provider keys write-only, return `has_api_key`/masked status, preserve existing keys when no replacement is supplied, redact logs/exports, and remove GET-side configuration seeding. Test responses never contain a sample saved key.
3. Add shared per-device admission control keyed by canonical normalized address. Initially reject a concurrent job with a structured busy response rather than build a durable scheduler. Keep independent printers usable. Define cancellation/disconnect cleanup and ensure timeout at the client does not imply the physical job stopped. Reject unsafe automatic retries after uncertain partial output.
4. Enforce positive integer counts, encoded payload/upload limits, decoded pixels, dimensions/pages/copies and matrix products on the backend before allocation/connection. Start with the existing frontend's 1,000 records, 100 copies, 500 output jobs and 50 million render pixels, reconciling both sides with a shared contract; encoded bytes need an additional tested cap. Validate file content, filenames and resource cleanup for font/PDF/import uploads.
5. Make Niimbot rejection/timeouts explicit outcomes; distinguish sent, accepted, complete and completion-unknown where the protocol lacks proof. Add reply-driven tests. Repair Phomemo per-row byte packing for widths 1/7/8/9/15/16 and verify dimensions/packing against fixtures.
6. Stage and validate all upstream catalog files before mutation. Handle the origin-file rename and schema version explicitly; provenance describes the entire applied set. Any acquisition/validation failure leaves the previous catalog intact. Keep actual catalog upgrade in phase 3.
7. Validate project parent references, prevalidate complete imports and commit the tree once. Add document schema/version validation and optimistic revisions to prevent lost updates across tabs. Preserve legacy documents through explicit migrations; return useful missing/corrupt-document errors rather than silently losing them.

Acceptance: focused API tests cover rejection before side effects, two competing clients, partial/unknown device completion, invalid import rollback and legacy project loading. Verify default network binding and provider DTOs. Protocol tests use fake devices; actual changed-family hardware evidence is tracked separately.

## Phase 2 Eliminate measured debt

Use a dedicated maintenance phase, not an indefinite baseline exemption. Work order: undefined annotations/imports and default lint; explicit compatibility exports; isolated formatting; modern annotations and clear ownership; type-correct SQLModel/FastAPI/transport interfaces; React component identities and derived state; unused exports and cycles.

The baseline's 199 Python diagnostics include seven missing optional/platform imports; classify those first, then repair the remaining source diagnostics by ownership. Type-only imports can fix the four undefined annotation names without runtime cycles. Framework-recommended dependency injection and SQL expression patterns need narrowly justified configuration or correct types, not blind automatic rewriting. Vulture's zero results do not authorize deleting registries.

Remove API main↔AI route coupling by extracting context assembly into a shared service consumed by both routes. Move protocol primitives/type definitions below registries and stop family modules from depending back on aggregation modules. Preserve legacy public imports with explicit compatibility modules/exports. Verify snapshots and layer tests before deleting an alias.

Milestones: default Ruff 36→0; formatter 83→0; two Knip exports→0 or specifically documented intentional exports; React recommended 19→0 reviewed diagnostics; Python source baseline→0 across the supported platform/feature matrix. No new runtime SCC; remove both recorded SCCs after classifying aggregation/type-only edges. Keep advisory checks informative without misrepresenting them as enforced gates.

Acceptance: full tests and import smoke checks after each coherent cleanup; no suppressions that merely conceal the baseline. Snapshot each milestone and require new/changed typed interfaces to pass without baseline entries. Enable the clean checks as hard gates once the cleanup lands.

## Phase 3 Adopt TiMini Print changes deliberately

Target released v0.8.1 first. Build a delta ledger recording exact upstream tag/SHA, local owner, imported/modified/deferred behavior and fixtures. Review catalog and runtime deltas together. Keep separate Niimbot/Phomemo ownership and a truthful model support state rather than enabling every upstream record.

Implement detection schema normalization and richer conditions; Tiny flow control and Classic receive pump; V5X framing/acknowledgement/readiness/signing/opaque-stream changes; Eleph/ToPrint separation and paper transforms; Funny LX correction; then new S001 runtime. Review D11S and dedicated vendor parity explicitly. Acquire released sources without importing unrelated upstream UI or installer behavior.

Keep stateless encoders in `protocol`, notification/state interpretation in `printing/runtime`, device transfer profiles in `devices`, and bytes/receive lifecycle in `transport`. Split the large Bluetooth backend only where the receive lifecycle or discovery/session responsibilities justify it.

Acceptance per family: byte fixtures; fragmented/coalesced and command-looking raster inputs; pause/resume; missing/negative replies; reconnect/cleanup; paper orientation/polarity; multi-page completion and retry semantics. Run applicable BLE/SPP Windows/Linux/macOS checks. Hardware receipts name model, firmware, transport, label/media and observed outcome. Until hardware is available, report source/fixture parity separately from physical acceptance and keep new support experimental/deferred.

Then evaluate selected master commits: complete-payload parser, control notification routing/pre-write hook, Luck APA49/A4 and Print Master ownership. Pin each adopted commit. Do not update the baseline to moving master.

## Phase 4 Installation and staged package updates

Use Pixi as the common locked bootstrap already established on Windows, after verifying solver/package support on linux-64/linux-aarch64/osx-64/osx-arm64. Split platform bridges and optional headless/provider features. Retain a practical fallback only where a platform cannot resolve, with its own generated lock. Pin and checksum bootstrap binaries on every OS; resolve paths from script location; add consistent `--setup-only`, `--install-headless`, `--skip-headless`, `--repair` and diagnostic output.

Move installed users to selected release manifests/artifacts rather than automatic repository-head pulls. Stage an update, back up/check project database compatibility, verify health/frontend identity, promote, and retain the prior accepted runtime until acceptance. A failed update must clearly identify that the local version is being used. Handle interrupted first setup and offline restart; never tell users to delete a data-bearing folder as a routine repair step.

Package bundles, each with its own rollback/acceptance:

- Prompt patches: DOMPurify, PostCSS and applicable transitive advisory fixes; Python patch/minor refresh; launcher pins. Run audit again after every resolved lock change.
- React group: React/DOM/React-Konva 19.3 together with compatible Konva; Zustand and barcode patches. Visual/editor/render-output checks are required.
- Markdown/formatters/icons: react-markdown 10 (replace its removed `className` prop with a wrapper), js-beautify 2, Lucide 1; test chat layout, formatting and icon names/lazy bundle size.
- Toolchain: Vite 8/plugin-react 6 with its Rolldown/Oxc migration and the root-logo/manual-chunk plugin; Vitest 5/jsdom 30 with timer/mock/image test review. Intermediate Vite 7 or Vitest 4 is acceptable if necessary for a simpler security-fix route; record final targets and migration steps.
- CSS: Tailwind 4 only after visual regression cases are established. Replace the PostCSS integration and migrate configuration, dark mode and preflight intentionally. Validate HTML label raster output as well as the app shell.
- ESLint 10 only when `eslint-plugin-react` declares support or the required plugin surface has a tested replacement. Current latest plugin peers stop at ESLint 9; do not force-install an incompatible tree. Keep 9.39.5 meanwhile and enable the broader Hooks checks now.
- AI dependencies: investigate the LiteLLM `<1.92.0` cap before changing it; trace Vertex/provider needs and Google aiplatform 2 migration. Validate provider request construction with fixtures and credentials-free tests; any live paid calls need a separate scoped test budget. Exclude known compromised versions and audit the resolved tree.

Acceptance: fresh/repeat install, repair, headless add-on, path with spaces, wrong cwd, interrupted download and offline boot on supported native systems. Record cold/warm timing and download footprint rather than promise speed. Normal design/printing needs neither system Python/Node nor optional Chromium. Verify the checked-in frontend artifact matches the tested source/lock/build manifest without rebuilding during promotion.

## Phase 5 Decompose the frontend and improve UX

Compose one Zustand store from named document/history, selection, printer, settings, persistence, batch/job and UI slices. Extract pure document normalization/page/template/geometry helpers into domain modules. Preserve atomic hydration, per-page isolation, physical-mm scaling, snapshot consistency, undo reset on project switch and existing selectors. Add typed document/item unions, printer capability DTOs and job/error states at these boundaries before migrating leaf components.

Split PropertiesPanel into canvas/printer defaults, template settings and typed element editors with shared labeled numeric controls. Split AIAssistant into chat presentation, provider/session interaction, external JSON flow and canvas command integration; keep destructive/physical side effects explicit. Split CanvasArea into page preview, selection/transform/keyboard/pan and capture orchestration. Rendering code remains shared across editor, local batch and headless output. Avoid circular domain→component→store imports.

Separate onboarding completion from AI media settings. Offer Start designing, later printer setup and later AI setup. Search models and show distinguishing geometry/protocol/transport; explain unknown/ambiguous/unsupported states without guessing. Persist useful profile choice while distinguishing offline configuration from connected device readiness. Print readiness includes connected printer, paper and accepted capability settings.

Add dirty/saving/saved/failed states, protection before replacing unsaved work and recoverable local drafts with schema/revision metadata. A recovered draft must not silently overwrite a newer saved project. Replace disruptive alerts with contextual errors/actions and consistent progress/cancel affordances. Backend truth controls completion wording.

Make narrow layouts canvas-first with drawers closed by default, update on breakpoint changes and ensure overlays can be dismissed by keyboard. Associate all fields with labels; implement tab keyboard navigation, pressed state, focus visibility, sufficient contrast, usable pointer targets and pointer/touch numeric scrubbing. Scope canvas shortcuts away from editable regions/dialogs. Add a keyboard-accessible object list/selection path for canvas items. Preserve modal focus restoration and make covered background content inert where appropriate.

Acceptance: create/edit/save/reload, project switch and draft recovery, DPI/printer switch, mixed HTML/canvas pages, batch CSV, offline setup and print errors at 390×844, 768, 1222 and >=1280 px. Keyboard-only completion and automated accessibility checks supplement parent visual inspection. Lazy chunk failures have an error boundary/retry affordance; loading never becomes a permanent blank overlay.

## Phase 6 Performance and backend lifecycle

Land the measured alpha hoist with exact-pixel regression coverage; rerun the recorded experiment once. Then fix rendering correctness: await all fonts/images/HTML/code resources through a per-job readiness contract, propagate errors and cancel stale tasks, and remove readiness dependence on fixed sleeps. Cache identical renders/codes within bounded budgets keyed by content, dimensions, font, record and dither state.

Choose one owning async Playwright service with a bounded semaphore/queue, deterministic shutdown and broken-browser recovery. Use the current application's explicit headless URL and job-size-aware deadline; avoid accidentally rendering an unrelated dev server as fallback. Verify concurrent requests, timeout/cleanup and large but permitted jobs. Separate render completion from physical device completion.

Virtualize page/record previews and use thumbnails for inactive content. Keep only visible interactive stages; export uses full-resolution state. Profile before item indexing or narrower selectors. Disable hit testing for noninteractive output and release caches when not needed. Benchmark IconPicker cold load/search and use a purpose-built searchable icon data boundary if the measured delay warrants it.

Replace whole-job base64 accumulation with bounded render/encode/transmit chunks. Track total labels, queued/rendered/sent/accepted/completed states and precise cancellation boundaries. Deduplicate copies only when device protocol supports that behavior. Add paginated project summaries/detail retrieval so a tree fetch does not load every embedded image. Stream PDF/pages and encoded jobs as practical, retaining limits and output parity.

Representative benchmark matrix: one 384×384 label; 20 pages; ten records; 200 canvas items; mixed HTML/images/barcodes; 100 labels; 4×6 PDF pages; two render requests and competing print submissions. Record p50/p95 edit/render latency, longest main-thread task, stage count, JS/heap and process RSS, time to first send, throughput and output checksum/geometry. Use fixed fixtures, pinned runtimes and declared hardware; compare the same build/hardware.

Proposed starting targets, to confirm against that matrix: common edit responses p95 <=100 ms; continuous drag frame p95 <=32 ms on the reference desktop; no new repeated >50 ms main-thread tasks in those interactions; no >10% unexplained regression in an unchanged path; memory bounded by configured queue/chunk capacity rather than total batch size. These are acceptance targets, not measured baseline claims. Treat print fidelity and absence of duplicate output as hard gates. Compiler adoption remains an optional follow-up experiment, not a substitute for these fixes.

## Phase 7 Keep debt from returning

Assign an owner for each remaining compatibility exception and hardware gap. Review dependency advisories/patches and upstream release deltas monthly, with major upgrades proposed separately. Refresh baseline artifacts only for reviewed scope/config changes; remove fixed fingerprints automatically and reject additions without review. Include dependency locks, checker versions, test summaries, source/frontend identity and hardware evidence in each release receipt.

Schedule no automation as part of this review. Establish the maintenance routine during implementation, with a monthly debt report and smaller weekly dependency checks if the project has active releases. Do not let an optional migration such as Tailwind 4 postpone concrete classifier, completion or local-secret fixes.
