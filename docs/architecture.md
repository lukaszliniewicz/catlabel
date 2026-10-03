# Backend architecture

CatLabel's printer backend separates descriptive device policy, stateless wire
encoding, live print-session behavior, and byte transport. The direction of
dependencies is intentional:

```text
API / vendor clients
        |
        v
printing (raster jobs and live runtime)
        |                         devices (catalog and BLE policy)
        v                                      |
protocol (stateless bytes and steps)           v
        |                                  transport
        +-------------------------------> (connect/send/notify)
```

## Shared application services

REST routes, the MCP adapter and built-in AI project operations share application
services in `catlabel/services/`. Projects use transactional revision guards; the
canonical document/edit models generate JSON schemas and frontend types. Managed
assets, immutable previews and frozen print plans share the application database
and artifact store. Durable jobs own their execution tasks and recovery state.

The optional MCP adapter mounts local Streamable HTTP in the existing FastAPI
process. It has its own bearer credential and shares the host lifespan, renderer,
printer admission and executor. It does not start another hardware-owning server
or introduce a second rendering engine. See [MCP](mcp.md) for the wire workflow.

## Layer responsibilities

- `catlabel/vendors/` identifies devices and orchestrates a print requested by
  the application. A vendor client selects a catalog model, raster pipeline,
  paper preset, and runtime controller.
- `catlabel/devices/` owns device metadata and Bluetooth transfer policy. BLE
  UUIDs, chunk sizes, pacing, endpoint preferences, and flow-control enablement
  belong here rather than in protocol encoders or adapters.
- `catlabel/printing/` converts a resolved model and raster into a stateless
  `ProtocolJob`. Runtime controllers in `printing/runtime/` own notification
  parsing, family handshakes and flow markers, control queries, retries, and
  completion waits for a connected print session.
- `catlabel/protocol/` produces deterministic bytes or declarative protocol
  steps from immutable inputs. It must not connect to a printer, own a live
  runtime controller, or import transport code.
- `catlabel/transport/` discovers endpoints and moves bytes. It applies a BLE
  transport profile supplied by the device layer and exposes notifications to
  an explicitly attached runtime controller; it does not select a printer
  family or construct a family-specific runtime.

## Print flow

1. A vendor manifest resolves an advertised name and optional MAC suffix to a
   catalog model. Ambiguous or catalogued-but-unavailable devices are not
   claimed.
2. The vendor client prepares the selected runtime. Capability-sensitive
   families such as PPA2 can query the connected device before raster format
   selection.
3. The client selects paper geometry and converts the rendered image to the
   model's effective raster format.
4. `printing.build_raster_job` returns a `ProtocolJob` containing either a byte
   payload or a sequence of protocol steps.
5. `printing.send_prepared_job` executes send/query/wait steps in order. A
   family runtime may take ownership of specialized sequences such as Funny LX
   packet retries.
6. The device layer supplies the transport profile. The transport sends bytes,
   exposes generic SPP queries or BLE notification waits, and forwards incoming
   notifications. The printing runtime decides whether a reply matches and
   when the job is complete.

This structure keeps protocol fixtures testable without Bluetooth hardware and
prevents family-specific session state from leaking into the BLE adapter.

## Catalog policy

The generic catalog is a generated, pinned snapshot of TiMini-Print. Catalog
data is descriptive; loading it does not imply that every upstream family is
executable in CatLabel. `PrinterModelRegistry` only advertises models whose
protocol and required session runtime are implemented locally. Detection is
conservative: exact names, prefixes, and MAC constraints come from source data,
unsupported rules can veto broader supported matches, and ambiguous matches
remain unresolved.

See [upstream-sync.md](upstream-sync.md) for the current source revision and
the compatibility ledger.

## Browser site tools

Compatible desktop browsers discover the MCP registry through the protected
`/api/harness/tools` adapter. The page registers these definitions with WebMCP and
forwards calls to the same registry; validation, saved revisions, previews and
durable print jobs remain shared. Headless renderer pages never register tools.
The browser route uses the editor session and existing host/origin/client-header
checks; external MCP clients still use the separate bearer credential.
