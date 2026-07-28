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
4. **Refresh the board file** at `config.schedule.boardPath` (see below).
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

Write a refreshed, read-only board to `config.schedule.boardPath` (overwrite in
place; a visible file, e.g. Markdown). Scheduled runs are non-interactive, so
this is the durable place the user looks between runs. Contents, rebuilt from
the ledger each run:

- the **chase-in** board (slipping promises, tiered),
- **drift** flags (stalled / no-due),
- **handoff follow-ups** the user is driving,

each line linking to its `source.url`. This is an INTERNAL board, so source
links belong here - the radiate-out no-internal-links rule is customer-facing
only and does not apply. If `boardPath` is unset, skip the file and only print
to chat.

The board is a generated VIEW, never a second store: link, never paste raw
feeds.

## Guardrails

- Only `state.json` and the board file are written. Read-only against read-only backends
  and every source (enrichment lands in `state.json` / `itemMeta`).
- Never auto-send / auto-post / auto-create tasks elsewhere.
- Weight is secondary to urgency (stakes > time > weight); every enabled source
  is swept at least once per day - no source is ignored.
- No hidden files. The board file is visible.
