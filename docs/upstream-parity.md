# Released printer parity ledger

Source baseline: [TiMini-Print v0.8.1](https://github.com/Dejniel/TiMini-Print/tree/f676917257b5d1f869e0f13beff03785258e2a2e), peeled commit `f676917257b5d1f869e0f13beff03785258e2a2e`. Research uses that immutable commit, even when the local clone has a newer HEAD. The immutable checked-in bundle is v0.8.1. Pinned local overlays and ownership corrections now yield 136 executable generic records, eight deferred records and 166 unsupported records (165 released records plus one ownership redirect).

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
| NIIMBOT D11/D11S/D110 | `protocol/families/niimbot_core.py`, dedicated `vendors/niimbot` | CONNECT/model/version probe before print commands; height-only versus height/width page commands; empty/sparse/dense row metadata; E0 versus finite A3/B3 completion. D11 auto-selection requires a complete B5 version field. | Integrated source/fixture path; experimental D11S 96 px / 203 DPI profile. Existing D11/D110 geometry retained; no retail-name DPI inference or physical acceptance. |
| Phomemo | `protocol/families/phomemo_esc_core.py`, dedicated `vendors/phomemo` | Released M02/M02S/M02X/T02 recipes, native raster pixels, source density/feed units, strip preflight and owned-image cleanup; Classic preferred with BLE fallback. M02 Pro retains its conflicting local geometry/recipe. | Ordinary recipes integrated. Exact M110/M120 names select experimental PrintMaster recipes; M220/M221/M260 and arbitrary M110/M120 suffixes remain unknown. Existing P12/D/M04/M03/M200 paths remain local extensions. Physical acceptance open. |
| Paper transforms | Generic client and shared paper/rendering helpers | Apply released render-height and preset rotation in the correct order; preserve user rotation and width budgets. Metadata parsing alone is not rendering parity. | Integrated; exact two-stage pixel references, pre-allocation limits and owned-image cleanup pass. Preset selection UX remains phase 5. |
| Selected post-release changes | Exact commits listed below | Declared-payload accessor, separate control notifications and physical-chunk permission hook, plus corrected Phomemo ownership vetoes. | Pinned Luck A4 overlay/transactions and PrintMaster recipe/runtime integrated with fixtures. No moving-master catalog update. |

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

## Selected post-release provenance and remaining deltas

- `1afe4287428a73a0be8beace8079efcfd0d70d6b`: BLE control-notification UUID routing and `before_write(size, timeout)`. Control replies never satisfy ordinary notification waiters. Each physical chunk waits for flow, reserves permission, then writes; failure aborts without replay/refund. Subscription rollback, cancellation and runtime-stop errors still attempt all unsubscribes and physical disconnect. Local transport has no persistent replay subsystem; source UUIDs are logged. Existing profiles keep an empty control UUID.
- `7be93f549597fe7e82ef67e3102c6233aa875f28`: the payload accessor accepts complete declared bytes without requiring a trailer. The decoder still requires CRC/footer. Six-byte V5X compact markers remain ambiguous with fragmented full-frame headers; this accessor is not validation or a claim of V5X stream-fragment acceptance.
- `3bd80bac89f8894e143ee867c63683b6c7f2f02b`: upstream corrects M110/M120 ownership to PrintMaster and marks M220 unsupported. CatLabel no longer advertises its former compact Phomemo aliases; the broader local M221/M260 aliases are also deferred without supporting evidence. Pure compact m110/m220 helpers remain reference fixtures only.

- `76b3171bb956603277f7d97863d7e607d3de2e89`: a validated local overlay splits APA41 from APA49/E49 and updates 16 A4 profiles and 29 referenced presets. APA41 defaults to density 2, APA49 to 3; explicit zero is preserved. A4 supports BW1, while normal Luck retains gray. Density/status/finalization replies are required; paper-setting windows are optional. Lujiang A4 finalization has a 120-second budget. Final motion follows media-page boundaries and last-marker ordering. LuckP A41 firmware-dependent density/speed is added in the follow-up below. Unused width/page-marker helpers remain deferred.
- `fe603ca2ee1d21866f66f86d63ca2fc101916de8`: PrintMaster M110/M120 optional density/speed precede reset, M120 adds print-multi, and GS v0 uses 384-pixel MSB rows. The public route omits global cat-printer speed/feed/energy defaults and waits after each page. Physical support remains experimental.
- `43b3203e229c271b75e86703e3a8f2ce428a8c45`: distinct Phomemo/PrintMaster frame lengths and prefixes. Known auxiliary frames are opaque even when their payload resembles completion or a fault.

PrintMaster scopes arm before the first write. First-byte receive offsets exclude stale partial completion; decoded faults remain fatal through scope exit, including completion followed by fault or disconnect. A missing completion observer fails before pixels; missing completion fails after a finite wait without retransmission. This is a conservative local adaptation. Complete delayed physical replies have no job identifier, so fixtures cannot establish their association. Classic/BLE portable contracts are tested; physical printing and Windows/macOS native receive remain unverified.

The immutable release bundle and legacy JSON hashes are unchanged. Source metadata retains the release pin and lists the selected catalog overlays separately. Ordinary Phomemo's direct pacing and reported-fault follow-up is described below; the upstream buffered idle-query/result-count branch does not apply to these ordinary recipes.

NIIMBOT completion is armed before pixels and remembers early live E0 events. Frames whose first byte arrived before arming and queued callbacks from another generation cannot complete the new page; partial device errors remain fatal. Neither the source protocol nor the local guard can prove physical job association for an entire delayed frame arriving after arming. Missing completion fails with delivery uncertainty and never retries pixels.


## LuckP A41 and ordinary Phomemo follow-up

LuckP A41 (`luck_normal_a4` / `luckp_a41`) now probes `10 ff 20 f1` before
encoding on each connection. The firmware policy is pinned to
`76b3171bb956603277f7d97863d7e607d3de2e89`: recognized text below `1.26` uses
density 0..2/default 1 without speed; recognized modern text uses density
1..15/default 8 and speed 0..8/default 4. The upstream lexicographic threshold
comparison is retained deliberately. Local strict ASCII parsing rejects malformed,
non-numeric and over-128-byte replies. Unknown firmware conservatively uses the
old range rather than upstream's wider unknown-firmware default. The full BLE
window uses a bounded callback collector because an optional always-false waiter
returns no payload; the native query route supplies its own aggregate.

Saved per-printer overrides resolve against the live range before encoding;
explicit density zero is preserved where allowed, speed zero means automatic,
and global cat-printer defaults do not select these controls. Speed requires an
OK-prefix reply before setup and raster bytes. APA41 (`lujiang_a4`) and A42 retain
their existing behavior. Catalogs, saved settings and profiles are not mutated.
Firmware-dependent ranges are not yet published through a connected settings UI;
the current UI retains the static catalog controls.

At `7be93f549597fe7e82ef67e3102c6233aa875f28`, ordinary M02/M02S/M02X/T02
recipes are direct, non-paginated and estimate completion for every page. They
arm zero result acknowledgements. Their connected dedicated client now preserves
page timing alongside the bounded spool, checks reported faults across all writes
and waits each page's estimate. Native Classic callbacks and BLE runtime attachment
own the decoder. No buffered idle query or artificial one-result-per-page wait is
introduced. A write-only connection still prints best effort, with no device-fault
coverage. Reported heat fails immediately locally; automatic cooling/recovery is
deferred. Success replies and elapsed estimates leave physical completion unverified.
The browser waits for the submitted print response without its former two-minute
abort timer, retaining the in-page submission guard for long paced jobs. Backend
operation budgets and network-error handling remain in force; reloading or losing
the response is not a durable job-status mechanism.

The raster builders remain pinned to v0.8.1. The selected newer compact recipes
change top/left padding, M02S tag placement and the M02X wire recipe; those changes
require a separate whole-payload/geometry migration. See the [next migration
packet](reviews/2026-10-02/plan.md#selected-upstream-follow-up-3-october).
Source/fixture acceptance and remaining hardware/platform limits are recorded in
the [follow-up receipt](reviews/2026-10-02/evidence/upstream-controls-receipt.json).
