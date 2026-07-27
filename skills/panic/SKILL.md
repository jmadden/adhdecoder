---
name: panic
description: >
  Regulate a spiral, not aggregate a report. Use when the user says things like
  "panic", "SOS", "I'm freaking out", "I'm spiraling", "what's on fire", "I
  don't know where to start", or "I'm overwhelmed". Reads the ledger only
  (same time-sensitive definition as chase-in) and never writes: shows the
  most time-sensitive item(s) first, a drift check, the one item likely being
  avoided, and one small next move. Ephemeral, renders in chat only, never
  saved to state.json or the knowledge base. This is ADHDecoder's panic
  button.
---

# Panic button (reactive)

Regulate, don't aggregate. The user is mid-spiral; the job is to shrink what
they're looking at, not list everything at once. Read `reference/method.md`
("Panic button", "Drift", "The ADHD design principles") and
`reference/ledger-schema.md` before running.

## What this does / does not do

- **Reads the ledger only.** Same load path as `chase-in`: locate `state.json`
  via `config.json` -> `instancePath`, recompute `overdue` and `stakes` at read
  time. No source sweeping, no connectors.
- **Pure ephemeral.** Everything here renders in chat and nowhere else. Never
  write to `state.json`, `Radar.md`, or any dashboard file.
- **Read-only, always.** If the user wants to act mid-panic (mark something
  met/cleared, log a new promise, clear a drift flag), hand the write off to
  the `ledger` skill (or the `drift` skill for a drift clear). Never write
  here.
- **De-escalate.** No wall of red, no urgency-shaming. Short, calm, specific.

## What to show, in this order

1. **Most time-sensitive first.** Use the same "time-sensitive" set `chase-in`
   surfaces (overdue at any stakes; due-today at any stakes; due-soon only if
   high-stakes), ranked most-overdue-and-highest-stakes first. Show the **top
   2-3**, not the full board - panic needs a short list, not a dump.
2. **A drift check.** Invoke the `drift` skill's ledger-only check and fold its
   output in as one or two short lines (e.g. "X hasn't visibly moved in N
   days"). If drift finds nothing, say so briefly and move on.
3. **"The one you're avoiding."** Approximate as the most time-sensitive
   **i-owe-them** item (something the user must DO - grunt work is what
   slips). Name it plainly. Note once, briefly, that this is an approximation
   until a real sweep can compare against visible activity.
4. **One small next move.** A single, concrete, tiny action tied to item #1 -
   not a plan. If it's a `they-owe-me` item, offer `chase-in`'s ready-to-send
   nudge for it. If it's `i-owe-them` and not ready to finish, offer a
   one-line holding status instead ("I'll have `<what>` to you by `<date>`")
   rather than the whole deliverable.

Keep the whole thing short enough to read in one breath. If there is
genuinely nothing time-sensitive open, say that plainly and stop - do not
manufacture urgency.

## Guardrails

- Never auto-send, never auto-post. Any nudge or holding status offered here
  is a draft to approve.
- Never auto-create a task or promise. Logging anything new still goes
  through the `ledger` skill's reality gate (owner + what + expectBy, or the
  user confirms).
- No flood. Top few items only, never the whole ledger.
- No hidden files. Nothing is written by this skill, ever.
