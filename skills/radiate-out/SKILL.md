---
name: radiate-out
description: >
  Compose a per-context "Where things stand" status draft from the ledger, so
  people stop chasing the user. Use when the user says things like "give me a
  status update for <customer>", "where do things stand with <customer>",
  "draft an update for <context>", "what should I tell <customer>", "post a
  status to <channel>", or reactively "any update on <thing>" / "did we ever
  hear back on <thing>". Reads the ledger through the same Query interface as
  chase-in/drift/panic (any backend), groups by context, and hands back a
  ready-to-publish draft plus a separate "confirm before sending" list for
  anything unverified. Never posts or sends anything itself. This is Phase 4
  of ADHDecoder.
---

# Radiate out (Phase 4)

The mirror of chase-in: chase-in nudges others, radiate-out tells others where
things stand before they ask. Publish status **outward** so nobody has to
chase the user. Read `reference/radiate-out.md` (the full spec) and
`reference/ledger-schema.md` (the promise shape) before running.

## What this does / does not do

- **Store-agnostic.** Reads the ledger through the exact same Query interface
  as `chase-in`/`drift`/`panic` (the `ledger` skill's Query, backend-aware) -
  works unchanged on `state.json`, the TaskNotes adapter, or any future
  backend.
- **Target-agnostic.** The publish target is whatever `~~chat` category is
  configured (a canvas/channel) - or, if none is configured, or the user just
  wants text, a plain copyable draft. No specific chat/vault product named
  here.
- **Drafts only, always.** Never auto-post, never auto-send. The user reviews
  and publishes every draft by hand.
- **Verified-only outward.** A wrong public status is worse than no status -
  see the Verified-only gate below.
- **Plain, reassuring tone.** Customer-facing copy: no internal jargon, no
  ticket IDs/status codes, no blame, no internal names the customer wouldn't
  already know.

## Load and group

1. Call the ledger's Query (exactly as `chase-in` does) to get the full
   promise set, recomputed fresh (overdue, stakes, etc.) at read time.
2. Group by `context` (the customer/context field). Within a context, split by
   `direction` and `status` into the three buckets below.

## Mode 1 - status board (proactive)

Per context, compose a short "Where things stand" draft with three sections
(omit any section that is empty - do not pad with "nothing to report"):

- **In flight** (we're on it) - open `i-owe-them` promises.
- **Waiting on you** (them) - open `they-owe-me` promises.
- **Recently shipped** - promises `met`/`cleared` in roughly the last 1-2
  weeks.

One line per promise: the plain-language `what`, in reassuring customer tone,
linking to its source. No internal ids, no raw ticket text.

**Batched: one review per context.** For the context currently being drafted,
reconcile each of its open/recently-closed promises (right before drafting -
see Verified-only gate) and produce that one draft for the user's review, not
a wall of every customer at once (no flood). Move to the next context - and
reconcile its items - only after the current one is handled (approved,
edited, or skipped). This keeps reconciliation bounded to what's actually
about to be published.

## Mode 2 - already-answered catch (reactive)

Given "any update on X?" (a customer or colleague asking about something
already addressed): locate the most recent matching promise/status in the
ledger for X, pull its source link and current state, and draft a **one-line
re-point**: what was last said/done, plus the source link, in the same plain
tone as Mode 1. This turns "let me dig that up" into a ready-to-send line.

If the located status fails the verified-only gate (below), do not draft a
confident re-point - draft a brief "let me confirm and get right back to you"
holding line instead, and flag it for the user to verify first.

## Verified-only gate (do not skip)

Only a promise **reconciled against its live source of truth** goes into the
customer-facing draft. Before including any promise, call the `reconcile`
skill (respecting its TTL cache, so already-fresh items are not re-hit) and
gate on its `verifyStatus`:

- **`verified-open`** -> include in In flight / Waiting on you as normal.
- **`resolved`** -> route per `reconcile`'s own handling (auto-marked met for
  `state.json`; a "looks done, close it?" draft for TaskNotes) - if it closed
  recently, it can appear under Recently shipped.
- **`reassigned`** -> drop from this context's draft; it is no longer this
  promise's story to tell here.
- **`mis-attributed`** -> withhold entirely and flag to the user separately
  ("this names `<person>`, not on `<customer>` - confirm") - never let a
  wrongly-tagged item near a customer draft.
- **`unverifiable`** -> withhold from the main draft; move to "confirm before
  sending" with the reason ("can't verify - confirm manually").

This replaces a plain freshness check with an actual source cross-check - see
`reference/reconciliation.md` for why (freshness alone missed a real
mis-attributed item in practice). `reconcile` itself is store-agnostic and
read-only except for its own `state.json` bookkeeping, so this gate works
unchanged on any backend.

## Output shape

For each context, produce:

1. The status draft (In flight / Waiting on you / Recently shipped, non-empty
   sections only), ready to copy or post to the configured `~~chat` target.
2. A separate, clearly labeled **"confirm before sending"** list of anything
   withheld, with the reason - the user decides what to add before
   publishing.

The user approves and posts (or asks for edits). This skill posts nothing
itself.

## Guardrails

- Never auto-post, never auto-send, never auto-create tasks. Drafts only, in
  every mode.
- Verified-only outward - unverified/possibly-stale stays in "confirm before
  sending," never silently included.
- No flood - one context's draft at a time in Mode 1.
- Plain tone - no jargon, ticket-speak, or blame in anything customer-facing.
- No hidden files. Reads the ledger backend; writes nothing outward itself.
