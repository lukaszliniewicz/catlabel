# Upstream BLE issue follow-up — 3 October 2026

The issue review supports a broader V5G throughput problem. It does not establish
that every generic BLE model has the same defect. Luna/max gathered bounded issue
and comment evidence; the parent inspected the decision-critical comments and
local transport/encoding paths. Runtime model metadata was unavailable.

| Upstream evidence | Finding and local consequence |
| --- | --- |
| [#20, MXTP-100 Linux log](https://github.com/Dejniel/TiMini-Print/issues/20#issuecomment-4455780608) and [timed log](https://github.com/Dejniel/TiMini-Print/issues/20#issuecomment-4501385330) | Same 15-byte chunks, five-byte reserve and 30 ms pause as PD01; timed throughput about 492 bytes/s. |
| [#20, later ATT result](https://github.com/Dejniel/TiMini-Print/issues/20#issuecomment-4502635126) | 240-byte chunks restored continuous motion. Output remained blank, showing a separate protocol defect. These logs support the same sizing bottleneck, but do not explicitly log the public characteristic property. |
| [#20, maintainer diagnosis](https://github.com/Dejniel/TiMini-Print/issues/20#issuecomment-4624145985) and [MX10 Windows confirmation](https://github.com/Dejniel/TiMini-Print/issues/20#issuecomment-4626718577) | Density encoding/setup correction fixed blank output. Local V5G already encodes the prefix plus density byte and uses the corrected setup order. |
| [#23](https://github.com/Dejniel/TiMini-Print/issues/23), [linked #26](https://github.com/Dejniel/TiMini-Print/pull/26) | MXW01/X6H V5X Linux connection hangs involved BlueZ selecting BR/EDR instead of LE. Upstream used direct ATT/L2CAP. Linked reports also mention stale device entries. This is separate from characteristic sizing; local transport has no direct ATT adapter. |
| [#25](https://github.com/Dejniel/TiMini-Print/issues/25) | MXW01 tall-output truncation involved MTU/pacing mitigations. Closure reports success while linked PR text retains a firmware-ceiling concern. Cause and generality remain uncertain. |
| [#27](https://github.com/Dejniel/TiMini-Print/issues/27) | MX10 discovery selected Classic while missing its BLE endpoint; subsequent blank output was tracked separately in #20. |

The scoped searches found no exact PD01/MX11 report and no inspected issue linking
Niimbot to this failure. Search results were noisy, so this is not a claim that no
such issue exists anywhere. This was a focused review of relevant reports, not a
complete issue-tracker audit. No GitHub comment, issue or PR was posted.

Local scope: V5G acquisition now applies to 14 catalog model records, including
PD01, MX02/03/05/08/09/10/11, V5G YT01/MX07/MX13, MINIPRINTER, BQ02 and MXW010;
each record can match multiple names. Physical acceptance covers PD01 only.
Niimbot has a dedicated sender with fixed 20-byte chunks and 10 ms pacing, rather
than the generic adapter's characteristic-size calculation. Other generic profiles
with caps above 20 remain candidates for measurement, not verified failures.

The follow-up plan keeps MTU negotiation scoped to measured V5G behavior. Add
effective payload/chunk/pacing diagnostics before enabling it elsewhere. Review
V5X direct-ATT compatibility and tall-page behavior against #23/#25/#26 as a
separate packet, with bounded connection and payload-parity acceptance. Preserve
Linux-only physical coverage and best-effort Windows/macOS limits.
