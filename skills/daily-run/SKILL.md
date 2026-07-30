---
name: daily-run
description: >
  The scheduled run routine: sweep configured sources by weight and cadence,
  reconcile about-to-surface items, update the ledger, refresh a read-only
  board file, and print a one-line recap. Use when the user or the host
  scheduler says "run the decoder", "daily run", "do a scheduled run",
  "refresh the board", or is wiring a scheduled/cron task to invoke
  ADHDecoder. Non-interactive-safe: writes only state.json + the board file,
  never auto-sends or auto-posts.
---

# Daily run (scheduled routine)

Orchestrates the existing skills into one non-interactive pass so ADHDecoder
runs without the user remembering to invoke it. Read `reference/scheduling.md`
(weight / cadence + the board), `reference/sweep.md`, and
`reference/ledger-schema.md` first. Invoked by the host scheduler at the
configured `pivots` (see README) or by the user on demand.

## What a run does (in order)

0. **First-run check (non-interactive).** If config is absent or thin (no
   enabled source, or missing backend + identity), do NOT prompt (a scheduled
   run cannot) - print a clear "ADHDecoder isn't set up; run `setup`" recap and
   exit cleanly. Never hang waiting for input, never sweep an empty config, never
   emit an empty board. See `reference/onboarding.md`.
1. **Sweep**, ordered by source `weight` (high first, deepest coverage),
   honoring `cadence` for this run: always include `every-run` sources; include
   any source whose cadence is due (`hourly` / `daily`); and **guarantee every
   enabled source is swept at least once per calendar day** - if a `daily` /
   `low` source has not been swept today, sweep it now. None ignored. (See
   `sweep`.)
2. **Reconcile** the new / aging / about-to-surface items via `reconcile`
   (verify before flagging; honor the TTL cache).
3. **Update the ledger**: dedup, write/enrich promises + source links, per the
   `ledger` skill and the active backend. Read-only backends get
   overlay writes to the `state.json` `itemMeta` companion only, never the note.
4. **Refresh the board file** at `config.schedule.boardPath` - render the HTML
   dashboard from the ledger per `reference/dashboard.md` (see below).
5. **Recap**: one line - ledger freshness (how long since `lastSwept`, now
   refreshed), what changed, and what is newly slipping. Print to chat.

Never auto-send, never auto-post. A run drafts, updates the ledger, and
refreshes the board; nothing leaves for a customer.

## Session-start refresh (lead with changes)

On session start, or the first surfacing after a gap, check ledger freshness
before showing anything. If `lastSwept` is stale (past the sweep cadence /
noticeably old), **run the sweep first**, then lead with **"what changed since
the last sweep"** - so the user works from current reality, not memory. The
sweep is read-only against sources and writes only `state.json` + the board, so
this auto-refresh stays within the hard guardrails (no auto-send/post). If the
ledger is already fresh, skip the sweep and surface directly. See
`reference/verification-discipline.md` (Rule 3).

## The board file (read-only generated view)

Render the multi-tab HTML dashboard to `config.schedule.boardPath` per
`reference/dashboard.md` (the shared render procedure - same one the on-demand
`board` skill uses). Overwrite in place; a visible file. Scheduled runs are
non-interactive, so this is the durable place the user looks between runs. Each
run rebuilds the whole board from the ledger into the five tabs (Board / Shipped /
Waiting on Others / Tomorrow's Headlines / History), so chase-in slips, drift
flags, and handoff follow-ups all land on it, each card carrying its
`verifyStatus` chip + `source.url` + record link.

This is an INTERNAL board, so source links belong here - the radiate-out
no-internal-links rule is customer-facing only and does not apply. If `boardPath`
is unset, skip the file and only print to chat.

The board is a generated VIEW, never a second store: regenerated from the ledger
each run (no hand-maintained board state); link, never paste raw feeds.

## Guardrails

- Only `state.json` and the board file are written. Read-only against read-only backends
  and every source (enrichment lands in `state.json` / `itemMeta`).
- Never auto-send / auto-post / auto-create tasks elsewhere.
- Weight is secondary to urgency (stakes > time > weight); every enabled source
  is swept at least once per day - no source is ignored.
- No hidden files. The board file is visible.
