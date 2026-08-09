"""
rig/ — the application spine.

LAYER: Controller + Application Logic. No hardware imports allowed here, ever.
Hardware reaches this package as events; this package reaches hardware as commands.
Phase 3's launchpad/ package plugs into the EventBus — nothing in here changes.
"""
