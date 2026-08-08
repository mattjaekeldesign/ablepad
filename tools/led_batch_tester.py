"""
Confirm and time the batched LED SysEx write.

LAYER: none. Bench instrument.

ANSWERS
    1. Does an 81-entry LED Lighting SysEx actually get accepted by the hardware?
    2. How long does one take, versus the 81 individual messages it replaces?
    3. What is the real settle time between entering Programmer Mode and the first
       accepted LED write? (_bench.PROGRAMMER_MODE_SETTLE_S is currently a guess.)
    4. What does the device do with an over-length message?

WHY THIS ONE MATTERS OUT OF PROPORTION TO ITS SIZE
    The manual states a ceiling of 81 <colourspec> entries per message (p.15). That
    is a documented limit, not a measured throughput -- it says the device will parse
    them, not that a full-surface repaint is fast enough to animate.

    ROADMAP.md S1 leans on this. The original argument for buying Bome was that 64
    individual note-ons from Python would stutter. Batching removes that argument, but
    only if the batch is genuinely quick. If one full repaint costs 40ms, a 70ms-per-
    frame animation has almost no headroom and the conclusion flips back.

    So: measure it, do not assume it.

    Note what this tool CANNOT settle. USB MIDI is buffered -- send() returning tells
    you the message was handed to the driver, not that the LEDs changed. Treat these
    numbers as a lower bound on cost and an upper bound on achievable frame rate, and
    sanity-check the animation visually before trusting either.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

from _bench import (
    ALL_LED_INDICES,
    MAX_COLOURSPECS_PER_MESSAGE,
    PAD_GRID_INDICES,
    Recorder,
    banner,
    bench,
    clear_all,
    led_batch,
    led_static,
    prompt,
)

WHITE = 3
OFF = 0


def time_send(session, message, repeats: int) -> list[float]:
    """Wall-clock per send, in milliseconds."""
    timings: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        session.send(message)
        timings.append((time.perf_counter() - start) * 1000.0)
    return timings


def summarise(rec: Recorder, label: str, timings: list[float]) -> float:
    median = statistics.median(timings)
    rec.add(
        f"#   {label:<34} median {median:>7.3f} ms   "
        f"min {min(timings):>7.3f}   max {max(timings):>7.3f}"
    )
    return median


def test_acceptance(session, rec: Recorder) -> None:
    """Light all 81 in one message and have a human confirm the whole surface lit."""
    rec.add("# --- 1. ACCEPTANCE ---")

    session.send(clear_all())
    time.sleep(0.2)
    session.send(led_batch([(index, WHITE) for index in ALL_LED_INDICES]))

    answer = prompt(
        f"\n  Sent one SysEx carrying {len(ALL_LED_INDICES)} entries.\n"
        "  Is the ENTIRE surface lit -- all 64 pads, the top row, the right\n"
        "  column, and the logo? (y/n): "
    ).strip().lower()

    accepted = answer.startswith("y")
    rec.add(f"#   81-entry message accepted: {'YES' if accepted else 'NO'}")
    if not accepted:
        rec.add("#   The documented ceiling does not hold on this hardware. Find the")
        rec.add("#   real maximum with --bisect before renderer.py is written.")
    session.send(clear_all())
    rec.add()


def test_timing(session, rec: Recorder, repeats: int) -> None:
    rec.add("# --- 2. TIMING ---")
    rec.add(f"#   {repeats} repeats each, wall clock around send()")
    rec.add()

    full_batch = led_batch([(index, WHITE) for index in ALL_LED_INDICES])
    grid_batch = led_batch([(index, WHITE) for index in PAD_GRID_INDICES])
    single = led_static(11, WHITE)

    batch_81 = summarise(rec, "one SysEx, 81 entries", time_send(session, full_batch, repeats))
    batch_64 = summarise(rec, "one SysEx, 64 entries", time_send(session, grid_batch, repeats))
    one = summarise(rec, "one single-LED SysEx", time_send(session, single, repeats))

    # The comparison that actually decides the architecture: what the naive
    # per-pad approach costs for the same visual result.
    per_pad_total = []
    for _ in range(max(3, repeats // 4)):
        start = time.perf_counter()
        for index in PAD_GRID_INDICES:
            session.send(led_static(index, WHITE))
        per_pad_total.append((time.perf_counter() - start) * 1000.0)
    naive = summarise(rec, "64 individual sends (the old way)", per_pad_total)

    session.send(clear_all())
    rec.add()

    rec.add("# --- VERDICT ---")
    if batch_64 > 0:
        rec.add(f"#   Batching a full grid repaint is {naive / batch_64:.1f}x cheaper.")
    frame_budget_ms = 70.0  # the folder-scanner animation's per-frame budget
    headroom = frame_budget_ms / batch_81 if batch_81 > 0 else float("inf")
    rec.add(f"#   At a {frame_budget_ms:.0f} ms animation frame, a full-surface repaint")
    rec.add(f"#   uses 1/{headroom:.0f} of the budget.")
    if headroom < 3:
        rec.add("#   THIN. Python-side animation is marginal; revisit ROADMAP.md S1.")
    else:
        rec.add("#   Ample. Python-side LED animation is viable, as ROADMAP.md S1 assumes.")
    rec.add(f"#   Single-LED write: {one:.3f} ms -- use for one-pad state changes.")
    rec.add()
    rec.add("#   Caveat: USB MIDI is buffered. send() returning means the driver took")
    rec.add("#   it, not that the LED changed. Lower bound on cost, upper bound on")
    rec.add("#   frame rate. Confirm visually.")
    rec.add()


def test_overlength(session, rec: Recorder) -> None:
    """
    Send more than the documented ceiling and observe.

    Undocumented behaviour, so the answer is whatever it is: the device may ignore
    the surplus, drop the message, or misparse it. Any of those is worth knowing
    before renderer.py can accidentally produce one.
    """
    rec.add("# --- 3. OVER-LENGTH BEHAVIOUR (undocumented) ---")

    over = MAX_COLOURSPECS_PER_MESSAGE + 10
    pairs = [(ALL_LED_INDICES[i % len(ALL_LED_INDICES)], WHITE) for i in range(over)]

    session.send(clear_all())
    time.sleep(0.2)
    try:
        session.send(led_batch(pairs))
        sent = True
    except Exception as exc:  # noqa: BLE001 -- the failure IS the finding
        sent = False
        rec.add(f"#   Backend refused a {over}-entry message: {type(exc).__name__}: {exc}")

    if sent:
        answer = prompt(
            f"\n  Sent {over} entries -- {over - MAX_COLOURSPECS_PER_MESSAGE} over the "
            "documented ceiling.\n"
            "  What happened? (all lit / partly lit / nothing / odd): "
        ).strip()
        rec.add(f"#   {over}-entry message: {answer!r}")
        rec.add("#   Whatever this says, renderer.py should chunk at 81 rather than")
        rec.add("#   rely on it. Recorded so nobody has to rediscover it.")

    session.send(clear_all())
    rec.add()


def test_settle(session, rec: Recorder, attempts: int) -> None:
    """
    Find the real delay needed after entering Programmer Mode before an LED write
    is accepted. The 100 ms in _bench.py was inherited from a draft and never measured.

    Method: leave and re-enter Programmer Mode, wait N ms, write one LED, ask whether
    it lit. Walk N down until it stops working.
    """
    from _bench import programmer_mode  # local: only this test needs the raw toggle

    rec.add("# --- 4. PROGRAMMER MODE SETTLE TIME ---")
    rec.add("#   Currently _bench.PROGRAMMER_MODE_SETTLE_S = 0.1 (a guess)")
    rec.add()

    candidates_ms = [100, 50, 20, 10, 5, 0][:attempts]
    lowest_working: int | None = None

    for delay_ms in candidates_ms:
        session.send(clear_all())
        session.send(programmer_mode(False))
        time.sleep(0.3)
        session.send(programmer_mode(True))
        time.sleep(delay_ms / 1000.0)
        session.send(led_static(11, WHITE))

        answer = prompt(
            f"  waited {delay_ms:>3} ms after Programmer Mode -- "
            "did the bottom-left pad light? (y/n): "
        ).strip().lower()

        worked = answer.startswith("y")
        rec.add(f"#   {delay_ms:>3} ms -> {'accepted' if worked else 'DROPPED'}")
        if worked:
            lowest_working = delay_ms
        else:
            break

    session.send(clear_all())
    rec.add()
    if lowest_working is not None:
        rec.add(f"#   Lowest confirmed working delay: {lowest_working} ms")
        rec.add(f"#   Set PROGRAMMER_MODE_SETTLE_S = {max(lowest_working * 2, 10) / 1000:.3f}")
        rec.add("#   (doubled -- this is a boot-path constant, and paying a few extra")
        rec.add("#    milliseconds once beats a surface that sometimes comes up blank)")
    else:
        rec.add("#   Nothing accepted. Retest before changing the constant.")
    rec.add()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=20, help="timing repeats (default 20)")
    parser.add_argument("--skip-settle", action="store_true", help="skip the settle-time test")
    parser.add_argument("--skip-overlength", action="store_true", help="skip the over-length test")
    args = parser.parse_args()

    banner(
        "LED batch write tester",
        "confirm and time the batched LED SysEx",
        "renderer.py design, and the Phase 8 Bome argument",
    )

    rec = Recorder(tool="led_batch_tester.py")

    with bench() as session:
        test_acceptance(session, rec)
        test_timing(session, rec, args.repeats)
        if not args.skip_overlength:
            test_overlength(session, rec)
        if not args.skip_settle:
            test_settle(session, rec, attempts=6)

    rec.save("led-batch-timings.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
