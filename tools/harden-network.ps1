# LAN hardening for the rig. Every one of these is a service listening on the
# network for a reason this machine does not have. Removing them is the control that
# actually addresses "a hacker on my local network" -- real-time antivirus scans
# files, and none of these are files.
#
# All reversible: Set-Service <name> -StartupType Automatic; Start-Service <name>.

Write-Output "=== firewall: inbound blocked by default on every profile ==="
Set-NetFirewallProfile -Profile Domain,Public,Private -DefaultInboundAction Block -ErrorAction SilentlyContinue
Get-NetFirewallProfile | Select-Object Name, Enabled, DefaultInboundAction | Format-Table -AutoSize

Write-Output "=== services this rig has no use for ==="
# Spooler     : no printer, and a service with a long history of remote exploits.
# LanmanServer: SMB FILE SHARING (445/139). Files move to this rig over scp/ssh, so
#               nothing needs the SMB server. This is the single biggest LAN surface.
# FDResPub,
# SSDPSRV,
# upnphost    : network discovery -- announcing this machine to the LAN. A rig should
#               be findable by people who already know where it is.
# DoSvc       : Delivery Optimization, peer-to-peer Windows Update (7680).
foreach ($s in "Spooler", "LanmanServer", "FDResPub", "SSDPSRV", "upnphost", "DoSvc") {
    $svc = Get-Service $s -ErrorAction SilentlyContinue
    if (-not $svc) { Write-Output "  $s : not present"; continue }
    try {
        Stop-Service $s -Force -ErrorAction SilentlyContinue
        Set-Service $s -StartupType Disabled -ErrorAction Stop
        Write-Output "  $s : stopped and disabled"
    } catch {
        Write-Output "  $s : FAILED - $($_.Exception.Message)"
    }
}

Write-Output ""
Write-Output "=== still listening on the network ==="
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -notmatch "^(127\.|::1)" } |
    Select-Object LocalPort, @{n = "proc"; e = { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } } |
    Sort-Object LocalPort -Unique | Format-Table -AutoSize
