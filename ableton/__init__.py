"""
ableton/ — launch, supervise and recover Ableton Live (Phase 5).

LAYER: Services. Talks to the OS through the ProcessController protocol ONLY;
psutil appears in exactly one module (process.py). Everything else is pure
policy, testable with fakes — which is how it was built, off-rig, before the
Beelink existed. The psutil adapter itself is UNVERIFIED on Windows until the
bench run.
"""
