# 🎛️ ablepad

Turn a mini PC + Launchpad into a **guitar-pedal-simple Ableton rig**. No monitor, no keyboard,
no mouse, no internet.

> 🔌 Power on → 🟢 hold a pad → 🎸 play. If something breaks, the Launchpad tells you.

---

## 🧰 What you need

| | Device | Job |
|---|---|---|
| 🖥️ | Beelink mini PC (Windows) | Runs this software + Ableton Live |
| 🟩 | Novation Launchpad X | Picks your set, then becomes Ableton's controller |
| 🔊 | Audient EVO 8 | Audio in/out |
| ⌨️ | 3-key USB strip (set to send **F13 / F14 / F15**) | Emergency buttons mid-gig |

---

## 🛠️ Install (one time, on the Beelink)

### ✅ Before you start

- 🪟 Windows + 🐍 Python 3.12 or newer
- 🎹 Ableton Live 12
- 🔊 Audient EVO 8 driver + **EVO Mixer** app (buffer size & sample rate live *there*, not in Ableton)
- In Ableton → **Preferences**:
  - 🎚️ Audio → driver **ASIO**, device **EVO 8**
  - 🟩 Link/Tempo/MIDI → control surface **Launchpad X**

### 1️⃣ Download the code

```powershell
git clone https://github.com/mattjaekeldesign/ablepad.git C:\LiveRig\Controller
cd C:\LiveRig\Controller
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
mkdir C:\LiveRig\Sets, C:\LiveRig\Logs
```

### 2️⃣ Install the Ableton helper script

This lets the rig know when a set has *finished* loading.

```powershell
powershell -ExecutionPolicy Bypass -File tools\install-remote-script.ps1
```

> ⚠️ **Ableton updates delete it.** Re-run this after every Live update.

### 3️⃣ Tell it where things are

Open `config\rig.yaml` and set:

| Setting | Put in |
|---|---|
| `ableton.exe` | Path to Ableton's `.exe` (usually under `C:\ProgramData\Ableton\…`) |
| `ableton.appdata_dir` | `C:\Users\<your user>\AppData\Roaming\Ableton` |
| `ableton.boot_set` | Your go-to set |

### 4️⃣ Make it start by itself

```powershell
schtasks /create /tn ablepad-rig /tr C:\LiveRig\Controller\tools\run-rig.bat /sc onlogon /it /rl highest
```

Then turn on Windows **auto-logon** for the rig user, so it boots with no keyboard.

> 🚫 Never start the rig from an SSH window. Ableton opens with no screen and **makes no
> sound**. Always use the task: `schtasks /run /tn ablepad-rig`

### 5️⃣ Check & reboot

```powershell
.venv\Scripts\python -m pytest
```

All green? 🔁 Reboot. You're done.

---

## 🎸 Playing a show

### 🔌 1. Power on

The Launchpad plays its boot animation ✨ then shows the **Set Browser**. Every lit pad is one
of your sets.

### 🟢 2. Pick a set

**Hold** the pad for **1 second**. ⏱️ A quick tap does nothing, so you can't load the wrong
one by accident. The rig always waits for you; it never picks a set by itself.

### 🎹 3. Play

Once the set loads, the Launchpad **belongs to Ableton**. Session, Note and your own Custom
layouts work exactly like they do in Live.

### 🚨 4. Emergency buttons (key strip)

Every button is a **hold**, so a stray foot or elbow won't stop the music.

| Key | Hold | What happens |
|---|---|---|
| ⏏️ **F13** | 1 s | Close Live → back to the Set Browser |
| 🔄 **F14** | 2 s | Restart Live on the **same** set |
| ⚡ **F15** | 4 s | Reboot the whole machine |

### 🟥 5. If it goes red

If Ableton won't start or the audio interface disappears, the rig takes the Launchpad back
and shows **Error Mode**.

> ⚡ **Static shock killed the sound or the Launchpad?** Unplug that USB cable and plug it
> back in. That's a hardware lock-up; no software can fix it.

📄 Logs: `C:\LiveRig\Logs\rig.log`

---

## ➕ Adding a new set to the Launchpad

You build sets **on the Beelink itself**, from your laptop or phone, with VNC (a remote
screen). Anything saved into `C:\LiveRig\Sets\` becomes a pad.

### 🌐 1. Get on the same network

VNC only answers on a **trusted** network. Use one of these:

- 🔒 **Tailscale**, signed in on both the Beelink and your laptop/phone *(works from anywhere)*
- 📱 your **phone hotspot**, if the Beelink has it marked as a Private network

> 🚫 Venue or public Wi-Fi won't connect. That's on purpose.

### 🖥️ 2. Open VNC Viewer

1. Install a VNC client: **RealVNC Viewer**, **TightVNC Viewer**, or any VNC app on your phone.
2. Connect to the Beelink's address (its Tailscale name or IP), port **5900**.
3. Enter the VNC password. 🔑

You'll see the Beelink's desktop. 🎉

### ⏏️ 3. Free up Ableton

- If a set is playing: **hold F13** (or in Ableton, **File → Quit**).
- The Launchpad goes back to the Set Browser.

> 🚫 Don't kill Ableton from Task Manager. Next time it starts, Live shows a "recover?"
> popup that nobody can click on a screenless rig.

### 🎹 4. Build your set

1. Open Ableton from the Start menu (or hold any set pad to load one to edit).
2. **File → New Live Set** (or edit an existing one).
3. Add your tracks, devices, clips, and Launchpad mappings.
4. **File → Save Live Set As…** 💾 and save it inside **`C:\LiveRig\Sets\`**

   ```text
   C:\LiveRig\Sets\
   └── 📁 My Gig Project\
       └── 🎵 My Gig.als      ← becomes a pad
   ```

   Ableton puts each set in its own `… Project` folder. That's fine; subfolders are found
   automatically.

> 🙈 Files named `autosave` / `[Recovered]`, and anything in `Backup\` folders, are hidden on
> purpose.

### 🚪 5. Quit Ableton

**File → Quit**, and **save** if it asks. Answer every popup now, while you can see them.
The Launchpad goes back to the Set Browser.

### 🔁 6. Make the pad appear

Press **Rescan**: the bottom button in the right-hand column of round buttons (pad 19). Your new set lights up. ✨

Or just reboot; it always rescans at startup.

### 🎨 7. (Optional) Name it and pick a colour

Create `C:\LiveRig\Sets\sets.yaml` (copy `docs\sets.yaml.example`):

```yaml
sets:
  My Gig.als:
    name: My Gig
    color: blue      # off · red · yellow · amber · orange · green · bright green · dim green · cyan · blue
```

No entry? The pad still shows, using the file name and a dim green colour.

### ✅ 8. Test it

Hold your new pad for 1 s, check it loads and **makes sound** 🔊, then hold **F13** to go back.
Disconnect VNC. Done!

---

## 💻 Development (off the rig)

The logic runs and tests anywhere (macOS/Linux):

```bash
pip install -r requirements.txt && pytest
just run   # Config Lab → http://localhost:5178/lab/
```

The **Config Lab** is a visual editor for pad layouts and animations (`configs/*.json`).

---

## 📚 Docs

| Document | What it is |
|---|---|
| `docs/ROADMAP.md` | Build history, exit tests, risk register |
| `docs/launchpad-x-sysex.md` | Launchpad X MIDI/SysEx spec |
| `docs/launchpad-x-hardware.md` | Device settings, static shock, Live vs Programmer mode |
| `docs/audient-evo-8-reference.md` | Audio interface: driver, tray app, failure modes |
| `docs/beelink-ssh-setup.md` | Key-based SSH into the rig |
| `tools/README.md` | Bench tools for checking hardware |
| `CLAUDE.md` | Architecture rules for working in this repo |
