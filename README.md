# ablepad

Control software for a headless Ableton Live performance rig. A Beelink mini PC, a Novation
Launchpad X, and an Audient EVO 8 in a box that behaves like a guitar pedal — no monitor,
no keyboard, no mouse, no internet.

Power it on, pick a set on the Launchpad, play. When something goes wrong, the Launchpad says
so.

## Hardware

| Device | Role |
|---|---|
| Beelink mini PC (Windows) | Runs the controller and Ableton Live |
| Novation Launchpad X | Set launcher before a set loads; Ableton's own controller after |
| Audient EVO 8 | Audio interface (ASIO) |
| 3-key USB strip, programmed to send **F13 / F14 / F15** | System control during a performance |
| Hotone Ampero II Stage *(optional)* | Guitar rack + foot controller, analog into the EVO 8 |

## Install (on the Beelink)

**Prerequisites:** Windows, Python 3.12+, Ableton Live 12, the Audient EVO 8 driver + EVO
Mixer app (buffer size and sample rate are set there, not in Live). In Live's Preferences,
enable **Launchpad X** as a control surface and select the EVO 8 as the ASIO device.

1. **Clone into the controller folder**

   ```powershell
   git clone https://github.com/mattjaekeldesign/ablepad.git C:\LiveRig\Controller
   cd C:\LiveRig\Controller
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   mkdir C:\LiveRig\Sets, C:\LiveRig\Logs
   ```

2. **Install the Remote Script** — tells the rig when a set has finished loading. Re-run after
   every Live update (updates delete it).

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\install-remote-script.ps1
   ```

3. **Configure** `config/rig.yaml` — at minimum:
   - `ableton.exe` — path to Live's exe (usually under `C:\ProgramData\Ableton\…`)
   - `ableton.appdata_dir` — `C:\Users\<rig user>\AppData\Roaming\Ableton`
   - `ableton.boot_set` — the set the rig treats as default

4. **Add your sets** to `C:\LiveRig\Sets\`. Optionally copy `docs/sets.yaml.example` to give
   them names and pad colours.

5. **Register the startup task.** The controller **must** run in the logged-on desktop
   session, elevated — started over SSH, Ableton launches with no desktop and makes no sound.

   ```powershell
   schtasks /create /tn ablepad-rig /tr C:\LiveRig\Controller\tools\run-rig.bat /sc onlogon /it /rl highest
   ```

   Enable Windows auto-logon for the rig user so it starts with no keyboard attached.

6. **Check it:** `.venv\Scripts\python -m pytest` should pass, then reboot.

## Use

**Boot.** The Launchpad shows the boot animation, then the **Set Browser**.

**Pick a set.** Each set is a lit pad in the top rows. **Hold it for 1 s** to load. The rig
waits for your choice — it never auto-loads the wrong set. Pad `19` rescans the sets folder.

**Play.** Once the set is loaded, the rig hands the Launchpad to Ableton. Session, Note and
your Custom layouts work exactly as they do in Live; the rig stays out of the way.

**System control (key strip)** — every action is a hold, so a knock never stops the audio:

| Key | Hold | Does |
|---|---|---|
| F13 | 1 s | Close Live, back to the Set Browser |
| F14 | 2 s | Restart Live on the **same** set |
| F15 | 4 s | Reboot the machine |

**Errors.** If Live doesn't come up or the audio interface disappears, the rig takes the
Launchpad back and shows **Error Mode**. If the EVO 8 or Launchpad goes dead after a static
shock, unplug and replug it — that's a hardware fault no software can clear.

**Logs:** `C:\LiveRig\Logs\rig.log`.

## Remote maintenance

SSH in for logs and updates (`docs/beelink-ssh-setup.md`), but never start the rig from the SSH
shell — use the task:

```powershell
schtasks /run /tn ablepad-rig
```

## Development

The logic is testable off-rig (macOS/Linux): `pip install -r requirements.txt && pytest`.
`just run` serves the architecture viewer and the Launchpad **Config Lab**
(`http://localhost:5178/lab/`) for designing pad layouts and animations in `configs/*.json`.

## Docs

| Document | What it is |
|---|---|
| `docs/ROADMAP.md` | Build history, exit tests, risk register |
| `docs/launchpad-x-sysex.md` | MIDI/SysEx spec for the Launchpad X |
| `docs/launchpad-x-hardware.md` | Device settings, ESD, Live vs Programmer mode |
| `docs/audient-evo-8-reference.md` | Audio interface: driver, tray app, ESD failure mode |
| `docs/hotone-ampero-ii-stage-reference.md` | Ampero II Stage MIDI map |
| `docs/beelink-ssh-setup.md` | Key-based SSH into the rig |
| `tools/README.md` | Bench tools for verifying hardware |
| `CLAUDE.md` | Architecture rules for working in this repo |
