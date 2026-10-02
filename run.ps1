param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Options)
$ErrorActionPreference = 'Stop'
$SetupOnly = $false
$InstallHeadless = $false
$SkipHeadless = $false
$Repair = $false
$Diagnose = $false
foreach ($Option in $Options) {
    switch ($Option) {
        '--setup-only' { $SetupOnly = $true }
        '--install-headless' { $InstallHeadless = $true }
        '--skip-headless' { $SkipHeadless = $true }
        '--repair' { $Repair = $true }
        '--diagnose' { $Diagnose = $true }
        '--help' { Write-Output 'Usage: run.bat [--setup-only] [--install-headless | --skip-headless] [--repair] [--diagnose]'; exit 0 }
        default { throw "Unknown option: $Option" }
    }
}
if ($InstallHeadless -and $SkipHeadless) { throw 'Choose either --install-headless or --skip-headless.' }
$Root = $PSScriptRoot
Set-Location -LiteralPath $Root
$Data = $env:CATLABEL_DATA_DIR
if (-not $Data) { $Data = Join-Path $Root 'data' }
if ($Data -eq '~') { $Data = $HOME }
elseif ($Data.StartsWith('~/') -or $Data.StartsWith('~\')) { $Data = Join-Path $HOME $Data.Substring(2) }
if (-not [IO.Path]::IsPathRooted($Data) -or $Data -notmatch '^(?:[A-Za-z]:[\\/]|\\\\)') {
    throw 'CATLABEL_DATA_DIR must be an absolute Windows path.'
}
$env:CATLABEL_DATA_DIR = $Data
$env:PIXI_HOME = Join-Path $Data 'pixi_home'
$env:PIXI_CACHE_DIR = Join-Path $Data 'pixi_cache'
$env:PIXI_NO_CONFIG = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = '0'
$Version = '0.72.2'
$Digest = '3f6e03db3cb275c028035ed3975180198064d8bb6d0352b5ab958c1fcfbddc4e'
$Size = 90571192
$Pixi = Join-Path $Root 'bin/pixi.exe'
$Environment = 'default'
if ((Test-Path -LiteralPath (Join-Path $Data '.headless-enabled')) -or $InstallHeadless) { $Environment = 'headless' }
if ($SkipHeadless) { $Environment = 'default' }
$Python = Join-Path $Root ".pixi/envs/$Environment/python.exe"
function Get-Identity {
    $ManifestHash = (Get-FileHash -LiteralPath (Join-Path $Root 'pixi.toml') -Algorithm SHA256).Hash.ToLowerInvariant()
    $LockHash = (Get-FileHash -LiteralPath (Join-Path $Root 'pixi.lock') -Algorithm SHA256).Hash.ToLowerInvariant()
    $Bytes = [Text.Encoding]::UTF8.GetBytes("catlabel-bootstrap-v1`n$Version`n$Environment`n$ManifestHash`n$LockHash`n")
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($Hasher.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $Hasher.Dispose() }
}
function Test-Binary([string]$Path) {
    return (Test-Path -LiteralPath $Path -PathType Leaf) -and
        (Get-Item -LiteralPath $Path).Length -eq $Size -and
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Digest
}
function Invoke-Pixi([string[]]$Arguments) {
    & $Pixi @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Pixi exited with code $LASTEXITCODE. Retry setup, or use --repair." }
}
$Identity = Get-Identity
$Stamp = Join-Path $Data "bootstrap-$Environment-$Identity.sha256"
$SavedIdentity = ''
if (Test-Path -LiteralPath $Stamp -PathType Leaf) { $SavedIdentity = (Get-Content -LiteralPath $Stamp -Raw).Trim() }
if ($Diagnose) {
    Write-Output "Code: $Root"
    Write-Output "Data: $Data"
    Write-Output "Platform: win-64; Pixi: $Version; environment: $Environment"
    if (Test-Binary $Pixi) { Write-Output 'Bootstrap binary: verified' } else { Write-Output 'Bootstrap binary: missing or invalid' }
    if ((Test-Path -LiteralPath $Python -PathType Leaf) -and $SavedIdentity -eq $Identity) {
        Write-Output 'Environment: previously verified for the current lock'
    } else { Write-Output 'Environment: setup or repair required' }
    exit 0
}
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'bin'), $Data, (Join-Path $Data 'tmp') | Out-Null
$env:TEMP = Join-Path $Data 'tmp'
$env:TMP = $env:TEMP
$LockStream = $null
$Download = $null
try {
    $LockStream = [IO.File]::Open((Join-Path $Data '.bootstrap-windows.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    if (-not (Test-Binary $Pixi)) {
        Write-Output "Downloading verified Pixi $Version..."
        $Download = Join-Path $Root ('bin/.pixi-download-' + [Guid]::NewGuid().ToString('N') + '.exe')
        $ProgressPreference = 'SilentlyContinue'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/prefix-dev/pixi/releases/download/v$Version/pixi-x86_64-pc-windows-msvc.exe" -OutFile $Download
        if (-not (Test-Binary $Download)) { throw 'Pixi download failed checksum or size verification. The previous binary was preserved.' }
        $ActualVersion = & $Download --version
        if ($LASTEXITCODE -ne 0 -or $ActualVersion -ne "pixi $Version") { throw 'The verified Pixi binary could not start with the expected version.' }
        if (Test-Path -LiteralPath $Pixi) {
            $Backup = "$Pixi.previous"
            [IO.File]::Replace($Download, $Pixi, $Backup)
            Remove-Item -LiteralPath $Backup -Force
        } else { [IO.File]::Move($Download, $Pixi) }
        $Download = $null
    }
    if ($Repair -or -not (Test-Path -LiteralPath $Python -PathType Leaf) -or $SavedIdentity -ne $Identity -or $InstallHeadless) {
        if (Test-Path -LiteralPath $Stamp) { Remove-Item -LiteralPath $Stamp }
        if ($Repair) { Invoke-Pixi -Arguments @('reinstall', '--environment', $Environment, '--locked') }
        else { Invoke-Pixi -Arguments @('install', '--environment', $Environment, '--locked') }
        if ($Environment -eq 'headless') {
            Invoke-Pixi -Arguments @('run', '--environment', $Environment, '--locked', '--no-install', 'python', '-m', 'playwright', 'install', 'chromium')
        }
        Invoke-Pixi -Arguments @('run', '--environment', $Environment, '--locked', '--no-install', 'python', '-m', 'tools.bootstrap_runtime', '--root', $Root, '--environment', $Environment, '--stamp', $Stamp)
    }
    if ($Environment -eq 'headless') { [IO.File]::WriteAllText((Join-Path $Data '.headless-enabled'), "1`n") }
    elseif ($SkipHeadless -and (Test-Path -LiteralPath (Join-Path $Data '.headless-enabled'))) {
        Remove-Item -LiteralPath (Join-Path $Data '.headless-enabled')
    }
} finally {
    if ($Download -and (Test-Path -LiteralPath $Download)) { Remove-Item -LiteralPath $Download -Force }
    if ($LockStream) { $LockStream.Dispose() }
}
Write-Output "CatLabel is ready ($Environment)."
if ($SetupOnly) { exit 0 }
& $Pixi run --environment $Environment --locked --no-install python -m catlabel
exit $LASTEXITCODE
