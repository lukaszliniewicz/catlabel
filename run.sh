#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$root"
setup_only=0 install_headless=0 skip_headless=0 repair=0 diagnose=0
for option in "$@"; do
    case "$option" in
        --setup-only) setup_only=1 ;;
        --install-headless) install_headless=1 ;;
        --skip-headless) skip_headless=1 ;;
        --repair) repair=1 ;;
        --diagnose) diagnose=1 ;;
        --help) echo 'Usage: ./run.sh [--setup-only] [--install-headless | --skip-headless] [--repair] [--diagnose]'; exit 0 ;;
        *) echo "Unknown option: $option" >&2; exit 2 ;;
    esac
 done
if (( install_headless && skip_headless )); then
    echo 'Choose either --install-headless or --skip-headless.' >&2; exit 2
fi
data="${CATLABEL_DATA_DIR-$root/data}"
case "$data" in
    '~') data="$HOME" ;;
    \~/*) data="$HOME/${data#\~/}" ;;
esac
case "$data" in
    /*) ;;
    *) echo 'CATLABEL_DATA_DIR must be an absolute path.' >&2; exit 2 ;;
esac
export CATLABEL_DATA_DIR="$data" PIXI_HOME="$data/pixi_home" PIXI_CACHE_DIR="$data/pixi_cache"
export PIXI_NO_CONFIG=1 PLAYWRIGHT_BROWSERS_PATH=0
version=0.72.2
case "$(uname -s):$(uname -m)" in
    Linux:x86_64)
        target=x86_64-unknown-linux-musl
        digest=2ff2bdf910f62b592e3485f3b252033a7ed2ec40a03b61bb6cc3e8ab16e2d963
        size=76337504 ;;
    Linux:aarch64|Linux:arm64)
        target=aarch64-unknown-linux-musl
        digest=4f445e30a116e92dbc2969bc0f2370f54cf50c7a1af99e70c19a93184c153796
        size=65447296 ;;
    Darwin:x86_64)
        target=x86_64-apple-darwin
        digest=58db8dfd76e752b6c161b9789221f4d93d68d2bee457db3be0edf402d974516a
        size=71468784 ;;
    Darwin:arm64|Darwin:aarch64)
        target=aarch64-apple-darwin
        digest=01e9421df661b45ede5939423ff7df0097afbbaea55a015b31980629f5f7b8ea
        size=62930304 ;;
    *) echo 'This installer supports Linux and macOS on x86_64 and ARM64.' >&2; exit 2 ;;
esac
hash_file() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
    else shasum -a 256 "$1" | awk '{print $1}'; fi
}
hash_input() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum | awk '{print $1}'
    else shasum -a 256 | awk '{print $1}'; fi
}
verified_binary() {
    [[ -f "$1" ]] && [[ "$(wc -c < "$1" | tr -d '[:space:]')" == "$size" ]] && [[ "$(hash_file "$1")" == "$digest" ]]
}
environment=default
if [[ -f "$data/.headless-enabled" ]] || (( install_headless )); then environment=headless; fi
if (( skip_headless )); then environment=default; fi
identity="$(printf 'catlabel-bootstrap-v1\n%s\n%s\n%s\n%s\n' "$version" "$environment" \
    "$(hash_file "$root/pixi.toml")" "$(hash_file "$root/pixi.lock")" | hash_input)"
stamp="$data/bootstrap-$environment-$identity.sha256"
pixi="$root/bin/pixi"
python="$root/.pixi/envs/$environment/bin/python"
saved_identity=''
if [[ -f "$stamp" ]]; then saved_identity="$(cat "$stamp")"; fi
if (( diagnose )); then
    echo "Code: $root"
    echo "Data: $data"
    echo "Platform: $target; Pixi: $version; environment: $environment"
    if verified_binary "$pixi"; then echo 'Bootstrap binary: verified'; else echo 'Bootstrap binary: missing or invalid'; fi
    if [[ -f "$python" && "$saved_identity" == "$identity" ]]; then echo 'Environment: previously verified for the current lock'
    else echo 'Environment: setup or repair required'; fi
    exit 0
fi
mkdir -p -- "$root/bin" "$data" "$data/tmp"
export TMPDIR="$data/tmp"
lock="$data/.bootstrap.lock"
if ! mkdir -- "$lock" 2>/dev/null; then
    owner=''
    owner_file=''
    for candidate in "$lock"/pid-*; do
        if [[ -f "$candidate" ]]; then
            if [[ -n "$owner_file" ]]; then
                echo 'Setup lock has multiple owners. Close setup processes before recovery.' >&2
                exit 3
            fi
            owner_file="$candidate"
            owner="${candidate##*/pid-}"
        fi
    done
    if [[ "$owner" =~ ^[0-9]+$ ]] && ! kill -0 "$owner" 2>/dev/null; then
        # The owner-specific filename prevents a competing recovery process
        # from removing a newly acquired lock after this stale owner is gone.
        rm -- "$owner_file"; rmdir -- "$lock"; mkdir -- "$lock"
    else echo 'Another setup is running. Retry when it finishes.' >&2; exit 3; fi
fi
owner_file="$lock/pid-$$"
printf '%s\n' "$$" > "$owner_file"
download=''
cleanup() {
    if [[ -n "$download" ]]; then rm -f -- "$download"; fi
    if [[ -f "$owner_file" ]]; then rm -- "$owner_file"; rmdir -- "$lock"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ! verified_binary "$pixi"; then
    echo "Downloading verified Pixi $version..."
    download="$(mktemp "$root/bin/.pixi-download.XXXXXX")"
    curl --fail --location --retry 3 --retry-delay 2 --connect-timeout 30 --max-time 600 \
        --output "$download" "https://github.com/prefix-dev/pixi/releases/download/v$version/pixi-$target"
    if ! verified_binary "$download"; then
        echo 'Pixi download failed checksum or size verification. The previous binary was preserved.' >&2; exit 4
    fi
    chmod 755 -- "$download"
    if [[ "$("$download" --version)" != "pixi $version" ]]; then
        echo 'The verified Pixi binary could not start with the expected version.' >&2; exit 4
    fi
    mv -f -- "$download" "$pixi"
    download=''
fi
if [[ ! -x "$pixi" ]]; then chmod 755 -- "$pixi"; fi
if (( repair )) || [[ ! -f "$python" || "$saved_identity" != "$identity" ]] || (( install_headless )); then
    rm -f -- "$stamp"
    if (( repair )); then
        echo "Repairing the locked $environment environment..."
        "$pixi" reinstall --environment "$environment" --locked
    else
        echo "Installing the locked $environment environment..."
        "$pixi" install --environment "$environment" --locked
    fi
    if [[ "$environment" == headless ]]; then
        "$pixi" run --environment "$environment" --locked --no-install python -m playwright install chromium
    fi
    "$pixi" run --environment "$environment" --locked --no-install \
        python -m tools.bootstrap_runtime --root "$root" --environment "$environment" --stamp "$stamp"
fi
if [[ "$environment" == headless ]]; then printf '1\n' > "$data/.headless-enabled"
elif (( skip_headless )); then rm -f -- "$data/.headless-enabled"; fi
cleanup
trap - EXIT INT TERM
echo "CatLabel is ready ($environment)."
if (( setup_only )); then exit 0; fi
exec "$pixi" run --environment "$environment" --locked --no-install python -m catlabel
