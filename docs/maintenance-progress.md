# Maintenance implementation ledger

Objective: implement the complete [2 October maintenance plan](reviews/2026-10-02/plan.md), making coherent verified commits. A completed checkpoint is not completion of the overall objective.

| Phase | State | Evidence / remaining work |
| --- | --- | --- |
| 0 — reproducible checks | Implemented locally; native acceptance open | Review committed as `0e61a31`; hermetic/portable tests as `2718c08` (67/67). Canonical dependencies, hashed check locks, diagnostic ratchet, graph/contracts, advisory gate and native CI are integrated. Full Linux check: 83 backend tests, 21 frontend tests and scratch production build pass. A deliberately introduced F821 failed the actual static gate; no new tooling debt is baselined. Existing Pixi lock verified unchanged by dry-run. Hosted/native validation remains unverified. |
| 1 — correctness and local operation | Implemented locally; hardware acceptance open | Classification/row packing, local-server/provider-secret fixes, device admission and Niimbot acknowledgements, shared processing limits, safe catalog publication and project transactions/revisions are integrated. Full Linux checks pass: 300 backend tests, 28 frontend tests and a scratch production build. |
| 2 — debt elimination | Implemented locally; native acceptance open | All source/check debt gates are zero, both full Python SCCs are removed, and no import-contract exception remains. 329 backend tests pass with one native SDK test skipped on Linux; 33 frontend tests and production build pass. |
| 3 — upstream parity | In progress; released generic integration implemented locally | V5X, Eleph/ToPrint, Tiny and S001 fixtures pass. Live Linux Classic receive, S001 encoder/runtime, paper transforms and v0.8.1 bundle are integrated. NIIMBOT and ordinary Phomemo recipes plus selected BLE/payload hooks are integrated. Luck A4 transaction and PrintMaster runtime adoption remain; unsafe compact M110/M120/M220 aliases are deferred. |
| 4 — installation/dependencies | Pending | Native locked bootstrap and release/update/repair workflow; staged major migrations and native installation matrix. |
| 5 — structure/UX | Pending | Typed interfaces/store/component decomposition; responsive/accessible setup/editor/save recovery. Parent owns browser acceptance. |
| 6 — performance/lifecycle | Pending | Measured alpha hoist, unified render readiness, Playwright ownership, bounded jobs/previews and representative benchmarks. |
| 7 — maintenance routine | Pending | Owners, expiry/review triggers, dependency/upstream/release receipts and debt gates maintained. |

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
