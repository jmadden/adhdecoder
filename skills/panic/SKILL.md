---
name: panic
description: >
  Regulate a spiral, not aggregate a report. Use when the user says things like
  "panic", "SOS", "I'm freaking out", "I'm spiraling", "what's on fire", "I
  don't know where to start", or "I'm overwhelmed". Reads the ledger and
  reconciles only the few items it surfaces (never the whole ledger), and
  writes no promise data itself: shows the most time-sensitive item(s) first, a
  drift check, the one item likely being avoided, and one small next move.
  Ephemeral, renders in chat only. This is ADHDecoder's panic button.
---

# Panic button (reactive)

Regulate, don't aggregate. The user is mid-spiral; the job is to shrink what
they're looking at, not list everything at once. Read `reference/method.md`
("Panic button", "Drift", "The ADHD design principles") and
`reference/ledger-schema.md` before running.

## What this does / does not do

- **First run.** If ADHDecoder isn't set up (no config / no enabled source),
  offer `setup` instead of returning an empty board. See
  `reference/onboarding.md`.
- **Reads the ledger; reconciles only what it surfaces.** Same load path as
  `chase-in`, recomputing `overdue` and `stakes` at read time. It does not
  sweep sources, but before showing an item it cross-checks that handful via
  the `reconcile` skill (the top time-sensitive items + the one being avoided) -
  never the whole ledger, to stay fast. Honors reconcile's TTL cache and reuses
  the drift check's results.
- **Pure ephemeral.** Everything here renders in chat and nowhere else. Panic
  writes no promise data - not to `state.json`, `Radar.md`, or any dashboard
  file; its only `state.json` touch is reconcile's own verify-metadata
  bookkeeping during the pre-check, not a panic write.
- **Draft-only for user actions.** If the user wants to act mid-panic (mark
  something met/cleared, log a new promise, clear a drift flag), hand the write
  off to the `ledger` skill (or the `drift` skill for a drift clear). Panic
  itself logs nothing.
- **De-escalate.** No wall of red, no urgency-shaming. Short, calm, specific.

## What to show, in this order

1. **Most time-sensitive first.** Use the same "time-sensitive" set `chase-in`
   surfaces (overdue at any stakes; due-today at any stakes; due-soon only if
   high-stakes), ranked most-overdue-and-highest-stakes first, using source
   `weight` only to break ties between otherwise-equal items (stakes > time >
   weight - weight never buries urgency; see `reference/scheduling.md`). Show
   the **top 2-3**, not the full board - panic needs a short list, not a dump.
   Each shown item includes its `verifyStatus` and its clickable `source.url`
   (panic renders to the user in chat, an internal surface, so the real link and
   status tag are fine here).
2. **A drift check.** Invoke the `drift` skill's check and fold its output in
   as one or two short lines (e.g. "X hasn't visibly moved in N days"). If
   drift finds nothing, say so briefly and move on.
3. **"The one you're avoiding."** Approximate as the most time-sensitive
   **i-owe-them** item (something the user must DO - grunt work is what
   slips). Name it plainly. Note once, briefly, that this is an approximation
   until a real sweep can compare against visible activity.
4. **One small next move.** A single, concrete, tiny action tied to item #1 -
   not a plan. If it's a `they-owe-me` item, offer `chase-in`'s ready-to-send
   nudge for it. If it's `i-owe-them` and not ready to finish, offer a
   one-line holding status instead ("I'll have `<what>` to you by `<date>`")
   rather than the whole deliverable.

**Reconcile only what you show.** Cross-check just the items you are about to
surface (item 1's top few, and item 3's avoided item) via the `reconcile`
skill - never the whole ledger, so panic stays fast. An item whose
`verifyStatus` is `null` or past the TTL is reconciled before it can show -
never assert a stale item, even mid-panic. Skip anything reconcile returns
`resolved` / `reassigned` / `mis-attributed` and drop to the next candidate.
Reuse the drift check's reconcile results (item 2) so nothing is verified twice.
An `unverifiable` item may still show, marked "unconfirmed" (never asserted).

Keep the whole thing short enough to read in one breath. If there is
genuinely nothing time-sensitive open, say that plainly and stop - do not
manufacture urgency.

## Guardrails

- Never auto-send, never auto-post. Any nudge or holding status offered here
  is a draft to approve.
- Never auto-create a task or promise. Logging anything new still goes
  through the `ledger` skill's reality gate (owner + what + expectBy, or the
  user confirms).
- No flood. Top few items only, never the whole ledger - and reconcile only
  those 2-3 shown items, to keep panic fast.
- No hidden files. Panic writes no promise data; the reconcile pre-check's only
  `state.json` touch is reconcile's own verify-metadata bookkeeping.
