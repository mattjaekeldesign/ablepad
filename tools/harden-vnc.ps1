# TightVNC hardening. VNC is the rig's dire-situation lifeline, which also makes it
# the most valuable thing on the machine to an attacker: a working VNC session is
# the whole desktop.

Write-Output "=== disabling the VNC web viewer (port 5800) ==="
# The Java/HTTP viewer is a second way in that nothing uses -- the phone connects
# with a VNC client on 5900. One less listener, no functionality lost.
Set-ItemProperty "HKLM:\SOFTWARE\TightVNC\Server" -Name AcceptHttpConnections -Value 0 -Type DWord
Restart-Service tvnserver -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Write-Output "  AcceptHttpConnections = " + (Get-ItemProperty "HKLM:\SOFTWARE\TightVNC\Server").AcceptHttpConnections

Write-Output ""
Write-Output "=== restricting VNC to trusted networks ==="
# The rule allowed ANY profile, so port 5900 was reachable from a venue LAN. Private
# only means: over Tailscale (a Private interface), or over a network deliberately
# marked trusted -- the phone hotspot. NOT from whatever wifi the venue runs.
# -Direction is not a filter on Get-NetFirewallRule in this parameter set; it has to
# be filtered afterwards or PowerShell reports AmbiguousParameterSet.
Get-NetFirewallRule -DisplayName "TightVNC" -ErrorAction SilentlyContinue |
    Where-Object { $_.Direction -eq "Inbound" } |
    ForEach-Object {
        Set-NetFirewallRule -Name $_.Name -Profile Private
        Write-Output "  $($_.DisplayName) -> Private only"
    }

Write-Output ""
Write-Output "=== listeners now ==="
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -notmatch "^(127\.|::1)" } |
    Select-Object LocalPort, @{n = "proc"; e = { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } } |
    Sort-Object LocalPort -Unique | Format-Table -AutoSize
