# Installation and recovery

Run `run.bat` on Windows or `bash ./run.sh` on Linux/macOS from the downloaded
CatLabel folder. The scripts resolve their own location, so a terminal opened
elsewhere is fine. Use a writable folder; spaces in the path are supported.
The bundled frontend runs without Node.js. Pixi supplies Python 3.11.15.

Pixi 0.72.2 is pinned to the official release's SHA-256 digest and file size for
each supported binary. A replacement downloads to a temporary file and must
pass both checks and its version check before replacing the existing binary.
Failed or interrupted downloads preserve the previous binary.

The lock contains Windows x86_64, Linux x86_64/ARM64 and macOS Intel/ARM targets.
Linux is the available native acceptance system. Windows/macOS locks and portable
contracts are checked; their native installs and Bluetooth bridges remain
unverified. Resolving a lock does not prove a native installation works.

The lock declares Linux kernel 4.18+/glibc 2.28+, macOS 13+, and Windows 10+
as its platform floors. Chromium has its own host-library requirements.

## Options

Use the same options with either script:

| Option | Behavior |
| --- | --- |
| `--setup-only` | Install/verify the environment and exit without starting the server. |
| `--install-headless` | Install the optional Playwright environment and Chromium, verify its executable, and remember the selection. |
| `--skip-headless` | Select the default environment; retain existing headless files for reuse. |
| `--repair` | Reinstall the selected environment from the lock and verify it. User data is preserved. |
| `--diagnose` | Report code/data paths, selected environment, binary verification and setup identity without installing or downloading. |

`--install-headless` and `--skip-headless` cannot be combined. There is no timed
installation prompt. First setup, changed locks, repair and explicit add-ons need
internet access. A verified repeat launch uses `pixi run --locked --no-install`;
it does not synchronize packages or install Chromium again.

Setup identity includes the Pixi version, selected environment and the content
digests of `pixi.toml` and `pixi.lock`. Stamps are named by identity, so preparing
a different lock retains the earlier verification record. The stamp is published only after runtime
imports and any headless executable check succeed. Failed setup can be retried.
One setup per data directory runs at a time. Close a running setup before retrying.
If an abruptly killed setup leaves an empty `data/.bootstrap.lock` directory,
close setup processes and remove that empty directory with `rmdir`; keep the
rest of the data directory. Locks with a recorded dead owner are recovered
automatically.

## Data and recovery

The scripts use `<CatLabel folder>/data` by default. `CATLABEL_DATA_DIR` can select
an absolute path; `~` expands to your home directory. Relative paths are rejected.
The database, uploaded fonts, Pixi cache and setup stamps use this directory.
Code and the bundled frontend resolve from the application directory.

Direct `python -m catlabel` retains its historical default of `./data` under the
current working directory. Set `CATLABEL_DATA_DIR` when using a separate code slot
or starting Python from another directory. Existing data is not moved or deleted.

Try `--diagnose`, then `--setup-only`, and use `--repair` if the installed runtime
is damaged. Keep the data directory when replacing code. Back up `catlabel.db`
and uploaded fonts before a manual update. The selected-artifact updater and its
database/health acceptance are still remaining maintenance work.

AI SDK candidates are pinned to LiteLLM 1.103.2 and Google AI Platform 2.3.0 after
credentials-free import/request/response probes. Live authentication and paid
provider acceptance are separate checks. Optional AI packaging remains the next
installation step.
