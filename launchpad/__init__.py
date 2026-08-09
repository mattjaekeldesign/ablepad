"""
launchpad/ — the Launchpad X service (Phase 3).

LAYER: Drivers + Services for the one piece of hardware that is the whole UI.

CURRENT STATE (2026-08-09): only the pure animation frame engine lives here.
Everything else in the Phase 3 tree (ports, device, grid, colors, renderer,
mappings, modes) requires Phase 1 measured constants from the Beelink and is
deliberately absent — an empty module is better than one built on guesses.
"""
