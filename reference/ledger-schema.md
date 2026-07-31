# Ledger Schema (Phase 1)

The ledger is the promise store. It lives in the instance layer as a single
visible file: `<instancePath>/state.json`. No hidden files. Single writer.

The ledger owns only the **promise triple** (expect-by / who-owes / direction)
plus the minimum needed to track and dedup. Everything else it references via
`source`.

## Top-level shape

```json
{
  "schemaVersion": 1,
  "lastSwept": null,
  "promises": [],
  "dedup": { "seen": [] },
  "knownChannels": [],
  "watchedThreads": [],
  "dismissedFromBoard": [],
  "itemMeta": {}
}
```

- **schemaVersion** — integer, for future migrations.
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
- **itemMeta** — `{ "<id>": { snoozedUntil, deadlineType, verifyStatus,
  verifyReason, lastVerified, source, noteOnly } }`. Overlay store for items
  whose canonical record is read-only (a read-only backend), incl. a
  reconcile-enriched `source` (and `noteOnly` cleared) for such a note. Builtin
  promises keep these on the record; the companion is never written into a
  note. The Query overlays it at read time.

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
  the future, consumers do not surface the item as a chase.
- **driftClearedUntil** — ISO 8601 cooldown after a "handled offline" clear.
- **history** — append-only log of `{ ts, note }`. Never rewrite prior entries.

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
