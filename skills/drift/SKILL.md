---
name: drift
description: >
  Flag promises that look stalled, observationally, never accusingly. Use
  when the user asks "what's drifting", "what's stalled", "what have I not
  touched", or "check for drift", and internally whenever `panic` runs its
  drift check, or as a quiet passive flag on a sweep. Detects staleness from
  the ledger (days since lastVerified + overdue/due-soon-high-stakes for dated
  promises, plus a business-day fallback for OPEN promises with no expectBy,
  common on real note-backed data), then reconciles each surfaced candidate
  against its live source so it never flags a resolved, reassigned, or
  mis-tagged item. Offers a one-tap "handled offline" clear. Never writes
  directly; the clear routes through the `ledger` skill, the source cross-check
  through `reconcile`.
---

# Drift

Notice what has gone quiet, without shaming anyone for it. Read
`reference/method.md` ("Drift", "The ADHD design principles") and
`reference/ledger-schema.md` (`lastVerified`, `driftClearedUntil`) before
running. "Boring beats shiny" is the failure mode this exists to catch: things
slip from inattention, not forgetting.

## What this does / does not do

- **First run.** If ADHDecoder isn't set up (no config / no enabled source),
  offer `setup` instead of returning an empty board. See
  `reference/onboarding.md`.
- **Detects from the ledger, then reconciles what it surfaces.** Staleness is
  computed from ledger dates - an **approximation** of activity (how long since
  the record was last confirmed, not a live activity feed). Before surfacing any
  candidate, cross-check it via the `reconcile` skill, bounded to the candidates
  (never the whole ledger), so a resolved/reassigned/mis-tagged item never
  appears. Deep activity-based drift (comparing to everything the user actually
  touched) remains a later capability.
- **Fires only on time-sensitive items** - overdue (any stakes) or due-soon at
  high stakes. Never flag something with slack unless it is already
  time-sensitive.
- **Respects cooldown.** Skip any promise whose `driftClearedUntil` is still
  in the future.
- **Respects dismissals and snoozes.** Never resurface an id in
  `dismissedFromBoard` (permanent) or one whose `snoozedUntil` is still in the
  future (temporary), regardless of which path below flagged it.
- **Owns ongoing items.** `soft`/`none` (no-hard-deadline) items never date-chase
  in `chase-in`; drift is where they surface if they go quiet - the existing
  staleness paths below already cover them, no threshold change.
- **Never writes.** The "handled offline" clear and its optional note are
  handed to the `ledger` skill; this skill only computes and displays.
- **Observational tone only.** "Hasn't visibly moved in N days" - never
  "you're behind" or similar.

## Two ways this runs

- **Inside `panic`:** called for its drift-check section; keep output to one
  or two lines. Reconcile results are shared with panic within the run, so an
  item is never verified twice.
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
3. `driftClearedUntil` is null or in the past (not in cooldown), the id is not
   in `dismissedFromBoard`, and `snoozedUntil` is null or in the past.
4. Days since `lastVerified` is 3 or more - nothing has touched or confirmed
   it in that window while it is due or overdue.

Present as: `<what>` (`<owner>`) hasn't visibly moved in `<N>` days -
`<verifyStatus>` - `<source.url>` (a "(note)" hint if `noteOnly`; for a
note-backed item, add the note's current status + latest update line).

### No-due staleness fallback (any backend)

Date-based chasing misses anything with no `expectBy` - and on real data a
large share of open items (many `blocked` or high-priority) carry no due date
at all: the silent-rot zone. For an **open** promise with no `expectBy`, use
**staleness** instead of overdue-ness:

1. `status` is `pending`, and `expectBy` is absent.
2. `driftClearedUntil` is null or in the past, the id is not in
   `dismissedFromBoard`, and `snoozedUntil` is null or in the past.
3. Compute days since `lastVerified` in **business days** (exclude weekends;
   a backend adapter supplies `lastVerified` - e.g. the note-backed adapter uses
   `dateModified` - this skill does the business-day math).
4. Surface when the Query says so. The thresholds live in
   `scripts/ledger_query.py` (`STALE_DAYS_HIGH` / `STALE_DAYS_ANY`), currently 2
   business days for a `blocked` or high-stakes item and 5 for any other open
   one, and `--select drifting` applies them. Do not restate the numbers here:
   this file and the adapter reference disagreed for weeks (15 versus 5) with
   nothing to catch it, which is what the single implementation is for.

Present as: `<what>` (`<owner>`) hasn't moved in `<N>` business days -
`<verifyStatus>` - `<source.url>` (a "(note)" hint if `noteOnly`; for a
note-backed item, add the note's current status + latest update line). Same
observational tone, never "you're behind" or similar - the absence of a date
is not the user's fault, it just means date-based checks can't see it, so this
fallback exists specifically to make it visible.

This fallback is generic across backends, not backend-specific: any backend
that supplies `lastVerified` gets it for free.

## Reconcile pre-check (before surfacing)

Once the candidates are computed (either path above), reconcile **only those
candidates** via the `reconcile` skill before showing anything - never the
whole ledger. Honor reconcile's TTL cache (an item verified within ~1 day
reuses its cached result; a result already produced earlier this run - e.g. by
a `panic` that also calls drift - is reused, not re-fetched).

**Verified before surfaced (hard bar).** A candidate whose `verifyStatus` is
`null` or whose `lastVerified` is past the TTL must be reconciled before it can
appear - a drift flag is a claim about reality and must rest on a fresh verdict.
Show the `verifyStatus` inline on the flag (below); anything `unverifiable` shows
under "confirm," never as a settled drift fact. See
`reference/verification-discipline.md`.

- **`verified-open`** -> surface as a drift flag, as computed.
- **`resolved`** -> drop it; it is done, not drifting. For a `state.json`
  promise `reconcile` marks it met; for a read-only backend it surfaces a "looks done,
  close it?" draft.
- **`reassigned`** -> drop it; it left the user's plate.
- **`mis-attributed`** -> do not present as a plain drift item; surface it
  clearly marked **"confirm"** with the reconcile `reason` ("names `<person>`,
  not on `<context>`").
- **`unverifiable`** -> surface clearly marked **"confirm"** with the reason
  ("can't verify - confirm manually"), never as a settled drift fact.

So the drift list is: verified-open items shown normally, plus any
mis-attributed / unverifiable ones clearly set apart under "confirm."

## The "handled offline" clear

Offer a one-tap clear per flagged item: "Handled offline?" with an optional,
skippable note ("what happened, if you want to note it").

If the user taps it: hand off to the `ledger` skill to set
`driftClearedUntil` **5 days out** from today and, if a note was given,
append it to `history`. Do not clear anything without the user's tap - never
auto-clear a flag.

## Getting the candidate set

**Do not re-derive staleness.** Ask the Query:

```
python3 <plugin-root>/scripts/ledger_query.py --config <instance config.json> \
    --select drifting --json
```

`drifting` is business-day staleness on open items with no date (the silent-rot
zone date-chasing misses: >= 2 business days when blocked or high-stakes, >= 5
for anything else), plus high-stakes items already overdue or due soon. It
honours `driftClearedUntil`, snooze and dismissal, and excludes ready-to-close.
`derived.staleDays` is the business-day count to quote.

**Yours is the judgment:** which of these is worth surfacing, and the
observational framing ("hasn't moved in N business days", never an accusation).
Reconcile each candidate before surfacing it, per the guardrails below.

## Guardrails

- Never auto-clear, never auto-send, never auto-post.
- No flood. Dedup against already-cleared/cooldown items; cap the standalone
  list to a scannable handful even if more qualify. When ordering/capping, rank
  stakes > staleness > source `weight` (weight is only a tiebreak between
  otherwise-equal items; see `reference/scheduling.md`).
- No hidden files. This skill writes nothing; all writes route through the
  `ledger` skill.
- Source cross-check runs through `reconcile` (read-only against sources and
  read-only backends); drift writes nothing itself, and any verify-metadata refresh is
  reconcile's own `state.json` bookkeeping.
- Advisor by default: report what looks stalled, let the user say what
  actually happened.
