# Installation and recovery

CatLabel runs a local server and opens your browser when it is ready. The bundled
frontend needs no Node.js installation, and the setup scripts provide Python
through a locked Pixi environment.

## Source-folder installation

Download and extract the source, or clone the repository into a writable folder.
Run `run.bat` on Windows or `bash ./run.sh` on Linux/macOS. The scripts resolve
their own location, and paths containing spaces are supported.

First setup needs internet access. Pixi downloads are checked against a pinned
SHA-256, size and version before use. Interrupted setup can be retried; repeat
verified launches reuse the installed environment.

The runtime lock targets Linux x86_64/ARM64, Windows x86_64 and macOS Intel/ARM.
Its platform floors are Linux kernel 4.18+/glibc 2.28+, macOS 13+ and Windows 10+.
Linux is the currently verified platform; Windows/macOS native installation and
Bluetooth behavior remain best effort. Chromium has additional host-library
requirements. Use a current browser; the frontend requires Chrome 111+,
Firefox 128+ or Safari 16.4+.

## Linux AppImage

When an AppImage is provided with a release, download the x86_64 asset and its
SHA-256 sidecar. Make it executable, then run it:

```sh
chmod +x CatLabel-VERSION-x86_64.AppImage
./CatLabel-VERSION-x86_64.AppImage
```

Fresh packaged desktop installs enable MCP and Chromium previews by default.
Use `--skip-mcp --skip-headless` for a smaller browser-only first installation.
Existing installations keep their choices.

This is a launcher AppImage: it contains the selected application release and
launcher, then installs the locked runtime on first use. It is not an offline
bundle of Chromium and every optional AI provider SDK. The server still opens in
your normal browser.

The default writable installation root is `$XDG_DATA_HOME/catlabel`, or
`~/.local/share/catlabel` when that variable is unset. Release slots, the runtime,
cache and projects stay outside the read-only AppImage. Move or replace the
AppImage without moving that data. Override the root with
`--installation-root /absolute/path/to/CatLabel` if needed.

If FUSE is unavailable, use the runtime's extraction fallback:

```sh
./CatLabel-VERSION-x86_64.AppImage --appimage-extract-and-run
```

See [AppImage's FUSE guidance](https://docs.appimage.org/user-guide/troubleshooting/fuse.html)
for host-specific setup. The first packaged target is Linux x86_64; use the source
installation for Linux ARM64.

## Add-ons and diagnostics

Use these options with the source scripts or the AppImage:

| Option | Behavior |
| --- | --- |
| `--setup-only` | Prepare the environment without starting the normal server. |
| `--install-headless` | Install and remember Playwright/Chromium for backend rendering. |
| `--install-ai` | Install and remember provider SDKs for built-in cloud chat. |
| `--install-mcp` | Install MCP and Chromium, and enable the authenticated local endpoint. |
| `--skip-headless`, `--skip-ai`, `--skip-mcp` | Disable the corresponding add-on while retaining its installed files and user data. |
| `--repair` | Reinstall the selected runtime from the lock. |
| `--diagnose` | Report installation paths, selected environment and verification state without downloads. |

An install flag cannot be combined with its matching skip flag. MCP requires
headless support; disable MCP before disabling headless. AI is independent of MCP.
First setup, changed locks, repair and newly selected add-ons need internet access.
Normal verified repeat launches do not reinstall packages or Chromium.

Try `--diagnose`, then `--setup-only`, and use `--repair` if the runtime is damaged.
On Linux, ensure the Bluetooth service is running; enable the printer before
scanning. Classic/SPP devices may need OS pairing, while BLE devices usually
connect directly.

## Projects and backups

Source scripts use `<CatLabel folder>/data` by default. AppImage installations use
`<installation root>/data`. This holds the database, uploaded fonts, artifact/job
storage and cache. `CATLABEL_DATA_DIR` can select another absolute path; `~` expands
to your home directory. Relative paths are rejected.

Keep the data directory when replacing code. Back up `catlabel.db` and uploaded
fonts before a manual update. Direct `python -m catlabel` uses `./data` under its
working directory unless `CATLABEL_DATA_DIR` is set.

One setup runs per state directory. Close a running setup before retrying. Dead
recorded lock owners are recovered automatically. If a killed setup leaves an
empty `data/.bootstrap.lock` directory, close setup processes and remove only
that empty directory with `rmdir`.

## Selected updates and rollback

A packaged launcher keeps using its accepted local release. It never pulls Git
HEAD automatically. To adopt the release embedded in a replacement AppImage,
close CatLabel and run:

```sh
./CatLabel-VERSION-x86_64.AppImage --update-bundled --setup-only
```

The launcher verifies the archive, prepares a separate release slot, backs up
SQLite and probes the candidate before atomically selecting it. Failed updates
retain the previous release and its add-on selection. Existing slots and backups
are retained.

For a separately downloaded release ZIP, use `--artifact /absolute/path/release.zip
--sha256 PUBLISHED_SHA256` with the launcher. Run `--rollback` to select the previous
verified code. Rollback retains the current database and uploaded fonts; restoring
an older database is a separate manual recovery step that can discard newer work.

See [MCP setup](mcp.md) for harness configuration and [release packaging](releases.md)
for contributor build commands and artifact verification.
