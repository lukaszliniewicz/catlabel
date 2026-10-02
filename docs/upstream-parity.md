# Released printer parity ledger

Source baseline: [TiMini-Print v0.8.1](https://github.com/Dejniel/TiMini-Print/tree/f676917257b5d1f869e0f13beff03785258e2a2e), peeled commit `f676917257b5d1f869e0f13beff03785258e2a2e`. Research uses that immutable commit, even when the local clone has a newer HEAD. The checked-in bundle is now v0.8.1, with 133 executable generic records and 12 records deferred to dedicated vendor ownership.

The source license is Apache 2.0. The repository `NOTICE` retains upstream attribution. Changed source modules and the implementation ledger distinguish local adaptations from upstream code.

| Surface | Local owner | Released behavior / local decision | State |
| --- | --- | --- | --- |
| Catalog schema/publication | `vendors/generic/models.py`, `tools/sync_timiniprint_catalog.py` | Normalize both schema generations, preserve origin/detection/preset metadata, validate all five files before atomic publication. | Published and integrated; source pin, counts and affected paths pass the Linux full gate. |
| Explicit write routes | `protocol/steps.py`, `printing/step_execution.py`, `printing/send.py` | Local improvement: separate CONTROL, BULK and STANDARD steps without interpreting raster bytes as commands. Preflight required routes before the first write; preserve concatenated wire bytes and old positional interfaces. | Integrated; full gate passes. |
| V5X | `protocol/families/v5x.py`, `printing/runtime/v5x.py` | A2/A9/raster/AD; literal A9 length/footer; no unconditional A7; opaque raster; atomic A9 acknowledgement; post-AD AA readiness; B3 challenge response. Explicit channels and refusal of generic fallback are local adaptations. | Complete-frame fixtures/full gate pass; transport fragmentation/coalescing and physical acceptance open. |
| Eleph / ToPrint | `protocol/families/{eleph,toprint}_*.py`, `devices/bluetooth_profiles.py` | Separate dialect identities. Eleph P1 integer-mm SIZE, GAP 2, DIRECTION 0, inverted bitmap. ToPrint retains its media prefix, uninverted bitmap and black-tag BLINE recipe. Positioning/final margin follow explicit media-page boundaries. Normalize two known legacy ToPrint profiles without mutating their raw source snapshot. | Integrated; full gate passes; physical acceptance pending. |
| Tiny | `protocol/packet.py`, `printing/runtime/tiny.py`, `devices/bluetooth_profiles.py` | Existing `tiny` and `tiny_prefixed` aliases already execute through legacy encoders. Add fragmented/coalesced AE pause/resume handling using the common 51 78 receive prefix; prefer notify and use a separate finite resume budget. | Integrated BLE and native Linux Classic routes pass; physical acceptance pending. |
| Classic receive | `transport/bluetooth/classic_receive.py`, `transport/bluetooth/backend.py` | One reader, bounded history and offset waiters; never shorten sendall timeouts to poll replies. Native selectable sockets only initially; WinRT retains its worker/loop ownership. | Live native Classic integration and Linux socketpair tests pass; custom WinRT/macOS readers retain their existing paths. |
| Funny LX | `printing/runtime/funny_lx.py` | Keep released direct packets and retries. Reject missing footer query capability before sending setup/image bytes. Existing reversed variant is a local extension, not released parity. | Focused preflight checks pass. |
| S001 | `protocol/families/yk_*.py`, `printing/runtime/yk_astra_p1.py` | Released Orgstra S001 uses 96-pixel head, four-row slices, six-pixel padding and distinct media feed recipes. New support requires both encoder and status/completion integration. | Encoder, live status/completion, public-client and multi-job fixtures pass; model promoted. Physical acceptance pending. |
| NIIMBOT D11/D11S/D110 | Dedicated `vendors/niimbot` | Review CONNECT/model/protocol probe, height-only versus height/width task commands, row metadata and E0 versus A3/B3 completion. Keep ownership separate from generic catalog. | Pending. D11 retail name spans 203/300 DPI revisions; do not infer geometry from the name alone. |
| Phomemo | Dedicated `vendors/phomemo` | Released compact/PrintMaster recipes differ from current custom paths. Prefer notification support independently. Preserve existing M02 Pro geometry until a verified revision/recipe resolves conflicting manufacturer width descriptions. | Notify policy implemented; recipe/geometry parity unresolved. No blind geometry replacement. |
| Paper transforms | Generic client and shared paper/rendering helpers | Apply released render-height and preset rotation in the correct order; preserve user rotation and width budgets. Metadata parsing alone is not rendering parity. | Integrated; exact two-stage pixel references, pre-allocation limits and owned-image cleanup pass. Preset selection UX remains phase 5. |
| Post-release master | Exact selected commits only | Complete-payload/control-notification/pre-write and Luck/PrintMaster changes require their own pin and fixtures after released baseline. | Pending; no moving-master adoption. |

Classic receive callbacks are marshalled synchronously to the owning asyncio loop;
runtime listeners consume notifications before reply predicates. S001 starts reset
active completion state and never replay historical bytes into the decoder. Its
source has no job ID, so fixtures cannot prove association of delayed physical
printer notifications. Missing status or completion remains an unverified warning.

Native Classic retains one transport worker. Inbound Tiny resume callbacks can
unblock writes independently; outbound control/query work does not progress
concurrently behind a paused write. Custom Windows/macOS readers have no equivalent
native socket-hub integration yet. No cross-platform receive parity is claimed.

## Acceptance levels

Source-backed fixtures establish command and state-machine compatibility, not physical output. Every changed family needs missing/negative replies, fragmented/coalesced notifications, opaque pixels, multi-page boundaries and cleanup tests appropriate to its transport.

Linux is the available native system. Windows/macOS are best effort for now: platform locks, scripts and portable interface tests, with native execution labelled unverified. Their unavailable native systems do not block local implementation completion.

Available hardware is PD01 and a printer tentatively identified as NIIMBOT D111/D100. Record exact advertised name, model/revision, firmware, transport and media before a physical receipt. PD01 is a generic cat-printer path; a D111-like advertised name alone is not proof of NIIMBOT protocol ownership. No physical acceptance is claimed by this ledger.
