---
name: board
description: >
  Render the ADHDecoder dashboard: a multi-tab HTML board (Board / Shipped /
  Waiting on Others / Tomorrow's Headlines / History) built from the current
  ledger and written to config.schedule.boardPath. Use when the user says "show
  my board", "refresh the dashboard", "open the board", "render the dashboard",
  or "regenerate my board". It only renders a read-only view from the ledger; it
  never sweeps a new pass on its own beyond a freshness refresh, and never sends
  or posts anything.
---

# Board (on-demand dashboard render)

Turn the current ledger into the multi-tab HTML dashboard on demand.

**Do not re-improvise the render.** `scripts/render-board.py` implements it.
Reconcile first (below), then call the script:

```
python3 <plugin-root>/scripts/render-board.py --config <instance config.json>
```

`<plugin-root>` is the directory holding this skill's own `skills/` parent (in an
installed instance, the version-keyed plugin cache directory; in a checkout, the
repo root). Resolve it from this file's path rather than hardcoding either.

It reads the ledger (union of open notes + `state.json`, deduped), fills
`assets/dashboard-template.html`, and writes `config.schedule.boardPath`
atomically. Optional flags: `--out` to render elsewhere, `--now <ISO>` to pin the
clock, `--quiet` to suppress the stdout recap. It prints a one-line recap of the
group counts plus any parse failures; relay that, and offer the board path.

`reference/dashboard.md` stays the reference for **what the code does** (grouping,
colour groups, placeholders, card contents). Read it when changing behaviour, not
to hand-render a board.

**The split.** The script is deterministic and offline: same config + ledger +
clock in, byte-identical HTML out. It renders the verdicts already in the ledger
and **does not reconcile**, because reconcile needs live sources. Verification is
this skill's job, before the call.

## What this does / does not do

- **Renders a view**, by calling `scripts/render-board.py`. The script groups
  promises into the five tabs, fills the template placeholders, emits each card
  with its `verifyStatus` chip + real source link + record link, and writes the
  HTML board. Full procedure and tab mapping live in `reference/dashboard.md`.
- **Freshness-aware** (verification-discipline Rule 3). Check `lastSwept` first.
  If it is stale (past the sweep cadence / noticeably old), **run a sweep first**,
  then render and **lead with what changed** since the last sweep. If the ledger
  is already fresh, render directly from current state.
- **Verifies before showing** (Rule 1). Any card whose `verifyStatus` is `null`
  or TTL-stale is reconciled **before the script runs**, so the verdict is in the
  ledger by render time; `unverifiable` shows as "confirm," never as an asserted
  action. The script never reconciles on its own.
- **Does not** invent grouping logic or hand-write HTML, and does not send, post,
  or auto-create anything.

## Surface what the render reports

The recap's parse-failure lines and the `{{BOARD_NOTE}}` line are the only place a
malformed note or a parked draft becomes visible. Relay them; never drop them
because the board "rendered fine."

## First run

If config is absent or thin (no backend + identity), do not invent paths - route
to `setup` ("ADHDecoder isn't set up yet - want to run setup?"). See
`reference/onboarding.md`.

## If boardPath is unset

Skip the file and print the one-line board summary to chat instead (per
`reference/dashboard.md`).

## Guardrails

- Read-only against sources and notes. Only `state.json` (reconcile enrichment /
  `itemMeta`) and the board file are written.
- Never auto-send / auto-post / auto-create tasks. The board is a view.
- Regenerated from the ledger each render - never a hand-maintained second store.
- The board file is visible (no hidden/dot-prefixed name); it is an internal
  board, so source links belong on it.
