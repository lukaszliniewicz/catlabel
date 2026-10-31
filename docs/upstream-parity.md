# Printer protocol compatibility

The generic catalog is pinned to [TiMini-Print v0.8.1](https://github.com/Dejniel/TiMini-Print/tree/f676917257b5d1f869e0f13beff03785258e2a2e), commit `f676917257b5d1f869e0f13beff03785258e2a2e`, with the selected overlays listed below. Separate Niimbot and Phomemo backends retain their own ownership. Catalog recognition and source-backed fixtures do not guarantee every firmware or host Bluetooth adapter; unknown and ambiguous models remain unavailable.

The source license is Apache 2.0. The repository `NOTICE` retains upstream attribution. Changed source modules and this guide distinguish local adaptations from upstream code.

| Surface | Local owner | Released behavior / local decision |
| --- | --- | --- |
| Catalog schema/publication | `vendors/generic/models.py`, `tools/sync_timiniprint_catalog.py` | Retain the active release bundle and selected overlays. Schema 2 accepts the four-file v0.9.1 source with separately hashed detection-veto provenance. Unknown variants, encodings and unimplemented geometry remain unavailable. |
| Explicit write routes | `protocol/steps.py`, `printing/step_execution.py`, `printing/send.py` | Local improvement: separate CONTROL, BULK and STANDARD steps without interpreting raster bytes as commands. Preflight required routes before the first write; preserve concatenated wire bytes and old positional interfaces. |
| V5X | `protocol/families/v5x.py`, `printing/runtime/v5x.py` | Preserve explicit A2/A9/raster/AD routes and strict acknowledgement validation. Busy A9 replies retry only page start within 60 seconds; no AA prerequisite between pages and no pixel retransmission. BH03 selects the separate gray-label variant. Signing and passive final completion remain local runtime responsibilities. |
| V5C | `protocol/families/v5c.py`, `printing/runtime/v5c.py` | Byte-identical setup/raster/finalizer phases; job-scoped sticky faults and finite completion waits. Completion is armed at finalization and fenced by the frame's first-byte offset. Fragmented/coalesced flow and status frames share the validated decoder. |
| Eleph / ToPrint | `protocol/families/{eleph,toprint}_*.py`, `devices/bluetooth_profiles.py` | Separate dialect identities. P1 ToPrint uses inverted MSB rows, a double line ending and source dot-to-mm units; unproven manual motion is unavailable. HPRT dimensions are validated before packing. Preserve source media recipes and explicit media-page boundaries. Legacy source profiles are normalized without mutating the snapshot. |
| Tiny | `protocol/packet.py`, `printing/runtime/tiny.py`, `devices/bluetooth_profiles.py` | Fragmented/coalesced AE flow handling, signed wide-sheet tail motion and corrected ESC-star band/feed commands. Large feed counts use bounded command bytes rather than truncation; continuous strips honor media boundaries. |
| Classic receive | `transport/bluetooth/classic_receive.py`, `transport/bluetooth/backend.py` | One inbox reader with bounded history and offset waiters for native sockets and push sources. WinRT owns a private asyncio I/O thread; macOS owns a native queue/run loop and receive delegate. The backend keeps one command sequencer and never shortens send timeouts to poll. |
| Funny LX | `printing/runtime/funny_lx.py` | Keep strict ready/footer queries and existing retries. Apply darkness only when negotiated; passive status stays diagnostic. Unsupported manual motion is unavailable. The reversed variant remains a local extension. |
| S001 | `protocol/families/yk_*.py`, `printing/runtime/yk_astra_p1.py` | Released Orgstra S001 uses 96-pixel head, four-row slices, six-pixel padding and distinct media feed recipes. New support requires both encoder and status/completion integration. |
| NIIMBOT D11/D11S/D110 | `protocol/families/niimbot_core.py`, dedicated `vendors/niimbot` | CONNECT/model/version probe before print commands; height-only versus height/width page commands; empty/sparse/dense row metadata; E0 versus finite A3/B3 completion. D11 auto-selection requires a complete B5 version field. |
| Phomemo | `protocol/families/phomemo_esc_core.py`, dedicated `vendors/phomemo` | Current compact M02/M02S/M02X/T02 geometry and wire recipes, integrated with local preflight, spooling and fault pacing. M02X uses density levels 1..4 and fixed compact feed. Classic remains preferred with BLE fallback. The advertised legacy M02 Pro retains its separate local geometry. |
| Paper transforms | Generic client and shared paper/rendering helpers | Apply released render-height and preset rotation in the correct order; preserve user rotation and width budgets. Metadata parsing alone is not rendering parity. |
| Selected post-release changes | Exact commits listed below | Declared-payload accessor, separate control notifications and physical-chunk permission hook, plus corrected Phomemo ownership vetoes. |

Classic receive callbacks are marshalled synchronously to the owning asyncio loop;
runtime listeners consume notifications before reply predicates. S001 starts reset
active completion state and never replay historical bytes into the decoder. Its
source has no job ID, so fixtures cannot prove association of delayed physical
printer notifications. Missing status or completion remains an unverified warning.

Classic retains one command worker. Incoming callbacks can unblock paused writes
independently. A per-chunk permission callback runs the runtime check on its owning
asyncio loop before each standard write. Windows/macOS wrappers push copied bytes
into the same receive hub; native resources stay on their private I/O owners.
Failed cleanup retains the socket and prevents replacement until a retry succeeds.
Portable SDK fakes and socket pairs cover these contracts; native Windows/macOS
hardware and firmware behavior remain unverified. Outbound control/query work
still does not run concurrently behind a paused standard write.

## Selected upstream changes and remaining differences

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

LuckP A41 (`luck_normal_a4` / `luckp_a41`) probes `10 ff 20 f1` before
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
arm zero result acknowledgements. Their connected dedicated client preserves
page timing alongside the bounded spool, checks reported faults across all writes
and waits each page's estimate. Native Classic callbacks and BLE runtime attachment
own the decoder. No buffered idle query or artificial one-result-per-page wait is
introduced. A write-only connection still prints best effort, with no device-fault
coverage. Reported heat fails immediately locally; automatic cooling/recovery is
deferred. Success replies and elapsed estimates leave physical completion unverified.
Application print-job handling is documented separately in [print jobs](print-jobs.md).

The compact raster builders now follow
`6a71ecf7742e36be05bed7f4e52c4822cccced68` (v0.9.1): four blank top rows,
unchanged plain content widths, and left padding to the 588-dot M02S tag surface.
M02X uses the plain-only compact recipe. The pure M02 Pro helper uses a 583-dot
tag surface, while its advertised legacy backend remains separate. Input and
padded dimensions are checked before pixel work. Independent whole-payload
fixtures cover odd widths, media and page boundaries; pacing still uses input
height and does not establish physical completion.

## Selected v0.9.1 behavior ports

- `45b00c50a4382a8df626aa67d656f1d60c825805`: V5X busy-only page-start retries with one monotonic acceptance budget. CatLabel retains its stricter control/bulk plan preflight and reply matcher.
- `95beec7ba0f6422c29fd480ca262e369caf5e375`: BH03's gray-label mode is distinct from ordinary V5X grayscale; the selected catalog correction preserves the immutable release data.
- `fea985b20dbfe06067be122b4b28c5e39b8fb48a`: V5C faults and completion adapted to local job scopes. Known faults block a new job until a fresh healthy status; a current job's fault cannot be erased by a healthy reply. Missing observers fail before pixels when completion was requested.
- `73172c621c3b7aea9c71c9c024f9cd549d0b314e`: ordinary V5G exposes only monochrome dot output. Older descriptive profiles are narrowed locally; explicit unsupported grayscale requests fail. V5X/V5C grayscale is retained.
- `06c52a371c2db88b04ed968019a49930961a0165`, `7c858d3a3f9415825549b0a83c533e4d9cbb45c5`, `8ad78ebb6394235bd39ffef23dabe83885158f6d`: selected Tiny, Funny LX and ToPrint recipe corrections above.
- `c85406ac80c4aab95e5939ed934e5ff7997d5bc0`, `c5d8ec4d3aa069c488c6545e54984baf25c1f9fe`: bounded BLE setup and retryable cleanup ownership; complete GATT layouts bind characteristic instances. Preserve the existing BlueZ MTU policy and per-chunk runtime permission hook.
- `312fef75fa53741fb1561d7ea36d25fc509515c7`: native Classic receive adapted to the existing inbox and command worker, with private SDK owners and retained cleanup failures. The unused serial transport is outside this port.

The v0.9.1 catalog adapter does not activate the full newer catalog. It retains
the prior unsupported-model policy independently, requires manufacturer bytes
for constrained matches and preserves source-specific regex exclusions. New
printer protocols, compression modes and raster-offset geometry require their
own implementation and acceptance before activation. The UI remains CatLabel's.
