# TiMini-Print synchronization ledger

CatLabel's generic printer logic is derived from
[TiMini-Print](https://github.com/Dejniel/TiMini-Print), licensed under
Apache-2.0. The checked-in catalog snapshot is pinned to:

- release: `v0.8.1`
- commit: `f676917257b5d1f869e0f13beff03785258e2a2e`
- source date: 2026-09-18

The publisher accepts a separate local upstream clone; its selected tag must
already be fetched. Run from the CatLabel checkout, passing that clone's path:

```powershell
bin\pixi.exe run --environment default --locked python tools\sync_timiniprint_catalog.py v0.8.1 --repository-path C:\path\to\TiMini-Print
```

The generated `catalog_snapshot.json` contains all five catalogs and their exact
repository, revision, peeled commit, license and source-file mapping. All sources
are acquired and validated before one atomic replacement. Individual legacy
files, including `catalog_source.json`, remain historical fallback data. Default
registry loads prefer the bundle; invalid bundles fail closed. Explicit custom
catalog paths retain the legacy loading API.

The parser accepts both v0.7.3 and v0.8.1 detection schemas, origin IDs, marketing
names, whitespace modes and ambiguity groups. Preset height and rotation metadata
are retained and applied by the generic image pipeline: clockwise preset rotation,
width normalization/padding, then height fitting and centering. User rotation is
applied before these preset transforms. The bundle is now the released v0.8.1
snapshot. Source-backed fixtures and Linux socket tests establish local protocol
compatibility; they do not establish physical output.

## Imported in this synchronization

- The complete upstream model, unsupported-model, profile, paper-preset, and
  origin-app data snapshot: 145 upstream supported records, 165 upstream
  unsupported records, and 129 profiles, 51 paper presets and 12 origins.
- 133 generic records whose protocol path is executable in CatLabel: Tiny,
  Tiny-prefixed, Luck (including PPA2L/PPA2LH), V5G, V5X, V5C,
  Eleph/TSPL, ToPrint/HPRT ESC, ToPrint/TSPL, Instaprint Core, Funny LX and YK Astra P1 (Orgstra S001).
- Source-backed exact/prefix/MAC detection with unsupported-model vetoes and no
  marketing-name guessing.
- Tiny `line_eight`, `professional`, `esc_star`, and `esc_star_eight` packet
  variants; paper width, render width, left padding, paper mode, and A4 sheet
  maximum-height behavior.
- Source-compatible paper layout, including centering 90-pixel render surfaces
  inside 96-pixel printheads before byte packing.
- Corrected V5G density encoding and job wrapper/feed ordering, plus an atomic
  temperature query used by the adaptive density runtime.
- V5G/V5X/V5C BLE profiles in the device layer, including V5X bulk pacing.
- Explicit printing-runtime ownership, notification consumption, and passive
  V5X completion waits without status queries that may move paper.
- Stateless protocol jobs and a shared payload/step representation.
- A printing-layer step executor for ordered send/query/wait plans, Classic
  SPP request/reply reads (including Windows WinRT), and atomic BLE
  write/notification queries.
- Lujiang runtime capability probing and interleaved query/reply execution for
  PPA2L/PPA2LH, including mono fallback and PPA2LH grayscale-level handling.
- Funny LX BLE verification, CRC challenge, notification-driven packet resend,
  transfer-ready/footer waits, and adaptive packet pacing.
- Upstream's pure-Python LZO1X encoder, removing the native `python-lzo`
  dependency from Windows installation.
- Pillow's flattened-pixel API, with compatibility fallback for older Pillow,
  so rasterization no longer relies on the deprecated `Image.getdata()` path.

## Deliberately not advertised by the generic backend

- Upstream Niimbot and Phomemo ESC records (12 records): CatLabel maintains
  separate Niimbot and Phomemo vendor backends, so importing the generic copies
  would create conflicting ownership.

Those records remain in the pinned source data for auditability but are filtered
from the executable registry. Unknown, ambiguous, unsupported, and deferred
devices resolve to CatLabel's generic sentinel and are excluded from automatic
scan results. This is intentional: a smaller truthful support list is safer
than selecting an incorrect wire protocol.

The released `d80_protocol` ambiguity group covers both a supported Luck and an
unsupported PrintMaster candidate. Bare `D80_` aliases remain unknown rather than
being assigned a wire protocol. More specific unambiguous aliases such as
`DP_D80_` still select Luck. This follows the pinned upstream group precedence.

## Future synchronization checklist

1. Fetch the upstream tag and review commits since the revision recorded in
   the active bundle's `source` metadata, or `catalog_source.json` for legacy data.
2. Regenerate the catalog and inspect the source commit recorded by the tool.
3. Add protocol fixtures and runtime tests before enabling a new family or
   runtime-dependent variant.
4. Verify the layer rules in [architecture.md](architecture.md).
5. Run the full backend test suite and an application import smoke test.
