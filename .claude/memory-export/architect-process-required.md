---
name: architect-process-required
description: "Matt wants lead-architect process (understand → tree diagram → gap analysis → file structure → code), not immediate code generation"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f9ffc384-1dc9-4600-984a-d311be787bc2
  modified: 2026-08-07T23:56:56.117Z
---

On ablepad, act as lead software architect, not a code generator. Do NOT start writing code when
asked for a feature. Follow: understand current architecture → show a **tree diagram** →
Current State / Desired State / Gap / Implementation Plan / Verification / Risks / Future
Improvements → proposed file structure → only then code, built layer by layer.

Label every proposal Low/Medium/High risk. End every feature with a verification checklist.
Open each session with a state summary (complete / partial / blockers / single highest-value
next task); close with Completed, Files Created, Files Modified, New Dependencies, Remaining
Tasks, Technical Debt, Recommended Next Session, Future Ideas.

**Why:** he understands systems far faster visually, and this is a reliability-critical appliance
where a skipped foundation surfaces as a failure on stage rather than a compile error. He asks
to be told when he's jumping ahead of a soft dependency.

**How to apply:** ASCII tree diagrams over prose whenever structure is involved. Never write into
a file without first showing where it sits in the layer stack. Full rules in the repo's
`CLAUDE.md`. See [[ablepad-project-state]].
