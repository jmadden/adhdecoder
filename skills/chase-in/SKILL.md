---
name: chase-in
description: >
  Surface the promises that are slipping and hand back a ready-to-send nudge for
  each, tiered by stakes. Use when the user says things like "who do I need to
  chase", "what's slipping", "what should I follow up on", "run my chases",
  "chase in", "who's overdue and what do I say", "draft a nudge for <person>", or
  "what's falling through the cracks". Reads the ledger only (recomputes overdue
  from expectBy vs today); never sweeps Jira/Slack/email and never sends. This is
  Phase 3 of ADHDecoder.
---

# Chase in (Phase 3)

Turn the promise ledger into a short, tiered board of what is slipping, each item
carrying one ready-to-send nudge. Read `reference/method.md` ("Chase in",
"Stakes", "The ADHD design principles") and `reference/ledger-schema.md` before
running.

Core principle: **a promise changes state, it never repeats.** Surface each
slipping promise once, at its current escalation rung. Aging overdue items get
more prominent, never more numerous (No flood).

## What this does / does not do

- **Reads the ledger, plus a reconcile pre-check.** Locate and load promises
  exactly as the `ledger` skill's Query does, recomputing `overdue` and
  `stakes` at read time. Do not sweep sources. Before drafting a nudge, cross-
  check the item via the `reconcile` skill (see Reconcile pre-check below) -
  that is chase-in's only source contact; it never queries Jira/Slack/email/
  CRM directly itself.
- **Drafts, never sends.** Every nudge is a draft the user approves and sends.
- **Does not write.** Chase-in only reads. When the user acts on a nudge ("sent
  it", "mark met", "handled offline"), hand the status change or history line to
  the `ledger` skill. Never touch `state.json` here.

Consume ledger state cleanly: a future sweep may refresh the ledger without
changing anything in this skill.

## State progression (derived each run from expectBy vs today)

| State | Condition |
|-------|-----------|
| due-soon | expectBy within the next ~2 days, not yet due |
| due-today | expectBy is today |
| overdue | expectBy is before today |
| aging | overdue by ~3+ days; louder again at ~7+ |

These are display states derived from dates, not persisted. The ledger's `status`
(pending/met/overdue/cleared) is the source of truth for whether a promise is
still open; skip anything `met` or `cleared`.

## Tiering by stakes (who surfaces, when)

Compute `stakes` per `method.md` (honor `stakesOverride`).

- **High-stakes:** proactive. Surface from **due-soon** onward, escalating through
  due-today, overdue, aging.
- **Normal-stakes:** quiet until **overdue.** Do not surface due-soon or due-today
  normal items; they join the board only once past due, then get louder as they
  age.

Never surface `met` or `cleared` promises, or ids in `dismissedFromBoard`.

## Escalation ladder (tone by rung, from method.md)

Pick the rung from how far past due and the stakes, not from a repeat count:

| Rung | When | Tone |
|------|------|------|
| 1 - friendly check-in | first surfacing (high-stakes due-soon/due-today; normal freshly overdue) | light, assume good faith |
| 2 - firmer + restate impact | overdue several days, or high-stakes already overdue | firmer, name what it blocks |
| 3 - loop in a manager | aging / well overdue on a high-stakes item | propose escalating; name who to add |

One promise sits at exactly one rung per run. Moving up a rung is a state change,
not a new item.

## Reconcile pre-check (before drafting a nudge)

Before drafting a nudge for a candidate item (after tiering/escalation
above), call the `reconcile` skill. This is chase-in's only source
cross-check - it never queries Jira/Slack/email/CRM directly; `reconcile`
owns that, per source category, and caches results (~1/day TTL) so this stays
cheap.

- **`verified-open`** -> proceed to Draft the nudge below, as normal.
- **`resolved`** -> drop from the board; it is done. For a `state.json`-backed
  promise `reconcile` auto-marks it met. For a TaskNotes-derived promise,
  surface its "looks done, close it?" draft instead of a nudge.
- **`reassigned`** -> drop from the board with a brief note ("reassigned to
  `<new owner>`, removed from your list").
- **`mis-attributed`** -> withhold the nudge; flag instead: "this names
  `<person>`, who isn't on `<context>` - confirm."
- **`unverifiable`** -> do not draft a confident nudge; surface "can't verify
  - confirm manually" instead.

Only reconcile the items about to appear on the board (the top few after
tiering), never the whole ledger - reconciliation is cost-bounded to what's
actually about to be chased.

## Draft the nudge (route by direction)

Each slipping promise carries **one** small, specific, ready-to-send draft:

- **they-owe-me** -> nudge **them**. Address the `owner`. Restate the ask, name the
  one `what` outstanding, and re-set the clock: "Can you get me `<what>` by
  `<date>`?" Raise the tone by rung; at rung 3, propose looping in a named manager.
- **i-owe-them** -> nudge **the user** to do the one thing, AND if it will slip,
  draft a **holding status** to the counterparty so nobody is left chasing: "I'll
  have `<what>` to you by `<new date>`." Never invent the new date; ask the user.

Keep each draft to one deliverable and one ask (One move). Never auto-send.

## The board (output)

Present a scannable board, not a feed:

1. **One move first:** the single most urgent item and its one next action, up top.
2. Two sections: **They owe me** and **I owe them.**
3. Within each: aging first, then overdue, then due-today, then due-soon.
   High-stakes flagged.
4. Per item, one line of facts: `what` - `owner` - `expectBy` (+ days over/until) -
   state - source link, then its drafted nudge.

Eat the grunt: the user's only job is to read the top item, approve a draft, and
send.

## Guardrails

- **Never auto-send, never auto-post.** Drafts only.
- **No flood.** Each promise appears once, at its current rung; aging gets more
  prominent, never duplicated. Respect `dismissedFromBoard`.
- **Read-only.** No writes here; status/history changes go through the `ledger`
  skill.
- **No direct source access.** Overdue is dates only; any source cross-check
  goes through the `reconcile` skill, never queried directly here. No hidden
  files.
- **Advisor by default.** Help set the date and word the nudge; never invent a
  commitment for the user.
