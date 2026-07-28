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

**Batched: one review per context.** Produce and present one context's draft
at a time for the user's review/approval, not a wall of every customer at
once (no flood). Move to the next context only after the current one is
handled (approved, edited, or skipped).

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

Only a promise **confirmed against its source of truth recently** goes into
the customer-facing draft. There is no dedicated "verified" flag in the
schema, so apply this read-time freshness check:

- **Open items** (In flight / Waiting on you): include only if `lastVerified`
  is within a recent freshness window (default **~5 business days** - tighten
  for high-stakes/customer-visible contexts if the user wants). Anything
  older was confirmed once, but not recently enough to publish as current
  fact.
- **Recently shipped:** include only items whose closing `history` line (the
  met/cleared confirmation) falls within the ~1-2 week window - an old
  closure re-surfacing is not "recent."
- Anything failing either check is **withheld** from the main draft and moved
  to a separate **"confirm before sending"** list instead - one line each,
  with the reason ("not re-verified in N days"), so the user can quickly
  confirm and add it, or leave it out.

This is the same spirit as `sweep`'s "verify before flagging" and `drift`'s
staleness check, applied to the outward-facing side.

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
