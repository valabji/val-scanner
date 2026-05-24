#Requires -Version 5.1
<#
.SYNOPSIS
    Build ValScanner as a native Windows executable.
.DESCRIPTION
    Uses PyInstaller to produce dist\ValScanner\ValScanner.exe with embedded
    icon and Windows version metadata (no console window).
    Optionally wraps it in an Inno Setup installer.
.PARAMETER Installer
    Build an Inno Setup installer after the PyInstaller step.
    Requires Inno Setup 6 to be installed.
.PARAMETER InnoPath
    Full path to ISCC.exe. Auto-detected from Program Files if omitted.
.EXAMPLE
    .\scripts\build_app.ps1
.EXAMPLE
    .\scripts\build_app.ps1 -Installer
#>
[CmdletBinding()]
param(
    [switch]$Installer,
    [string]$InnoPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir   = Split-Path -Parent $ScriptDir
$AppName   = "ValScanner"
$Version   = "0.1.10"

function Write-Info    { Write-Host "[build] $args" -ForegroundColor Cyan }
function Write-Success { Write-Host "[build] $args" -ForegroundColor Green }
function Fail($msg)    { Write-Host "[build] ERROR: $msg" -ForegroundColor Red; exit 1 }

# ── pre-flight ────────────────────────────────────────────────────────────────
$IconPath = Join-Path $RepoDir "assets\icon.ico"
if (-not (Test-Path $IconPath)) {
    Fail "Missing icon: assets\icon.ico`nSee icon placeholder instructions at the bottom of the README."
}

try { python -c "import PyInstaller" 2>$null }
catch {
    Write-Info "Installing PyInstaller..."
    pip install --quiet pyinstaller
}

# ── build ─────────────────────────────────────────────────────────────────────
Set-Location $RepoDir
Write-Info "Cleaning previous build..."
@("build", "dist") | ForEach-Object {
    if (Test-Path $_) { Remove-Item $_ -Recurse -Force }
}

Write-Info "Running PyInstaller (this takes a minute)..."
python -m PyInstaller valscanner.spec --noconfirm

$ExePath = Join-Path $RepoDir "dist\$AppName\$AppName.exe"
if (-not (Test-Path $ExePath)) { Fail "Build failed — $ExePath not found" }
Write-Success "Executable: $ExePath"

# ── Inno Setup installer ──────────────────────────────────────────────────────
if ($Installer) {
    if (-not $InnoPath) {
        $candidates = @(
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            "C:\Program Files\Inno Setup 6\ISCC.exe",
            "C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
        )
        foreach ($c in $candidates) {
            if (Test-Path $c) { $InnoPath = $c; break }
        }
    }

    if (-not $InnoPath -or -not (Test-Path $InnoPath)) {
        Write-Info "Inno Setup not found — skipping installer."
        Write-Info "Download from https://jrsoftware.org/isinfo.php, then re-run with -Installer."
    } else {
        $IssPath = Join-Path $RepoDir "assets\installer.iss"
        Write-Info "Building installer with Inno Setup..."
        & $InnoPath $IssPath
        $InstallerOut = Join-Path $RepoDir "dist\${AppName}-${Version}-setup.exe"
        if (Test-Path $InstallerOut) {
            Write-Success "Installer: $InstallerOut"
        }
    }
}

Write-Success "Done -> dist\$AppName\$AppName.exe"
