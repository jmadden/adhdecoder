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
   surface its one-line rename note. If a read-only backend adapter is configured, read/Query are served by that adapter; writes stay on the builtin `state.json`
   companion in v1.
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

**Query.** If a read-only backend adapter is active, obtain the promise set from that adapter (the union of its open records + builtin
`state.json`), then apply the grouping/sorting/recompute below unchanged.
Otherwise read `state.json`. For read-only-backend promises, overlay
`itemMeta[<id>]` (`snoozedUntil`, `deadlineType`, verify metadata, and a
reconcile-enriched `source`/`noteOnly`) onto the record at read time. Recompute
`overdue` (expectBy < today, not met, AND
`deadlineType` is `hard` - `soft`/`none` are never overdue) and `stakes` at read
time. Expose `snoozedUntil` on each promise so consumers can skip snoozed items.
Then present, grouped and sorted:

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
- **Backend-aware, single write path.** Reads honor `config.ledger.backend`. In
  v1 a read-only backend does not write its underlying records: mark-met / update
  / flip / note-edit actions produce drafts for the user to apply, never vault
  writes. ADHDecoder-owned overlay metadata for a read-only note (`snoozedUntil`,
  `deadlineType` override, verify metadata) is written to the `itemMeta`
  companion in `state.json`, never into the note. Builtin `state.json` stays the
  only store ADHDecoder writes.
