# Synthesise an F13/F14/F15 keypress, so a configurator that only CAPTURES keys can
# be taught a key no physical keyboard has.
#
#   powershell -File send-fkey.ps1 -Key F13 -DelaySeconds 6
#
# Run it, then click into the configurator's "press a key" field before the countdown
# ends. The keypress goes to whatever window has focus at that moment.
#
# MUST RUN IN THE INTERACTIVE SESSION -- synthesised input goes to the calling
# session's desktop, and an SSH shell is session 0. Use the scheduled task.
#
# keybd_event rather than SendKeys: SendKeys posts through a higher-level path that
# some configurators ignore, whereas keybd_event injects at the same level the driver
# does, which is what a key-capture field is listening to.

param(
    [ValidateSet("F13", "F14", "F15", "F16")][string]$Key = "F13",
    [int]$DelaySeconds = 6
)

$vk = @{ "F13" = 0x7C; "F14" = 0x7D; "F15" = 0x7E; "F16" = 0x7F }[$Key]

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Keys {
    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
}
"@

Write-Output "Sending $Key (0x$('{0:X2}' -f $vk)) in $DelaySeconds seconds."
Write-Output "Click into the configurator's key field NOW."
for ($i = $DelaySeconds; $i -gt 0; $i--) {
    Write-Output "  $i..."
    Start-Sleep -Seconds 1
}

[Keys]::keybd_event([byte]$vk, 0, 0, [UIntPtr]::Zero)        # key down
Start-Sleep -Milliseconds 80
[Keys]::keybd_event([byte]$vk, 0, 2, [UIntPtr]::Zero)        # key up (KEYEVENTF_KEYUP)

Write-Output "$Key sent."
