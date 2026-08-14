# Ableton's user-facing folder: User Library, Factory Packs, Live Recordings.
# Live reads and writes here constantly while a set is open.
$path = "C:\Users\rigma\Documents\Ableton"
try {
    Add-MpPreference -ExclusionPath $path -ErrorAction Stop
    Write-Output "added path: $path"
} catch {
    Write-Output "FAILED path: $($_.Exception.Message)"
}

# Deliberately NOT excluding python.exe as a process. Process exclusions apply to
# everything that process touches, and "python.exe" is a generic name -- it would
# hand a blanket exemption to any python on the machine. C:\LiveRig is already a
# path exclusion, which covers the controller and its venv without that.

$p = Get-MpPreference
Write-Output ""
Write-Output "paths     : $($p.ExclusionPath -join '; ')"
Write-Output "processes : $($p.ExclusionProcess -join '; ')"
