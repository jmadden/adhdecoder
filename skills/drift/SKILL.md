---
name: drift
description: >
  Flag promises that look stalled, observationally, never accusingly. Use
  when the user asks "what's drifting", "what's stalled", "what have I not
  touched", or "check for drift", and internally whenever `panic` runs its
  drift check, or as a quiet passive flag on a sweep. Derives drift from the
  ledger only (days since lastVerified + overdue/due-soon-high-stakes, since
  no activity-source data exists yet) and offers a one-tap "handled offline"
  clear. Never writes directly; hands the clear to the `ledger` skill.
---

# Drift

Notice what has gone quiet, without shaming anyone for it. Read
`reference/method.md` ("Drift", "The ADHD design principles") and
`reference/ledger-schema.md` (`lastVerified`, `driftClearedUntil`) before
running. "Boring beats shiny" is the failure mode this exists to catch: things
slip from inattention, not forgetting.

## What this does / does not do

- **Reads the ledger only.** No activity data from sources exists yet (no
  sweep), so drift here is an **approximation**: staleness by date, not by
  what the user has actually touched. Say so if asked; true activity-based
  drift is a later capability.
- **Fires only on time-sensitive items** - overdue (any stakes) or due-soon at
  high stakes. Never flag something with slack unless it is already
  time-sensitive.
- **Respects cooldown.** Skip any promise whose `driftClearedUntil` is still
  in the future.
- **Never writes.** The "handled offline" clear and its optional note are
  handed to the `ledger` skill; this skill only computes and displays.
- **Observational tone only.** "Hasn't visibly moved in N days" - never
  "you're behind" or similar.

## Two ways this runs

- **Inside `panic`:** called for its drift-check section; keep output to one
  or two lines.
- **Standalone / passive:** run directly ("what's drifting"), or as a quiet
  flag each sweep once sweeping exists. Standalone can show the full flagged
  list (still capped, still deduped - see Guardrails).

## Computing the flag

A promise is **drifting** when all of:

1. `status` is `pending` (skip `met` / `cleared`).
2. It is time-sensitive: `overdue` is true, OR (`due-soon` and `stakes` is
   `high`).
3. `driftClearedUntil` is null or in the past (not in cooldown).
4. Days since `lastVerified` is 3 or more - nothing has touched or confirmed
   it in that window while it is due or overdue.

Present each as: `<what>` (`<owner>`) hasn't visibly moved in `<N>` days. -
plus the offer below.

## The "handled offline" clear

Offer a one-tap clear per flagged item: "Handled offline?" with an optional,
skippable note ("what happened, if you want to note it").

If the user taps it: hand off to the `ledger` skill to set
`driftClearedUntil` **5 days out** from today and, if a note was given,
append it to `history`. Do not clear anything without the user's tap - never
auto-clear a flag.

## Guardrails

- Never auto-clear, never auto-send, never auto-post.
- No flood. Dedup against already-cleared/cooldown items; cap the standalone
  list to a scannable handful even if more qualify.
- No hidden files. This skill writes nothing; all writes route through the
  `ledger` skill.
- Advisor by default: report what looks stalled, let the user say what
  actually happened.
