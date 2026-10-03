# Release packaging

Build from an immutable Git commit and an inspected, committed frontend.
Installation scripts and launchers use the same hash-checked ZIP and release-slot
manager. They do not update from a moving branch head.

## Application ZIP

```sh
python -m tools.build_release --source-commit COMMIT --release-id RELEASE_ID \
  --frontend-sha256 ACCEPTED_FRONTEND_DIGEST --output dist/CatLabel-release.zip
```

The builder reads committed Git blobs, excluding dirty/untracked files. Its
allowlist includes the runtime source, bootstrap/probe helpers, bundled frontend,
licensing, README and public Markdown guides. Private plans and review evidence
are excluded even if present in the selected commit. It also writes a SHA-256 sidecar.

The frontend digest hashes sorted full `frontend/dist/` paths, a NUL separator,
each file's ASCII SHA-256 and a newline. Compare the exact files with the tested
build before accepting that digest. Preserve the accepted archive during release
publication.

## Windows launcher

`build_launcher.ps1 -ReleaseId RELEASE_ID -FrontendSha256 ACCEPTED_FRONTEND_DIGEST`
builds the selected ZIP, then packages it with pinned PyInstaller. Native Windows
launcher acceptance must be performed on Windows.

## Linux AppImage

Use Linux x86_64 with Python 3.11, Git, GNU binutils and the `file` utility,
plus the pinned launcher requirements:

```sh
python -m pip install --requirement launcher-requirements.txt
python -m tools.build_appimage --source-commit COMMIT --release-id RELEASE_ID \
  --frontend-sha256 ACCEPTED_FRONTEND_DIGEST \
  --output dist/CatLabel-RELEASE_ID-x86_64.AppImage
```

The builder freezes the committed launcher into an AppDir, embeds the same verified
release ZIP and creates a type-2 AppImage. AppImage tool and runtime downloads have
separate pinned URLs, sizes and SHA-256 values in `tools/appimage_tool.json`;
`--runtime-file` prevents a moving latest-runtime download. `--cache-dir` selects a
build-tool cache. Supplied `--appimagetool` and `--runtime-file` paths must match the
same pins.

The AppImage stores runtime environments, releases and projects in a writable
user installation root. It is a bootstrap launcher rather than a full offline
runtime bundle. Build on an older supported Linux userland, and verify the frozen
launcher's shared-library requirements before advertising a compatibility floor.
Check both ordinary/FUSE launch and extract-and-run as appropriate to the host.

Publish the AppImage and its checksum sidecar, not build logs, private acceptance
reports or diagnostic directories. Inspect installation, repeat launch, MCP
configuration and explicit update/rollback on disposable data before release.
The source ZIP and AppImage must identify the same source commit and frontend.
