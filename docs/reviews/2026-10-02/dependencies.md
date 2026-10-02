# CatLabel dependency update evidence

Observed 2026-10-02. Repository: `/home/lliniewicz/Projects/catlabel`, commit `c193e93d82b13724196aa29b22d52055fd112406`; working tree was clean before and after the audit. Registry versions are point-in-time observations from official npm and PyPI APIs.

## Resolver picture

`frontend/package.json` declares semver ranges and `frontend/package-lock.json` resolves the current install. The direct lock snapshot is behind latest stable for many packages. The Windows backend is constrained by `pixi.toml` and pinned by `pixi.lock` (Pixi lock format 7, win-64, Python 3.11.15); `requirements.txt` is a broad pip input without an accompanying lock. `requirements.txt` and Pixi share 12 backend constraints; PyObjC is Darwin-only in requirements and absent from the Windows Pixi lock. Playwright is only the optional Pixi headless feature. `launcher-requirements.txt` pins Dulwich, PyInstaller and urllib3 for the isolated launcher build, but does not lock transitive packages or hashes.

## Python direct dependencies

| Dependency | Declaration | Current lock/pin | Latest stable on PyPI | Python compatibility / note |
|---|---|---:|---:|---|
| fastapi | `>=0.115.6` | 0.139.0 | 0.142.2 | `>=3.10` |
| python-multipart | `>=0.0.20` | 0.0.32 | 0.0.32 | `>=3.10` |
| uvicorn | `>=0.34.0` | 0.51.0 | 0.54.0 | `>=3.10` |
| sqlmodel | `>=0.0.22` | 0.0.39 | 0.0.47 | `>=3.10` |
| Pillow | `>=11.1.0` | 12.3.0 | 12.3.0 | `>=3.10` |
| pypdfium2 | `>=4.30.1` | 5.11.0 | 5.13.0 | `>=3.6`; v5 API break is already reflected in lock |
| bleak | `>=0.22.3` | 3.0.2 | 3.0.2 | `>=3.10`; lock is already on v3 |
| crc8 | `>=0.2.1` | 0.2.1 | 0.2.1 | No `Requires-Python` metadata |
| pyserial | `>=3.5` | 3.5 | 3.5 | No `Requires-Python` metadata |
| pyobjc-framework-IOBluetooth | `>=11.0` on Darwin | no win-64 lock | 12.2.2 | `>=3.10`; platform specific |
| winsdk | `>=1.0.0b10` on Windows | 1.0.0b10 | 1.0.0b10 beta-only | `>=3.8`; PyPI has no non-prerelease release |
| google-cloud-aiplatform | unbounded | 1.160.0 | 2.3.0 | `>=3.10`; major 2 migration needed if using moved surfaces |
| litellm | `>=1.59.3,<1.92.0` | 1.91.3 | 1.103.2 | `>=3.10,<3.15`; current upper bound blocks latest stable |
| Playwright (headless only) | `>=1.40.0` | 1.61.0 | 1.63.0 | `>=3.10` |
| Dulwich (launcher) | `==1.2.10` | pin 1.2.10 | 1.2.15 | `>=3.10`; direct pin, no full lock |
| PyInstaller (launcher) | `==6.21.0` | pin 6.21.0 | 6.22.3 | `>=3.8,<3.16`; direct pin, no full lock |
| urllib3 (launcher) | `==2.7.0` | pin/lock 2.7.0 | 2.8.0 | `>=3.10`; Pixi includes 2.7.0 transitively |

Prereleases observed separately: pypdfium2 `5.14.0b1`, LiteLLM `1.105.0.dev2`; winsdk’s newest and only observed release remains beta `1.0.0b10`. These were not counted as stable updates. PyPI source for each row: `https://pypi.org/pypi/{name}/json`, with project names substituted; detailed endpoints are recorded in `evidence/registry-versions.json`.

## Frontend direct dependencies

| Package | package.json range | package-lock | Latest stable | Boundary / note |
|---|---|---:|---:|---|
| bwip-js | `^4.5.1` | 4.9.0 | 4.11.4 | In declared range |
| dompurify | `^3.4.12` | 3.4.12 | 3.4.16 | In range; direct advisories affect lock (details below) |
| html-to-image | `^1.11.11` | 1.11.13 | 1.11.13 | Current |
| js-beautify | `^1.15.1` | 1.15.4 | 2.0.3 | Major outside range; Node engine evidence conflicts |
| konva | `^10.0.0` | 10.2.5 | 10.7.0 | In range |
| lucide-react | `^0.474.0` | 0.474.0 | 1.50.0 | Major outside range |
| qrcode | `^1.5.4` | 1.5.4 | 1.5.4 | Current |
| react | `^19.0.0` | 19.2.5 | 19.3.0 | In range; update alongside React DOM and React-Konva |
| react-dom | `^19.0.0` | 19.2.5 | 19.3.0 | In range; latest peer requires React `^19.3.0` |
| react-konva | `^19.0.2` | 19.2.3 | 19.3.0 | In range; 19.3 requires React and React DOM `^19.3.0`; Konva 10 is peer-compatible |
| react-markdown | `^9.0.1` | 9.1.0 | 10.1.0 | Major outside range; v10 removes `className` prop |
| remark-gfm | `^4.0.0` | 4.0.1 | 4.0.1 | Current |
| zustand | `^5.0.3` | 5.0.12 | 5.0.15 | In range |
| @eslint/js | `^9.39.5` | 9.39.5 | 10.0.1 | Major outside range; pairs with ESLint 10 |
| @vitejs/plugin-react | `^4.3.4` | 4.7.0 | 6.1.1 | Major outside range; latest requires Vite 8 and Node 20.19+/22.12+ |
| autoprefixer | `^10.4.20` | 10.4.27 | 10.6.1 | In range; Tailwind 4 can remove this in its new pipeline |
| eslint | `^9.39.5` | 9.39.5 | 10.11.0 | Major outside range; Node 20.19+/22.13+/24+ |
| eslint-plugin-react | `^7.37.5` | 7.37.5 | 7.37.5 | Current; its peer range supports ESLint 9 (`^9.7`) but not 10, blocking ESLint 10 |
| eslint-plugin-react-hooks | `^7.1.1` | 7.1.1 | 7.1.1 | Current; peer permits ESLint 10 |
| eslint-plugin-react-refresh | `^0.4.24` | 0.4.24 | 0.5.7 | 0.x minor outside declared range; latest peers ESLint 9/10 |
| globals | `^16.4.0` | 16.4.0 | 17.13.0 | Major outside range; latest Node >=18 |
| jsdom | `^26.1.0` | 26.1.0 | 30.1.1 | Major outside range; Node 22.22.2+, 24.15+, or 26+ |
| postcss | `^8.5.1` | 8.5.19 | 8.5.28 | In range; lock affected by advisory |
| tailwindcss | `^3.4.17` | 3.4.19 | 4.3.3 | Major outside range; PostCSS integration and browser baseline change |
| vite | `^6.0.7` | 6.4.3 | 8.3.2 | Major outside range; Node 20.19+/22.12+; Vite 8 uses Rolldown/Oxc |
| vitest | `^3.2.6` | 3.2.6 | 5.0.3 | Major outside range; requires Vite >=6.4 and Node >=22.12 |

Latest NPM prerelease tags were kept separate: React/React DOM have Sep 29 canary and experimental tags; Vite has `8.3.0-beta.1`; Vitest has `5.0.0-rc.4` and `5.0.0-beta.7`; ESLint has `10.0.0-rc.2`; @eslint/js has `10.0.0-rc.0`; plugin-react has `6.0.0-beta.0`. Stable `latest` versions remain the table values. Package metadata endpoints are `https://registry.npmjs.org/{package}/latest`; scoped package endpoints and peer metadata are in the registry JSON artifact.

## Coupled changes and primary migration evidence

React-Konva 19.3 pairs with React and React DOM 19.3; latest registry peer metadata and the [React-Konva README](https://github.com/konvajs/react-konva/blob/master/README.md) say to align those three. Vite 8 and `@vitejs/plugin-react` 6 form a pair: the plugin’s peer requires Vite 8, and Vite 8 changes optimizer/bundler internals to Rolldown/Oxc ([Vite migration](https://vite.dev/guide/migration.html)). Vitest 5 can pair with Vite 6.4+, but requires Node 22.12+ and changes `clearMocks` default to true ([Vitest migration](https://vitest.dev/guide/migration/)).

ESLint 10 needs Node 20.19+/22.13+/24+ and updates config lookup plus supported config format ([ESLint guide](https://eslint.org/docs/latest/use/migrate-to-10.0.0)). Current latest `eslint-plugin-react` remains 7.37.5 and peers with ESLint 9 (`^9.7`) but not 10; hooks and refresh plugin peer ranges admit ESLint 10. Tailwind 4 moves the PostCSS plugin into `@tailwindcss/postcss` (or recommends the Vite plugin) and targets Safari 16.4+, Chrome 111+, Firefox 128+; current `frontend/postcss.config.js` still declares `tailwindcss` and `autoprefixer` ([upgrade guide](https://tailwindcss.com/docs/upgrade-guide)).

Other concrete breaks: `react-markdown` 10 removes `className` ([changelog](https://github.com/remarkjs/react-markdown/blob/main/changelog.md)); pypdfium2 5 removed `PdfDocument.render()` and related bitmap APIs ([changelog](https://pypdfium2-team.github.io/pypdfium2/changelog.html)), though the Pixi lock already runs 5.11.0. Bleak 3.0 changes GATT protocol errors, rejects direct CCCD descriptor writes in favor of `start_notify()`/`stop_notify()`, and removes an undocumented `device` keyword; the lock is already on Bleak 3.0.2 ([changelog](https://bleak.readthedocs.io/en/stable/history.html)). The Google Cloud SDK 2.0.1 migration guide says not to install 2.0.0 and moves `vertexai.generative_models`, `language_models`, `vision_models`, `caching`, and `tuning` to Google Gen AI; classic training/prediction remains supported ([guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/python-sdk/sdk-migration)). LiteLLM 1.92.0 (excluded by the current ceiling) makes permissions and allowed routes admin-only ([release notes](https://docs.litellm.ai/release_notes/v1.92.0/v1-92-0)).

## Verified advisories

`npm audit --package-lock-only --json` reported exit 1 with 10 affected package entries: 4 high, 5 moderate, 1 low, 0 critical. Three direct lock entries are affected:

- DOMPurify 3.4.12: GHSA-55q2-fjhq-7xh7, affected through 3.4.12, patched in 3.4.13. A later vendor advisory GHSA-6688-9rhm-gjv2 affects through 3.4.15 and is patched in latest 3.4.16. Both are `IN_PLACE` trigger families; usage relevance is parent-owned.
- PostCSS 8.5.19: GHSA-fxqj-rqcc-2cmp affects through 8.5.22, patched in 8.5.23.
- Vitest 3.2.6: GHSA-82fw-gwwq-j7x9 affects versions below 4.1.11 (and early v5 prereleases); patched in 4.1.11 or 5.0.0-rc.2. Current package range is v3-only; NPM audit offered v5.0.3 as a major fix.

The seven other NPM audit entries are transitive: `@vitest/mocker`, `baseline-browser-mapping`, `brace-expansion`, `browserslist`, `js-yaml`, `nanoid`, and `postcss-selector-parser`. Exact advisories and full output are preserved in [`npm-audit.json`](evidence/npm-audit.json). A separate primary-source lookup found LiteLLM’s official report of compromised PyPI versions 1.82.7 and 1.82.8; both were removed. Current lock 1.91.3 is outside those versions, but the declared open range spans them ([incident report](https://docs.litellm.ai/blog/security-update-march-2026)). No Python advisory audit was run.

One metadata contradiction remains unresolved: NPM registry metadata for js-beautify 2.0.3 says Node `>=14`, while its official changelog says v2.0.1 moved the minimum to Node 22.x; querying registry version 2.0.1 returned HTTP 404. The current project Node target was not inspected, so do not assume js-beautify 2.x is compatible from registry metadata alone.

## Checks and limits

- Passed: repository identity, manifest/lock reads, official registry GETs, and clean working-tree/diff checks after the audit.
- Findings: the read-only NPM audit exited 1 due to reported advisories. This is not a test/build result.
- Failed discovery: `.github` workflow lookup returned a missing-path error; no `.github` directory was present.
- Not run: install, build, tests, runtime Node check, Python advisory audit.
- Scope note: an initial broad dependency-text `rg` did not exclude `frontend/dist`, and its truncated output included a minified built frontend snippet. No conclusion was derived from that output; inspection then stopped. All subsequent frontend reads were limited to package manifests/lock and the PostCSS config.

## Registry sources

PyPI source pattern: `https://pypi.org/pypi/{name}/json`. NPM source pattern: `https://registry.npmjs.org/{name}/latest`, plus the NPM dist-tag API for prereleases. All rows, engine/peer metadata, source URLs, prerelease notes, and date stamps are available in [`registry-versions.json`](evidence/registry-versions.json).

## Parent assessment of advisory relevance

The inspected sanitizer accepts a string and does not enable `IN_PLACE` (`frontend/src/utils/htmlSecurity.js:33`). The two cited in-place DOMPurify advisories therefore do not demonstrate an exploitable path in this app. Update to 3.4.16 and retain sanitization regressions, while prioritizing the independently observed local API exposure. npm audit package severity/counts are not a count of proven application vulnerabilities. No Python advisory scan or native dependency upgrade acceptance was performed. Parent frontend checks used Node 24.18.0, which satisfies the recorded tool engine floors; js-beautify still needs runtime behavior testing.
