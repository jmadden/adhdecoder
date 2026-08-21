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

- **First run.** If ADHDecoder isn't set up (no config / no enabled source),
  offer `setup` instead of returning an empty board. See
  `reference/onboarding.md`.
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

**Only `deadlineType: hard` items get these date-driven states.** `soft`/`none`
(ongoing) items never become due-soon/overdue here - a placeholder date must not
manufacture a chase. They surface via `drift` staleness instead, not this board.
Also skip any item whose `snoozedUntil` is in the future (temporary dismiss, kept
not deleted - distinct from `dismissedFromBoard`).

## Tiering by stakes (who surfaces, when)

Compute `stakes` per `method.md` (honor `stakesOverride`).

- **High-stakes:** proactive. Surface from **due-soon** onward, escalating through
  due-today, overdue, aging.
- **Normal-stakes:** quiet until **overdue.** Do not surface due-soon or due-today
  normal items; they join the board only once past due, then get louder as they
  age.

Never surface `met` or `cleared` promises, promises the Query marks
`derived.dismissed` (never the raw `dismissedFromBoard` list, which is only one of
its two storage forms), items
snoozed into the future (`snoozedUntil`), or `soft`/`none` ongoing items (those
belong to `drift`).

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

**Verified before surfaced (hard bar).** A candidate whose `verifyStatus` is
`null` (never reconciled) or whose `lastVerified` is past the TTL must be
reconciled before it can appear - never chase off a stale or unverified record.
If it comes back `unverifiable`, it surfaces marked **"unverified, confirm"**
with the reason, never as a confident nudge. See
`reference/verification-discipline.md`.

- **`verified-open`** -> proceed to Draft the nudge below, as normal.
- **`resolved`** -> never nudge; it is done. For a `state.json`-backed promise
  `reconcile` auto-marks it met and it leaves the board. For a promise whose
  record it cannot write, `reconcile` parks a `markMetDraft` in `itemMeta` and
  the item moves to the board's **Ready to close** group - it does NOT silently
  vanish and it does NOT stay in "your move". Dropping it from chase-in without
  surfacing the draft is how finished work goes on looking outstanding. See
  `reference/dashboard.md` and `reference/ledger-schema.md`.
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

**Nudge judgment** (see `reference/parity-port.md`):

- **Internal teammate vs counterparty.** A nudge to an internal teammate is a
  collaborative sanity-check ("does that sound right?"), not a deadline-y chase;
  keep the firm, dated tone for the external counterparty who owes the thing.
- **Don't chase the wrong side.** Distinguish the internal team from the
  counterparty; the reality gate (named owner + concrete ask + date) decides who
  is actually chaseable.
- **Route technical work to its owner.** For real technical build work, address
  the owner and include a worked example / concrete artifact; never make the
  user guess technical details to fill in.

When a promise carries a `why`, use it in the nudge to make the stakes concrete
("...so we can `<why>`").

**Handoff follow-ups.** A handed-off action is a `they-owe-me` promise the user
drives to confirmation (`owner` = counterparty, `what` = "confirm/complete X",
`why` = what it unblocks); it surfaces via the they-owe path above. For each,
also offer **"no follow-up needed this time"** -> hand off to the `ledger`
skill's **Set snooze** (`snooze --id <id> --until <date> --reason "<why>"`, record
kept, never deleted), which drops it off the chase until the snooze date. Ask for
the reason rather than inventing one: it is required, and on a note-backed record
it is the only audit trail. The item stays visible in the board's **Snoozed**
group. See `reference/handoff-followups.md`.

## The board (output)

Present a scannable board, not a feed:

1. **One move first:** the single most urgent item and its one next action, up top.
2. Two sections: **They owe me** and **I owe them.**
3. Within each: high-stakes first, then by time (aging, overdue, due-today,
   due-soon). Source `weight` breaks ties **only** between otherwise-equal
   items - ranking is stakes > time > weight, so a low-weight source's genuine
   emergency still surfaces at the top (see `reference/scheduling.md`).
4. Per item, one line of facts: `what` - `owner` - `expectBy` (+ days over/until) -
   state - its `verifyStatus` (a short tag, e.g. `✓ verified-open`, or the
   `verifyReason` when it adds signal) - a clickable `source.url` (the actionable
   source; if `noteOnly`, the note link with a small "(note)" hint), optionally
   `noteRef` too. For a note-backed item, add the note's current status + latest
   update line. Then its drafted nudge. An item marked "unverified, confirm"
   shows the confirm prompt in place of a confident nudge.

Eat the grunt: the user's only job is to read the top item, approve a draft, and
send.

## Getting the promise set

**Do not re-derive what is slipping.** Ask the Query:

```
python3 <plugin-root>/scripts/ledger_query.py --config <instance config.json> \
    --select slipping --json
```

`slipping` is items with a real hard date that has passed or lands today, with
snoozed / dismissed / ready-to-close items already excluded. Soft and dateless
items are deliberately NOT here: chasing a soft date as though it were a missed
commitment aims a false nudge at a real person. Those reach the user through
`drift` instead (`--select drifting`).

Each record carries its recomputed state under `derived` (`overdue`, `staleDays`,
`flagged`, `pronouns`). Read it; do not recompute it, or your list and the board
will disagree about the same ledger.

**Yours is the judgment:** tiering by stakes, what the nudge says, and the tone.
Relay `parseFailures` and `frontmatterWarnings` from the response rather than
dropping them.

## Naming a person

Before writing any copy that refers to a person, read `state.json`'s **`people`**
map (`reference/ledger-schema.md`) and use the pronouns recorded there. Where a
person has none recorded, use they/them; never infer pronouns from a name. If the
user corrects a pronoun, record it in `people` so the next run does not repeat the
error, and say that you have.

This map exists because a run wrote the wrong pronoun for a real person. A stored
correction that nothing reads gets the same thing wrong again.

## Guardrails

- **Never auto-send, never auto-post.** Drafts only.
- **No flood.** Each promise appears once, at its current rung; aging gets more
  prominent, never duplicated. Respect a dismissal (permanent) and
  `snoozedUntil` (temporary); never date-chase `soft`/`none` ongoing items.
- **Read-only.** No writes here; status/history changes go through the `ledger`
  skill.
- **No direct source access.** Overdue is dates only; any source cross-check
  goes through the `reconcile` skill, never queried directly here. No hidden
  files.
- **Advisor by default.** Help set the date and word the nudge; never invent a
  commitment for the user.
