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
  "dismissedFromBoard": []
}
```

- **schemaVersion** — integer, for future migrations.
- **lastSwept** — ISO 8601 of the last successful sweep, or null.
- **promises** — the ledger proper (array of promise records below).
- **dedup.seen** — ids of items already decoded, so nothing is re-decoded.
- **knownChannels** — `{ id, name, customer }` for chat channels to back-stop.
- **dismissedFromBoard** — ids the user killed off the board; never re-surface.

## Promise record

```json
{
  "id": "ISSUE-123:login-redirect-url",
  "title": "Login redirect URL fix",
  "context": "Acme Corp",
  "direction": "they-owe-me",
  "what": "Eng confirms UAT login redirect returns 404 vs 403",
  "owner": "A. Contact (Acme)",
  "expectBy": "2026-07-28",
  "status": "pending",
  "stakes": "high",
  "stakesOverride": null,
  "source": { "type": "issues", "ref": "ISSUE-123", "url": "https://..." },
  "created": "2026-07-24T11:05:00-07:00",
  "lastVerified": "2026-07-24T11:05:00-07:00",
  "verifyStatus": null,
  "verifyReason": null,
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
- **status** — `pending` | `met` | `overdue` | `cleared`.
  - `overdue` is derived (expectBy < today and not met); persist it on write.
  - `cleared` = user dismissed/handled outside the system.
- **stakes** — `high` | `normal`, auto-computed (see method.md). Recompute each
  read; do not hand-edit.
- **stakesOverride** — `high` | `low` | null. User escape hatch. Wins over auto.
- **source** — `{ type, ref, url }`. Link, never paste raw content.
- **lastVerified** — ISO 8601, when a source last confirmed this promise.
- **verifyStatus** — `verified-open` | `resolved` | `reassigned` |
  `mis-attributed` | `unverifiable` | `null` (not yet reconciled). Set only by
  the `reconcile` skill; doubles as the TTL cache paired with `lastVerified`.
  Never hand-edited.
- **verifyReason** — short plain-language reason from the last reconcile, or
  `null`.
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
