# CatLabel application review

Reviewed on 2 October 2026 against commit `c193e93d82b13724196aa29b22d52055fd112406`. The checkout was clean at the start. This review adds documentation and evidence only; application code, dependencies, printer configuration and release artifacts remain unchanged.

CatLabel has a useful foundation, particularly its protocol/runtime/transport separation and recent frontend hardening. The next work should prioritize truthful printer selection and completion, safe local operation, reproducible installation, and backend resource limits. Decomposition and major upgrades should follow clear contracts and a measured debt cleanup, rather than arrive as one large rewrite.

Read the [implementation plan](plan.md), [measured baseline](baseline.md), and [dependency inventory](dependencies.md). Proposed work is not implemented by this review.

## Findings that should lead the work

| Priority | Finding and concrete consequence | Local evidence |
| --- | --- | --- |
| P1 | Phomemo claims generic and unsupported names beginning with D. Actual classifier execution resolves D80, D100, D1 and D2 to D30, at 120 px / 203 DPI. M02PRO and M02 PRO resolve to ordinary M02 at 384 px / 203 DPI instead of the Pro geometry. This can select the wrong wire protocol or size. | `catlabel/vendors/phomemo/manifest.py:72,93`; `catlabel/vendors/registry.py:38` |
| P1 | The nominally local app binds to `0.0.0.0`, permits wildcard CORS, has no authentication in the inspected routes, and serializes saved provider API keys from `/api/ai/config`. LAN reachability depends on the host firewall; the code exposes an unnecessary secret-reading surface. No real credentials were read. | `catlabel/__main__.py:31`; `catlabel/api/main.py:87`; `catlabel/api/routes_ai.py:180,214` |
| P1 | Niimbot explicitly continues after missing/rejected start replies and after an end-page timeout. HTTP success therefore does not establish device acceptance or completed printing. | `catlabel/vendors/niimbot/client.py:337,383` |
| P1 | Concurrent HTTP requests create independent clients for the same printer. Instance-local locks cannot serialize those sessions. There is no backend print admission gate shared across requests. | `catlabel/api/routes_print.py:266` |
| P1 | Backend request models lack matching limits for copies, matrix products, image count, decoded pixels and uploads. PDF conversion and printing eagerly materialize whole image collections. Frontend limits can be bypassed by direct API calls. | `catlabel/api/routes_print.py:73,370,401`; `catlabel/api/main.py:294`; `catlabel/vendors/generic/client.py:230,353` |
| P1 | Catalog synchronization writes files one at a time and expects the obsolete `origin_apps.json` path. A newer sync can fail after replacing four files, leaving old provenance alongside new data. The newer detection schema also cannot simply be copied into the existing loader. | `tools/sync_timiniprint_catalog.py:21,46,54`; `catlabel/vendors/generic/models.py:372` |
| P2 | The synchronous Playwright browser is cached globally but invoked through thread-pool calls. Only creation is locked; subsequent operations may occur on different threads. This is a source-backed thread-affinity/concurrency risk, not a reproduced renderer failure. Shutdown and broken-browser recovery are absent. | `catlabel/rendering/template.py:14,58`; `catlabel/api/routes_print.py:352,384`; `catlabel/api/main.py:75` |
| P2 | Project import commits each node, so invalid later input leaves a partial import and retry can duplicate it. Project category references are not validated. Project listing transfers every full document, and updates have no revision fence. | `catlabel/api/routes_project.py:35,48,62,199,221` |
| P2 | macOS/Linux install from broad requirements while Windows uses a concrete win-64 lock. The Unix bootstrap downloads an unpinned, unchecked bootstrap binary and uses the caller's current directory. The Windows launcher follows the repository rather than a selected release. | `run.sh:8,37,51,97`; `run.bat:36,106`; `launcher.py:46` |
| P2 | Rendering does not have a unified readiness barrier for canvas images, barcodes and HTML items. `HeadlessPage` waits for HTML readiness and a fixed 100 ms delay; canvas image/HTML hooks and barcode generation complete independently. Errors can become blank output. This is a credible source-backed race requiring a delayed-resource test. | `frontend/src/components/HeadlessPage.jsx:68`; `CanvasItemNode.jsx:37,125`; `frontend/src/utils/rendering.js:54,220` |

Priorities express this review's judgment, not a full security audit or hardware certification.

## TiMini Print compatibility

The app is derived from [TiMini-Print](https://github.com/Dejniel/TiMini-Print). Its catalog is pinned to v0.7.3, commit `3373a037ccbaafc32cfafd5ed9ef496efd1efacd`, with 143 supported source records and 132 executable generic records locally. Eleven source records are separately owned by Niimbot/Phomemo; that exclusion is intentional.

The [latest release v0.8.1](https://github.com/Dejniel/TiMini-Print/releases/tag/v0.8.1), commit `f676917257b5d1f869e0f13beff03785258e2a2e`, was published on 17 September UTC / 18 September in Warsaw. Its consequential printer changes arrived in v0.8; v0.8.1 is primarily a packaging/regression follow-up. Released data contains 145 supported / 165 unsupported records, 129 profiles and 51 presets. These counts are catalog records, not unique retail devices.

Released changes requiring explicit adoption:

- Catalog schema and origin-file changes; richer detection conditions, exclusions and ambiguity handling.
- Orgstra S001 / `yk_astra_p1` encoder and session/status runtime; the distinct D11S record needs dedicated-vendor reconciliation.
- Tiny AE buffer pause/resume and a continuous Classic receive lifecycle, including polling independent of the send timeout. CatLabel has Tiny encoders but no Tiny runtime controller. [Released Tiny runtime](https://github.com/Dejniel/TiMini-Print/blob/v0.8.1/timiniprint/printing/runtime/tiny.py), [Classic receive code](https://github.com/Dejniel/TiMini-Print/blob/v0.8.1/timiniprint/transport/bluetooth/classic_receive.py).
- V5X A9 framing and atomic acknowledgement, removal of A7 from every stream, AA next-page readiness, B3 signing, and opaque raster preservation. These are present in v0.8.1, not merely master. [Released encoder](https://github.com/Dejniel/TiMini-Print/blob/v0.8.1/timiniprint/protocol/families/v5x.py#L70), [runtime](https://github.com/Dejniel/TiMini-Print/blob/v0.8.1/timiniprint/printing/runtime/v5x.py#L145).
- Separate Eleph/ToPrint families, corrected Eleph P1 commands, bitmap polarity, orientation, SPP preference/pacing, and ToPrint black-mark media. Paper metadata now needs more than width/padding/mode. [Released Eleph encoder](https://github.com/Dejniel/TiMini-Print/blob/v0.8.1/timiniprint/protocol/families/eleph_tspl/core.py#L13), [released profiles](https://github.com/Dejniel/TiMini-Print/blob/v0.8.1/timiniprint/data/printer_profiles.json#L5818).
- Funny LX reversal removal, plus Niimbot and Phomemo geometry, raster and session changes. Dedicated local clients require independent comparison; updating generic JSON does not update them.

Master at review time is [7be93f549597fe7e82ef67e3102c6233aa875f28](https://github.com/Dejniel/TiMini-Print/commit/7be93f549597fe7e82ef67e3102c6233aa875f28), dated 29 September UTC. Post-release changes include Luck A4/APA49 profiles, DPI/media/rotation changes, revised Phomemo/Print Master ownership, separate BLE control notification routing and a runtime pre-write hook. The latest shared parser accepts complete declared payloads without requiring frame trailers. Master has 144 supported / 166 unsupported records, 128 profiles and 79 presets; fewer records does not mean less support. Adopt a tagged baseline first and review selected master fixes by exact commit.

Phomemo also flattens the whole raster before packing, while advertising `ceil(width/8)` bytes per row. A 9×2 raster produces three packed bytes instead of four. Row padding must be applied per row (`client.py:53`; `protocol/encoding.py:45`).

## UX and installation

Parent-owned browser inspection used a disposable application copy and database, the rebuilt production frontend, an isolated Python 3.11 environment, and no print calls. Font downloading was disabled. Real printer discovery was not part of acceptance; the initial scan ran before the review's incomplete scan stub was identified. Successful Bluetooth connection and physical output remain unverified.

Observed in the browser:

- First-run setup offers scan or offline profile selection, with no direct start-designing exit. AI configuration is skippable, but remains a prominent setup step. Setup completion is coupled to `intended_media_type`, which is also an AI setting.
- The generic model list is long, has no search, and includes identical display names such as BQ02, MX02 and P1 without visible protocol/profile distinction. The suggestion that a cat-shaped printer is almost always GT01 is too confident for conservative detection.
- An offline GT01 profile enables Print. Printing is guarded later by an alert, but the enabled control misstates readiness. Offline profile selection also disappears on reload even though the profile remains stored.
- At the default 1222 px viewport, the open 360 px properties overlay covers part of the label. At 390×844 after reload it covers nearly the whole workspace. Sidebar collapse responds to initial mount, not subsequent viewport changes.
- Seventeen visible text-element property fields had neither associated HTML labels nor `aria-label`; the accessibility tree showed unnamed steppers/selects. Tabs expose semantics but lack full tab keyboard navigation. Canvas shortcuts ignore input/textarea/select but not every editable or modal context.
- Many controls use very small uppercase text and faint neutral colors. Some buttons already have accessible names and dialogs already trap/restore focus; preserve that work while repairing remaining fields, contrast and keyboard behavior.
- Save/load is explicit. No dirty-document indicator or unload protection was found. Recoverable drafts and a clear saved state would materially reduce accidental work loss.

Installation needs a stable release target, consistent locked environments, clear progress/retry/offline state, a diagnostic repair command and an optional headless feature that can be added later on every OS. Bundling provider SDKs in the base installation should be reconsidered after tracing LiteLLM's optional requirements. No cold-install duration or Windows/macOS native acceptance was measured.

## React, structure and performance

Preserve existing selectors, shallow object selection, memoized canvas nodes, local snap state, lazy AI/modals/code engines, sanitized DOM insertion, frontend batch limits and centralized API errors. React 19 is already in the lockfile; the app does not need a React 18-to-19 migration.

The current ESLint configuration enables only two Hooks rules. Enabling the installed plugin's full recommended preset adds 19 diagnostics: 11 `set-state-in-effect` and eight `static-components`. Nested `SidebarButton`, `PresetCard` and `Section` definitions create new component identities. Effects that reset derived UI/mapping state need targeted replacement; DOM, image and Konva synchronization legitimately use effects. [React Hooks rules](https://react.dev/reference/eslint-plugin-react-hooks), [effect guidance](https://react.dev/learn/you-might-not-need-an-effect).

The store has 1,707 lines; PropertiesPanel 1,209; AIAssistant 849; CanvasArea 668. Boundaries should follow document/history, selection, printer/profile, persistence, batch preparation, AI, element properties and canvas interactions. `store.js` imports template generation from `components/templateStyles.js`; extract reusable domain functions from the component directory. Retain one composed store and atomic hydration/history contracts initially.

Backend hotspots include Bluetooth backend 829 lines, generic models 662, AI routes 665 and AI tools 693. The full static import graph has two strongly connected components: API main ↔ AI routes, and an 18-module protocol aggregation group. Excluding deferred and type-only edges leaves zero import-time cycles. Shared services and acyclic protocol primitives would still make ownership clearer; no import-time crash was demonstrated.

Measured grayscale preprocessing repeatedly calculates `ImageStat.Stat` in a 256-entry LUT. Hoisting one invariant calculation preserved exact output on four synthetic fixtures and reduced medians from 44.6–405.6 ms to 3.9–25.8 ms, a 7.85–15.69× speedup for this function. This does not establish an end-to-end print speedup. [Experiment](evidence/raster-results.md).

The built initial script plus three modulepreloads total 776,074 bytes, approximately 228 KB gzip. Lazy chunks include IconPicker at 763.52 KB and bwip-js at 951.49 KB. Measure their cold interaction cost before changing chunk strategy. CanvasArea renders up to ten records multiplied by every page, with a Stage for each; only the records are capped. Offscreen pages and inactive records need preview virtualization/culling, with full-resolution output retained separately. [Konva performance guidance](https://konvajs.org/docs/performance/All_Performance_Tips.html).

Batch preparation stores all base64 results, copying the growing array for every result. Frontend render limits help, but chunked job rendering/transmission and backend limits are still needed. Image/barcode caches, item indexing and tighter store subscriptions should follow profiling. React Compiler is a later bounded experiment, after the recommended rules and render contracts are clean.

## Evidence boundaries and review provenance

Native evidence tasks used configured GPT-6.1 Sol/high for printer/backend comparison, and GPT-6 Luna/max for dependency research, baseline checks and the raster experiment. Child runtime identity was not independently exposed. OpenCode via the Subagent MCP reported OpenCode 2.0.21 and a configured `opencode-go/muse-spark-1.3-contributor` model; it supplied a bounded non-UI install/persistence/rendering perspective. Its claim that a global lock serialized whole render operations was rejected after parent source inspection: the lock covers browser creation only. Its other hypotheses were retained only where local source supported them.

All architecture, UI/browser work, proposed policy and final judgments were parent-owned. No specialist implementation occurred. Hardware fidelity, native installation, Python advisory scanning, exhaustive accessibility testing, representative browser latency/heap profiling and renderer thread-failure reproduction remain open acceptance work. Passing unit tests and registry metadata do not establish those results.
