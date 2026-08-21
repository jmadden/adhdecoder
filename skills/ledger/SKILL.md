---
name: ledger
description: >
  Add a task, and read/write/query the ADHDecoder promise ledger. Use when the
  user says things like "add a task", "remind me to <do X>", "I need to <do X>",
  "put this on my list", "capture this", "add a task to <do X> by <date>" - each
  of which creates a real task note where they work - and also "what am I waiting
  on", "who owes me", "what do I owe", "add a promise", "log that <person> owes me
  <thing> by <date>", "I told <person> I'd deliver <thing> by <date>", "mark this
  met / done", "what's overdue", or "show my chases". Adding a task needs no due
  date and no counterparty: it is written immediately, not interrogated. Phase 1
  of ADHDecoder. It does not sweep sources and never sends anything.
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
1. Read the instance `config.json`. To find it, in this order: a path already
   in the session's own context (the user's `CLAUDE.md` may name their instance
   directory - check before asking); then a `_decoder/config.json` under their
   knowledge vault; then ask, once, and reuse the answer for the rest of the
   conversation. Do NOT say "its path is `instancePath`" and stop - that value
   lives inside the file being looked for, so it cannot help you find it.
   **First-run gate:** if `config.json`
   is absent or unparseable, do not invent paths - route to `setup`
   ("ADHDecoder isn't set up yet - want to run setup?"). Read-side skills inherit
   this through Query. See `reference/onboarding.md`.
2. State file = `<storage.instancePath>/<storage.overrides.stateFile>`
   (default `state.json`).
3. If it does not exist, create it from `config/state.example.json` shape.
4. Never use a hidden/dot-prefixed filename.

## Operations

`<plugin-root>` below is the directory holding this skill's own `skills/` parent
(in an installed instance, the version-keyed plugin cache directory; in a
checkout, the repo root). Resolve it from this file's path rather than hardcoding
either.

**Never hand-write `state.json` or a note.** Every operation below runs through
`scripts/ledger_write.py`, which enforces the reality gate and the schema, dedups
against the full union (notes included), keeps history append-only, writes
atomically with a backup, and refuses if another session wrote meanwhile.

**Add a task (the most common thing a user asks for).** "add a task", "remind me
to...", "I need to...", "put this on my list". On a note-backed backend this
creates a real note where they actually work, rather than a `state.json` record
they will never see:

```
python3 <plugin-root>/scripts/ledger_write.py --config <cfg> capture --confirmed \
    --title "<short headline>" [--customer "<context>"] [--requester "<who asked>"] \
    [--due YYYY-MM-DD] [--priority high|medium|low] [--summary "<one or two lines>"] \
    [--source-url <link>]
```

**Write it, then report one line.** Do not preview it, do not ask for approval,
do not ask about a deadline or who it is for. "On the fly" means one turn: the
title, where it landed, and - when there is no date - that drift will surface it.
Everything about the task is optional except the title, so infer what the user
already said and stop there. If they mention a date or a person, use it; if they
do not, that is the answer, not a gap to fill.

**No `--due` is required, and that is not a loophole.** The reality gate governs
`state.json` promises, which must be chaseable. A note legitimately has no due
date - most real ones do not - and drift staleness surfaces those instead. Never
manufacture a deadline to satisfy a gate that does not apply here.

`--title` is a headline: it becomes the filename and the promise id, so a
paragraph is refused (120 chars). Put the detail in `--summary`.

**If the title already exists**, capture refuses rather than overwriting - which
is correct, but say something useful: name the existing note, and offer either to
log an update against it (`enrich`) or to use a more specific title. Never
silently pick a variant title on the user's behalf.

`--dry-run` is a GLOBAL flag and belongs before the operation
(`--config <cfg> --dry-run capture ...`). A quick capture does not need it; it is
there for `promote`.

**Add a `state.json` promise.** For something that should NOT become a note -
typically a sweep-found `they-owe-me` stall - use `add` instead, which does
enforce the full reality gate (`direction` + concrete `what` + named `owner` +
`expectBy`; ask for whatever is missing, never invent it):

```
echo '<promise JSON>' | python3 <plugin-root>/scripts/ledger_write.py --config <cfg> add
```

**Promote a `state.json` promise into a note.** When a stranded promise should
live where the user works:

```
python3 <plugin-root>/scripts/ledger_write.py --config <cfg> promote --confirmed \
    --id <id> --title "<short headline>"
```

Always `--dry-run` first and show the note verbatim; the user approves before it
is created. The original record is kept, marked `promoted`, and given
`promotedTo`, so a later sweep enriches the note instead of resurrecting it.

**Track a larger project.** When the user says "start a new project", "track X
as a project" or "I've been assigned X", hand off to the `projects` skill - it
interviews them and previews what the project would claim before writing. Do not
declare one from here, and never infer a project from a customer.

**Update / log progress.** `ledger_write.py … enrich --id <id> --note "<what
changed>"` - history is append-only and the script enforces it.

**Mark met / cleared.** `enrich --id <id> --status met --note "…"` (delivered or
received) or `--status cleared` (handled outside the system). Never delete a
record. For a record ADHDecoder cannot write (a read-only note), park a
`draft-mark-met` instead, which the board renders in **Ready to close**.

**Set snooze.** Park a promise until a date (temporary per-item dismiss). The
record is **kept, never deleted** - this is distinct from `dismissedFromBoard`
(permanent).

```
ledger_write.py --config <cfg> snooze --id <id> --until YYYY-MM-DD --reason "<why>"
ledger_write.py --config <cfg> snooze --id <id> --unsnooze
```

`snooze` is the writer, **not `enrich`** - `enrich` never touches the field and
cannot reach a note-backed id at all. The op routes itself: builtin -> the record,
plus a history line; a read-only backend -> `itemMeta[<id>]`, never the note, in
either write mode. `--reason` is required, because on an overlay there is no
history and the reason is the only audit trail. The board lists everything snoozed
in a collapsed **Snoozed (N)** group, so a hold stays reviewable.

Do not confuse this with `project-set --snooze <project-id>`, which quiets a
project's rollup and deliberately leaves its members surfacing.

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
