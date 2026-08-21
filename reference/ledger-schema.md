# Ledger Schema (Phase 1)

The ledger is the promise store. It lives in the instance layer as a single
visible file: `<instancePath>/state.json`. No hidden files. Single writer.

The ledger owns only the **promise triple** (expect-by / who-owes / direction)
plus the minimum needed to track and dedup. Everything else it references via
`source`.

## Top-level shape

```json
{
  "schemaVersion": 2,
  "lastSwept": null,
  "promises": [],
  "dedup": { "seen": [] },
  "knownChannels": [],
  "watchedThreads": [],
  "dismissedFromBoard": [],
  "suppressed": [],
  "people": {},
  "sweepLog": [],
  "itemMeta": {}
}
```

- **schemaVersion** — integer, for future migrations. **3** is the current
  version: 2 named every field and deprecated the duplicates (see Migration), 3
  adds `projects`. Documentary: nothing branches on it yet, and no automated run
  may bump it. `validate-state.py` reports the declared version; changing it is a
  deliberate user action. A file still declaring 2 is served normally - `projects`
  is optional and no existing field moved, so the bump is a one-line no-op.
- **lastSwept** — ISO 8601 of the last successful sweep, or null.
- **promises** — the ledger proper (array of promise records below).
- **dedup.seen** — ids of items already decoded, so nothing is re-decoded.
- **knownChannels** — `{ id, name, customer }` for chat channels the sweep reads
  directly as a backstop. **Self-expanding:** add a channel the first time it
  produces a hit; never remove it. The safety net for "chat search returned
  empty but a real mention exists" (see `reference/parity-port.md`).
- **watchedThreads** — `{ channel, ts }` for threads the user has posted in
  (parent message ts). The sweep re-reads these each run and surfaces new
  replies since `lastSwept` even when they never re-mention the user
  (silent-reply tracking). Self-expanding, same discipline as `knownChannels`.
- **dismissedFromBoard** — ids the user killed off the board; never re-surface.
  Canonical form. An `itemMeta.<id>.dismissedFromBoard: true` means the same
  thing for one item; Query treats the two as a union (either one dismisses).
  A pending draft outranks a dismissal, so the board still renders a dismissed
  item in **Ready to close** (`reference/dashboard.md`) — dismissal means "stop
  showing me this as work", a draft is an unanswered question about the record.
- **suppressed** — `{ ref, reason, ts, recordId?, source?, context? }` for source
  refs the sweep must stop resurfacing at all (a dead lead, a self-created record,
  a wrong-attribution hit). `ref` and `reason` are always present; `ts` is set by
  the writer and absent only on hand-written legacy entries; `recordId` is the
  **source system's** record id, not a promise id. Distinct from
  `dismissedFromBoard`: that suppresses a **promise** on the board, this
  suppresses a **source ref** at sweep time, so no promise is created from it
  again.
  **Append-only, with exactly one exception:** `suppress --unsuppress` removes an
  entry, and nothing else in the system may shorten this list. `reason` is
  required, since an unexplained suppression is indistinguishable from a bug and a
  ref nothing can justify silencing becomes permanent by default;
  `validate-state.py` reports a reasonless entry as a gap, and any key outside the
  set above as a gap too — the container-only type check is what let an
  undeclared `ts` into a real ledger unnoticed.
  **The writer is `suppress`**, and until it existed there was none: the field was
  documented, schema-declared and doctor-validated with hand-editing `state.json`
  as the only route, the one write method this document names as the source of
  every stale entry in the wild. Unlike `snooze` it does **not** route through
  `_route()` — a suppression is about a source ref, not per-promise metadata, so it
  lives in one place whatever backend is active, and no note is written in any
  write mode.
  **The reader is `ledger_query.suppressed_source_refs()`**, surfaced as
  `suppressedRefs` by `scripts/sweep_plan.py` and counted in the board recap.
  Before that the list had no reader at all, so honouring it depended on a model
  remembering the field existed. Reasons are surfaced by `doctor`.
  **`add` enforces it**, which is what makes a suppression structural rather than
  advisory: `add` is the only way a promise is born, so a suppressed `source.ref`
  cannot be resurrected by any sweep, skill or unattended run regardless of what
  it read. Matching is **exact on `source.ref`**, case-folded and trimmed - never
  a substring, never a scan of `source.url` for an id it contains. The refusal
  names the ref, its reason and `--unsuppress`, so an over-broad suppression fails
  loudly instead of quietly hiding a real ask. `capture` is deliberately not
  gated: it runs with the user present asking for that task by name, and refusing
  an explicit human ask answers the wrong question.
  Note the word is overloaded: `promise["_suppressed"]`, the emitted
  `derived.suppressed`, and `--select suppressed` all mean the derived **board**
  term ("do not render this card now"), which is a different concept at a
  different layer.
- **people** — `{ "<name>": { pronouns, note, recordedAt } }`. Facts about a
  person that ADHDecoder would otherwise get wrong, most importantly
  **pronouns**. **Any skill writing copy that refers to a person MUST read this
  first** (`chase-in` nudges, `radiate-out` status, `set-the-clock` prompts, the
  board's action lines) and must never infer pronouns from a name; where they
  are unrecorded, use they/them. This map exists because a run wrote the wrong
  pronoun for a real person and the user had to correct it; a stored correction
  that nothing reads gets the same thing wrong again next run.
- **sweepLog** — `{ ts, sources: { "<type>(<provider>)": "<result>" } }` per
  run, newest last. The record of which sources actually answered, so a source
  that has quietly returned nothing for days is visible rather than assumed
  healthy. Cap it (keep the last ~10 runs); it is a log, not a store. Surfaced
  by `doctor`.
- **projects** — array of project records: a multi-week effort the user
  **declared**, which then claims matching work as it arrives.
  `{ id, name, status, note, keywords, aliases, sources, include, exclude,
  targetDate, checkInEvery, lastCheckIn, snoozedUntil, updated }`. A project
  never owns or changes a promise, and its `targetDate` never becomes a second
  definition of `overdue`. **A customer is never inferred to be a project.**
  Membership, the three lag signals and their thresholds live in
  `reference/projects.md`, stated once.

  The rule fields (`keywords`/`sources`/`exclude`/`checkInEvery`/`lastCheckIn`)
  were added inside schemaVersion 3 rather than bumping to 4: no file in
  existence had a `projects` array, so nothing was ever written against the
  narrower vocabulary, and `validate_project()` refuses unknown fields so an
  older plugin reports rather than misreads.
- **itemMeta** — `{ "<id>": { snoozedUntil, snoozeReason, deadlineType,
  deadlineTypeReason, verifyStatus, verifyReason, lastVerified, source, noteOnly,
  dismissedFromBoard, frontmatterWarning, markMetDraft, updateDraft,
  appliedMarkMet } }`. Overlay
  store for items whose canonical record is
  read-only (a read-only backend), incl. a reconcile-enriched `source` (and
  `noteOnly` cleared) for such a note. Builtin promises keep these on the
  record; the companion is never written into a note. The Query overlays it at
  read time.

### Pending-decision fields (`itemMeta`)

A read-only backend cannot apply a decision to the record, so the decision is
parked here until the user acts. **A parked draft is not a closed item.** These
fields are written by `reconcile` and read by the board; both sides are
required, or drafts accumulate invisibly and the board keeps showing finished
work as open.

- **markMetDraft** — `{ status, completedDate, reason }`. Set when `reconcile`
  returns `resolved` for an item whose record still reads open. It means "the
  source says this is done; the record has not caught up." The board MUST
  surface it in the **Ready to close** group (`reference/dashboard.md`), never
  as an ordinary open item. Cleared when applied or dismissed.
- **updateDraft** — `{ <changed fields>, reason, bodyLine }`. A proposed
  record edit (priority/status/date correction) awaiting approval. Same
  surfacing rule: visible, never silently held.
- **appliedMarkMet** — `{ ts, completedDate, reason, by?, backup? }`. Written when
  a draft is actually applied to the record (readwrite only,
  `reference/cutover.md`). Replaces `markMetDraft`; keep it as the audit trail of
  who closed what and why. **by** is who applied it (the deprecated `closedBy`
  lands here), so the audit trail is one object rather than two fields that can
  disagree.

### Other overlay fields (`itemMeta`)

- **deadlineTypeReason** — why `deadlineType` was overridden (e.g. "the note's
  `due` was the original working-session date, not a live commitment"). Required
  whenever a run overrides `deadlineType`, because an unexplained override looks
  like the system losing a deadline. The board renders it on the card for any
  item whose date is soft.
- **snoozeReason** — why a promise was parked, in the user's words ("on hold
  pending the de-dup check"). Required by the `snooze` op, never optional, for
  the same reason `reason` is required on `suppressed[]`: an unexplained hold is
  indistinguishable from a bug three weeks later. On a record it accompanies a
  history line; on an overlay entry there is no history, so this **is** the audit
  trail. The board renders it on the Snoozed group's line for the item.
- **frontmatterWarning** — a lint on a record that **parsed**: a non-canonical
  value, a duplicate key. Surfaced in the board note beside parse failures.
  Distinct from a parse *failure*, which makes a record invisible.

  **One rule: it is computed live on every read, and never stored.**
  `live_frontmatter_warnings()` in `scripts/ledger_query.py` re-derives it from
  the note in front of it, so fixing the note clears the warning on the next
  read with no reconcile pass and no write. Adding a check there is the only way
  to add a lint. A stored `itemMeta.frontmatterWarning` is **deprecated** and
  ignored on read; `doctor` reports any left in a live state file.

  Storing one was tried twice and failed twice. First ungated, where it simply
  outlived the note it described: a run recorded "priority: normal is not
  canonical," the user fixed the note days later, and the warning kept showing
  because nothing re-checked it — the write-once-stale bug `parseError` was
  deprecated for. Then gated on "is the note's `dateModified` newer than this
  finding?", which failed because the finding had no timestamp of its own and
  borrowed `lastVerified`. Any unrelated verify write bumps that, so a verify 16
  seconds after a note was **fixed** re-validated a days-old warning and the
  board asserted a contradiction the user could see with their own eyes.

  The deeper reason it cannot work: a stored lint is a claim about content that
  has since changed, with no way to re-check it. A timestamp says when the claim
  was made, never whether it still holds. And in practice nothing in the
  codebase ever wrote the field — every instance in the wild was hand-written by
  a session, which is why no writer needed removing, only the reader. If a lint
  is worth showing, it is worth being checkable; make it a live check.
- **dismissedFromBoard** — per-item form of the top-level list; see above.

Invariant: **no overlay field is write-only.** If a run can write a field here,
a surface must render it, in the same change that introduces it. This started as
a rule about drafts and was broadened in schemaVersion 2, because the failure
mode never depended on the field being a draft: a run recorded a malformed note
in `itemMeta` and nothing ever surfaced it, so the damaged file was found weeks
later only by parsing the vault by hand. A field nothing reads is not a record,
it is a place where a correction goes to die.

## Promise record

```json
{
  "id": "ISSUE-123:login-redirect",
  "title": "Login redirect fix",
  "context": "Acme Corp",
  "direction": "they-owe-me",
  "what": "Eng confirms the staging login redirect returns 404 vs 403",
  "owner": "A. Contact (Acme)",
  "expectBy": "2026-07-28",
  "status": "pending",
  "stakes": "high",
  "stakesOverride": null,
  "source": { "type": "issues", "ref": "ISSUE-123", "url": "https://..." },
  "noteRef": null,
  "noteOnly": false,
  "created": "2026-07-24T11:05:00-07:00",
  "lastVerified": "2026-07-24T11:05:00-07:00",
  "verifyStatus": null,
  "verifyReason": null,
  "why": null,
  "deadlineType": "hard",
  "snoozedUntil": null,
  "driftClearedUntil": null,
  "history": [
    { "ts": "2026-07-24T11:05:00-07:00", "note": "Promise captured." }
  ]
}
```

### Field rules

- **id** — stable and unique. Convention: `<source-ref>:<slug>`.
- **direction** — `they-owe-me` or `i-owe-them`. Routes the action.
- **what** — one concrete deliverable. Not "an update."
- **owner** — a named person/party who owes it. Required to be chaseable.
- **expectBy** — `YYYY-MM-DD`. Required to be chaseable.
- **status** — `pending` | `met` | `overdue` | `cleared` | `promoted`.
  - `overdue` is derived (expectBy < today, not met, AND `deadlineType` is
    `hard`); persist it on write. `soft`/`none` items are never overdue.
  - `cleared` = user dismissed/handled outside the system.
  - `promoted` = collapsed into a record the active backend now owns (see
    `reference/promotion.md`); keep the record, set **promotedTo** = the new
    record's id, and stop serving it from Query as open.
- **promotedTo** — optional; the id of the record this promise was promoted
  into. Sweeps match on it to enrich the promoted record instead of
  resurrecting this one.
- **stakes** — `high` | `normal`, auto-computed (see method.md). Recompute each
  read; do not hand-edit.
- **stakesOverride** — `high` | `low` | null. User escape hatch. Wins over auto.
- **source** — `{ type, ref, url }`, the best ACTIONABLE source: prefer the
  underlying ticket / chat permalink / email over a note link. Link, never
  paste raw content.
- **noteRef** — optional `{ url }` to the backing note (e.g. a file or app URL
  link), so the record is one click away. Distinct from `source`; null when
  there is no backing note.
- **noteOnly** — bool (default false). True when no actionable source was found
  and `source` is itself the note link.
- **lastVerified** — ISO 8601, when a source last confirmed this promise.
- **verifyStatus** — `verified-open` | `resolved` | `reassigned` |
  `mis-attributed` | `unverifiable` | `null` (not yet reconciled). Set only by
  the `reconcile` skill; doubles as the TTL cache paired with `lastVerified`.
  Never hand-edited.
- **verifyReason** — short plain-language reason from the last reconcile, or
  `null`.
- **why** — string or null. What the promise unblocks / why it matters. Feeds
  stakes (a `why` naming a go-live or dated dependency -> high) and nudge copy.
- **deadlineType** — `hard` (default) | `soft` | `none`. `overdue` is derived
  ONLY when `hard`. `soft`/`none` are ongoing: never overdue, surface via drift
  staleness only.
- **snoozedUntil** — ISO date or null. Temporary per-item dismiss; the record is
  kept, never deleted. Distinct from `dismissedFromBoard` (permanent). While in
  the future, consumers do not surface the item as a chase, but the board still
  lists it under **Snoozed** — a hold nothing displays is an invisible
  off-switch, not a record.
  **The writer is `snooze`, not `enrich`.** `enrich` never touches the field, and
  cannot reach a note-backed id at all (it walks `state.json` promises only), so
  `snooze` routes through `_route()`: a builtin promise snoozes on the record with
  a history line, a note-backed one in the `itemMeta` companion, and no note is
  written in either write mode. `project-set --snooze` is a different thing
  entirely: it quiets a project's rollup and deliberately leaves its members
  surfacing (`reference/projects.md`).
- **driftClearedUntil** — ISO 8601 cooldown after a "handled offline" clear.
- **note** — string or null. The **latest-state** summary in plain language: what
  is currently true about this promise ("X emailed on the 5th still waiting on Y,
  and asked to cancel today's meeting"). Overwritten as reality changes, while
  every transition also appends to `history`. The two are not duplicates:
  `history` is the append-only ledger of what happened, `note` is the current
  situation, and it is the richest per-promise context in the store. The board
  renders it in the card body.
- **completedDate** — `YYYY-MM-DD` or null. When the promise actually closed, as
  distinct from when a run noticed. Drives the Shipped / Done-today grouping and
  the History date.
- **relatedRefs** — optional array of other source refs bearing on this promise
  (a sibling ticket, a superseding issue). Links only; never a second promise.
  Rendered on the card beside the source link, so a superseding ticket is one
  click away rather than buried in the record.
- **history** — append-only log of `{ ts, note }`. Never rewrite prior entries.

## Deprecated fields (schemaVersion 2)

Each of these was invented by a run, duplicates a field that already existed, and
must not be written again. **Read them where they still exist** (an old file is
not wrong, it is old); write only the replacement.

| Deprecated | Level | Replacement | Why |
|---|---|---|---|
| `createdAt` | promise | `created` | Same fact, two spellings. |
| `counterparty` | promise | `owner` (+ `note` for the nuance) | Held prose like "Nobody, the assignee is still null", which is situational context, not a party. |
| `resolvedNotDropped` | itemMeta | `markMetDraft` | An earlier ad-hoc version of Ready-to-close, superseded once the draft fields were specced. |
| `closedBy` | itemMeta | `appliedMarkMet.by` | Audit info belongs with the rest of the apply record, not beside it. |
| `recommendation` | itemMeta | `updateDraft` | A proposed record change with no apply path. `updateDraft` is that concept, with a surface. |
| `parseError` | itemMeta | nothing; detect live | A stored parse failure goes stale the moment the file is fixed, and one sat unread while the damaged note stayed invisible. Parse failures are recomputed on every read and surfaced by the renderer and `doctor`. |

### Migration

There is no automated migration and no run may perform one. `state.json` is the
user's data and the repo's rule is validate-never-repair, so:

1. `scripts/validate-state.py` (via `doctor`) reports what a file declares and
   what it contains: unknown keys as gaps, deprecated keys as notes naming the
   replacement.
2. The user applies the rename or removal by hand, or asks for a one-off pass.
3. `schemaVersion` is bumped by that deliberate act, never as a side effect.

A file still declaring `schemaVersion: 1` is served normally. The version records
which vocabulary the file was written against; it does not gate reads.

## Reality gate (never create phantom chases)

A promise may be added to the ledger ONLY when it has all three: **owner**,
concrete **what**, and an **expectBy**. If any is missing, do not log it; prompt
the user to supply it (or leave it as a note elsewhere). This is what keeps
ADHDecoder from resurrecting vague "go find out X" chasing.

## Write discipline

- Preserve everything. Append to `history`; never delete records (set `status`).
- Atomic write: write a temp file, then replace, to avoid corrupting state on a
  crash mid-write.
- Visible file only. Never a dot-prefixed name.
