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
   `builtin`, use `state.json` as below. If `tasknotes`, read/Query are served
   by the read-only `ledger-tasknotes` adapter (`skills/ledger-tasknotes`, spec
   in `reference/adapter-tasknotes.md`); writes stay on the builtin `state.json`
   companion in v1.
1. Read the instance `config.json` (its path is the configured `instancePath`,
   or ask the user once and remember it).
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

**Record reconcile result (state.json backend only).** Called by the
`reconcile` skill after it cross-checks a promise's live source. Set
`verifyStatus`, `verifyReason`, and refresh `lastVerified` to now; append one
`history` line with the reason. If `verifyStatus` is `resolved`, also set
`status: met` (bookkeeping, not a customer-facing action - the same spirit as
`sweep`'s silent enrich). Never call this for a TaskNotes-derived promise -
that backend stays read-only; `reconcile` surfaces a draft instead.

**Query.** If the active backend is `tasknotes`, obtain the promise set from
the `ledger-tasknotes` adapter (the union of open TaskNotes + builtin
`state.json`), then apply the grouping/sorting/recompute below unchanged.
Otherwise read `state.json`. Recompute `overdue` (expectBy < today, not met)
and `stakes` at read time. Then present, grouped and sorted:

- **They owe me** and **I owe them**, as two sections.
- Within each: overdue first (most overdue on top), then due-soon, then the rest.
- High-stakes items flagged.
- Keep it scannable. For each: `what`, `owner`, `expectBy`, a source link.

## Rules

- **Data, not tasks.** A promise is a lightweight record. Never auto-create a
  TaskNote or any task from it. Promotion stays a separate, deliberate act.
- **Reference, do not duplicate.** Link to the source; never paste raw content.
- **Preserve everything.** Append-only history; status changes instead of
  deletes.
- **Atomic write.** Write temp, then replace, so a crash cannot corrupt state.
- **Single writer.** Assume one machine writes state; do not design for
  concurrent sweeps.
- **Stakes are computed**, never hand-edited. Honor `stakesOverride` if set.
- **Backend-aware, single write path.** Reads honor `config.ledger.backend`. In
  v1 the `tasknotes` backend is read-only: mark-met / update / add actions
  produce drafts for the user to apply, never vault writes. Builtin
  `state.json` stays the only store ADHDecoder writes.
