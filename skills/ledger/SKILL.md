---
name: ledger
description: >
  Read, write, and query the ADHDecoder promise ledger (state.json in the
  instance layer). Use when the user says things like "what am I waiting on",
  "who owes me", "what do I owe", "add a promise", "log that <person> owes me
  <thing> by <date>", "I told <person> I'd deliver <thing> by <date>", "mark
  this met / done", "what's overdue", or "show my chases". This is Phase 1 of
  ADHDecoder: the promise store only. It does not sweep sources or send anything.
---

# Ledger (Phase 1)

Manage the promise ledger. Read `reference/ledger-schema.md` for the exact
record shape before writing.

## Locate state

0. **Select backend.** Read `config.ledger.backend` (default `builtin`). If
   `builtin`, use `state.json` as below. Any other value `X` resolves to the
   adapter skill `ledger-X` (per `reference/ledger-backend-interface.md`). If no
   `ledger-<X>` skill matches the configured value, it may be a **deprecated
   alias** an adapter still accepts - route to the adapter that declares it and
   surface its one-line rename note. An adapter's capability (writable vs
   read-only) comes from `config.ledger.writeMode` per
   `reference/ledger-backend-interface.md`: read/Query are served by the
   adapter either way; writes go to the adapter only when it is writable,
   otherwise they stay on the builtin `state.json` companion and become drafts.
1. Read the instance `config.json` (its path is the configured `instancePath`,
   or ask the user once and remember it). **First-run gate:** if `config.json`
   is absent or unparseable, do not invent paths - route to `setup`
   ("ADHDecoder isn't set up yet - want to run setup?"). Read-side skills inherit
   this through Query. See `reference/onboarding.md`.
2. State file = `<storage.instancePath>/<storage.overrides.stateFile>`
   (default `state.json`).
3. If it does not exist, create it from `config/state.example.json` shape.
4. Never use a hidden/dot-prefixed filename.

## Operations

**Add a promise.** Enforce the reality gate: require `direction`, a concrete
`what`, a named `owner`, and an `expectBy` date. If any is missing, ask for it;
do not invent it and do not log a partial promise. Build the record per the
schema, set `status: pending`, stamp `created`/`lastVerified`, seed `history`
with one "Promise captured." line, then write.

**Update / log progress.** Append a `{ ts, note }` to `history`. Refresh
`lastVerified`. Never rewrite prior history.

**Mark met / cleared.** Set `status: met` (delivered/received) or `cleared`
(handled outside the system). Add a history line. Never delete the record.

**Set snooze.** Set `snoozedUntil` to a date (temporary per-item dismiss). The
record is **kept, never deleted** - this is distinct from `dismissedFromBoard`
(permanent). Append a history line. Builtin -> write it on the record; a read-only backend
-> write it to `itemMeta[<id>]`, never the note. "Unsnooze" clears it the same
way.

**Mark ongoing (set deadlineType).** Set `deadlineType` to `soft`/`none` (ongoing,
no date-chasing) or back to `hard`. Builtin -> on the record; a read-only backend ->
`itemMeta[<id>]` override, never the note.

**Flip direction on delivery (builtin).** When the user has delivered the thing
(see `reconcile` delivery detection), turn an `i-owe-them` promise into the
they-owe follow-up: set `direction: they-owe-me`, `owner` = the recipients,
`what` = "confirm/complete <the action>", `expectBy` = a confirm-by date, `why` =
what it unblocks; append a history line ("delivered; now awaiting confirmation").
Reality gate still applies. For a **read-only-backend** promise, never rewrite the source record -
`reconcile` proposes a note-update draft and registers a new they-owe follow-up
via **Add a promise** instead.

**Record reconcile result.** Called by the `reconcile` skill after it
cross-checks a promise's live source. Set `verifyStatus`, `verifyReason`, and
refresh `lastVerified` to now; and when reconcile located a better live source
link, upgrade `source` to it and clear `noteOnly`. Builtin -> write these on the
record, append one `history` line with the reason, and if `verifyStatus` is
`resolved` also set `status: met` (bookkeeping, not a customer-facing action -
the same spirit as `sweep`'s silent enrich). read-only-backend -> write the
verify metadata AND the upgraded `source` to `itemMeta[<id>]` (never the note),
and surface `resolved` as a "looks done, close it?" draft rather than
auto-marking met.

**Query.** **Do not re-derive the read.** `scripts/ledger_query.py` is the one
implementation, for every backend:

```
python3 <plugin-root>/scripts/ledger_query.py --config <instance config.json> \
    --select open --json
```

It resolves the backend, reads the promise set (for a read-only note-backed
backend, the union of its open records with the builtin `state.json`, deduped
one-way by source link), overlays `itemMeta[<id>]` (`snoozedUntil`,
`deadlineType` + reason, verify metadata, drafts, a reconcile-enriched
`source`/`noteOnly`, `frontmatterWarning`), and recomputes derived state:
`overdue` (expectBy < today, not met, AND `deadlineType` is `hard` - `soft`/`none`
are never overdue), `stakes`, business-day staleness, snooze, dismissal, and
ready-to-close. Each record carries that under `derived`, so a consumer reads it
rather than recomputing it.

Selectors: `all` `open` `closed` `ready-to-close` `slipping` `drifting`
`waiting` `owed` `upcoming` `snoozed`, plus `--context` and `--direction`
filters. Every response also carries `parseFailures`, `frontmatterWarnings`,
`collapsed` and `lastSwept`, which a surface must relay rather than drop.

The script is read-only and has no write path at all. Writes stay with the
operations above.

**Why this is code and not prose:** a second derivation of "overdue" is a second
answer, and the two disagree exactly where it hurts - an overridden deadline
chased as if it were hard, a snoozed item resurfacing, a dismissed item whose
draft should have revived it. One definition means the board and every chase
agree about the same ledger.

Then present, grouped and sorted (this part is yours):

- **They owe me** and **I owe them**, as two sections.
- Within each: overdue first (most overdue on top), then due-soon, then the rest.
- High-stakes items flagged.
- Keep it scannable. For each: `what`, `owner`, `expectBy`, a source link.

## Rules

- **Data, not tasks.** A promise is a lightweight record. Never auto-create a
  a source record or any task from it. Promotion stays a separate, deliberate act.
- **Reference, do not duplicate.** Link to the source; never paste raw content.
- **Preserve everything.** Append-only history; status changes instead of
  deletes.
- **Atomic write.** Write temp, then replace, so a crash cannot corrupt state.
- **Single writer.** Assume one machine writes state; do not design for
  concurrent sweeps.
- **Stakes are computed**, never hand-edited. Honor `stakesOverride` if set.
- **Backend-aware, single write path.** Reads honor `config.ledger.backend`;
  writes honor the backend's **capability** (from `config.ledger.writeMode`,
  see `reference/ledger-backend-interface.md`). Read-only backend: mark-met /
  update / flip / note-edit actions produce drafts for the user to apply, never
  record writes; ADHDecoder-owned overlay metadata (`snoozedUntil`,
  `deadlineType` override, verify metadata) goes to the `itemMeta` companion in
  `state.json`, never the record. Writable external backend (post-cutover):
  those same actions write the underlying record via the adapter, but ONLY on
  an explicit user action in the conversation - non-interactive runs still
  write only `state.json` and the board. Overlay metadata stays in `itemMeta`
  either way.
- **Promote (deliberate).** "Make this a real task" on a `state.json` promise
  -> follow `reference/promotion.md`: draft the record, get approval, create it
  via the writable backend's `promote()` (or hand the user the draft when
  read-only), then collapse the `state.json` record to a cross-reference. Never
  from a sweep.
