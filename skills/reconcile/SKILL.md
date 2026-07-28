---
name: reconcile
description: >
  Cross-check a promise against its live source of truth before it's chased or
  published, so stale or mis-tagged ledger records never drive an action. Use
  when the user says things like "verify this", "double-check X against
  Jira/Salesforce/Slack", "is this still open", "reconcile my chases", or
  "confirm before we publish" - and internally, whenever chase-in, drift, or
  panic is about to surface an item, radiate-out is about to draft a context
  status, the sweep verifies a candidate, or the user references a specific
  tracked item or context in conversation (verify before any status claim).
  Dispatches
  by promise.source.type to a per-source adapter (issues, crm, chat, email
  lighter; read-only-backend promises reconcile against their underlying
  source ref). Read-only against every source and against read-only backends; only the
  state.json backend gets verify-metadata writes. Never sends, never posts.
---

# Reconcile

Freshness is not verification. A ledger record - especially one read from the
read-only backend - can be stale or mis-tagged even when it was captured
correctly once. Before ADHDecoder chases a promise, publishes it, or surfaces
it with confidence, cross-check it against the **live source**. Read
`reference/reconciliation.md` (the full spec) and `reference/ledger-schema.md`
(`verifyStatus`, `verifyReason`, `lastVerified`) before running.

## The operation

`reconcile(promise) -> { status, reason, updates }`

- `status` is one of: `verified-open` | `resolved` | `reassigned` |
  `mis-attributed` | `unverifiable`.
- Dispatches by `promise.source.type` to the matching adapter below (same
  per-source-adapter pattern `sweep` uses to find candidates).
- Returns a short `reason` (one line, plain) and any `updates` the caller
  should apply (e.g. a new owner on `reassigned`).

## Reconcile on reference (reactive)

Reconcile fires not only before a chase, a publish, or a sweep, but **whenever
the user references a specific tracked item or context in conversation** and a
status claim is about to be made. "What's the status of X?" -> reconcile X (read
its live source - the full thread - and its note's current status) -> then
answer. Never answer about an item's status from memory or a search snippet.
This is still TTL-cached and read-only: a just-verified item reuses its cached
verdict. See `reference/verification-discipline.md`.

## TTL cache (cost-aware - do not skip)

Do not re-hit a source for every promise on every run. Before dispatching:

- If the promise already has a `verifyStatus` and `lastVerified` is **less
  than ~1 day old**, reuse the cached `verifyStatus`/`reason` - skip the
  adapter call entirely.
- Otherwise run the adapter and refresh.
- Within a single run, reuse a result already computed for an item this run
  rather than calling the adapter again (e.g. when `panic` surfaces an item the
  `drift` check already reconciled).

**Persistence is backend-scoped:** persist the refreshed `lastVerified` +
`verifyStatus` + `verifyReason` (and any upgraded `source`, see below) via the
`ledger` skill's **Record reconcile result** operation. For a
`state.json`-backed promise these live on the record; for a read-only-backend
promise they go to the `state.json` `itemMeta` companion keyed by the item id
(never the note). Either way the result is cached against the TTL above.

**Write the discovered source link back.** When an adapter locates or confirms
the live source (the ticket, the chat permalink, the sent email/thread, the CRM
record), return its canonical URL and write it onto the promise's `source`,
upgrading a note-only link and clearing `noteOnly`. Same persistence split:
builtin -> the record; a read-only backend -> `itemMeta[<id>].source` (never the note, so
read-only holds). This keeps the real link that reconcile found instead of
discarding it.

## Per-source adapters

- **`issues` (e.g. Jira):** fetch the issue. Done/closed -> `resolved`.
  Assignee moved off the user, and it is not the user's to own -> `reassigned`.
  Otherwise -> `verified-open`, refresh `lastVerified`. **Priority persistence:**
  a high-priority item is `resolved` only when actually closed or reassigned -
  never mark it resolved just because it has gone quiet (a quiet high-priority
  item is still open; see `reference/parity-port.md`).
- **`crm` (e.g. Salesforce):** the record's closed flag -> `resolved`. Owner/
  assignee changed -> `reassigned`. Otherwise -> `verified-open`. If the record
  links a tracker issue, it is the **same** work item - reconcile against that
  issue too and cross-reference both ids rather than treating them separately.
- **`chat` (e.g. Slack):** use `config.contacts` to find the right context's
  channel/thread. Open the FULL thread - never trust a mention/keyword search
  hit alone (a search can show a thread as unanswered when the user already
  replied or acted). Check clear signals only (defer deep NLP): the user
  replied/acted after the ask, or an explicit resolved/closed/done word ->
  `resolved`; someone else visibly took it over -> `reassigned`; a named person
  not on the context -> `mis-attributed`; otherwise -> `verified-open`.
- **`email`:** lighter touch - the thread's latest message and whether the
  user has replied. Replied -> lean `resolved`/`verified-open` per context;
  otherwise -> `verified-open`.
- **`calendar`:** the event still exists and is not cancelled -> `verified-open`;
  cancelled/past-and-done -> `resolved`. A pure RSVP change is not a resolution.
- **`docs`:** the page/comment still open and awaiting the user -> `verified-open`;
  the user (or someone) resolved the comment / addressed the edit -> `resolved`.
- **`calls`:** the action item still open -> `verified-open`; visibly done or
  owned by someone else -> `resolved`/`reassigned`. Auto-generated notes are
  **last-resort** corroboration (lossy owner labels) - do not resolve on notes
  alone; prefer the richer source.
- **read-only-backend promise:** its real source of truth is the underlying
  system referenced IN the note (a Jira key, a chat channel) - not the note
  itself. Extract that reference and dispatch to the matching adapter above.
  No linkable reference -> `unverifiable`.

## Research order (when an item spans sources)

When a single item could be checked in more than one source, research in the
configured **source-weight** order (high first), and lead with the source that
actually **assigns ownership** (issue tracker / CRM record / the chat thread
where it was handed off) - that is the source of truth for who owes what.
Auto-generated meeting notes are **last-resort corroboration only**, never the
lead: they mislabel owners and bury direct mentions. See
`reference/parity-port.md`.

Beyond confirming a promise is still open, the **email** and **chat** adapters
also watch for the user having **delivered** the deliverable or handed the
counterparty an action in a SENT message (config sent, request made, answer
given). When detected, the user's move is done and the ball is now in the
counterparty's court - the promise should become a they-owe follow-up:

- **A matching `i-owe-them` promise exists** -> flip it. Builtin: apply via the
  `ledger` skill's **Flip direction on delivery** (`direction: they-owe-me`,
  `owner` = recipients, `what` = "confirm/complete <the action>", prompt the
  user for a confirm-by `expectBy` + `why`). read-only backend: never rewrite the source record -
  surface a "looks delivered - update the note?" draft AND register a new
  they-owe follow-up in `state.json` via **Add a promise**.
- **No matching promise exists** -> register a NEW they-owe-me handoff follow-up
  so it is not lost.

The reality gate still applies: a follow-up is logged only with `owner` +
concrete `what` + a confirm-by date, or the user's explicit confirm. Never
auto-send/auto-post; the flip/registration is a ledger action, and any outward
message stays a draft. See `reference/handoff-followups.md`.

## Mis-attribution check (uses config.contacts)

For any promise with a named `owner`/person and a `context`, check that the
name appears in that context's `contacts.people` list (schema in
`reference/reconciliation.md`). If it does not, the promise is
`mis-attributed` regardless of what the adapter above would otherwise return -
this catches a promise tagged to the wrong context/person even when the
source itself looks fine.

## Acting on results

- **`verified-open`** -> proceed (safe to chase / publish).
- **`resolved`** -> for a `state.json`-backed promise, mark it `met` via the
  `ledger` skill (background bookkeeping on ADHDecoder's own store - the same
  spirit as `sweep`'s silent enrich/update), with a history line noting it was
  auto-resolved via reconciliation. For a **read-only-backend** promise, do
  **not** write the note - surface "this looks done, close it?" as a draft/
  instruction for the user (or their existing Decoder) to apply.
- **`reassigned`** -> record the new owner (state.json backend only) with a
  history note; drop it from the user's chase list with a brief note
  explaining why. For a read-only backend, surface the same as an instruction, no write.
- **`mis-attributed`** -> withhold from any outward-facing output; flag to
  the user: "this names `<person>`, who isn't on `<context>` - confirm."
- **`unverifiable`** -> never chase or publish with confidence; surface as
  "can't verify - confirm manually."

## Guardrails

- **Read-only against every source, and against read-only backends.** Reconciliation
  reads; it never writes to Jira/Slack/email/CRM/etc., and never writes a
  vault file.
- **Only the `state.json` backend gets verify-metadata writes.** Everything
  else routes through the `ledger` skill's write path; nothing here touches a
  file directly.
- **Never auto-send, never auto-post, never auto-create tasks.** Any action
  beyond the ledger's own bookkeeping is a draft for the user.
- **Cost-aware.** Honor the TTL cache; never re-verify the same item against
  the same source more than ~once/day.
