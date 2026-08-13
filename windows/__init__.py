"""
windows/ — everything that only makes sense on the target machine.

LAYER: Drivers. Registry reads, process inspection, and later hotspot/SSH/power.

Isolated here for one reason: nothing above this package may import it directly on
a developer machine and fail. The rig is written on macOS and runs on Windows, so
platform code lives behind probes and adapters that the pure layers receive by
injection — see rig/boot.py, which is fully tested with none of this present.
"""
