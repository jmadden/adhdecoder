# ADHDecoder — Promotion (unifying the two stores)

Written 2026-07-31. How a `state.json`-resident promise becomes a real record
in an external note-backed store, deliberately, so the board converges on one
store without ever auto-creating tasks.

## The problem this solves

With a note-backed ledger backend active, the board is a UNION of two stores:

- the user's open notes (mostly `i-owe-them`), served by the adapter, and
- `state.json` promises (mostly sweep-found `they-owe-me`) that were never
  promoted, served by the builtin companion.

The union works, but long-lived promises deserve to live where the user's real
tasks live. The guardrail ("never auto-create tasks") means the sweep can never
do this. Promotion is the deliberate path.

## When to offer promotion (offer, never push)

Offer a one-line "promote this to a task?" only when a `state.json` promise
shows signs of being long-lived or load-bearing:

- it has survived 2+ sweeps (still open, still relevant), or
- it is high-stakes, or
- the user acts on it repeatedly (snoozes it, asks about it, chases it), or
- the user says anything like "make this a real task" / "track this properly".

Never offer during `panic` (regulation, not admin). At most one promotion offer
per conversation; this is not a backlog-grooming engine.

## The flow (draft -> approve -> create -> collapse)

1. **Draft.** Build the full record the backend's `promote()` would create
   (for a note-backed store: complete frontmatter + a `> **Summary:**` body
   opening + the source link). Show it verbatim.
2. **Approve.** The user says yes, edits it, or declines. Declined = drop it,
   do not re-offer for that item for ~a week (`itemMeta[<id>].promotionDeclinedUntil`).
3. **Create.**
   - Writable backend (post-cutover): call `promote()`; the adapter creates
     the record.
   - Read-only backend: hand the user the draft as a ready-to-paste file/
     instruction instead. Creation is theirs.
4. **Collapse the original.** Once the record exists, the `state.json` promise
   collapses to a **cross-reference**: keep the record (append-only history
   preserved), set `status: promoted`, store `promotedTo: <new record id>`, and
   stop serving it from Query as an open promise. The new record now carries
   the promise; its `source` keeps pointing at the ORIGINAL live source (the
   thread/issue/case), never at the note that replaced it.

## Dedup rules (both directions)

- Query already dedups union items by source link, preferring the note. After
  promotion this happens structurally: the collapsed record is skipped.
- A sweep that re-finds the same source ref must match the PROMOTED record via
  `promotedTo` and enrich the note-backed promise (via `itemMeta`), never
  resurrect the collapsed `state.json` record and never create a duplicate.

## Invariants

- Promotion is user-approved, always. No exceptions, no batch mode.
- The collapsed record is never deleted (append-only survives unification).
- One promise, one open record, one source of truth per item after promotion.
- Works identically for any writable backend; nothing here names an adapter.
