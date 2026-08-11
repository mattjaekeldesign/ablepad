---
name: quick-commits-preferred
description: "Matt wants commits fast and cheap — one commit, short subject, no diff spelunking, unless he asks for a proper milestone commit"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c0e57cce-140d-44cd-8e85-382d5c9933ae
  modified: 2026-08-08T05:34:36.126Z
---

After the 2026-08-08 session Matt said committing "took too long" and wants faster, less
token-hungry commits — but still with simple, relevant titles.

**Why:** he commits mainly as safety checkpoints before experimenting; splitting into logical
commits and reading every diff burns time and tokens he doesn't want to spend.

**How to apply:**
- Default commit request → ONE commit, `git add -A`, terse conventional subject from
  `git status --short` alone (no diff reading), body only when something non-obvious happened.
- Only split commits / inspect diffs when he says "proper commit", "clean history", or it's a
  milestone he'll want to read later.
- He has global aliases (set 2026-08-08): `git save "msg"` and `git checkpoint` (auto
  timestamp message) — for zero-token snapshots he can run himself, `! git save "msg"` from
  inside a Claude session.
