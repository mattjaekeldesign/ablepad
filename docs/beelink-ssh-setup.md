# Getting Claude Code onto the Beelink over SSH

**Purpose.** Everything needed to let Claude Code (running on `matts-mac-mini`) execute commands
on the Beelink. Do the steps in order — the ordering is deliberate and step 7 can lock you out
if you run it early.

**Time:** ~15 minutes. **You need:** the Beelink with a monitor and keyboard attached, one last
time, and an admin PowerShell.

---

## 0. TL;DR

```text
1. Install OpenSSH Server on the Beelink          (§3)
2. Install Tailscale on the Beelink               (§4)   ← recommended path
3. Paste my public key into the ADMIN key file    (§5)   ← the step everyone gets wrong
4. Test it works                                  (§8)
5. THEN harden                                    (§7)
6. Send me the block in §9
```

The public key you need is in §2. It is already generated and waiting on this Mac.

---

## 1. Which network path

You already run Tailscale — `matts-mac-mini`, `matt-jaekels-air`, `sharon-hp` (Windows),
`iphone-13`, and two others are on the tailnet. A Windows machine is already working on it, so
this is a proven route for you, not a new experiment.

| Path | Works across networks | Port forwarding | Firewall exposure | Verdict |
|---|---|---|---|---|
| **Tailscale** | Yes | None | None — nothing public | **Use this** |
| LAN IP | Same network only | None | LAN only | Fine as a fallback |
| Port-forwarded WAN | Yes | Yes | **Port 22 exposed to the internet** | **Don't** |

> **Do not port-forward SSH to the open internet.** Port 22 on a public IP gets credential-stuffed
> within hours. Tailscale gives you the same reach with nothing listening publicly.

**Note on the rig's own design.** This is a *development* lifeline, not the Phase 6 gig-time
lifeline. Tailscale needs internet; the finished rig is specified to run offline with its own
hotspot. Both can coexist — Tailscale for building, hotspot+SSH for the stage. Don't let this
replace the Phase 6 work in `ROADMAP.md`.

---

## 2. My public key

Generated on `matts-mac-mini`. The private half never leaves this machine.

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIUAR27ix75nF8ILm+UQW2wtP/ggQTKxMh98VEkgZeR/ claude-code@ablepad-20260811
```

Fingerprint, so you can confirm it arrived intact:

```text
SHA256:5XCTYCztzigGUW86jyIOY+WB/g5v5zHdlhHNLAmwa0g
```

- Type: ed25519, single purpose, this host only
- Private key: `~/.ssh/ablepad_beelink_ed25519` on the Mac
- **No passphrase** — deliberate, so commands can run without an interactive prompt. See §10 for
  what that does and does not mean.

---

## 3. Install OpenSSH Server

Open **PowerShell as Administrator** on the Beelink.

```powershell
# Is it already there?
Get-WindowsCapability -Online -Name OpenSSH.Server*

# Install it
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# Start now, and on every boot
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic

# Confirm
Get-Service sshd
```

`Status` should read `Running` and `StartType` `Automatic`.

The installer normally creates the firewall rule. Verify:

```powershell
Get-NetFirewallRule -Name *ssh* | Select-Object Name, Enabled, Direction, Action
```

If nothing comes back:

```powershell
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' `
  -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

### Make PowerShell the default shell — do this, it matters

Out of the box, sshd drops you into `cmd.exe`. Almost everything useful for this rig is
PowerShell (`Get-PnpDevice`, `Get-WmiObject`, the whole Phase 1 toolchain).

```powershell
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell `
  -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
  -PropertyType String -Force
```

---

## 4. Tailscale on the Beelink

1. Download: `https://tailscale.com/download/windows`
2. Install, sign in with **the same account as your other devices** (`mattjaekeldesign@`)
3. **Turn on "Run unattended"** — Tailscale tray icon → Preferences → *Run unattended*

> **"Run unattended" is not optional for this rig.** Without it Tailscale only stays connected
> while a user is logged in interactively. A headless Beelink that reboots at 3pm before a gig
> would come back with no network path in, and you would be driving to it with a monitor.

Then, on the Beelink:

```powershell
tailscale ip -4
tailscale status
```

Write down the `100.x.x.x` address — that goes in §9.

---

## 5. Install my key — THE STEP THAT GOES WRONG

Windows OpenSSH ships with this at the **bottom** of `C:\ProgramData\ssh\sshd_config`:

```text
Match Group administrators
       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys
```

**If your account is an Administrator, `C:\Users\<you>\.ssh\authorized_keys` is ignored
entirely.** Every "I added the key and it still asks for a password" thread on the internet is
this. Which file you use depends on the account:

| Account type | Key goes in |
|---|---|
| **Administrator** (most likely you) | `C:\ProgramData\ssh\administrators_authorized_keys` |
| Standard user | `C:\Users\<you>\.ssh\authorized_keys` |

Not sure? `whoami /groups | findstr /i administrators`

### For an admin account

```powershell
$key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIUAR27ix75nF8ILm+UQW2wtP/ggQTKxMh98VEkgZeR/ claude-code@ablepad-20260811'
$f   = 'C:\ProgramData\ssh\administrators_authorized_keys'

# -Encoding ascii is NOT a style choice -- see the warning below
Add-Content -Path $f -Value $key -Encoding ascii

# Lock the file down. sshd REFUSES to read it if anyone else can write to it.
icacls.exe $f /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"

# Check it looks right: one line, no stray characters
Get-Content $f
```

> ⚠️ **Two silent killers, both invisible in Notepad.**
>
> **BOM.** `-Encoding utf8` in Windows PowerShell 5.1 writes a UTF-8 *byte order mark*. sshd
> reads the first key line as corrupt and ignores the file. No error, no log entry that makes
> sense. **Always `-Encoding ascii`.**
>
> **ACLs.** If the file inherits permissions that let non-admins write to it, sshd refuses to
> use it — again quietly. The `icacls` line above is what fixes it, and `/inheritance:r` is the
> part doing the work.

### For a standard account

```powershell
$key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIUAR27ix75nF8ILm+UQW2wtP/ggQTKxMh98VEkgZeR/ claude-code@ablepad-20260811'
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh" | Out-Null
Add-Content -Path "$env:USERPROFILE\.ssh\authorized_keys" -Value $key -Encoding ascii
icacls.exe "$env:USERPROFILE\.ssh\authorized_keys" /inheritance:r /grant "$env:USERNAME:F" /grant "SYSTEM:F"
```

Then restart the service:

```powershell
Restart-Service sshd
```

---

## 6. Stop the machine sleeping

A sleeping Beelink is an unreachable Beelink, and USB selective suspend will also drop the
Launchpad and the EVO 8. This overlaps Phase 7 in the roadmap, so it is work you owed anyway.

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0
powercfg /hibernate off
```

USB selective suspend is per-power-plan and easiest in the GUI:
*Control Panel → Power Options → Change plan settings → Advanced → USB settings →
USB selective suspend → **Disabled***.

---

## 7. Harden — AFTER §8 passes, not before

**Do not run this until key login is proven working.** If the key is broken and you have already
turned off password auth, the only way back in is a monitor and keyboard.

Edit `C:\ProgramData\ssh\sshd_config`:

```powershell
notepad C:\ProgramData\ssh\sshd_config
```

Set these (uncomment where needed):

```text
PubkeyAuthentication yes
PasswordAuthentication no
PermitEmptyPasswords no
```

```powershell
Restart-Service sshd
```

Keep the `Match Group administrators` block at the bottom exactly as it is.

---

## 8. Test — in this order

**a) On the Beelink itself.** Proves sshd works, independent of any network question:

```powershell
ssh localhost
# expect a PowerShell prompt. 'exit' to leave.
```

**b) Grab the host key fingerprint** — send this to me so I can verify I am talking to the right
machine and not something in the middle:

```powershell
ssh-keygen -lf C:\ProgramData\ssh\ssh_host_ed25519_key.pub
```

**c) From another machine on your tailnet** (your Air, say):

```bash
ssh <windows-username>@<tailscale-ip>
```

If that lands in a PowerShell prompt without asking for a password, you are done — go to §9.

---

## 9. Send me this

Copy, fill in, paste back:

```text
BEELINK CONNECTION
------------------
Tailscale IP:        100.
Tailscale hostname:
LAN IP (fallback):   192.168.
Windows username:
Admin account?       yes / no
SSH port:            22
Key installed in:    administrators_authorized_keys  /  ~/.ssh/authorized_keys
Password auth:       still on / disabled
Host key fingerprint: SHA256:
Local test (ssh localhost):   worked / failed
Remote test from another box: worked / failed / not tried
```

If anything failed, send the error text verbatim and whatever §11 turned up — a real error
message is worth more than a description of one.

---

## 10. Security — what this key can and cannot do

**What it is.** One ed25519 key, no passphrase, on one Mac, authorised on one Windows box.

**Why no passphrase.** A passphrase would mean an interactive prompt on every command, which
defeats the purpose. The mitigation is scope, not secrecy: the key does nothing except log into
your Beelink, and only from a machine that already has your Tailscale identity.

**Revoking it — 10 seconds, any time:**

```powershell
# Delete the line containing this key
(Get-Content C:\ProgramData\ssh\administrators_authorized_keys) |
  Where-Object { $_ -notmatch 'claude-code@ablepad' } |
  Set-Content C:\ProgramData\ssh\administrators_authorized_keys -Encoding ascii
Restart-Service sshd
```

Or kill the whole path: `Stop-Service sshd; Set-Service sshd -StartupType Disabled`.

**Attack surface.** With Tailscale and no port forwarding, nothing is listening on the public
internet. Someone would need to be on your tailnet already.

**What I will do with it.** Read state, run the Phase 1 bench tools, install and configure
things you have asked for, and report what I find. **What I will not do without asking first:**
delete or overwrite anything outside the repo, change Windows security settings, touch your
Ableton sets, or install software you have not asked for. Destructive or hard-to-reverse
commands get confirmed with you first — same rule as in this repo.

---

## 11. Troubleshooting

| Symptom | Almost always |
|---|---|
| `Permission denied (publickey)` and you are an admin | Key is in `~/.ssh/authorized_keys` instead of `administrators_authorized_keys` (§5) |
| `Permission denied (publickey)`, key in the right file | BOM from `-Encoding utf8`, or ACLs — re-run the `icacls` line (§5) |
| Prompts for a password | sshd is not accepting the key and falling back. Same two causes as above |
| `Connection refused` | sshd not running (`Get-Service sshd`) or firewall rule missing (§3) |
| `Connection timed out` | Wrong IP, machine asleep (§6), or Tailscale not up / not unattended (§4) |
| Works via `ssh localhost`, not remotely | Network layer, not SSH. Check `tailscale status` on both ends |
| Was working, stopped after reboot | `Set-Service sshd -StartupType Automatic`, and Tailscale "Run unattended" |
| Lands in `cmd.exe` not PowerShell | DefaultShell registry value (§3) |

**Read the actual log.** Far faster than guessing:

```powershell
Get-WinEvent -LogName 'OpenSSH/Operational' -MaxEvents 30 | Format-List TimeCreated, Message
```

Or run sshd in the foreground with full debug in a second admin window:

```powershell
Stop-Service sshd
& "C:\Windows\System32\OpenSSH\sshd.exe" -d -d -d
# reproduce the failed login, read the output, Ctrl+C, then: Start-Service sshd
```

That second one prints the exact reason a key was rejected, including the ACL and BOM cases.

---

## 12. What happens once I am in

I add an SSH config entry on this Mac so commands are one word:

```text
Host beelink
    HostName 100.x.x.x
    User <username>
    IdentityFile ~/.ssh/ablepad_beelink_ed25519
    IdentitiesOnly yes
    ServerAliveInterval 30
```

Then, in roughly this order — all of it currently blocked on not having hardware access:

```text
1. Confirm the environment       Python 3.12+, Git, Ableton exe path recorded verbatim
2. Install the EVO 8 driver      and record driver + firmware versions while still online
3. tools/midi_port_inspector.py  twice: Ableton closed, then open. The diff IS the
                                 MIDI-exclusivity constraint the Phase 8 decision rests on
4. interface_name_inspector.py   --label evo8 — the real Get-PnpDevice endpoint names
5. Prove the restore contract    kill a tool with Ctrl+C, confirm hold-Session still
                                 opens the Launchpad Setup menu
6. launchpad_note_tester --frame the CC frame, ~2 minutes, the actual unknown
```

Steps 3–6 are the Phase 1 exit test. They are the reason this document exists: every one of them
needs a Windows box with the hardware plugged in, and that has been the blocker since the repo
was created.

One caveat worth setting expectations on: the LED colour sweep (`led_color_tester.py`) needs a
human to *look at the pads and photograph them*. I can drive it over SSH, but you have to be in
front of the device for that one.
