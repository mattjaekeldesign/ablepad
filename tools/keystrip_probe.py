"""
What does the key strip actually send?

Polls EVERY virtual key code and reports each one that goes down. Needed because a
macro strip can be configured to send almost anything, and the rig's whole design
here rests on it sending F13-F15 -- keys no physical keyboard has and Ableton binds
nothing to.

MUST RUN IN THE INTERACTIVE SESSION. GetAsyncKeyState reads the calling session's
input state, and an SSH shell is session 0 -- it cannot see what is typed on the
desktop. Run it through the scheduled task, not directly.

If the strip turns out to send ordinary letters, that is a hardware configuration
problem to solve in the strip's own software BEFORE wiring it here. The rig does not
consume the keystroke, so a key Ableton binds would fire Live's shortcut as well as
the rig's action.
"""

from __future__ import annotations

import ctypes
import sys
import time

DURATION_S = 45.0

#: Names worth printing. Everything else is reported by number, which is enough to
#: recognise and to configure against.
NAMES = {
    0x08: "BACKSPACE", 0x09: "TAB", 0x0D: "ENTER", 0x10: "SHIFT", 0x11: "CTRL",
    0x12: "ALT", 0x13: "PAUSE", 0x14: "CAPSLOCK", 0x1B: "ESC", 0x20: "SPACE",
    0x25: "LEFT", 0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN",
    0x5B: "LWIN", 0x5C: "RWIN",
    0xA0: "LSHIFT", 0xA1: "RSHIFT", 0xA2: "LCTRL", 0xA3: "RCTRL",
    0xA4: "LALT", 0xA5: "RALT",
    0xAD: "VOL_MUTE", 0xAE: "VOL_DOWN", 0xAF: "VOL_UP",
    0xB0: "MEDIA_NEXT", 0xB1: "MEDIA_PREV", 0xB2: "MEDIA_STOP", 0xB3: "MEDIA_PLAY",
}
for i in range(1, 25):
    NAMES[0x6F + i] = f"F{i}"          # F1 = 0x70 ... F24 = 0x87
for c in range(0x30, 0x3A):
    NAMES[c] = chr(c)                   # 0-9
for c in range(0x41, 0x5B):
    NAMES[c] = chr(c)                   # A-Z


def name(vk: int) -> str:
    return NAMES.get(vk, f"VK_0x{vk:02X}")


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    user32 = ctypes.windll.user32

    print("Press each key on the strip, one at a time, holding briefly.")
    print("Watching every virtual key for %.0fs.\n" % DURATION_S)

    down: set[int] = set()
    seen: dict[int, int] = {}
    end = time.monotonic() + DURATION_S
    while time.monotonic() < end:
        for vk in range(0x01, 0xFF):
            if vk in (0x01, 0x02, 0x04):
                continue  # mouse buttons -- the strip enumerates a mouse too
            is_down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if is_down and vk not in down:
                down.add(vk)
                seen[vk] = seen.get(vk, 0) + 1
                print("  DOWN  %-12s (0x%02X)" % (name(vk), vk))
            elif not is_down and vk in down:
                down.discard(vk)
        time.sleep(0.02)

    print()
    if not seen:
        print("NOTHING CAPTURED.")
        print("Either no key was pressed, or this ran outside the interactive session")
        print("-- GetAsyncKeyState cannot see the desktop's input from session 0.")
        return 1

    print("=== keys the strip sends ===")
    for vk, count in sorted(seen.items()):
        print("  %-12s 0x%02X   pressed %d time(s)" % (name(vk), vk, count))

    wanted = {0x7C: "F13", 0x7D: "F14", 0x7E: "F15"}
    hits = {vk: n for vk, n in wanted.items() if vk in seen}
    print()
    if len(hits) == 3:
        print("All three are F13-F15 already. Nothing to configure -- the rig is")
        print("listening for exactly these.")
    elif hits:
        print("Partly there: %s already correct." % ", ".join(sorted(hits.values())))
        print("Set the remaining key(s) to the missing F13/F14/F15 in the strip's software.")
    else:
        print("None of F13/F14/F15. Configure the strip to send them -- or tell the")
        print("rig these codes instead, ONLY if Ableton binds nothing to them.")
        print("The rig does not swallow the keystroke: whatever has focus sees it too.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
