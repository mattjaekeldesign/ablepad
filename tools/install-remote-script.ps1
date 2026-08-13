# Install the Ablepad readiness Remote Script into Ableton Live.
#
# Live 12.4.3 lists scripts ONLY from its own Resources folder -- both user-scoped
# locations were tested and are ignored (remote_script/README.md). That folder is
# inside the installation, so a Live UPDATE DELETES THIS SCRIPT. Re-run this after
# every update; the symptom is a boot that suddenly takes the full settle time again.
#
# Usage:  powershell -ExecutionPolicy Bypass -File install-remote-script.ps1 [-Source <dir>]

param(
    [string]$Source = "C:\LiveRig\Controller\remote_script\Ablepad",
    [string]$LiveRoot = "C:\ProgramData\Ableton"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Source)) {
    Write-Error "source not found: $Source"
    exit 1
}

# Globbed rather than pinned: the edition and version are both in the path, and a
# pinned one would silently stop matching after an upgrade -- the exact failure this
# script exists to repair.
$targets = Get-ChildItem $LiveRoot -Directory -Filter "Live *" -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "Resources\MIDI Remote Scripts" } |
    Where-Object { Test-Path $_ }

if (-not $targets) {
    Write-Error "no 'Resources\MIDI Remote Scripts' found under $LiveRoot — is Live installed?"
    exit 1
}

foreach ($t in $targets) {
    $dest = Join-Path $t "Ablepad"
    New-Item -ItemType Directory -Force $dest | Out-Null
    Copy-Item (Join-Path $Source "*") $dest -Recurse -Force
    Write-Output "installed -> $dest"
}

Write-Output ""
Write-Output "Now: restart Live (it scans only at startup), then"
Write-Output "Preferences -> Link, Tempo & MIDI -> Control Surface -> Ablepad"
Write-Output "Leave Input and Output as None."
