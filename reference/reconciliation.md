# ADHDecoder — Source Reconciliation Spec

Build input. Drop into the plugin repo as `reference/reconciliation.md`. Written
2026-07-27. This is a core, cross-cutting capability, not a phase, because the
plugin reads from many sources and a promise is only trustworthy if it still
matches its source of truth.

_Note: the worked example below and the `contacts` sample are genericized for
this repo (placeholder customer/person/channel names, per this repo's "no
personal or company data" rule). Real contacts entries belong in your own
instance `config.json`, not here - same as your watchlist/roster already work._

## Why this is front and center

The ledger (especially the read-only backend) inherits any staleness
or mis-tagging in its records. **Freshness is not verification.** Before
ADHDecoder acts on a promise (chase it, publish it, or confidently surface it),
it must confirm against the **live source** that the item is: still open,
correctly owned, on the right customer, and current.

Proven need (2026-07-27): a read-only-backend promise "Respond to `<person>` re `<topic>`"
tagged to a customer was mis-attributed - the named person was not actually on
that customer's team (the customer's real CSM/TAM were different people), and
the topic had already been handled. Only a live chat/issue-tracker cross-check
catches that; the freshness gate caught it by luck.

## The reconcile operation (generic core)

`reconcile(promise) -> { status, reason, updates }`

- `status` in: `verified-open` | `resolved` | `reassigned` | `mis-attributed`
  | `unverifiable`.
- Dispatches by `promise.source.type` to a **per-source reconcile adapter**
  (same adapter pattern as the sweep's candidate-finding). Generic core, plug
  in a source.
- Stamps `lastVerified` (now) + a `verifyStatus` + a short `reason`.

## Per-source reconcile adapters

- **issues (Jira):** fetch the issue. Done/closed status => `resolved`.
  assignee moved off the user (and not the user's to own) => `reassigned`. Else
  `verified-open`, refresh `lastVerified`.
- **crm (Salesforce):** `IsClosed` => `resolved`. owner/assignee changed =>
  `reassigned`.
- **chat (Slack):** using the contacts map to find the customer's channel/thread:
  did the user already reply after the ask? did someone else take it over? is
  there an explicit "resolved/closed/done"? A named person not on the customer
  => `mis-attributed`. Use clear signals in v1 (user replied after the ask,
  explicit resolution words, linked ticket status); defer deep NLP.
- **email:** the thread's latest state, whether the user has replied.
- **note-backed promise:** its real source of truth is the UNDERLYING system
  referenced in the note (a Jira key, a customer channel), not the note itself.
  Extract that ref and reconcile against it. No linkable source => `unverifiable`.

## The contacts map (instance config, the other half of the fix)

Add `config.contacts`: per customer, the people and places that define it.

```json
"contacts": {
  "Acme Corp": {
    "channels": ["#acme-corp-support"],
    "csm": "<CSM name>",
    "tam": "<TAM name>",
    "people": ["<CSM name>", "<TAM name>"]
  }
}
```

Derived from activity and confirmed by the user (like the customer roster). Used
to (1) locate the right channel/thread to reconcile a chat item, and (2)
sanity-check that a promise's owner/named person actually belongs to that
customer, catching mis-tags like the "named person not actually on this
customer" case above.

## Triggers (cost-aware, this scales across many sources)

Do NOT re-verify every promise against every source every run. Reconcile a
promise:

- **right before** it would be chased (chase-in) or published (radiate-out);
- as a **bounded batch** during the sweep for high-stakes / aging items;
- **on reference:** whenever the user references a specific tracked item or
  context in conversation and a status claim is about to be made - verify that
  item (full thread + note status) before answering (see
  `reference/verification-discipline.md`).

Cache `lastVerified` with a TTL (e.g. do not re-hit a given source for the same
item more than ~once/day). This keeps reconciliation affordable as sources grow.

## Acting on results (respect read-only + guardrails)

- `verified-open` => proceed (chase / publish).
- `resolved` => for the `state.json` backend, mark the promise met/closed. For
  the **read-only backend, do NOT write** the note; surface "this looks
  done, close it?" as a draft/instruction for the user (or their existing
  Decoder) to apply.
- `reassigned` => record the new owner; if it moved off the user, drop it from
  the user's chase list with a note.
- `mis-attributed` => withhold from any customer-facing output; flag to the user:
  "this names X, who isn't on <customer>, confirm."
- `unverifiable` => never chase/publish confidently; surface as "can't verify,
  confirm manually."

Never auto-send, never auto-post, never write to the user's other systems.
Reconciliation READS sources and, only for the ADHDecoder-owned `state.json`,
updates verify metadata.

## Integration

- **radiate-out** (first, highest risk): its verified-only gate uses
  `verifyStatus` from reconcile, not just a freshness window.
- **chase-in**: reconcile an item before drafting a nudge; drop resolved /
  reassigned ones, flag mis-attributed / unverifiable.
- **drift / panic**: same reconcile before surfacing.
- **sweep**: already verifies inbound candidates; unify it onto the same
  per-source reconcile adapters so there is one verification path.

## Scope for v1

- Reconcile adapters for **issues (Jira)**, **crm (Salesforce)**, **chat
  (Slack)**; email lighter.
- The `contacts` map schema (real entries are seeded in the user's own instance
  `config.json`, not in this repo).
- Wire reconcile into **radiate-out's verified-only gate** and a
  **chase-in pre-check** first; drift/panic/sweep unification follows.
- Read-only on read-only backends preserved (propose closes, never write).

## Defer

- Deep NLP resolution detection in chat.
- Auto-writing closes back into a read-only backend (stays read-only; propose only).
