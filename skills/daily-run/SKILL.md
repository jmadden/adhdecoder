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
4. **Refresh the board file** at `config.schedule.boardPath` by running
   `scripts/render-board.py` (see below); the script implements
   `reference/dashboard.md`.
5. **Recap**: one line - ledger freshness (how long since `lastSwept`, now
   refreshed), what changed, what is newly slipping, and any project the
   renderer reported as lagging (it prints `project lagging: <name> (<reason>)`;
   relay it, do not recompute it). Print to chat.

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

**Call the renderer; do not hand-render.** After step 3's reconcile pass has put
current verdicts in the ledger:

```
python3 <plugin-root>/scripts/render-board.py --config <instance config.json>
```

`<plugin-root>` is the directory holding this skill's own `skills/` parent, resolved
from this file's path (the version-keyed plugin cache dir in an installed instance).

That is the shared implementation of `reference/dashboard.md` - the same script
the on-demand `board` skill calls. It is deterministic and offline (it never
reaches a source and never reconciles), writes only `config.schedule.boardPath`,
and prints a one-line recap of group counts plus any unparseable notes. Fold that
recap into step 5's line, parse failures **and the `snoozed N` and `suppressed N`
counts** included. A scheduled run is where a growing pile of holds gets noticed:
if any snooze has passed its return date, say so by name rather than letting the
count absorb it. `suppressed N` is a different thing wearing the same word - source
refs the sweep must never raise, not cards being hidden - so relay the count and
leave the reasons to `doctor`.

It writes to `config.schedule.boardPath`, overwriting in place; a visible file.
Scheduled runs are non-interactive, so this is the durable place the user looks
between runs. Each run rebuilds the whole board from the ledger into the six tabs
(Board / Shipped / Waiting on Others / Tomorrow's Headlines / Projects /
History), so
chase-in slips, drift flags, and handoff follow-ups all land on it, each card
carrying its `verifyStatus` chip + `source.url` + record link.

This is an INTERNAL board, so source links belong here - the radiate-out
no-internal-links rule is customer-facing only and does not apply. If `boardPath`
is unset, skip the file and only print to chat.

The board is a generated VIEW, never a second store: regenerated from the ledger
each run (no hand-maintained board state); link, never paste raw feeds.

## Guardrails

- Only `state.json` and the board file are written. Read-only against read-only
  backends and every source (enrichment lands in `state.json` / `itemMeta`).
- **Never `capture` or `promote`.** Both create notes and require `--confirmed`,
  an explicit human action. A scheduled run creates no notes in any write mode.
- Never auto-send / auto-post / auto-create tasks elsewhere.
- Weight is secondary to urgency (stakes > time > weight); every enabled source
  is swept at least once per day - no source is ignored.
- No hidden files. The board file is visible.
