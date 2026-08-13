# Close Ableton Live GRACEFULLY, so it saves its preferences and clears its crash
# journal on the way out.
#
# WHY THIS EXISTS
#   Stop-Process -Force is TerminateProcess: Live never runs its shutdown, so
#   Preferences.cfg is not written and the crash journal survives. Two consequences,
#   both observed on this rig:
#     * a Control Surface selected in Preferences is LOST
#     * the next launch offers "recover the last session?", which is modal and
#       unanswerable on a rig with no keyboard
#
#   taskkill WITHOUT /F posts WM_CLOSE instead, which is a real close request.
#
# MUST RUN IN THE USER'S SESSION, AT LIVE'S INTEGRITY LEVEL
#   From an SSH shell (session 0) taskkill cannot see Live's windows and reports
#   "can only be terminated forcefully". Unelevated against an elevated Live it
#   reports "Access is denied". Run it via the scheduled task, not directly:
#
#     schtasks /run /tn ablepad-close-live
#
# A set with unsaved changes raises Live's save prompt, which nothing headless can
# answer -- the wait below then expires and the process is left alone rather than
# killed, because losing the prompt's answer is the caller's decision, not this
# script's.

param([int]$TimeoutSeconds = 20)

$live = Get-Process -Name "*Live*" -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -like "*Live*" }

if (-not $live) {
    Write-Output "Ableton is not running"
    exit 0
}

foreach ($p in $live) {
    Write-Output "asking Ableton (pid $($p.Id)) to close"
    taskkill /PID $p.Id | Out-Null
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-Process -Id $live[0].Id -ErrorAction SilentlyContinue)) {
        Write-Output "closed gracefully"
        exit 0
    }
    Start-Sleep -Milliseconds 500
}

Write-Output "STILL RUNNING after $TimeoutSeconds s."
Write-Output ""
Write-Output "Almost certainly Live is showing 'Save changes to <set>?' -- click"
Write-Output "Don't Save on the rig's screen and it will close."
Write-Output ""
Write-Output "Deliberately NOT killing it. This tool is for the operator sitting at"
Write-Output "the machine, and the moment you most want to close Live by hand is"
Write-Output "right after changing Preferences -- which is exactly what a force kill"
Write-Output "discards. The RIG does escalate to a kill after"
Write-Output "GRACEFUL_CLOSE_TIMEOUT_S, because on stage a dirty set must not cost"
Write-Output "more than a moment of silence."
exit 1
