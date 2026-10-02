# Maintenance implementation ledger

Objective: implement the complete [2 October maintenance plan](reviews/2026-10-02/plan.md), making coherent verified commits. A completed checkpoint is not completion of the overall objective.

| Phase | State | Evidence / remaining work |
| --- | --- | --- |
| 0 — reproducible checks | Implemented locally; native acceptance open | Review committed as `0e61a31`; hermetic/portable tests as `2718c08` (67/67). Canonical dependencies, hashed check locks, diagnostic ratchet, graph/contracts, advisory gate and native CI are integrated. Full Linux check: 83 backend tests, 21 frontend tests and scratch production build pass. A deliberately introduced F821 failed the actual static gate; no new tooling debt is baselined. Existing Pixi lock verified unchanged by dry-run. Hosted/native validation remains unverified. |
| 1 — correctness and local operation | Pending | Classification, write-only keys/binding/origins, device admission, backend limits, completion/row packing, safe catalog sync and project transactions/revisions. Prompt dependency patches in separate commits. |
| 2 — debt elimination | Pending | Reduce Ruff/format/typing/React/Knip debt to zero; remove coupling and temporary exceptions. |
| 3 — upstream parity | Pending | Tagged v0.8.1 catalog/schema/protocol/runtime ledger and fixtures; separately recorded hardware acceptance. |
| 4 — installation/dependencies | Pending | Native locked bootstrap and release/update/repair workflow; staged major migrations and native installation matrix. |
| 5 — structure/UX | Pending | Typed interfaces/store/component decomposition; responsive/accessible setup/editor/save recovery. Parent owns browser acceptance. |
| 6 — performance/lifecycle | Pending | Measured alpha hoist, unified render readiness, Playwright ownership, bounded jobs/previews and representative benchmarks. |
| 7 — maintenance routine | Pending | Owners, expiry/review triggers, dependency/upstream/release receipts and debt gates maintained. |

The original [review baseline](reviews/2026-10-02/baseline.md) remains immutable historical evidence. Updated checks describe their configuration/environment; changed counts must not be interpreted as fixes without comparing the diagnostics.

Current migration baseline: Ruff 629 under the explicit Python-3.11 policy; 83 formatter files; 193 standard/strict Python diagnostics (six missing Windows SDK imports in Linux); 19 React rule findings; two exports in each Knip mode; two full Python SCCs and zero eager/frontend cycles. Import Linter contracts pass with the one named stateless-family-ID exception. Source and checker environment/configuration changes explain count differences; the debt is still scheduled for phase 2.

The locked Linux check environment audit covered 123 packages and found three urllib3 2.7.0 advisories, all listing 2.8.0 as fixed. Current npm metadata reports eight vulnerable package entries, represented by 21 advisory/exposure records. Exact temporary exceptions are recorded with rationale, owner and expiry; neither advisory audit is being called clean. The first prompt-patch commit must remove applicable exceptions.
