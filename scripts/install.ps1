#Requires -Version 5.1
<#
.SYNOPSIS
    ValScanner installer for Windows (PowerShell 5.1+)
.DESCRIPTION
    Installs ValScanner and its dependencies into a virtual environment,
    then adds launcher wrappers to a directory of your choice.
.PARAMETER NoVenv
    Install into the current Python environment instead of a new venv.
.PARAMETER NoRich
    Skip optional rich-metadata deps (Pillow, mutagen, PyPDF2).
.PARAMETER Prefix
    Directory to write launcher scripts into (default: %LOCALAPPDATA%\Programs\ValScanner).
.EXAMPLE
    .\scripts\install.ps1
.EXAMPLE
    .\scripts\install.ps1 -NoVenv -NoRich
#>
[CmdletBinding()]
param(
    [switch]$NoVenv,
    [switch]$NoRich,
    [string]$Prefix = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir   = Split-Path -Parent $ScriptDir
$VenvDir   = Join-Path $RepoDir ".venv"

function Write-Info    { Write-Host "[valscanner] $args" -ForegroundColor Cyan }
function Write-Success { Write-Host "[valscanner] $args" -ForegroundColor Green }
function Write-Warn    { Write-Host "[valscanner] WARNING: $args" -ForegroundColor Yellow }
function Fail          { Write-Host "[valscanner] ERROR: $args" -ForegroundColor Red; exit 1 }

# ── find Python ────────────────────────────────────────────────────
$Python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $v = & $cmd -c "import sys; print(sys.version_info[:2] >= (3,8))" 2>$null
        if ($v -eq "True") { $Python = $cmd; break }
    } catch { continue }
}
if (-not $Python) {
    Fail "Python 3.8+ is required but was not found.`nDownload it from https://python.org/downloads"
}

$PyVer = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Info "Using $Python ($PyVer)"

# ── optional: create venv ──────────────────────────────────────────
if (-not $NoVenv) {
    if (-not (Test-Path $VenvDir)) {
        Write-Info "Creating virtual environment at $VenvDir ..."
        & $Python -m venv $VenvDir
    } else {
        Write-Info "Re-using existing virtual environment at $VenvDir"
    }
    $Pip        = Join-Path $VenvDir "Scripts\pip.exe"
    $ValScanBin = Join-Path $VenvDir "Scripts\valscanner.exe"
    $ValScanGui = Join-Path $VenvDir "Scripts\valscanner-gui.exe"
} else {
    $Pip = "$Python -m pip"
    Write-Warn "-NoVenv: installing into the active Python environment"
}

# ── install package ────────────────────────────────────────────────
$Extras = if ($NoRich) { "." } else { ".[rich]" }
Write-Info "Installing valscanner ($Extras) ..."
& $Pip install --quiet --upgrade pip
& $Pip install --quiet -e "$RepoDir\$Extras"
Write-Success "Package installed."

# ── write launcher scripts ─────────────────────────────────────────
if (-not $NoVenv) {
    if (-not $Prefix) {
        $Prefix = Join-Path $env:LOCALAPPDATA "Programs\ValScanner"
    }
    $BinDir = Join-Path $Prefix "bin"
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

    foreach ($entry in @(
        @{ src = $ValScanBin;  name = "valscanner.cmd" },
        @{ src = $ValScanGui;  name = "valscanner-gui.cmd" }
    )) {
        if (Test-Path $entry.src) {
            $dst = Join-Path $BinDir $entry.name
            "@echo off`r`n`"$($entry.src)`" %*" | Set-Content -Path $dst -Encoding ASCII
            Write-Info "Wrote launcher: $dst"
        }
    }

    # Check PATH
    $UserPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    if ($UserPath -notlike "*$BinDir*") {
        Write-Warn "$BinDir is not in your user PATH."
        Write-Warn "Run the following to add it permanently:"
        Write-Warn "  [System.Environment]::SetEnvironmentVariable('PATH', `"$BinDir;`$env:PATH`", 'User')"

        $ans = Read-Host "Add $BinDir to your user PATH now? [y/N]"
        if ($ans -match "^[Yy]") {
            [System.Environment]::SetEnvironmentVariable("PATH", "$BinDir;$UserPath", "User")
            $env:PATH = "$BinDir;$env:PATH"
            Write-Success "PATH updated. Restart your shell for it to take effect."
        }
    }
}

Write-Success "Done! Run 'valscanner --help' or 'valscanner-gui' to get started."
