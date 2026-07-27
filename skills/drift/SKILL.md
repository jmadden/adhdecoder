---
name: drift
description: >
  Flag promises that look stalled, observationally, never accusingly. Use
  when the user asks "what's drifting", "what's stalled", "what have I not
  touched", or "check for drift", and internally whenever `panic` runs its
  drift check, or as a quiet passive flag on a sweep. Derives drift from the
  ledger only: days since lastVerified + overdue/due-soon-high-stakes for
  dated promises, plus a business-day staleness fallback for OPEN promises
  with no expectBy (common on real TaskNotes data), since no activity-source
  data exists yet. Offers a one-tap "handled offline" clear. Never writes
  directly; hands the clear to the `ledger` skill.
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
- **Respects dismissals.** Never resurface an id in `dismissedFromBoard`,
  regardless of which path below flagged it.
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

A promise is **drifting** via either path below (whichever applies; a promise
with an `expectBy` uses the dated path, one without uses the no-due fallback -
never both, never double-counted).

### Dated path

All of:

1. `status` is `pending` (skip `met` / `cleared`).
2. It is time-sensitive: `overdue` is true, OR (`due-soon` and `stakes` is
   `high`).
3. `driftClearedUntil` is null or in the past (not in cooldown), and the id is
   not in `dismissedFromBoard`.
4. Days since `lastVerified` is 3 or more - nothing has touched or confirmed
   it in that window while it is due or overdue.

Present as: `<what>` (`<owner>`) hasn't visibly moved in `<N>` days.

### No-due staleness fallback (any backend)

Date-based chasing misses anything with no `expectBy` - and on real data a
large share of open items (many `blocked` or high-priority) carry no due date
at all: the silent-rot zone. For an **open** promise with no `expectBy`, use
**staleness** instead of overdue-ness:

1. `status` is `pending`, and `expectBy` is absent.
2. `driftClearedUntil` is null or in the past, and the id is not in
   `dismissedFromBoard`.
3. Compute days since `lastVerified` in **business days** (exclude weekends;
   a backend adapter supplies `lastVerified` - e.g. the TaskNotes adapter uses
   `dateModified` - this skill does the business-day math).
4. Surface when: (`status` is `blocked` OR `stakes` is `high`) AND business
   days >= ~2, **or** any open item AND business days >= ~5.

Present as: `<what>` (`<owner>`) hasn't moved in `<N>` business days. Same
observational tone, never "you're behind" or similar - the absence of a date
is not the user's fault, it just means date-based checks can't see it, so this
fallback exists specifically to make it visible.

This fallback is generic across backends, not TaskNotes-specific: any backend
that supplies `lastVerified` gets it for free.

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
