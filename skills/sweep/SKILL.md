---
name: sweep
description: >
  Scan the user's configured sources for items pointed at them that are
  stalling, verify each against its source of truth, dedup against the ledger,
  and record them as promises. Use when the user says things like "run a
  sweep", "scan my sources", "what's stalled across my tools", "check for new
  stalls", "sweep my chat/email/issues", or "refresh the ledger from my
  sources". Reads sources and writes promises only through the ledger backend
  (state.json by default); never sends, never posts, never auto-creates tasks
  elsewhere. This is the source-facing pass that feeds chase-in, drift, and
  panic.
---

# Sweep

A source-agnostic, store-agnostic pass: for each configured source, find items
pointed at the user, keep only the ones genuinely **stalling**, and record them
as promises in the ledger backend. It maintains the ledger and drafts only.
Read `reference/sweep.md`, `reference/method.md` ("Stakes", "Chase in", "The
ADHD design principles"), and `reference/ledger-schema.md` before running.

## What this does / does not do

- **Source-agnostic and store-agnostic.** Knows nothing about any specific
  product or knowledge base. It works from source **categories** (`~~chat`,
  `~~email`, `~~issue tracker`, ...) mapped in `config.json`, and writes to the
  active **ledger backend** (default `state.json`; an optional external-store
  adapter comes later - build and prove everything on `state.json`).
- **Reads sources, writes only the ledger.** Every promise write/update, plus
  `dedup.seen` and `lastSwept`, goes through the ledger backend (the `ledger`
  skill for the default `state.json`). Never write `state.json` directly.
- **Never sends, posts, or auto-creates tasks** in the user's other systems.
  Maintains the ledger and produces drafts; promotion stays deliberate.
- **Hide raw feeds.** Link to the source; never paste raw thread/email/issue
  content into the ledger.

## Load config

1. Read the instance `config.json` (via the `ledger` skill's Locate step).
2. Sweep the **enabled** sources in the **order** listed in `config.sources`
   (`{ type, enabled, category, provider }`). Source priority is config, not
   code: one user lives in chat, another in email.
3. Read `lastSwept` to scope each source to "changed since lastSwept." First
   run: use a sensible recent window.

## Find candidates (per source, generic)

Ask each enabled source the same question: **items pointed at me, changed since
lastSwept, still open.** Category patterns (exact mechanics live in each source
adapter, not here):

- **`~~chat`:** threads the user engaged in that went quiet after their last
  message; unanswered @mentions/pings; DMs awaiting reply. A mention/keyword
  search surfaces candidates but is not evidence by itself - back it with the
  `knownChannels` registry in the ledger, and always open the full thread (see
  Verify before flagging).
- **`~~email`:** threads addressed to the user awaiting their reply. The signal
  is "last message is from someone else, to me, and I have not replied" -
  filter automated / no-reply senders. Do **not** rely on unread.
- **`~~issue tracker`:** open issues the user is involved in (assignee,
  reporter, commenter, watcher, or an external-dependency-on-user field) that
  have gone quiet; pull priority + status.
- **`~~crm` / `~~docs` / `~~calls`:** as configured; lower priority for most
  users.

A ping is a **candidate, not a stall.**

## The stall signal (all four must hold)

1. **The user owes the next move** - a reply, answer, escalation, or
   deliverable. Set `direction` (`they-owe-me` vs `i-owe-them`) accordingly.
2. **Genuinely still open** - verified against the source of truth (below), not
   inferred from a ping.
3. **Gone quiet** - no visible movement from the user within the quiet window,
   counted in **business days**, not calendar days (Fri -> Mon is ~1 business
   day, not 3; do not call something stale across a weekend or a known OOO
   stretch). Items the user **owns** (`i-owe-them`, in-flight) trip **sooner**
   than things others owe the user (the "worked it partway then got
   distracted" failure).
4. **Someone is waiting** - a customer/context or a named person.

## Verify before flagging (do not skip)

Cross-check each candidate's underlying status before surfacing: an issue's
tracker status, a case's state, or the thread's latest message. If the source
of truth shows it resolved/closed, **drop it** - never chase a closed item (a
chat thread can look hot while the tracked issue is already Done). Stamp
`lastVerified` when you confirm.

**Always read the full thread; never trust a mention/keyword search alone.**
A search hit is a candidate, not proof of silence - open the thread and check
the user's OWN latest activity in it before flagging. A keyword/mention search
can show a thread as unanswered when the user already replied or acted (e.g. a
Slack search surfacing a question and a separate "we need help" ping as
untouched, when opening both threads showed the user had already responded the
same day - both would have been false alarms). Confirm no reply/action from the
user after the other party's last message, not just that a matching message
exists.

## Dedup against the ledger

Read the ledger backend first. If a candidate matches an existing promise (same
source ref or clear overlap, or an id in `dedup.seen`), **enrich/update** it -
refresh `lastVerified`, append a `history` note, adjust `expectBy` if the source
moved it - never create a second record. Add newly-decoded ids to `dedup.seen`.

## Write through the ledger (reality gate applies)

For a verified, de-duplicated stall, record it via the `ledger` skill's Add /
Update operation with `direction`, a concrete `what`, a named `owner`, an
`expectBy`, `source` ({ type, ref, url }), and `lastVerified`. `stakes` is
computed by the ledger at read time; do not hand-set it.

Reality gate: only write with owner + concrete `what` + `expectBy`. When the
source implies a date (SLA/priority tier, a go-live, a due field) use it and
note in `history` that it is an estimate to confirm. If owner, `what`, or a
defensible date is missing, do **not** write a phantom - surface it as a
candidate for the user to confirm.

## Finish

Record the sweep timestamp as `lastSwept` (through the ledger backend). The
resulting promises feed `chase-in`, `drift`, and `panic`; sweep itself surfaces
nothing to any customer-facing surface and sends nothing.

## Guardrails

- Never auto-send, never auto-post, never auto-create tasks elsewhere. Drafts
  and ledger records only.
- Verify against the source of truth before flagging; a ping (or a bare
  mention/keyword search hit) is only a candidate - read the full thread and
  confirm the user hasn't already acted.
- Count quiet windows in business days; never call something stale across a
  weekend or known OOO stretch.
- Dedup hard; enrich existing promises rather than duplicating.
- Hide raw feeds - link, never paste. No hidden files. Single writer: all
  writes go through the ledger backend.
