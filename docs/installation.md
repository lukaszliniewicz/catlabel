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
| `--skip-headless` | Disable backend Chromium rendering; retain installed files for reuse. |
| `--install-ai` | Install cloud provider SDKs and remember the selection. |
| `--skip-ai` | Disable the AI add-on; preserve provider settings/history and installed files. |
| `--repair` | Reinstall the selected environment from the lock and verify it. User data is preserved. |
| `--diagnose` | Report code/data paths, selected environment, binary verification and setup identity without installing or downloading. |

`--install-headless` and `--skip-headless` cannot be combined. The same applies
to `--install-ai` and `--skip-ai`. AI and headless selections are independent. There is no timed
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
and uploaded fonts before a manual update.

AI SDK candidates are pinned to LiteLLM 1.103.2 and Google AI Platform 2.3.0 after
credentials-free import/request/response probes. Live authentication and paid
provider acceptance are separate checks. Basic installation omits both AI SDKs. Cloud chat needs `--install-ai`; provider
settings, history and external prompt/JSON workflows remain available without it.
The four locked environments are `default`, `headless`, `ai` and `ai-headless`.

## Selected release updates

The launcher uses an accepted local release on repeat starts. It no longer pulls
Git HEAD or replaces the application folder automatically. A frozen launcher can
include a release ZIP for its first installation. To select another release,
close the running CatLabel server and provide its ZIP and the SHA-256 published
through a trusted channel:

```sh
python launcher.py --installation-root /absolute/path/to/CatLabel \
  --artifact /absolute/path/to/CatLabel-release.zip --sha256 PUBLISHED_SHA256
```

Use `--setup-only` to install and accept a release without opening the normal
server. Add-on flags also apply to the candidate. Each release keeps its own
remembered AI/headless selection; a failed candidate does not change the previous
release's selection. `CATLABEL_BOOTSTRAP_STATE_DIR` is an internal absolute-path
override for this state. Source-folder installations continue storing selections
in their data directory.

The launcher verifies the complete archive, installs code under
`.releases/<archive-sha256>`, prepares the locked runtime at that final path, and
starts a candidate server on a disposable database clone. Acceptance checks the
release identity and exact served frontend. Existing SQLite data is backed up
with SQLite's online backup API, including committed WAL content, under
`data/backups/`. Code selection changes atomically only after acceptance. Existing
slots and backups are retained; failed setup can be retried.

```sh
python launcher.py --installation-root /absolute/path/to/CatLabel --rollback
```

Rollback selects the previous verified code and its add-on selection. It retains
the current database and uploaded fonts. Manifest database epoch 1 permits the
current additive schema changes; incompatible epochs are rejected. Database
restoration is a separate manual recovery action, since restoring an old backup
can discard projects saved after the update. Keep backups and previous slots
until you have confirmed your projects and printer behavior.

## Building a release

Build from an immutable Git commit and supply the digest of the accepted,
committed frontend. Dirty and untracked files are excluded:

```sh
python -m tools.build_release --source-commit COMMIT --release-id RELEASE_ID \
  --frontend-sha256 ACCEPTED_FRONTEND_DIGEST --output dist/CatLabel-release.zip
```

The builder also writes `CatLabel-release.zip.sha256`. On Windows,
`build_launcher.ps1 -ReleaseId RELEASE_ID -FrontendSha256 ACCEPTED_FRONTEND_DIGEST`
builds that bundle before PyInstaller packages it. Linux acceptance does not
confirm a Windows executable build, native macOS launch, or physical printing.
