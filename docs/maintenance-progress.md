# Maintenance implementation ledger

Objective: implement the complete [2 October maintenance plan](reviews/2026-10-02/plan.md), making coherent verified commits. A completed checkpoint is not completion of the overall objective.

| Phase | State | Evidence / remaining work |
| --- | --- | --- |
| 0 — reproducible checks | Implemented locally; native acceptance open | Review committed as `0e61a31`; hermetic/portable tests as `2718c08` (67/67). Canonical dependencies, hashed check locks, diagnostic ratchet, graph/contracts, advisory gate and native CI are integrated. Full Linux check: 83 backend tests, 21 frontend tests and scratch production build pass. A deliberately introduced F821 failed the actual static gate; no new tooling debt is baselined. Existing Pixi lock verified unchanged by dry-run. Hosted/native validation remains unverified. |
| 1 — correctness and local operation | Implemented locally; hardware acceptance open | Classification/row packing, local-server/provider-secret fixes, device admission and Niimbot acknowledgements, shared processing limits, safe catalog publication and project transactions/revisions are integrated. Full Linux checks pass: 300 backend tests, 28 frontend tests and a scratch production build. |
| 2 — debt elimination | Implemented locally; native acceptance open | All source/check debt gates are zero, both full Python SCCs are removed, and no import-contract exception remains. 329 backend tests pass with one native SDK test skipped on Linux; 33 frontend tests and production build pass. |
| 3 — upstream parity | Implemented locally within pinned scope; hardware acceptance open | Released generic/dedicated recipes, Classic receive and selected BLE hooks pass fixtures. Pinned Luck A4 overlay/transactions and experimental PrintMaster M110/M120 are integrated. Explicit unadopted deltas and physical/native limits remain in the parity ledger. |
| 4 — installation/dependencies | Implemented locally within accepted scope; foreign native acceptance open | Locked bootstrap, selected-artifact update/rollback and accepted dependency bundles have receipts below. ESLint10/TypeScript7 remain peer-gated compatibility deferrals. Windows/macOS are best effort. |
| 5 — structure/UX | Implemented locally; native interaction acceptance limited | Named store slices, typed domain/API boundaries, decomposed editor/properties/assistant, responsive setup and save/draft recovery have receipts below. Whole-app JSX typing and native pointer/keyboard acceptance remain limited. |
| 6 — performance/lifecycle | Implemented locally within measured scope; hardware/native interaction limits remain | Alpha/readiness, renderer ownership, paginated summaries, bounded previews/code cache, owned decoding, protocol spooling, one-frame headless output and binary local staging pass. Representative measurements and cancellation/output parity are recorded below. Decoded source lists remain bounded by the configured total pixel ceiling rather than constant memory. |
| 7 — maintenance routine | Policy implemented; recurring execution is future work | Manual weekly advisories/monthly upstream/debt review, ownership, compatibility reconsideration dates and exact release receipts are specified in development-checks.md. No automation is scheduled. |

The original [review baseline](reviews/2026-10-02/baseline.md) remains immutable historical evidence. Updated checks describe their configuration/environment; changed counts must not be interpreted as fixes without comparing the diagnostics.

Historical migration baseline at phase 1 integration: Ruff 400 under the explicit Python-3.11 policy; 64 formatter files; 92 standard/strict Python diagnostics (six missing Windows SDK imports in Linux); 18 React rule findings; one export in each Knip mode; two full Python SCCs and zero eager/frontend cycles. Import Linter contracts pass with the one named stateless-family-ID exception. Source and checker environment/configuration changes explain count differences; that debt was eliminated at the phase 2 checkpoint below.

Prompt patch checkpoint: launcher urllib3 2.7.0 → 2.8.0, DOMPurify 3.4.12 → 3.4.16, and compatible transitive patches for baseline-browser-mapping, brace-expansion, browserslist, js-yaml and postcss-selector-parser. PostCSS was already locked to 8.5.28; no unnecessary direct change was made. The [urllib3 release](https://github.com/urllib3/urllib3/releases/tag/2.8.0) lists the three fixes found by our audit; [DOMPurify's release](https://github.com/cure53/DOMPurify/releases/tag/3.4.16) is the selected sanitizer patch.

The hash-locked Linux check environment still contains 123 packages; its repeated audit now has zero Python advisory findings. npm audit is down to two moderate vulnerable package entries (Vitest and its mocker), represented by three exact records. Twenty-one resolved exceptions were removed; the remaining three expire on 16 October and belong to the tested toolchain migration. The combined advisory gate passes with those explicit exceptions; the frontend audit is not clean yet. Ten launcher/manifest tests, 22 frontend tests, and a scratch production build passed. An initial duplicate environment/build attempt hit `/tmp` quota; only those newly generated failed outputs were removed, and the build succeeded on retry. Existing runtime Pixi lock and tracked frontend dist were preserved.

Classification/raster checkpoint: Phomemo and Niimbot use explicit model aliases, delimiter boundaries and longest-match precedence. Global conflicting claims return an ambiguous sentinel instead of a registration-order winner. Unknown devices remain unknown. M02 Pro keeps its 624 px / 300 DPI geometry; generic D names no longer get a Phomemo D30 profile. Phomemo packs each raster row independently, including widths not divisible by eight. Nineteen focused regression tests pass. All touched classifier/raster files are linted/formatted; 43 resolved Ruff records, four formatter records and three typing records were removed from the baseline without adding debt. No physical printer acceptance is claimed.

Local-operation checkpoint: the server defaults to loopback; explicit LAN access requires a token and trusted origins. The bundled frontend sends the required header on every API method. Provider keys are write-only, blank edits preserve them, and explicit retirement scrubs retained observations transactionally. Environment credentials and Vertex temporary-file cleanup are covered. A fresh configured GPT-6.1 Sol/high reviewer identified three concrete issues in the first patch; all were reproduced and corrected. History timestamps preserve the existing naive UTC SQLite contract under the newer SQLModel version.

Eight boundary tests, nineteen credential tests, one history compatibility test and three launcher startup tests pass. Parent browser inspection verified saved-key presentation and preservation during an alias edit. The sign-in form renders and HTTP/cookie tests pass; in-app browser submission was blocked before reaching the server, so browser sign-in completion remains unverified. The aggregate 24-file accepted frontend artifact digest is `2661a8a5581bcfd74347d8f2bf670020b2db06107755b74260a649dad8753a61`; the bundled files match that scratch build byte-for-byte. No deployed/native acceptance is implied. Full Linux checks at integration pass with 171 backend tests, 24 frontend tests, a scratch build and zero new static diagnostics. Eighty resolved Ruff records, three formatter records, thirteen typing records and one unused export in each Knip mode were retired. Remaining source debt is still visible and scheduled for phase 2.

Print-admission/acknowledgement checkpoint: one active job per canonical printer address, immediate structured 409 for contenders, and cleanup on failed connection, print error and cancellation. Independent printer addresses remain concurrent. Responses report submitted labels and unverified physical completion. Niimbot commands use explicit response IDs and positive required acknowledgements; device errors remain sticky during raster transmission, and failed writes/end-page waits are never automatically replayed. Nineteen admission/cleanup tests and twenty-six acknowledgement/parser/write-mode tests pass from a disposable directory. Scoped Ruff/format/typing checks have no new diagnostics; 43 Ruff records, two formatter records and seven typing records were retired. The admission module is now under strict typing. Physical acceptance remains open for PD01 and the unconfirmed D111/D100. The next integrated full run will include the resource-limit and project-transaction work.

Resource/project/catalog checkpoint: shared JSON ceilings are consumed by backend validation and frontend batch controls. Declared and received API bodies, Cartesian products, copies, canvas geometry, image decoding, driver transforms, font uploads and PDF rasterization are bounded before expensive processing or printer connection. Font publication preserves existing files and rolls back a newly created file on database failure. PDF resources and print images close on failures. A maintained PDFium helper stub replaces import suppression; new resource, upload and catalog boundaries use strict typing.

Project revisions prevent stale canvas saves; rename/move requests omit unrelated canvas state. Folder mutations serialize validation and commit in one process; import validates the complete tree and commits once. AI tools share the guarded mutators and bound generated batch records. The generic catalog publisher validates all five sources before atomically replacing one bundle; modern/legacy parsing preserves aliases, origin IDs, whitespace modes, ambiguity groups and preset metadata. Actual v0.8.1 data promotion, preset transform application and protocol/runtime parity remain phase 3 work.

The final complete Linux check passes with 300 backend tests, 28 frontend tests and an 8.03-second scratch production build. No new static diagnostics remain. Exactly 63 resolved Ruff records, ten formatter records, 78 typing records and one React record were retired; no additions were accepted. Parent browser acceptance on disposable data covered creation, explicit overwrite and reload; the stored revision advanced from 1 to 2 and the reloaded editor retained the full updated text. An in-app browser confirmation temporarily interrupted control; closing that tab and reopening recovered inspection. The test also exposed text-box clipping for a longer string, retained as phase 5 layout/overflow work. The 24-file shipped frontend matches the tested build, aggregate digest `ab4590c2ab9088be552f0c816e67ccb1ad73bd69966bfaf47a4aa8f6b0a2bb68`. No physical printer, paid provider, native installation or deployment acceptance is claimed.

Debt-elimination checkpoint: all 400 Ruff records, 64 formatter files, 92 Python diagnostics, 18 React findings, one unused export in each Knip mode and two full Python SCCs are resolved. `checks/debt.json` now has empty arrays; no additions were accepted. Maintained stubs are part of lint, format and typing scope. The Windows SDK uses a licensed, pinned-wheel-derived subset; the adapter alone disables the native-source availability warning on Linux while retaining import/type checks. Native CI has a real SDK-import test, whose execution remains unverified. The removed device-policy import exception was replaced with stable string identifiers; shared API context assembly and protocol specification ownership remove the former cycles.

Parent review retained enum string/format compatibility, generic enum metadata, legacy registry iteration and pixel-format coercion. Backend contract tests cover async/byte boundaries, raster/PDF helpers and the documented Windows enumeration overload. React component identities are stable, derived state no longer cascades through effects, and replaced render jobs cancel stale callbacks/timers. Five new frontend lifecycle tests protect these changes. Browser acceptance on disposable data covered presets, template defaults, batch mode and generated canvas output with no console warnings/errors.

The complete Linux gate passes: 330 backend tests run (329 passed, one Windows-only skip), 33 frontend tests passed, production build 9.61 seconds, all static categories zero. The shipped 24-file frontend matches the inspected build, aggregate digest `668b0d78e0a373ea6502f0828149683548f6e397184a77f46bbf1a94faabaf8a`. [Machine-readable receipt](reviews/2026-10-02/evidence/phase2-receipt.json). The two moderate npm package entries and their three exact advisory exceptions are still phase 4 toolchain work; zero source debt is not a clean dependency audit or hardware receipt.

Acceptance scope clarified by the user: Linux is the available native test system. Windows and macOS are best effort for now: resolve/check platform locks, inspect bootstrap/platform branches and exercise portable interface contracts, but label native execution unverified. Unavailable native systems do not block local implementation completion. Available printers are PD01 and a Niimbot tentatively identified as D111/D100; exact model/firmware/media still need confirmation before a physical receipt.

Released-protocol foundation checkpoint: explicit CONTROL/BULK/STANDARD routes preflight capability before any job write. V5X preserves opaque raster bytes, uses the released A9 frame/mode/footer and positive atomic ACK, waits for AA between pages, and handles B3 signing with tracked cancellation. The configured GPT-6.1 Sol/high review reproduced a mixed-plan fallback bypass; it is closed with whole-job tests. Parent acceptance also reproduced and fixed a caller path where skipping final completion skipped runtime selection. ACK/flow handling now remains active for intermediate jobs.

Eleph and ToPrint have distinct families/encodings, released polarity/media commands, transport profiles and physical-page boundaries. Two exact legacy ToPrint profiles normalize locally so the older shipped snapshot continues selecting the correct recipe; source data/provenance are unchanged. Tiny has CRC-validated fragmented/coalesced notifications, runtime adoption/reset and a tested BLE pause/resume route with a separate finite resume budget. Strict typing now covers the shared packet decoder, Tiny runtime, YK frame/status helpers and Classic receive hub; a maintained crc8 hash-API stub removes the untyped boundary without suppressing diagnostics.

The standalone Classic hub passes real Linux socketpair tests for single-reader ownership, reply offsets, partial timeouts, overflow, EOF, callback/predicate failure and shutdown without changing socket timeouts. It is not yet connected to the live backend. S001 frame/status helpers are tested, but its encoder/runtime/model promotion remain pending. V5X fixtures currently deliver complete notification frames; transport fragmentation/coalescing and selected post-release parser hooks remain separate work.

Final Linux full gate: 410 backend tests run (409 passed, one Windows-only skip), 33 frontend tests pass, production build 10.53 seconds, every static category zero and no debt additions. Frontend source and shipped artifact are unchanged from the accepted phase 2 build. [Machine-readable receipt](reviews/2026-10-02/evidence/phase3-protocol-foundation-receipt.json), [current parity ledger](upstream-parity.md). No physical output, Windows/macOS native execution, dependency-audit refresh or deployment is claimed by this checkpoint. The remaining plan stays active.

Live Classic/S001/catalog checkpoint: native Classic queries, passive waits and
atomic writes share one receive hub, preserving socket timeout and reply offsets.
Disconnect wakes flow-blocked sends, stops the reader before socket teardown and
clears state for reconnect. Tiny raw notifications reach the owning asyncio loop
before predicates. Native socketpair tests exercise actual backend pause/resume,
fragmented replies, failure/EOF, shutdown, reconnect and callback cleanup. Custom
WinRT/macOS wrappers retain their prior receive paths; their native execution is
best effort and unverified.

Orgstra S001 now has its released four-row/96-dot encoder, three media feed
recipes, speed/density capability metadata and live status/completion controller.
Each new payload clears active completion state; waiters never replay historical
notifications into that state. Two integrated Classic jobs and fragmented BLE
notifications guard against stale completion. Missing status/completion is an
explicit warning, not a physical-success receipt. Paper transforms apply preset
rotation, width normalization and then height fitting; exact pixels match two-stage
references, intermediate/output budgets are checked before allocation, and owned
images close on success and failure.

The all-five-file v0.8.1 bundle is published at peeled source commit
`f676917257b5d1f869e0f13beff03785258e2a2e`: 145 source models, 133 executable generic
records, 12 records deferred to dedicated vendors, 165 unsupported records, 129
profiles, 51 paper presets and 12 origins. D80 ambiguity follows upstream group
precedence; unambiguous aliases still select Luck. Historical raw files remain
fallback data. S001 preset-selection/editor geometry is still phase 5 UX work.

Final Linux full gate: 476 backend tests run (475 passed, one Windows SDK skip),
33 frontend tests pass, production build 8.78 seconds and every static category is
zero. Frontend source and shipped artifact retain the accepted phase 2 digest.
[Machine-readable receipt](reviews/2026-10-02/evidence/phase3-classic-s001-catalog-receipt.json).
Luna/max implementers supplied bounded non-UI transport, codec, runtime and paper
packets; a Luna/max researcher confirmed the D80 source ambiguity. These are
configured assignments; runtime model telemetry is unavailable. Parent owns
integration and acceptance. No physical printer output, Windows/macOS native run,
dependency audit refresh or deployment is claimed. Dedicated vendor parity,
selected master changes and phases 4–7 remain active.

Dedicated-vendor/BLE-hook checkpoint: NIIMBOT probes before job commands, emits
released D-row frames and uses E0 or finite A3/B3 completion before advancing.
D11 auto-selection rejects short B5 version fields; the experimental D11S profile
is 96 px / 203 DPI. A GPT-6.1 Sol/high read-only review reproduced a fragmented
pre-arm completion race; first-byte offsets and generation guards now exclude it
without dropping partial device errors. Missing completion fails with delivery
uncertainty; pixels are never resent. Existing B/D101 paths remain legacy.

Phomemo M02/M02S/M02X/T02 use released page recipes and native raster pixels,
model-specific density/feed units and actual strip splitting. Budgets/counts are
checked before allocation and owned images close on failures. Released variants
prefer Classic with BLE fallback. M02 Pro keeps its conflicting local geometry
and recipe. Selected upstream ownership correction `3bd80ba` defers M110/M120
PrintMaster and M220/M221/M260 aliases; compact helper fixtures do not advertise
those devices. The immutable generic v0.8.1 catalog is unchanged.

Selected `1afe428` adds separate BLE control notifications and a physical-chunk
permission hook after flow resume. Partial subscription/cancellation/stop failures
still attempt all unsubscribes and physical disconnect while retaining the primary
error. `7be93f5` separates declared-payload access from frame validation. Pure
vendor wire helpers now live in the stateless protocol layer; direct imports
preserve zero cycles. Luna/max implementers supplied the bounded non-UI packets
and a Luna/max researcher collected selected Luck/PrintMaster evidence. These are
configured assignments; runtime telemetry is unavailable. Parent reviewed edits,
corrected integration tests and owns acceptance.

Final Linux full gate: 558 backend tests run (557 passed, one Windows SDK skip),
33 frontend tests pass, production build 7.25 seconds and every static category
is zero, with no baseline additions. Frontend source/artifact and dependency locks
are unchanged. [Machine-readable receipt](reviews/2026-10-02/evidence/phase3-dedicated-and-write-hooks-receipt.json).
No physical output, Windows/macOS native run, advisory refresh or deployment is
claimed. Remaining pinned Luck A4/PrintMaster work and phases 4–7 stay active.

Phase 4 preparation only: a disposable Pixi 0.72.2 candidate resolves unchanged
application dependencies and optional headless support for linux-64, linux-aarch64,
osx-64, osx-arm64 and win-64 at Python 3.11.15. Linux candidate installation and
imports pass; foreign native environments were not installed. Installation took
14.52 seconds after lock resolution; this is not a fully cold download benchmark.
The environment occupies about 667 MiB and its candidate cache about 650 MiB.
Isolated imports measured roughly 0.58 seconds/49 MiB for the vendor registry,
2.79 seconds/196 MiB for LiteLLM and 2.47 seconds/228 MiB for the Google SDK.
These measurements are preparation evidence, not bootstrap or dependency promotion.

Pinned Luck/PrintMaster checkpoint: APA41 and APA49/E49 are distinct, A4 profiles
use source BW1 geometry/defaults, and Luck jobs require status/setup/finalization
replies. Optional paper windows preserve prior local required-query defaults.
PrintMaster exact names use their separate 384-dot recipe and distinct reply
decoder. Completion arms before every page, excludes pre-arm partial replies,
and retains faults/disconnection through scope exit. No observer fails before
pixels; a connected unobservable Classic bridge falls back to BLE. Unknown
suffixes and M220 remain unknown through the pinned ownership redirect.

The raw release and legacy JSON hashes are unchanged. Normalized catalogs now
have 136 executable, eight deferred and 166 unsupported records. A validated
Luck overlay holds two models, 16 profiles and 29 presets; metadata lists selected
updates separately from the release. Parent review corrected a wrong speed
opcode and added literal odd-width row packing checks. The configured
GPT-6.1 Sol/high reviewer found no consequential PrintMaster defect; Luna/max
specialists supplied bounded codecs, runtime, overlay, cleanup and integration
tests. Runtime model telemetry is unavailable.

The full Linux gate passes: 629 backend tests run (628 passed, one Windows SDK
skip), 33 frontend tests, production build 6.82 seconds, and all static categories
zero. Frontend source/artifact and dependency locks are unchanged by this
printer checkpoint. [Machine-readable receipt](reviews/2026-10-02/evidence/phase3-luck-printmaster-receipt.json).
Physical printing, foreign native execution, advisory refresh and deployment are
unverified. Explicit unadopted source deltas remain in [the parity ledger](upstream-parity.md).

Phase 4 preparation advanced: exact LiteLLM 1.103.2 and Google AI Platform 2.3.0
import successfully in a disposable Python 3.11.15 environment. Nineteen
credential-handling tests pass and all 97 installed packages are compatible.
Completion was mocked; request serialization and live providers are unverified.
The five-platform dependency generator passed nine tests in scratch and has not
yet been promoted. These preparations do not change application dependencies.


Phase 4 bootstrap foundation: Pixi 0.72.2 is pinned by official binary digest,
size and version on five targets. Bash and PowerShell share setup, headless,
repair and diagnostic options. Verified restarts avoid synchronization; scoped
identity stamps preserve prior lock verification. Failed downloads preserve the
old binary. Shared absolute data paths keep SQLite/fonts separate from code;
SQLite URL delimiters, Unicode, spaces and foreign working directories are tested.

LiteLLM 1.103.2 and Google AI Platform 2.3.0 are promoted after credentials-free
SDK request/response probes. Saved Vertex JSON goes inline, with malformed values
rejected before SDK invocation; supported WIF/authorized-user shapes are preserved.
No live authentication or paid provider call was made. Earlier preparation entries
above are historical; the generator and dependencies are now promoted.

Final Linux checks: 666 backend tests run (665 pass, one Windows SDK skip),
including 21 tests for the next, not-yet-integrated artifact library; 33 frontend
tests and production build (8.84 seconds) pass, all nine static categories zero.
Python audit has zero findings; three exact existing npm exceptions remain until
the toolchain migration. Fresh setup, repair, headless retry, offline warm setup
and invalid/partial download preservation pass in disposable paths. An initial
Chromium download hit temporary-directory quota; routing temporary files into
its data directory fixed it. Parent launched Chromium and inspected a fixture
render. PowerShell portable contracts pass on Linux; Windows/macOS native runs
remain unverified under the user's best-effort scope.

[Machine-readable receipt](reviews/2026-10-02/evidence/phase4-bootstrap-foundation-receipt.json).
Luna/max implementers, researcher and verifier supplied bounded non-UI packets
and evidence; configured assignments are recorded, runtime telemetry unavailable.
No physical printing, deployment or automatic update is claimed. Optional AI,
selected releases, remaining dependencies and phases 5–7 remain active.

Phase 4 optional-AI/selected-release source checkpoint: basic setup omits cloud
SDKs; four locked environments keep AI and Chromium independent. Missing SDKs
return a structured add-on requirement before context/provider work. All 115
unique PyPI name/version pairs across every platform/feature lock have zero
known advisories in the recorded audit. Conda/system libraries and the browser
binary are outside that audit's scope. Existing npm exceptions remain pending
the frontend toolchain migration.

The launcher selects checksum-verified immutable ZIPs, keeps prior code slots,
backs up committed SQLite/WAL data and probes a disposable database clone before
atomic code selection. Runtime leases serialize cooperating updates/servers;
rollback swaps code only. Per-slot add-on selections preserve the previous
runtime after failed candidates. Releases are built from committed Git blobs
and the accepted frontend digest. There is no automatic Git HEAD pull.

The configured GPT-6.1 Sol/high read-only reviewer found an archive-open race
and a reserved-path omission; both are corrected with regression tests. Luna/max
specialists supplied bounded manifest, lease and release-slot packets. Runtime
model telemetry is unavailable. Parent inspected edits and owns acceptance.

Linux full gate: 702 backend tests run (701 pass, one Windows SDK skip), 33
frontend tests pass, production build 6.94 seconds and all nine static categories
zero. ShellCheck and portable PowerShell parsing pass. The frontend artifact is
unchanged. [Source checkpoint receipt](reviews/2026-10-02/evidence/phase4-selected-release-source-receipt.json).
An actual immutable-release installation/probe receipt follows this checkpoint;
native Windows/macOS execution, physical printing and deployment are unverified.

Selected-release integration acceptance passed on Linux using source commit
`7fe7277546615e9471d53be861efd7548f76f9c4`. Two immutable bundles installed and
accepted exact health/frontend identity; an intentionally broken candidate failed
startup and fell back to the accepted slot. Code rollback, busy-runtime rejection
and a download-blocked warm restart pass. Database, committed WAL and font
witnesses remained unchanged; three durable backups include the WAL sentinel,
and no probe directories remain. First preparation took 7.67 seconds with a warm
package cache; warm repeat took 0.26 seconds. These are not cold-download claims.
[Integration receipt](reviews/2026-10-02/evidence/phase4-selected-release-integration-receipt.json).

All four optional environments pass Linux setup/import/feature selection checks.
The final per-slot marker check preserves shared data and previous slot selection,
uses the right warm runtime without Pixi/download execution, and rejects relative
paths before writing. [Optional-bootstrap receipt](reviews/2026-10-02/evidence/phase4-optional-bootstrap-receipt.json).
The 24 frontend files retain byte parity with the accepted historical artifact;
the release manifest's documented aggregation yields `584aa51c9f50d137e5f824a4b7042c948b25f93dd65ddd97385f8c52960c9861`.
Native foreign systems remain best effort and unverified. Frontend package groups
and phases 5–7 remain active.

Frontend runtime/toolchain checkpoint accepted locally: React/DOM/React-Konva 19.3,
Konva 10.7, Zustand 5.0.15, Markdown 10.1, js-beautify 2.0.3 and Lucide 1.50 are
integrated with Vite 8.3.2/plugin-react 6.1.1/Vitest 5.0.3/jsdom 30.1.1.
Markdown uses an explicit class wrapper. Rolldown groups include the canvas
reconciler dependencies after production browser acceptance exposed an entry
initialization cycle. Canonical icon names and 80-result pagination replace the
6,355-export grid that stalled inspection. Search/selection/capture and pagination
tests pass. ESLint remains on the compatible 9.x line; Tailwind 4 remains a separate
visual migration.

Parent production-browser checks cover text, QR/barcode, cat raster capture,
save/reload and fixture Markdown history. The saved project has revision 1 and
three retained objects; no provider or print job was submitted. Automatic printer
discovery still runs in the current UI. Discovered pre-existing UX debt includes
offline profile selection being replaced by discovery and displayed millimetres
depending on unresolved printer DPI. Phase 5 must address both.

The refreshed Python/npm advisory gate passes with zero findings and no
exceptions. The former three exact Vitest exceptions are retired. A new icon
pagination regression brings frontend coverage to 34 tests. Production build
observations are recorded separately from edit/render performance.

Full Linux gate: 702 backend tests (701 passed, one Windows SDK skip), 34 frontend
tests and a 1.47-second scratch production build pass; all nine static categories
are zero. The shipped 26-file frontend matches the accepted production build,
including exact root-logo bytes. Old generated assets were retained in the
disposable acceptance backup before replacement.
[Runtime/toolchain receipt](reviews/2026-10-02/evidence/phase4-frontend-runtime-toolchain-receipt.json).

The remaining phase 4 frontend migrations are accepted as a local source checkpoint:
bwip-js 4.11.4, globals 17.13.0, React Refresh 0.5.7 and Tailwind/PostCSS 4.3.3.
The pinned official Tailwind upgrade tool migrated utility names and CSS theme
configuration. Parent review retained class-based dark mode, font families,
border/placeholder/cursor defaults and explicit dark scrollbar selectors.
Autoprefixer and the obsolete JavaScript Tailwind configuration are removed.
Knip now includes CSS imports; no unused-dependency exception was introduced.
ESLint 10 remains deferred because the React plugin's declared peer range stops
at ESLint 9. The resolved tree has no other outdated direct packages.

All 12 barcode fixtures preserve dimensions, exact pixels and PNG hashes. The
nonblank HTML background fixture also preserves exact print-resolution pixels.
Light/dark shell inspection covers effective CSS widths 390, 768, 1222 and 1280
at height 843 (the browser's zoom leaves a one-pixel difference from the planned
844). Earlier inactive-view JPEG captures are excluded from acceptance.
The narrow drawer/canvas problems remain phase 5 defects.

The broader headless fixture exposed missing individual HTML elements and
variable image/code capture in the existing renderer. Matching blank output is
explicitly rejected as fidelity evidence. Phase 6's resource-readiness contract
is required before release acceptance, alongside phase 5's save/DPI/draft work.
These are local maintenance commits, not a promoted release.

The full execution passes 702 backend tests (701 pass, one Windows-only skip),
34 frontend tests and production build. Its initial Knip CSS-scope finding was
fixed; the subsequent complete static report is zero across all nine categories.
Python/npm advisories remain zero with no exceptions. Vulture's two unused
context-manager protocol parameters are advisory candidates, not removed hooks.
The shipped 26-file artifact matches the inspected final build and has release
manifest digest `3429f55d5f3cdce08d225312412eb11e3874763d25ccc6591299f6026c66418b`.
[CSS/patch receipt](reviews/2026-10-02/evidence/phase4-css-and-patches-receipt.json).
Linux installation/recovery and dependency work are implemented; native foreign
systems and physical printers remain best effort/unverified. Phases 5–7 remain
required work on the active goal.

Phase 5 document foundation is accepted locally. A versioned serializer now includes DPI in project saves, AI snapshots and clean capture. Document/template/variable helpers and history middleware have separate ownership. Loading resets document and history atomically; unsupported/oversize documents preserve the prior project. Selecting a printer preserves populated label geometry and rescales numeric nested coordinates while keeping percentages and rotation.

The production browser saved a 600×300 pixel / 300-DPI fixture at 400×200 / 200 DPI, then reloaded it before and after printer discovery: the physical size remained 50.8×25.4 mm. No print job was submitted. Strict TypeScript 5.9.3 covers the new document boundary; JavaScript/JSX callers remain unchecked. Version 7 conflicts with current analysis-tool peers and is deferred.

Full Linux checks pass: 702 backend tests (701 pass, one Windows SDK skip), 42 frontend tests, production build, ten empty static categories and zero Python/npm advisory findings. The shipped 26-file frontend matches the inspected build with canonical digest `dc3521dbda7b0269b9251556b2ac9b9e441d853c9d00fdbc14730c53266a60d1`. [Document receipt](reviews/2026-10-02/evidence/phase5-document-receipt.json). Named store slices, component decomposition, unsaved-work/draft UX, accessibility and phases 6–7 remain active. Windows/macOS and physical devices remain best effort/unverified.

Phase 6 rendering foundation is accepted locally. A per-job readiness contract
waits for fonts, images, HTML and generated codes, propagates errors and ignores
stale callbacks. Individual HTML objects now appear in output. Print canvas
buffers use document pixels independently of browser zoom; fixed readiness sleeps
are removed. React rendering hooks have separate resource ownership.

The backend uses one owning async Playwright service, with two active/four admitted
jobs, a job-size deadline, bounded request cleanup and shutdown, and an explicit
loopback headless identity wait. Decode remains inside the active-job bound.
Cleanup failure stops admission; successful shutdown permits a fresh service.
The GPT-6.1 Sol/high source review found a cleanup-failure admission gap, which is
corrected and covered by fault-injection tests. Hung external SDK processes can
still require process-level termination; a bounded API wait is not a guarantee
that such a process has exited.

Paginated project summaries exclude embedded document blobs, and selection fetches
detail with a stale-response fence. The production browser reopens the saved DPI
fixture at 50.8×25.4 mm. The former tree batch hint, inferred from full document
blobs, is absent from summaries. The alpha hoist preserves all four fixed-fixture
pixel hashes and reduces median preprocessing time by 7.69–15.89×. These are local
step measurements, not printer throughput or end-to-end p95 results.

Final Linux checks pass: 730 backend tests (729 pass, one Windows-only skip),
47 frontend tests, production build and ten empty static categories. Resolved
dependency locks are unchanged, so the preceding zero-advisory receipt carries
forward without a new live audit. Two actual Chromium requests produce identical
mixed output and close cleanly; two app-browser captures also match exactly.
Chrome 153 headless and Chrome 154 app-browser antialiasing differ; cross-version
pixel equality is not claimed. Both outputs contain the inspected HTML object.
Quota failures, an exited-preview run and early blank captures are excluded.

The shipped 26-file frontend matches the final inspected build, with canonical
digest `4834b45e5e33914d87ace0c2535e58ef832fa65ef494ca2daf0c7059a894085c`.
[Rendering foundation receipt](reviews/2026-10-02/evidence/phase6-rendering-foundation-receipt.json)
and [alpha measurements](reviews/2026-10-02/evidence/phase6-alpha-results.json).
Named store/component decomposition, draft and accessibility UX, preview
virtualization, batch memory/chunking, the broader performance matrix and phase 7
remain required. No printer or provider calls were made in acceptance; foreign
native systems and physical printer outcomes remain best effort/unverified.

Phase 5 store decomposition is accepted locally. One Zustand store and one history wrapper compose document/history, selection, printer, settings, persistence, batch and UI slices. All 146 fields and action bodies match the previous parsed syntax trees, apart from passing the existing store getter through each factory. There are no new cycles. The 47 frontend tests, ten empty static categories and production build pass; backend and dependency locks are unchanged. The compiled editor opens the saved DPI document. The 26-file shipped build matches the inspected scratch build. [Store slice receipt](reviews/2026-10-02/evidence/phase5-store-slices-receipt.json). Unsaved-work/recovery UX, component decomposition and the remaining phase 5–7 acceptance stay active.

Phase 5 document lifecycle is accepted locally. Saved/unsaved/saving/failed status uses immutable document baselines, excluding view-only active-page selection. Saves capture their own snapshot and session; edits during a request stay dirty, and responses from an earlier document cannot attach to a new one. Opening protects unsaved work and rejects a detail response if intervening edits occurred. Undo can return to the saved baseline. Clearing during a save detaches the request. Versioned, size-bounded browser recovery copies never silently overwrite saved projects: recovery always creates a new design. Storage failure is visible, pending recovery copies are protected, and dirty documents receive an unload guard. A delayed modal focus callback no longer steals focus from an already-focused child.

The 54 frontend tests, production build and ten empty static categories pass. The parent inspected compiled edit/recovery/save/reload on disposable data. Native confirm-decline handling was not observable through the browser controller; its rejection and delayed-load fences are unit-tested. The shipped frontend matches the final build. [Document lifecycle receipt](reviews/2026-10-02/evidence/phase5-document-lifecycle-receipt.json). Automatic printer selection, onboarding and narrow-layout defects remain for the next UX step.

A separate phase 6 cleanup closes Phomemo-owned legacy copy/resize/rotation/inversion images in success, exception and cancellation paths while preserving borrowed source images and raster bytes. The Luna/max implementer ran all 44 Phomemo tests and scoped lint/format checks; the parent inspected every edit and test, and the complete static report remains empty. [Cleanup receipt](reviews/2026-10-02/evidence/phase6-phomemo-cleanup-receipt.json). Whole-job memory/chunking and broader performance work remain active.

Phase 5 optional onboarding is accepted locally. Welcome completion has its own browser flag, Start designing needs neither discovery nor AI configuration, and printer setup can be reopened. Explicit scans preserve the selected offline profile. Model search distinguishes protocol, geometry and DPI; the PD01 v5g profile persists across a fresh page. Discovery is described as discovery, with connection deferred to submission. Offline physical printing is disabled in the sidebar and rejected by the store. Scan teardown aborts pending requests. Contextual print errors replace batch alerts. All 59 frontend tests, production build and ten empty static categories pass. The compiled onboarding/profile flow was inspected; the native unsaved-work confirmation stalled browser control, and the per-page error was not observable, so those paths retain unit evidence pending the next UX step. The shipped build matches the inspected scratch build. [Onboarding receipt](reviews/2026-10-02/evidence/phase5-onboarding-receipt.json). Responsive/accessibility, component decomposition and phases 6–7 remain required. No physical printer or provider calls were made.

Phase 5 project switching now uses an in-app guard with Keep editing as initial focus, an explicit discard choice and a session/revision fence against edits made while confirmation is open. Modal background ownership is reference-counted across nested dialogs, retains pre-existing inertness and restores prior connected focus. All 63 frontend tests, lint, strict boundary typing, Knip, cycle checks and production build pass. Compiled DOM activation verifies both choices, saved50.8×25.4mm geometry and contextual per-page offline rejection. Ordinary input was affected by the earlier stalled native prompt; pointer/keyboard acceptance requires a clean browser session. The shipped artifact matches the inspected build. [Project guard receipt](reviews/2026-10-02/evidence/phase5-project-guard-receipt.json). Responsive and decomposition work continues.

Phase 6 PDF safeguards are accepted locally. Uploaded PDFs preflight every page geometry and the total pixel budget before allocating a bitmap, then cap accumulated data URL bytes before each base64 allocation. The separate converter rejects out-of-range ranges before expansion and detaches fallback PIL output before closing the bitmap/source, including failures. The Luna/max implementer ran 15 upload and eight rendering-contract tests, scoped Ruff/format and zero-diagnostic typing; the parent inspected every edit. An actual two-page PDF also converts correctly after metadata page handles close/reopen:203×102 and102×203RGB output. [PDF receipt](reviews/2026-10-02/evidence/phase6-pdf-preflight-receipt.json). Upload buffering, worker cancellation and whole-job spooling remain active work; bounded response bytes are not a claim of bounded totalRSS.

Phase 5 lazy features now have visible loading/cancel affordances and isolated error boundaries with Close/Reload recovery. A failed icon chunk in the production browser showed recovery and preserved the editor after Close; the temporary blocked-URL injection was cleared. Normal input remains affected by the earlier native prompt, so this uses DOM activation and is not keyboard/pointer acceptance. Print preparation is a focus-managed modal with explicit cancellation before submission; late readiness cannot complete a cancelled job. All66frontendtests, productionbuild andtenempty staticcategoriespass. [Lazy recovery receipt](reviews/2026-10-02/evidence/phase5-lazy-recovery-receipt.json). Whole-job memory and physicalsubmission cancellation remain separate work.

Phase 5 responsive controls are implemented locally. Below 1280 pixels, the
editor opens with the canvas visible and panels closed; projects/printers and
properties use mutually exclusive, focus-managed drawers. Breakpoint changes
update the layout. Default narrow zoom fits the inner available width, and preview
geometry changes no longer animate independently of the canvas layers. Numeric
controls use associated labels and pointer capture with cancellation; properties
tabs and the saved-project tree support their keyboard navigation. Canvas shortcuts
leave controls and modal interactions alone. Shared property fields now have
visible-label associations, including capability-dependent density controls.

All 93 frontend tests in 19 files pass, as do the ten static categories and the
production build. Parent inspection covers 390, 768, 1222 and 1280 CSS-pixel widths
at height 843, plus light/dark property drawers. Axe 4.13.0 reports no violations
on the inspected editor/drawer surfaces, with incomplete contrast results retained.
Ordinary browser input still has no effect after the earlier stalled native
prompt; DOM activation and keyboard/pointer unit evidence do not establish a full
native keyboard-only workflow. That acceptance gap remains explicit.

Build inspection found Tailwind scanning generated bundles and stale chunks in
reused scratch output. Source detection now names maintained frontend source and
index HTML explicitly. Two clean 26-file builds match byte-for-byte after replacing
dist between builds. The retained artifact has digest
`143e3423f1d083c4d21b01413d14cfb0db94fec8b90d52e88873666ef1e6628d`.
[Responsive receipt](reviews/2026-10-02/evidence/phase5-responsive-receipt.json).
These captures establish preview layout, not print fidelity. Object-list selection,
keyboard file controls, project action/recovery dialogs, component and API/job
boundaries, and the remaining performance/maintenance work stay active. No printer
or provider call, external promotion or native foreign-system acceptance occurred.

Phase 5 project actions and typed request boundaries are accepted locally. Saved
project export fetches document detail rather than relying on blob-free tree
summaries. Overwrite, deletion and dirty recovery use explicit in-app confirmations;
failed actions retain contextual errors, and intervening document/saved revisions
prevent stale replacement. Deleting a saved folder/project detaches its write
identity while preserving the current canvas as dirty unsaved work. Nested actions
return focus to their named trigger.

API utilities now use strict TypeScript and type-aware ESLint. JSON decoding and
validation remain inside the request deadline, with external abort reasons and
structured errors narrowed defensively. Model/scan/profile responses are validated;
all 155 actual local model profiles pass the guard. Print receipts require a
positive integral submitted count and nonempty job identity, explicitly retain
physical completion as unverified, and are visible above the canvas. Preparation
snapshots use the central versioned DPI serializer. Cancelled/superseded or duplicate
preparation callbacks cannot submit a second job.

All 124 frontend tests in 24 files, ten empty static categories, refreshed Python
and npm advisory checks, and the clean production build pass. Axe reports zero
violations on final action, overwrite and recovery dialogs; incomplete contrast
results remain recorded. Parent DOM activation verifies confirmation/cancellation
and focus return at 390 CSS pixels. Browser download observation timed out; export
contents and blob disposal are unit-tested, but a downloaded file is not claimed.
Native keyboard/pointer acceptance remains affected by the earlier stalled prompt.
The shipped 26-file artifact matches the inspected build, with digest
`82c166eea65f449ca4bf6f0340cc9f6493bfcfeeb8596d785cf84aada1acc0d0`.
[Project actions and transport receipt](reviews/2026-10-02/evidence/phase5-project-actions-receipt.json).
Component decomposition, keyboard file/object workflows, backend preflight/spooling,
the broader performance matrix and phase 7 remain active. No physical print,
provider call or external promotion occurred; Windows/macOS native acceptance is
best effort and physical printer outcomes remain unverified.

Phase 5 property sections now separate canvas geometry, printer overrides, global
defaults and template/background fields. Narrow store subscriptions include
reactive dithering. Named native buttons expose image/PDF/project/font file
controls. Printer/default saves distinguish pending, failed, acknowledged and
changed drafts; failure rollback preserves intervening document edits and new
document sessions. Failed default saves retain newer form drafts. Delayed HTML
formatting rejects stale content rather than replacing newer edits.

All 140 frontend tests in 27 files, ten empty static categories and a clean
production build pass. Parent inspection at 390 CSS pixels covers canvas, printer,
defaults and background HTML. Axe reports zero violations, retaining incomplete
contrast results. DOM activation and unit semantics do not establish native
keyboard/pointer/file-chooser acceptance while the controller's earlier prompt
remains stalled. No Python product or dependency lock changes occurred.
The shipped 26-file frontend matches the inspected artifact; canonical digest
`c2978b195e22ebe81918e5b0fc08be4025bda2486202496b2641ca12ecb8f9fe` uses the relative-path JSON format recorded in the
[property receipt](reviews/2026-10-02/evidence/phase5-properties-receipt.json).
Media import ownership, element/AI/canvas decomposition, keyboard object workflows,
backend spooling, performance and phase 7 remain active. No printer/provider calls,
foreign native acceptance or external promotion occurred.

Phase 5 media imports now belong to their captured document session/revision/page.
Image and PDF processing has visible progress/cancellation, bounded reading/load
deadlines, contextual failures and shared size/geometry/item budgets. PDF JSON
decoding stays inside its request deadline. Every image must decode successfully
before one atomic append; later-page failures cannot leave partial content. Edits,
page/document changes and editor teardown cancel preparation. Browser image
geometry limits apply after decoding; total browser allocation and cancellation
of the server's synchronous PDF worker are not claimed.

Element editing is separated from properties navigation/default drafts, reducing
the properties container from 630 to 218 lines. Delayed element/template icon
selection checks document ownership; selected-element lifetimes also include the
document session. Redundant group position fields were removed. Parent visual
inspection caught and fixed the canvas floating toolbar painting above drawers.
All 150 frontend tests in 28 files, ten empty static categories and the clean build
pass; the final CSS-only fix additionally passes scoped lint and visual inspection.
Axe reports zero element-drawer violations at 390 CSS pixels, retaining incomplete
contrast results. The real file chooser attempt timed out; native file-picker,
keyboard and pointer acceptance remain unverified despite passing import-race tests.
The shipped 26-file frontend matches the final inspected build, digest
`6777a5156a1a28f9936fddb43bcde35790288d994ea56757f61746ac55d4b97d`. [Media/element receipt](reviews/2026-10-02/evidence/phase5-media-receipt.json).
AI/canvas decomposition, stronger leaf typing, keyboard object workflows, backend
spooling, performance and phase 7 remain active. No physical printer/provider
call, foreign native acceptance or external promotion occurred.

Phase 6 now retains a focused decode-memory baseline: nine fresh Linux workers,
three repetitions each for 1, 20 and 100 deterministic384×384RGB PNG payloads.
The parent inspected the Luna verifier's script, source identities and all count,
geometry/mode and pixel-hash invariants. The 100-image path takes0.180–0.183s
and raises the process high-water mark by50620–50816KiB while retaining
44,236,800decoded RGB bytes. Only165,600base64 bytes were supplied. This supports
replacing whole-job decoded accumulation; it measures decoder time/high-water RSS,
not net RSS, render latency, p95, time-to-first-send or physical throughput.
Imports/fixture creation precede the initial sample and pixel hashing follows the
final sample. No product/source/test change or hardware call was made.
[Fixed protocol and baseline](reviews/2026-10-02/evidence/phase6-decode-memory-baseline.json).
The broader performance matrix and backend ownership/spooling remain active.

Phase 5 adds a current-label object list with roving arrow/Home/End navigation,
Enter selection and modifier-assisted multiple selection. It includes legacy
page-zero objects and treats groups as one object. Selection leaves document
revision unchanged. Canvas capture, keyboard/pan handling and pointer/transform/
snapping responsibilities are separated from the page-preview container. Pan ends
on window focus loss. Legacy objects now participate in page-zero snapping.
Capture requests have identity/deadline/teardown ownership and reject duplicate
requests or stale completion callbacks.

All 161 frontend tests in32files, final ten empty static categories and the clean
production build pass. The affected two interaction tests also pass after moving
the test handoff out of render. The parent inspected the compiled object list at
390CSS pixels; Axe reports zero violations with incomplete contrast retained.
An actual full-resolution378×378PNG contains the label text and matches exactly
after editor zoom changes. Native keyboard-only completion remains unverified due
to the controller's earlier prompt stall; unit navigation evidence is distinct.
The shipped 26-file frontend matches the inspected build with digest
`2b7f29140f79a7b34ab1bc4416d87ad0659b0fcff5f2d0c85f8b0f735d8bac91`. [Canvas controls receipt](reviews/2026-10-02/evidence/phase5-canvas-controls-receipt.json).
Page-preview separation/virtualization, AI decomposition, stronger leaf typing,
backend preflight/spooling, performance and phase7remain active. No physical print,
provider call, foreign native acceptance or external promotion occurred.

Phase 6 now gives off-thread image decode an explicit, locked ownership box.
Successful calls transfer usable images to the caller. Normal caller cancellation
drains the same shielded task, tolerates repeated cancellation, closes late outputs
and preserves the original cancellation reason. Independently cancelling the async
wrapper cannot stop its worker thread; late publication still closes the images.
The helper is integrated into browser output and direct image printing.

The parent inspected the Luna implementer's helper, integrations and seven new
regression cases. Focused backend tests pass (38); the full suite passes 745 tests
with one skip. Final ten static categories are empty; a Vulture advisory for the
intentional context-manager exception argument remains informational. Dependency
locks are unchanged. [Owned decode receipt](reviews/2026-10-02/evidence/phase6-owned-decode-receipt.json).
Device admission before preparation, disconnect cancellation, whole-job spooling,
PDF worker lifecycle and the broader performance matrix remain active. No physical
printer/provider call, foreign native acceptance or external promotion occurred.

Phase 5/6 separates CanvasPagePreview from its container and mounts HTML/canvas
content near the scroll viewport, retaining the primary active page for editing.
Secondary batch records have no item hit testing, transform, selection overlays
or editing toolbar. Primary page headers provide named native editing and print/
duplicate/delete controls. Selection handles now reattach when panning ends.

All 166 frontend tests in33files pass, including four visibility/ownership cases
and the pan reattachment regression; the final affected three interaction tests
also pass. Final ten static categories are empty and a clean production build
passes. Parent browser acceptance at390×843CSS pixels uses20identical text labels:
the previous build mounts20stages; the new build mounts3at the same zoom/top view,
5while viewing the middle with an offscreen active page, and4after selecting the
visible page. Canvas backing pixels drop941780→141267at the matched top view.
This is an85%resource-count reduction for that fixture, not heap/RSS or latency
evidence. Full-resolution378×378PNG output matches byte-for-byte across builds
and after scrolling, changing page and zoom. Axe reports zero violations while
retaining an incomplete contrast result. Native keyboard/pointer acceptance remains
unverified; developer DOM activation and unit semantics are distinct evidence.

The shipped frontend matches the inspected artifact. [Preview receipt](reviews/2026-10-02/evidence/phase6-preview-receipt.json).
Headers/placeholders remain mounted; inactive raster thumbnails, stronger typing,
AI decomposition, backend admission/spooling, broader benchmarks and phase7remain
active. No physical print/provider call, foreign native acceptance or external
promotion occurred.

Phase 6 claims the printer before rendering or decoding, so same-device contenders
return 409 before preparation. The public executor retains borrowed-image behavior;
route-owned outputs close on success, failure and cancellation. Disconnect drains
the same shielded task through repeated caller cancellation and preserves the first
reason. PDF cancellation signals its synchronous worker, stops later pages and
drains normal caller cancellation before closing the upload. Native resources still
belong to the worker until it exits; independently cancelled wrappers and shutdown
do not prove thread or physical disconnect completion.

Parent inspected the Luna implementations and tests. Focused admission tests pass
(58), PDF/upload tests pass (17), and the current accepted backend snapshot passes
757 tests with one skip. Ten static categories are empty. Concurrent unintegrated
spool/paper-stream additions are excluded from this acceptance. Locks are unchanged.
[Admission/PDF receipt](reviews/2026-10-02/evidence/phase6-admission-pdf-cancellation-receipt.json).
Whole-job spooling, code caches, broader performance and phase 7 remain active. No
physical printer/provider call, foreign native acceptance or promotion occurred.

Phase 5 separates assistant chat presentation, live-session ownership, external JSON
flow, validated response boundaries and canvas application. Request identity includes
document session/revision/page, conversation/reset epoch, mode and printer. Late or
cancelled replies cannot apply canvas state, history or side effects. External prompts
become stale when their captured context changes. Visual review awaits fresh capture
and stops after three follow-ups. History deletion uses the existing confirmation
dialog. Already-started server work may continue after client cancellation.

AI deletion tools now only look up saved targets and request review through Projects
→ Actions → Delete. No saved content is deleted by them. AI print requests show a
review instruction; the user submits through the normal Print control. Manual tool
errors, success and confirmation-required outcomes are distinct. Direct deletion
routes still lack expected-state fences; this is not a claim that all deletion races
are solved. Parent inspected the Luna backend implementation and all UI work.

All 185 frontend tests in 34 files pass, including 19 assistant cases. The accepted
backend snapshot passes 757 tests with one skip; the focused AI backend tests pass
(7). Ten static categories are empty; clean build passes. Parent inspected the final
compiled live/external drawers at390×843CSS pixels: Axe reports zero violations,
retaining incomplete contrast. Native keyboard/pointer and live provider behavior
remain unverified. The shipped27-file frontend matches the inspected build.
[Assistant receipt](reviews/2026-10-02/evidence/phase5-ai-receipt.json).
Stronger element typing, code caching, whole-job spooling, broader performance and
phase7remain active. No physical printer/provider call, foreign native acceptance
or external promotion occurred.

Phase6 adds a shared immutable QR/barcode data-URL cache, bounded to128 completed
entries and8MiB of UTF-16 key/value strings, with at most128 tracked pending
generations. Duplicate requests share generation; failed generations retry, oversized
results render without retention, and LRU eviction bounds completed strings. Canvas
and HTML preserve their different scale/options keys. Module-load failures can retry.
This is not a measured JS-heap limit or full HTML raster cache.

All192 frontend tests in36files pass; seven focused cache/hook cases include100
mounted identical codes using one mocked producer call and stale QR completion.
TypeScript, scoped ESLint and five frontend static categories pass. Root static
collection found two concurrent backend import-order edits outside this frontend
acceptance, corrected separately without baseline changes. Clean build passes. Parent
inspected toolbar-created real barcode/QR output:5138-byte barcode and7774-byte
combined full-resolution PNGs match the accepted uncached build byte-for-byte.
The shipped27-file frontend matches the inspected artifact.
[Code cache receipt](reviews/2026-10-02/evidence/phase6-code-cache-receipt.json).
Stronger element typing, whole-job spooling, broader performance and phase7remain
active. No physical printer/provider call, foreign native acceptance or promotion.

Phase5 adds a strict typed element geometry/change boundary. Percentage sizes and
positions resolve to the appropriate canvas axis before millimetre display, centering
or aspect-preserving image resizing. Invalid numeric dimensions cannot enter the
helper patch. QR resizing updates both axes atomically in one history revision.
Opening the panel preserves persisted percentage values and document revision.
This checks the extracted TS boundary; the whole JSX/store surface is not yet TS.

All206frontend tests in37files pass, including31focused element/properties tests.
The integrated backend passes776tests with one platform skip, and all ten static
categories are empty without a baseline change. Parent inspected the clean compiled
QR controls, one Undo15mm→Redo20mm and the accessible object-selection path.
Axe has zero violations with one incomplete contrast result. Native keyboard/pointer
and physical output remain unverified. The shipped27-file frontend matches the
inspected clean build. [Element receipt](reviews/2026-10-02/evidence/phase5-elements-receipt.json).
The lightweight paginated project summaries and detail-on-selection work was already
accepted earlier in phase6; it is not an outstanding implementation task.

Phase7 maintenance policy names the repository maintainer and change/integration
owners, weekly live advisory checks during active development, monthly upstream/debt
reviews, peer-gated major-version triggers and release-receipt requirements. Future
review dates do not imply those reviews or unavailable native/hardware tests ran.
The policy distinguishes Vulture protocol-parameter false positives, compatibility
deferrals and the currently empty advisory exception list. The table above now
reflects completed work; historical checkpoints below remain unchanged.
[Maintenance routine](development-checks.md#maintenance-ownership-and-review-cadence).

Phase6 printer preparation yields one owned transformed page at a time and closes
it after encoding. Generic protocol jobs and released Phomemo page streams move to
a private temporary spool (500jobs/256MiB maximum), preserving every protocol step
and matcher identity. All payloads are encoded before the first payload send.
Released Phomemo sends the identical concatenated stream in at most64KiB calls.
Runtime control probing can still precede encoding. Failure/cancellation closes the
spool/iterator and owned page images; borrowed sources remain open.

Parent inspected all Luna non-UI edits and tests. The integration passes776backend
tests with one platform skip and ten empty static categories, including45Generic,
36released-Phomemo/spool, nine helper and15paper-layout scoped tests. Full source
input lists and matcher closures remain retained; no whole-pipeline constant-memory
claim is made. The dedicated legacy Phomemo path is unchanged. The fixed memory
experiment is in progress; this receipt makes no unmeasured performance claim.
[Protocol spool receipt](reviews/2026-10-02/evidence/phase6-protocol-spool-receipt.json).
No hardware/provider/foreign native acceptance or promotion occurred.

The fixed PD01 spool matrix passes18valid fresh-process samples (1/20/100labels,
three repetitions per candidate), with byte/metadata hashes equal at every count.
At100labels median replay RSS falls195148→137764KiB and process lifetime highwater
198444→141400KiB (about29%). Median encode+fake replay is4.254→4.400seconds; this
is a memory improvement, not a speed or physical-throughput claim. At most one
prepared image/job is live in the streaming candidate. Full source RGB lists remain
retained. One excluded harness close-verifier failure and its replacement are recorded.
Spool fstat lengths precede buffered flushing and are not full logical-byte counts.
[Memory receipt](reviews/2026-10-02/evidence/phase6-spool-memory-receipt.json).


Final phase6 integration replaces headless whole-job base64 transfer with one
acknowledged frame and local whole-job PNG accumulation with binary staging.
Local preparation overlaps one upload with one rendered successor, retaining at
most two page payloads and strictly ordered uploads. Server sessions have private
files, single-use commit leases, expiry and limits (four sessions, 500 pages,
8MiB/page, 64MiB/session, 50 million pixels). A canceled preparation never commits;
committed output retains the existing truthful physical-completion receipt.

The final Linux full gate runs810 backend tests (809 passed, one Windows SDK skip),
220 frontend tests, all ten empty static categories and a clean production build.
No baseline diagnostics or suppressions were added. Parent inspected the Luna
non-UI changes and owns all UI/compiled-browser acceptance. The bundled27-file
frontend matches the inspected artifact exactly; its canonical release digest is
`de8c72340261a8d51bffc2877d5fbfdb20edda26cbd7b647633a98bfa954de9c`.
[Streaming/performance receipt](reviews/2026-10-02/evidence/phase6-stream-performance-receipt.json)
and [local staging receipt](reviews/2026-10-02/evidence/phase6-local-staging-receipt.json).

On the declared desktop, numeric-edit paint proxies have p95 of60.9ms (one QR)
and48.6ms (200 painted rectangles); displacement-verified synthetic drag frames
have p95 of21ms. Native pointer/keyboard latency remains unverified. Icon search
has p95 of39.6ms and the one cold-dialog sample is352ms; a new icon data subsystem
is not justified by these observations. Earlier blank200-item and idle-pointer
measurements are explicitly excluded. Heap snapshots are not leak proof.

The corrected5ms headless handoff stays within about1.2% of the legacy median for
20 pages and100 mixed labels, with exact pixel/geometry parity. The local workflow
has an intentional per-page HTTP/validation boundary: three paired100-label runs
have medians14.306s legacy and14.967s staging (4.6% overhead), with all100 outputs
identical and at most three stages including the visible editor/previews.
The broad one-label,10-record, concurrent-render and four-page4x6 PDF observations
are retained with candidate/version provenance; three samples do not establish p95.

Acceptance reconciles the proposed memory target with current printer contracts:
encoded jobs and browser handoff are bounded by chunk capacity, while decoded RGB
source lists remain under the50-million-pixel ceiling. Eliminating those lists
requires a separate repeatable-image/preflight driver contract; it is an explicit
remaining optimization, not an assertion of whole-pipeline constant memory.
The dedicated legacy Phomemo sender is unchanged. Physical PD01 and tentative
Niimbot D111/D100 checks, foreign native installers, live providers and native UI
input remain unverified. These are retained compatibility/acceptance limits under
the user's Linux-only and best-effort instructions. No deployment or push occurred.

The locally executable maintenance phases are now implemented and verified within
the documented scope. The phase7 routine is manual future upkeep, with named owners
and review dates; recurring execution and automation were not requested.

### Selected upstream controls and ordinary Phomemo follow-up — 3 October

LuckP A41 now resolves density/speed from each connection's bounded firmware
window and requires speed acknowledgement before setup/pixels. It is scoped to
`luckp_a41`, preserving APA41/A42 behavior. Unknown firmware conservatively uses
density 0..2/default 1 and no speed. Catalogs and saved settings remain immutable;
connected UI publication of these ranges is deferred.

Connected dedicated M02/M02S/M02X/T02 clients now retain per-page delay estimates
alongside the bounded spool and consume Classic/BLE reported faults through scope
exit. Ordinary recipes do not use upstream's buffered idle query or completion
count branch. Coalesced recovery cannot erase an active-job fault, and disconnect
preserves the first error. Raster payloads remain at the accepted v0.8.1 recipes;
the newer compact placements/M02X recipe have a separate migration packet in the
[plan](reviews/2026-10-02/plan.md#selected-upstream-follow-up-3-october).

The print request no longer aborts after an arbitrary browser two-minute deadline.
A virtual 121-second test retains the submission guard; the inspected compiled
app accepted a recorder response after 130 seconds, showing one label submitted
with physical completion unverified. Exactly one recorder job was observed.
No hardware was called. The accepted 27-file frontend is copied into the bundle
with canonical digest `28e5293879eab44d6c944c10c154d214254cd783373c799925cf59203c9f7789`;
the previously accepted artifact is retained in scratch as a recovery copy.

The final Linux full gate runs852 backend tests (851 passed, one Windows SDK skip),
221 frontend tests, ten empty static categories and a successful production build.
Both new runtimes and their control DTOs enter strict typing coverage. The first
full attempt caught28 typing errors in new test fixtures; matching interfaces,
keyword signatures and Optional narrowing repaired them without ignores, baseline
additions or configuration relaxation. Parent inspected all delegated edits.
Luna/max handled bounded evidence and exact non-UI implementation; OpenCode's
configured Muse Spark1.3 profile reviewed the A41 contract without findings.
Runtime model/effort telemetry was unavailable.

[Follow-up receipt](reviews/2026-10-02/evidence/upstream-controls-receipt.json)
records source pins, hashes, validation, local adaptations and remaining limits.
Physical printing, foreign native acceptance, deployment and push remain unperformed.

### Physical PD01 acceptance and quieter print feedback — 3 October

The standard locked Linux setup completed and the actual app runs locally on port
18260 because 8000 is occupied by another service. The user confirmed the PD01
printed the short text test and reported printing larger QR codes. QR scanning
and Niimbot physical acceptance are not established by that report.

Save, recovery and submission details now live behind Status. Recovery persistence
and unload protection remain mounted with that panel closed. Preparation no longer
opens or blurs a full-screen dialog; print buttons display Preparing/Printing and
remain disabled until the guarded request ends. Progress and cancellation before
submission remain available inside Status. The parent inspected the compiled app,
observed both button states, the unobscured canvas and the final submission receipt.
The test design was saved as a project before refresh.

PD01 settings no longer advertise an unsupported speed default and explain that
raw density controls darkness rather than a speed command. A Luna/max researcher
checked current backend and pinned upstream; runtime model metadata was unavailable.
The user reports good text but very slow, intermittent motion. A no-print-data link
probe observed public characteristic write sizes of 20 bytes; backend diagnosis
continues before changing transport pacing or print-head settings.

Frontend lint, typing, 226 tests and production build passed. All ten static policy
categories remain empty. Existing large optional-chunk warnings and Vulture context
manager advisories remain. No backend behavior changed in this UI packet.
[Receipt](reviews/2026-10-02/evidence/printing-ui-receipt.json) records source and
bundle hashes, evidence boundaries and the pending throughput diagnosis.
