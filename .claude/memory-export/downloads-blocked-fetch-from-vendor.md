---
name: downloads-blocked-fetch-from-vendor
description: "Claude Code cannot read ~/Downloads on this Mac (macOS TCC) — fetch datasheets from the vendor's CDN instead of asking Matt to move files"
metadata: 
  node_type: memory
  type: reference
  originSessionId: f9ffc384-1dc9-4600-984a-d311be787bc2
  modified: 2026-08-09T05:25:23.615Z
---

`/Users/matt/Downloads` returns `EPERM` / "Operation not permitted" for both Bash and the file
reader. This is **macOS TCC (Full Disk Access)**, not the Claude Code sandbox — running with the
sandbox disabled fails identically. Do not burn turns retrying it.

**The working move: fetch the document from the manufacturer's own CDN and commit it into the
repo.** Done twice now, both first-try:

- Launchpad X Programmer's Reference —
  `https://fael-downloads-prod.focusrite.com/customer/prod/s3fs-public/downloads/Launchpad%20X%20-%20Programmers%20Reference%20Manual.pdf`
- Audient EVO 8 Manual V1.0 —
  `https://d9w4fhj63j193.cloudfront.net/EVO/EVO%208/Drivers/EVO%208%20Manual%20V1.0.pdf`

Both landed in `docs/datasheets/` with a sha256 recorded in the matching reference doc. That is
better than reading his local copy anyway: the repo ends up carrying its own citable source.

For PDF text: this Mac has no `pdftotext`/`poppler`/`mutool`, and `pip install` is PEP-668
blocked. Make a venv in the scratchpad and `pip install pypdf` — a page-image PDF still will not
extract (the Launchpad palette and grid pages are images), and that limitation belongs in the
doc as `UNVERIFIED`.

**Why:** the repo's rule is that every hardware constant carries a citation or is marked
UNVERIFIED, so the source PDF needs to be in the repo regardless of whether a local copy exists.

**How to apply:** when Matt says "refer to the doc in my downloads", search for the vendor's
official PDF URL and pull it in, then tell him that is what happened. Only ask him to move the
file if the vendor copy cannot be found. See [[ablepad-project-state]].
