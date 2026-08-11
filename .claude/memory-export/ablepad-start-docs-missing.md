---
name: ablepad-start-docs-missing
description: "The Start_DOCS master blueprint (§1–56) that every ablepad doc cites lives only in the claude.ai project, not in the repo"
metadata: 
  node_type: memory
  type: reference
  originSessionId: f9ffc384-1dc9-4600-984a-d311be787bc2
  modified: 2026-08-07T23:57:31.989Z
---

Every document in the ablepad repo cites a master blueprint by section number — `§8` folder tree,
`§30` MIDI routing, `§40` startup chain, `§51` rehearsal test, `§56` build order, and many more.
That blueprint is `Start_DOCS`, roughly 4,073 lines, §1–56.

**It is not in the repo.** It lives in the knowledge attached to Matt's "Ableton launchpad"
project on claude.ai, which is not reachable from Claude Code — there is no connector for
claude.ai project knowledge or chat history.

**Why:** any `§n` citation is currently uncheckable, so it cannot be treated as verified. Design
work that leans on one is leaning on something nobody in the session can read.

**How to apply:** if a `§` reference matters to the task, ask Matt to paste or commit that
section rather than inferring what it says. Getting `Start_DOCS` committed into `docs/` is a
standing high-value task. Same limitation applies to anything else in that project — ask him to
paste, download the files into the repo, or publish an artifact and share the URL. See
[[ablepad-project-state]].
