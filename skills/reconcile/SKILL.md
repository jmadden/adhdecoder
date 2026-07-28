---
name: reconcile
description: >
  Cross-check a promise against its live source of truth before it's chased or
  published, so stale or mis-tagged ledger records never drive an action. Use
  when the user says things like "verify this", "double-check X against
  Jira/Salesforce/Slack", "is this still open", "reconcile my chases", or
  "confirm before we publish" - and internally, whenever chase-in, drift, or
  panic is about to surface an item, radiate-out is about to draft a context
  status, or the sweep verifies a candidate. Dispatches
  by promise.source.type to a per-source adapter (issues, crm, chat, email
  lighter; TaskNotes-derived promises reconcile against their underlying
  source ref). Read-only against every source and against TaskNotes; only the
  state.json backend gets verify-metadata writes. Never sends, never posts.
---

# Reconcile

Freshness is not verification. A ledger record - especially one read from the
TaskNotes backend - can be stale or mis-tagged even when it was captured
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

## TTL cache (cost-aware - do not skip)

Do not re-hit a source for every promise on every run. Before dispatching:

- If the promise already has a `verifyStatus` and `lastVerified` is **less
  than ~1 day old**, reuse the cached `verifyStatus`/`reason` - skip the
  adapter call entirely.
- Otherwise run the adapter and refresh.
- Within a single run, reuse a result already computed for an item this run
  rather than calling the adapter again (e.g. when `panic` surfaces an item the
  `drift` check already reconciled).

**Persistence is backend-scoped:** for a promise whose record lives in the
`state.json` backend, persist the refreshed `lastVerified` + `verifyStatus` +
`verifyReason` via the `ledger` skill's **Record reconcile result** operation.
For a TaskNotes-derived promise, the note is read-only (no field to cache
into) - the fresh result is used for this run only and is not persisted; it
is re-checked next time it matters. Deliberate v1 tradeoff, not an oversight.

## Per-source adapters

- **`issues` (e.g. Jira):** fetch the issue. Done/closed -> `resolved`.
  Assignee moved off the user, and it is not the user's to own -> `reassigned`.
  Otherwise -> `verified-open`, refresh `lastVerified`.
- **`crm` (e.g. Salesforce):** the record's closed flag -> `resolved`. Owner/
  assignee changed -> `reassigned`. Otherwise -> `verified-open`.
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
- **TaskNotes-derived promise:** its real source of truth is the underlying
  system referenced IN the note (a Jira key, a chat channel) - not the note
  itself. Extract that reference and dispatch to the matching adapter above.
  No linkable reference -> `unverifiable`.

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
  auto-resolved via reconciliation. For a **TaskNotes-derived** promise, do
  **not** write the note - surface "this looks done, close it?" as a draft/
  instruction for the user (or their existing Decoder) to apply.
- **`reassigned`** -> record the new owner (state.json backend only) with a
  history note; drop it from the user's chase list with a brief note
  explaining why. For TaskNotes, surface the same as an instruction, no write.
- **`mis-attributed`** -> withhold from any outward-facing output; flag to
  the user: "this names `<person>`, who isn't on `<context>` - confirm."
- **`unverifiable`** -> never chase or publish with confidence; surface as
  "can't verify - confirm manually."

## Guardrails

- **Read-only against every source, and against TaskNotes.** Reconciliation
  reads; it never writes to Jira/Slack/email/CRM/etc., and never writes a
  vault file.
- **Only the `state.json` backend gets verify-metadata writes.** Everything
  else routes through the `ledger` skill's write path; nothing here touches a
  file directly.
- **Never auto-send, never auto-post, never auto-create tasks.** Any action
  beyond the ledger's own bookkeeping is a draft for the user.
- **Cost-aware.** Honor the TTL cache; never re-verify the same item against
  the same source more than ~once/day.
