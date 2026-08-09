"""Pytest path setup: repo root for rig/ + storage/, tools/ for _bench imports."""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
for entry in (str(ROOT), str(ROOT / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)
