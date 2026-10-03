# CatLabel MCP

CatLabel's optional MCP add-on lets a harness create and edit saved designs,
import images or PDFs, retrieve PNG previews, export portable designs, discover
printers and submit prints. It shares the editor's database, React renderer and
printer services. No AI provider is required in CatLabel.

## Install and start

Close a running CatLabel server before enabling the add-on. From the application
folder, run `bash ./run.sh --install-mcp` on Linux/macOS, or
`run.bat --install-mcp` on Windows. MCP also installs the headless Chromium add-on.
Subsequent normal launches remember the choice. `--skip-mcp` disables the endpoint
without removing designs or job receipts. Linux is the first acceptance platform;
native Windows/macOS installation and credential ACLs still need verification.

The endpoint is `http://127.0.0.1:8000/mcp/` by default. If you set
`CATLABEL_PORT`, use that port in the client configuration too. MCP requires a
loopback host and its own bearer credential even when the browser editor has no
sign-in. Keep the app running while a harness uses it.

Create a private OpenCode v2 configuration fragment and test readiness:

```sh
PLAYWRIGHT_BROWSERS_PATH=0 ./bin/pixi run --environment mcp-headless --locked --no-install \
  python -m catlabel.mcp config --port 8000
PLAYWRIGHT_BROWSERS_PATH=0 ./bin/pixi run --environment mcp-headless --locked --no-install \
  python -m catlabel.mcp doctor --port 8000
```

On Windows use `bin\pixi.exe` and set `PLAYWRIGHT_BROWSERS_PATH=0` in the terminal.
If AI is also enabled, use environment `ai-mcp-headless`. Set `CATLABEL_DATA_DIR`
consistently when using a separate data folder. The doctor launches Chromium and
checks the authenticated MCP endpoint; it never prints a label.

The generated `data/mcp-opencode.json` contains a `mcp.servers.catlabel` entry.
Its bearer header refers to a private local token file, so the token is not
printed or embedded in the JSON fragment. Copy that entry into your OpenCode
project configuration; preserve the project's existing entries. Alternatively,
`config --output /absolute/path/to/project/opencode.json` can create a new private
configuration. Existing different files are never overwritten. Keep credential
and generated configuration files outside Git and shared folders.

For OpenCode v2, retain `oauth: false`, `protocol: "auto"` and `codemode: false`.
These select header authentication, July discovery with legacy fallback and
native tool exposure. After changing config, reload OpenCode and inspect the
connection with `/mcps`. If an already-running client has not loaded a new server,
register it from the intended project using the official command:

```sh
opencode mcp add catlabel --url http://127.0.0.1:8000/mcp/ \
  --header 'Authorization=Bearer {file:/absolute/path/to/CatLabel/data/mcp-token.txt}'
```

That command may replace the server entry; restore the three settings above from
the generated fragment afterwards. Do not assume `OPENCODE_CONFIG` isolates a
running OpenCode service. Check the connection in the intended project/session.
See the [OpenCode v2 MCP documentation](https://opencode.ai/v2/docs/mcp-servers)
for configuration and connection management. OpenCode names tools with its server
prefix, for example `catlabel_catlabel_design_create`.

## Workflow

1. Inspect `catlabel_server_info` and `catlabel_catalog_get` for fonts, templates,
   models and the document/edit schema.
2. Create a named design, load an existing one or make a working copy. Creation
   dimensions use millimetres; ordinary element geometry uses document pixels.
3. Apply supported edits with the saved `expected_revision`. Stale edits fail
   instead of overwriting somebody else's changes.
4. Create a preview at that revision. The result includes a PNG, immutable preview
   ID/hash, selected pages, dimensions and renderer identity. `preview_get` accepts
   `image_index` for other pages or batch records; `artifact_get` retrieves a
   bounded PNG without requiring resource browsing. Full artifacts are resources.
5. Scan printers and choose an explicit address. Prepare a plan using the preview
   ID/hash. Inspect its printer, frozen settings, copies, source pages and expiry.
6. Start that plan with its exact hash and a unique idempotency key, using the
   harness's physical-action approval policy. Poll `job_get` or list receipts.

A repeated start with the same key and request returns the same job, including
across reconnects and restarts. Reusing a key for a different request fails.
`submitted` means the backend sent the label data; check the actual printer for
completion. A job interrupted after delivery begins becomes `delivery_uncertain`
and is never replayed automatically. Cancellation is available before delivery
starts. A deliberate retry after uncertainty needs a new key and physical review.

Source previews freeze the rendered design. Vendor resizing, dithering, cut/feed
and firmware behavior may still transform the physical result; the plan reports
that these transformations are unresolved. Portable JSON export embeds managed
images so designs remain usable outside the original artifact store.

## Retention and boundaries

Assets/previews have a 24-hour default lifetime; saved designs retain their image
assets. Unstarted plans expire after 15 minutes. Job receipts and idempotency
reservations are retained for 90 days; uncertain delivery sources are retained
for seven days. The artifact quota is 1 GiB. Limits also bound request size,
image/PDF decoding, document complexity and rendered pixels.

The server supports July `2026-07-28` and legacy `2025-11-25` through the official
SDK. Ordinary durable job tools work without the Tasks extension. The first
slice uses local Streamable HTTP. Stdio, SSE, LAN/OAuth, contact sheets and fully
printer-transformed proofs are deferred. Arbitrary server paths, shell commands,
provider credentials and automatic URL downloads are not tools.

The editor notices external saved revisions and offers a reload; it keeps the
current canvas and undo history until you choose to reload. Dirty edits still
require the normal replacement confirmation.
