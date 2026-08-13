# Boot-time trimming for the rig. Idempotent; every change is reversible and the
# original values are backed up under HKLM:\SOFTWARE\ablepad-disabled-startup.
#
# MEASURED 2026-08-13 from Microsoft-Windows-Diagnostics-Performance/Operational,
# which is where Windows records what actually slowed a boot rather than what you
# suspect did:
#
#     total     84-112 s   (plus ~20 s of BIOS splash, which this cannot touch)
#     mainpath  23-32 s    kernel, drivers, logon -> desktop
#     postboot  60-83 s    after the desktop appears   <- the elephant
#
#   worst offenders, average over several boots:
#     DSAService.exe            32.0 s   Intel Driver & Support Assistant
#     MsMpEng.exe               25.5 s   Defender
#     Ableton Live 12 Suite.exe 14.8 s   the rig doing its job -- keep
#     IntelGraphicsSoftware.exe  6.5 s
#
# INTEL DSA IS THE BIG ONE, AND REMOVING IT IS RIGHT TWICE OVER
#   It is the single largest cost, and it exists to auto-update drivers -- which
#   directly contradicts freezing driver versions (ROADMAP section 5) and is the
#   most plausible way the EVO's audio driver gets changed overnight without anyone
#   touching the machine. On a rig that is offline by design it can never do
#   anything useful.
#
# WHAT THIS DELIBERATELY DOES NOT TOUCH
#   Defender real-time protection. Disabling it would be the next big win and it is
#   a security decision, not a performance one, so it stays a human's call. The
#   exclusions (C:\LiveRig, VST3, ProgramData\Ableton) are already in place.
#   AudientAppLauncher, Tailscale, tvncontrol -- all load-bearing.

$ErrorActionPreference = "Stop"
$backup = "HKLM:\SOFTWARE\ablepad-disabled-startup"
$run = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"

Write-Output "=== Intel Driver & Support Assistant ==="
foreach ($s in "DSAService", "DSAUpdateService") {
    $svc = Get-Service $s -ErrorAction SilentlyContinue
    if ($svc) {
        Stop-Service $s -Force -ErrorAction SilentlyContinue
        Set-Service $s -StartupType Disabled -ErrorAction SilentlyContinue
        Write-Output "  $s -> disabled"
    }
}

Write-Output "=== unused startup entries ==="
# Realtek is the ONBOARD audio stack. The rig's audio is the EVO 8 over ASIO, so
# this is an unused audio path loading at every boot -- cost with no benefit, and
# one more thing that can grab an audio device.
foreach ($n in "RTHDVCPL", "RtkAudUService", "SecurityHealth") {
    $v = (Get-ItemProperty $run -Name $n -ErrorAction SilentlyContinue).$n
    if ($v) {
        # NOT New-Item -Force: on an existing key that RECREATES it, discarding
        # every value already saved. Done that -- it silently wiped two backups and
        # left only the last entry, so the removals it was protecting became
        # irreversible. Create only when missing.
        if (-not (Test-Path $backup)) { New-Item -Path $backup -Force | Out-Null }
        Set-ItemProperty $backup -Name $n -Value $v
        Remove-ItemProperty $run -Name $n -ErrorAction SilentlyContinue
        Write-Output "  $n -> removed (backed up to $backup)"
    }
}

Write-Output ""
Write-Output "To undo: copy the values back from $backup into $run,"
Write-Output "and Set-Service DSAService,DSAUpdateService -StartupType Automatic."
Write-Output ""
Write-Output "STILL ON THE TABLE, and both need a human:"
Write-Output "  * the ~20 s BIOS splash -- see docs/ROADMAP.md Phase 7"
Write-Output "  * Defender real-time protection (~25 s) -- a security decision"
