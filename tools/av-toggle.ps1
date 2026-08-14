# Turn Defender real-time protection on or off.
#
#   tools\av-toggle.ps1 on    before installing plugins or anything downloaded
#   tools\av-toggle.ps1 off   back to performance configuration
#
# WHY IT IS OFF BY DEFAULT ON THIS RIG
#   It cost ~25 s of every boot, and it is not the control that addresses the threat
#   this machine actually faces. "A hacker on my local network" is answered by the
#   firewall and by not listening on ports nobody needs -- SMB, the print spooler,
#   the VNC web viewer and network discovery are all disabled, inbound is blocked by
#   default, and VNC is restricted to trusted networks. Real-time AV scans FILES, and
#   none of those paths involve a file.
#
#   What it IS good at is a downloaded installer carrying something nasty. That is a
#   real risk on the days you add plugins -- so turn it on for those, and off again
#   afterwards.
#
# REQUIRES Tamper Protection to be OFF (Windows Security -> Virus & threat
# protection -> Manage settings), which is by design: Microsoft does not let a script
# change this while it is on.

param([Parameter(Mandatory = $true)][ValidateSet("on", "off")][string]$State)

$k = "HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection"
if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null }

if ($State -eq "on") {
    Set-ItemProperty $k -Name "DisableRealtimeMonitoring" -Value 0 -Type DWord
    Set-MpPreference -DisableRealtimeMonitoring $false -ErrorAction SilentlyContinue
    Write-Output "real-time protection ON — installing software is safe(r) now"
} else {
    Set-ItemProperty $k -Name "DisableRealtimeMonitoring" -Value 1 -Type DWord
    Set-MpPreference -DisableRealtimeMonitoring $true -ErrorAction SilentlyContinue
    Write-Output "real-time protection OFF — performance configuration"
}

Start-Sleep -Seconds 2
$s = Get-MpComputerStatus
Write-Output "RealTimeProtectionEnabled : $($s.RealTimeProtectionEnabled)"
if ($s.IsTamperProtected) {
    Write-Output ""
    Write-Output "NOTE: Tamper Protection is ON, so this may not have taken effect."
    Write-Output "Turn it off in Windows Security and run this again."
}
