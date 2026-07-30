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

Turn the current ledger into the multi-tab HTML dashboard on demand. Read
`reference/dashboard.md` (the full render procedure) and
`reference/ledger-schema.md` (the promise shape) before running. The styled,
data-free shell ships at `assets/dashboard-template.html`; this skill fills it
from the user's ledger and writes the result to `config.schedule.boardPath`.

## What this does / does not do

- **Renders a view.** Reads the ledger via the `ledger` Query, groups promises
  into the five tabs, fills the template placeholders, emits each card with its
  `verifyStatus` chip + real source link + record link, and writes the HTML board.
  Full procedure and tab mapping live in `reference/dashboard.md`.
- **Freshness-aware** (verification-discipline Rule 3). Check `lastSwept` first.
  If it is stale (past the sweep cadence / noticeably old), **run a sweep first**,
  then render and **lead with what changed** since the last sweep. If the ledger
  is already fresh, render directly from current state.
- **Verifies before showing** (Rule 1). Any card whose `verifyStatus` is `null`
  or TTL-stale is reconciled before it is rendered; `unverifiable` shows as
  "confirm," never as an asserted action.
- **Does not** invent grouping logic (it reuses `reference/dashboard.md`), and
  does not send, post, or auto-create anything.

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
