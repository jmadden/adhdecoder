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

## Plan the run (do not re-derive the TTL by hand)

**Ask the planner what actually needs verifying.** The TTL decision, the working
order, and the mis-attribution lookup are arithmetic:

```
python3 <plugin-root>/scripts/reconcile_plan.py --config <instance config.json> \
    --select slipping --json
```

It returns `verify` (each with the reason it is stale) and `cached` (each with
the reason its verdict is still good), ordered **urgency first, then source
weight**. Verify exactly the `verify` list; reuse the cached verdict for the
rest. `--ttl-hours` overrides the default 24h; `--id` restricts to specific
promises; `--select` takes any `ledger_query` selector.

Getting this wrong costs both ways: too eager and every run re-hits every source
for nothing; too lax and a closed ticket gets chased at a real person. Within a
single run, also reuse a result already computed this run (e.g. when `panic`
surfaces an item `drift` already reconciled) - the planner cannot see that, so it
is yours.

## Persist the result (routed for you)

**Never hand-write the verify metadata.** One command, and it decides where the
result belongs:

```
python3 <plugin-root>/scripts/ledger_write.py --config <cfg> record-verify \
    --id <id> --status verified-open --reason "<one line>" \
    [--source-url <the link you found> --source-type issues --source-ref KEY]
```

A promise living in `state.json` gets it on the record; a note-backed record gets
it in the `itemMeta` companion keyed by id, **never the note**. That branch is
what keeps a read-only backend read-only, so it is decided in code rather than
restated at each call site, and a test asserts no note file is written.

**Pass the source link you found.** When an adapter locates or confirms the live
source (the ticket, the chat permalink, the sent email, the CRM record), pass it
as `--source-url`: it is persisted and clears `noteOnly`, so the real link is
kept rather than discovered and thrown away.

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

## Mis-attribution signal (advisory, not a verdict)

`reconcile_plan.py` reports this in `misattributionSignals`. It fires only when
it has real evidence: the `owner` names someone who **is** on another context's
`contacts.people` roster but not on this promise's context. Treat it as a prompt
to confirm the context, never as a verdict - the adapter's read of the live
source outranks it.

**This is deliberately weaker than this spec originally said**, and the change
is load-bearing. The original rule was decisive: an owner not listed in that
context's roster made the promise `mis-attributed` regardless of the source.
Measured against a real 31-promise ledger, that rule fired on **8 of 10**
checkable promises and was wrong nearly every time, because real `owner` values
are prose describing a party - a vendor (`Acme Telecom/Northwind`), a team
(`platform triage`), an org (`Acme Corp (customer)`), or several people
at once - not a single roster name. Shipping it as specified would have buried
the user in false "confirm this" prompts, which is precisely the noise the whole
product exists to remove. The evidence-only rule cut that to 2 signals, both
worth a glance.

## Acting on results

- **`verified-open`** -> proceed (safe to chase / publish).
- **`resolved`** -> for a `state.json`-backed promise, mark it `met` via the
  `ledger` skill (background bookkeeping on ADHDecoder's own store - the same
  spirit as `sweep`'s silent enrich/update), with a history line noting it was
  auto-resolved via reconciliation. For a promise whose record this cannot
  write, do **not** write the record - persist a **`markMetDraft`**
  (`{ status, completedDate, reason }`) to the `itemMeta` companion, keyed by
  item id, per `reference/ledger-schema.md`.

  **Parking a draft is not closing an item.** The draft is a pending decision
  the user has not seen yet, so the board renders it in the **Ready to close**
  group (`reference/dashboard.md`) until they act. Never park one without that
  surface: a write-only draft means finished work keeps rendering as
  outstanding, and the board stops being believable.
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
