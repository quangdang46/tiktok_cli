# tiktok-cli installer for Windows — irm ... | iex
# Installs the `tiktok` command via uv (preferred), pipx, or pip.
$ErrorActionPreference = "Stop"

# === Config ===
$Package   = "tiktok-cli"
$BinName   = "tiktok"
$Owner     = "quangdang46"
$Repo      = "tiktok_cli"
$GitUrl    = "https://github.com/$Owner/$Repo.git"
$Quiet     = $false
$Verify    = $false
$Uninstall = $false
$WithMlx   = $false
$Prefer    = ""
$Version   = ""
$MaxRetries = 3

function Write-Info    { if (-not $Quiet) { Write-Host "[tiktok-cli] $args" } }
function Write-Warn2   { Write-Host "[tiktok-cli] WARN: $args" -ForegroundColor Yellow }
function Write-Ok2     { Write-Host "✓ $args" -ForegroundColor Green }
function Die           { Write-Host "ERROR: $args" -ForegroundColor Red; exit 1 }

# === Args ===
for ($i = 0; $i -lt $args.Count; $i++) {
    switch -Regex ($args[$i]) {
        '^--version=(.+)$'  { $Version = $Matches[1]; break }
        '^--version$'       { $i++; $Version = $args[$i]; break }
        '^--prefer=(.+)$'   { $Prefer = $Matches[1]; break }
        '^--prefer$'        { $i++; $Prefer = $args[$i]; break }
        '^--with-mlx$'      { $WithMlx = $true; break }
        '^--verify$'        { $Verify = $true; break }
        '^--uninstall$'     { $Uninstall = $true; break }
        '^--quiet$|^-q$'    { $Quiet = $true; break }
        '^--help$|^-h$'     {
            Write-Host "Usage: install.ps1 [--version V] [--prefer uv|pipx|pip] [--with-mlx] [--verify] [--uninstall] [--quiet]"
            exit 0
        }
        default             { Write-Warn2 "unknown arg: $($args[$i])" }
    }
}

# === Spec ===
function Get-Spec {
    if ($Version) {
        if ($Version -match '^(v|http|git|/|[A-Za-z]:\\)') { return "git+$GitUrl@$Version" }
        return "git+$GitUrl@$Version"
    }
    return "git+$GitUrl"
}

function Test-Python311 {
    try {
        $v = & python --version 2>&1
        if ($v -match 'Python (\d+)\.(\d+)') {
            return ([int]$Matches[1] -gt 3) -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11)
        }
    } catch {}
    return $false
}

function Install-Uv {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { return $false }
    $spec = Get-Spec
    $extra = if ($WithMlx) { "[mlx]" } else { "" }
    Write-Info "Installing via uv tool: $spec$extra"
    & uv tool install --force "$spec$extra" --python ">=3.11"
    return ($LASTEXITCODE -eq 0)
}

function Install-Pipx {
    if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) { return $false }
    $spec = Get-Spec
    $extra = if ($WithMlx) { "[mlx]" } else { "" }
    Write-Info "Installing via pipx: $spec$extra"
    & pipx install --force "$spec$extra"
    return ($LASTEXITCODE -eq 0)
}

function Install-Pip {
    if (-not (Test-Python311)) {
        Die "Python 3.11+ not found. Install from https://www.python.org/downloads/ (tick 'Add to PATH') or install uv."
    }
    $spec = Get-Spec
    $extra = if ($WithMlx) { "[mlx]" } else { "" }
    Write-Info "Installing via pip: $spec$extra"
    & python -m pip install --user --upgrade "$spec$extra"
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Uninstall {
    $removed = $false
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $list = & uv tool list 2>$null
        if ($list -match "^$Package") { & uv tool uninstall $Package | Out-Null; $removed = $true }
    }
    if ((Get-Command pipx -ErrorAction SilentlyContinue) -and -not $removed) {
        $list = & pipx list 2>$null
        if ($list -match $Package) { & pipx uninstall $Package | Out-Null; $removed = $true }
    }
    if (-not $removed -and (Test-Python311)) {
        & python -m pip uninstall -y $Package 2>$null | Out-Null
    }
    Write-Ok2 "uninstall complete"
    exit 0
}

# === Main ===
if ($Uninstall) { Invoke-Uninstall }

$method = $Prefer
if (-not $method -or $method -eq "auto") {
    if (Get-Command uv -ErrorAction SilentlyContinue)        { $method = "uv" }
    elseif (Get-Command pipx -ErrorAction SilentlyContinue) { $method = "pipx" }
    elseif (Test-Python311)                                 { $method = "pip" }
    else { Die "No installer found. Install uv: https://docs.astral.sh/uv/getting-started/installation/" }
}
Write-Info "Method: $method | Package: $Package"

$ok = $false
switch ($method) {
    "uv"   { $ok = Install-Uv }
    "pipx" { $ok = Install-Pipx }
    "pip"  { $ok = Install-Pip }
    default { Die "Unknown --prefer method: $method (uv|pipx|pip)" }
}

if (-not $ok) {
    Write-Warn2 "Trying fallback installers..."
    $ok = (Install-Uv) -or (Install-Pipx) -or (Install-Pip)
    if (-not $ok) { Die "All install methods failed" }
}

# Refresh PATH lookup for this session
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

if ($Verify) {
    $bin = Get-Command $BinName -ErrorAction SilentlyContinue
    if (-not $bin) { Die "$BinName not found on PATH after install — open a new terminal and retry" }
    Write-Info "$BinName -> $($bin.Source)"
    & $BinName --help | Out-Null
    if ($LASTEXITCODE -ne 0) { Die "$BinName --help failed" }
    & $BinName --version 2>$null
}

Write-Host ""
Write-Ok2 "$BinName installed"
Write-Host "  Run:    $BinName --help"
Write-Host "  Verify: $BinName doctor"
Write-Host "  Note:   open a NEW terminal if '$BinName' is not recognized yet (PATH refresh)."
