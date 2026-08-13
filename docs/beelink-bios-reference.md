# Beelink BIOS — AMI Aptio V, core 2.22.1293

**Purpose:** cut the ~20 s POST that Windows tuning cannot touch, and make the rig
behave like an appliance at power-on.

**Status:** PARTLY VERIFIED, 2026-08-13. The Fast Boot submenu (§2.2) was read off
this machine and its options are recorded as found. Everything else is still written
from AMI Aptio V conventions and UNVERIFIED here — menu names vary between firmware
builds, so treat those as "look for something like this" and correct this file with
what is actually on screen.

**Dependencies:** none — this is below every layer the rig owns.

**Failure modes:** there is an undo *within a session* (**F2**, §1) and nothing
commits until **F4** — but across sessions there is no history at all, so a setting
changed last month is unrecoverable knowledge. Photograph every screen before
changing it. A wrong setting can stop the machine booting entirely, and that recovery
is a CMOS reset, which throws away everything else with it.

---

## 1. Getting in

- **DEL** repeatedly from power-on → Setup
- **F7** → one-time boot menu (not what you want here)

Navigation: arrows move, **+/-** change values, **ESC** backs out of a submenu.

### Getting back out — nothing is permanent until F4

| Key | Effect |
|---|---|
| **ESC** | leave a submenu without applying |
| **F2** | **Previous Values** — undoes every change made since entering Setup. This is the undo. |
| **F3** | Optimized Defaults — factory reset of EVERYTHING, including settings you meant to keep |
| **ESC** at the top level | exit without saving; discards the whole session |
| **F4** | save and exit — the only step that commits anything |

So the safe loop is: change one thing, and if it looks wrong press **F2** or exit
with **ESC**. Change one thing at a time and reboot between them, or a machine that
will not POST leaves you guessing which setting did it.

### If it will not POST at all

Black screen, no Setup, no beep: clear CMOS. Unplug power, open the base, short the
CLR_CMOS pads/jumper or pull the coin cell for ~60 s. That resets EVERYTHING to
factory — which is why §1 says photograph the screens first.

### If Setup itself becomes unreachable

Fast Boot (§2.2) can shorten the POST past the point where **DEL** is polled. The
way in from Windows: Settings → System → Recovery → **Advanced startup → Restart
now** → Troubleshoot → Advanced options → **UEFI Firmware Settings**. This works
however short the POST gets, and is worth trying ONCE before you need it.

---

## 2. The changes, in order of how much they are likely to matter

### 2.1 Network Stack → **Disabled**  ← try this first

`Advanced → Network Stack Configuration → Network Stack`

The single most likely cause of a long POST. With it enabled the firmware initialises
a network stack and may wait for a PXE boot server that will never answer. On a rig
that boots from its own SSD and is offline by design, it can do nothing useful.

Expected saving: often most of a 15–20 s POST.

If disabling the whole stack is not offered, disable **IPv4 PXE Support** and
**IPv6 PXE Support** individually.

### 2.2 Fast Boot → **Enabled**

`Boot → Fast Boot`

Skips parts of hardware enumeration on a machine whose hardware has not changed.

No **MRC Fast Boot** on this board — it is Intel-platform-specific and not offered
here. OBSERVED 2026-08-13, the Fast Boot submenu on this machine instead contains:

| Setting | As found | Do | Why |
|---|---|---|---|
| USB Support | Full Initial | → **Partial Initial** | Biggest win here. Full Initial enumerates every USB device during POST; the Launchpad, EVO and hubs do not need BIOS to see them, Windows enumerates them itself. **But see the catch below.** |
| UFS Support | Enabled | → **Disabled** | Universal Flash Storage. This machine has none, so it is probing for a device class that is not there. |
| PS2 Devices Support | Enabled | → **Disabled** | A mini PC with no PS/2 ports. |
| NVMe Support | Enabled | **leave** | The boot drive. Disabling it is how the machine stops booting. |
| VGA Support | EFI driver | leave | Needed for display, no meaningful time in it. |
| Network Stack Driver Support | Disabled | already right | — |
| Redirection Support | Disabled | already right | serial console redirection |

**The USB catch, decided deliberately rather than discovered:** with *Partial Initial*
some firmware does not bring up a USB keyboard during POST, so **DEL stops reaching
Setup**. Recoverable through Windows → Advanced startup → UEFI Firmware Settings —
confirm that route works BEFORE relying on it.

The cautious order is UFS and PS2 first, which are free and cannot bite, then USB
separately so you know which one cost you the keyboard if it does.

### 2.3 CSM → **Disabled**

`Boot → CSM Configuration → CSM Support`

Legacy BIOS compatibility. Windows here is UEFI, so CSM only adds legacy option ROM
scanning. Often already disabled.

**Do not change this if you are unsure the install is UEFI.** Check first, in Windows:
`msinfo32` → **BIOS Mode** should read *UEFI*. If it says *Legacy*, leave CSM alone —
disabling it makes the machine unbootable.

### 2.4 Boot order → SSD only

`Boot → Boot Option Priorities`

Put the Windows Boot Manager / NVMe SSD first and set every other entry to
**Disabled**. Each enabled device is something the firmware probes and waits on.

### 2.5 Quiet Boot / logo

`Boot → Quiet Boot`

Cosmetic only — it hides POST messages rather than shortening them. Turning it
**off** is arguably better on a headless rig: if something goes wrong at POST you get
text instead of a logo. No measurable time either way.

---

## 3. Not about speed, but you want it

### 3.1 Restore on AC Power Loss → **Power On**

`Advanced → Power Management` (sometimes `Chipset → PCH → State After G3`)

Values are usually *Power Off* / *Power On* / *Last State*. Set **Power On**.

This is what makes the machine an appliance: pull the power at the end of a gig,
plug in at the next one, and it comes up on its own without anyone finding the
button. Combined with autologin and the logon-triggered rig task, that is the whole
unattended-boot story.

### 3.2 Wake on USB / Wake on LAN → Disabled

Nothing should be able to wake this machine except its own power button. Wake events
from a hub or a network are how a rig turns itself on in a flight case.

---

## 4. Do not touch

| | why |
|---|---|
| **Secure Boot** | Windows boots fine with it on. Changing it can require reinstalling. |
| **VT-d / VT-x** | No effect on boot time here. |
| **SATA/NVMe mode** (AHCI ↔ RAID) | Changing this makes Windows unbootable without a driver dance. |
| **Above 4G Decoding, Re-Size BAR** | Graphics features, not boot time. |
| **XMP / memory overclocking** | Instability on an audio rig is not worth a few ns of latency. |

---

## 5. After the changes

Time it the same way as before, so the numbers stay comparable:

1. Stopwatch from the power button to the Set Browser appearing on the Launchpad.
2. In Windows, the phase breakdown:

```powershell
Get-WinEvent -LogName "Microsoft-Windows-Diagnostics-Performance/Operational" -MaxEvents 20 |
  Where-Object { $_.Id -eq 100 } | Select-Object -First 1 | ForEach-Object {
    $x = [xml]$_.ToXml(); $d = @{}
    foreach ($n in $x.Event.EventData.Data) { $d[$n.Name] = $n."#text" }
    "total={0}ms mainpath={1}ms postboot={2}ms" -f $d["BootTime"], $d["MainPathBootTime"], $d["BootPostBootTime"]
  }
```

BIOS time does **not** appear in those numbers — it is entirely before Windows starts
counting. So: stopwatch minus `total` ≈ the POST, and that difference is how you know
whether §2.1 worked.

### Baseline to beat (MEASURED 2026-08-13)

| | |
|---|---|
| stopwatch, power → Set Browser | 57 s (before the Windows trims) |
| Windows `total` | 57.8 s → after trims |
| Windows `mainpath` | 19.1 s |
| Windows `postboot` | 38.7 s (was 82.7 s before Intel DSA was removed) |
| implied POST | ~20 s |
