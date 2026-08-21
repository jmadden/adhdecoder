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

- **First run.** If ADHDecoder isn't set up (no config / no enabled source),
  offer `setup` instead of sweeping against an empty config. See
  `reference/onboarding.md`.
- **Source-agnostic and store-agnostic.** Knows nothing about any specific
  product or knowledge base. It works from source **categories** (`~~chat`,
  `~~email`, `~~issue tracker`, ...) mapped in `config.json`, and writes to the
  active **ledger backend** (default `state.json`; an optional external-store
  adapter comes later - build and prove everything on `state.json`).
- **Reads sources, writes only the ledger.** Every promise write/update, plus
  `dedup.seen` and `lastSwept`, goes through `scripts/ledger_write.py`. Never
  write `state.json` directly and never compose the JSON by hand.
- **Never sends, posts, or auto-creates tasks** in the user's other systems.
  Maintains the ledger and produces drafts; promotion stays deliberate.
- **Hide raw feeds.** Link to the source; never paste raw thread/email/issue
  content into the ledger.

## Plan the run (do not re-derive the schedule)

**Ask the planner which sources are due.** Weight ordering, cadence, and the
once-per-day guarantee are arithmetic, not judgment:

```
python3 <plugin-root>/scripts/sweep_plan.py --config <instance config.json> --json
```

It returns `sweep` (ordered, each with the reason it is included) and `skip`
(each with the reason it is not). Sweep exactly the `sweep` list, in that order.
Add `--scope every-run` for a light intra-day pass, `--scope all` to force
everything.

It also returns **`suppressedRefs`**: source refs that must never become a
promise again. **Drop any candidate whose source ref matches one** - no promise,
no enrich, no mention - matching case-folded and exact on the ref, nothing
looser (`reference/sweep.md`). This is reported to you rather than remembered by
you on purpose: the list previously had no reader, and a ref marked dead came
back on a later run. To add one, `ledger_write.py suppress --ref REF --reason
"<why>"`; never hand-edit `state.json`.

The rule it enforces, which prose kept having to restate: **every enabled source
is swept at least once per calendar day**, whatever its weight or cadence, so
nothing is silently ignored. Per-source freshness comes from the `sweepLog`
entry naming that source, not from the global `lastSwept` - which only says some
sweep ran, not that this source was in it.

Then scope each source's query to "changed since that source's last sweep"
(`lastSwept` in the plan entry). First run: a sensible recent window.

## Find candidates (per source, generic)

Ask each enabled source the same question: **items pointed at me, changed since
lastSwept, still open.** The per-source techniques below are ported from a
proven prior decoder; full detail and rationale in `reference/parity-port.md`.
Every specific (handle, channel list, watched accounts, timezone, noise pattern)
reads from `config.identity` / `config.sources[]` / `config.contacts` /
`state.json` - never hard-coded here.

- **`~~chat` (three passes every run - search alone silently misses real
  messages):**
  1. **Mention-token search** for the user's handle
     (`config.identity.handles.chat`) over `lastSwept - overlap` to now (a few
     hours of overlap absorbs search-index lag), plus a `to:`/recipient pass for
     DMs.
  2. **Known-channel backstop.** Read `state.json.knownChannels` directly each
     run and scan each since `lastSwept` for the user's mentions, regardless of
     what search returned. Add a channel on its first hit; never remove it. This
     is the safety net for "search returned empty but a real mention exists."
  3. **Silent-reply tracking.** Re-read `state.json.watchedThreads`
     (channel + parent ts) and surface new replies since `lastSwept` even when
     they never re-mention the user.
  On any hit, read the **full thread** before deciding (prior messages carry the
  substance). Maintain both registries in `state.json` as you go.
- **`~~email`:** threads addressed to the user awaiting their reply. The signal
  is "last message is from someone else, to me, and I have not replied" -
  filter automated / no-reply senders. Do **not** rely on unread.
- **`~~issue tracker`:** buckets - **assignee**, **comment-mentions**,
  **watcher** (with new activity). **Timezone-correct filtering:** convert the
  since-cutoff to the tracker's tz (`config.sources[].tz`) or filter by each
  issue's own `updated` offset; never trust a naive datetime. **Sync-noise:** a
  recurring bulk bump (`config.sources[].noise`) is not real activity. **Priority
  persistence:** an item at/above the configured high-priority threshold that is
  assigned / mentions / watched stays flagged until it is **closed or
  reassigned** - a quiet high-priority item is not resolved, never drop it for
  "no new comment."
- **`~~crm`:** open records on the user's **watched accounts**
  (`config.contacts`) AND records the user owns or follows. **Severity / SLA at
  or above the configured tiers on a watched account always flags.** A "blocked
  on our team" internal-dependency value is an **action item, not FYI**. Treat
  CRM datetimes in its own tz (often UTC). If a record links a tracker issue, it
  is the **same** work item - decode once, cross-reference both ids.
- **`~~calendar`:** query the calendar **directly** for events changed since
  `lastSwept` (self-created / self-organized events leave no email trail, so
  email alone misses them). Decode **substantive** changes only - new event,
  time/date change, attendee add/drop, real agenda edit; **skip pure RSVP**
  changes.
- **`~~calls` (call-intelligence + meeting-notes):** only meetings the user
  actually **attended** (confirm attendance, do not trust an org-wide feed);
  extract **user-owned** action items. **Dedup across both** - one meeting can
  produce a call record AND a notes doc; decode once, prefer the **richer**
  source, cross-reference the other. Treat auto-generated notes as **lossy**:
  match names loosely, use only as last-resort corroboration, never as the lead
  (they mislabel owners and bury direct mentions).
- **`~~docs`:** mentions of the user in comments, and **others'** edits/comments
  on pages the user authored. **Never surface the user's own edits** back at
  them.

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

Run each candidate through the **same per-source reconcile adapter** the rest of
ADHDecoder uses (`reconcile`, dispatched by the candidate's source type) - one
verification path, no bespoke duplicate logic here. Pass the candidate's source
(`{ type, ref, url }`); reconcile returns the same status set:

- **`resolved`** -> drop it. Never chase a closed item (a chat thread can look
  hot while the tracked issue is already Done).
- **`reassigned`** -> it is no longer the user's; do not add it to the chase
  list.
- **`mis-attributed`** -> do not create a chase; surface it to confirm the tag.
- **`verified-open`** -> a real stall; proceed to dedup + write. Reconcile has
  already refreshed `lastVerified`.

Honor reconcile's TTL cache: a candidate that dedups to an existing promise
reconciled within ~1 day reuses that result instead of re-hitting the source
(dedup below runs first for exactly this reason). The read-the-full-thread rule
for chat now lives in reconcile's chat adapter, so the same care applies without
being duplicated here.

## Context enrichment before creating (dedup)

Read the ledger backend first, through the Query, so the existing set you match
against is the same one every other surface sees:

```
python3 <plugin-root>/scripts/ledger_query.py --config <instance config.json> \
    --select all --json
```

Dedup has a mechanical half and a judgment half. **The mechanical half is the
Query's:** an exact `source.url` match against an existing record is already
decided, and the Query's key is authoritative (non-`noteOnly` urls only, since a
note link identifies one note rather than a shared item). Do not invent a second
url-matching rule; a candidate you create under a different key becomes a
`state.json` record the Query then collapses into the note that owns it, so the
duplicate never shows on the board but accumulates in the file forever. The
board note's collapse count is the only symptom.

**The judgment half is yours:** matching **by context + topic** when the refs
differ (a CRM record and its linked tracker issue, a meeting's call record and
its notes doc, are one work item). That needs reading, not string equality.

Before recording a candidate as a NEW promise, match it both ways, and also
against `dedup.seen`. If it matches,
**enrich/attach** - refresh `lastVerified`, append a `history` note, adjust
`expectBy` if the source moved it - never create a second record. Decode as new
**only if it maps to nothing**. Add newly-decoded ids to `dedup.seen`. A CRM
record and its linked tracker issue, or a meeting's call record and notes doc,
are one work item - attach, do not duplicate. A match against a record with
`status: promoted` routes the enrichment to the record its `promotedTo` points
at (via `itemMeta` for a note-backed store) - never resurrect the collapsed
record, never create a duplicate (`reference/promotion.md`).

## Write through the ledger (never hand-write JSON)

**Every write goes through `scripts/ledger_write.py`.** Do not edit `state.json`
directly, and do not compose the JSON yourself from the schema: this runs
unattended three times a day, and a hand-written record is the one place a
subtle bug corrupts the ledger with nobody watching.

New promise:

```
echo '<promise JSON>' | python3 <plugin-root>/scripts/ledger_write.py \
    --config <instance config.json> add
```

Existing promise (enrich, never duplicate):

```
python3 <plugin-root>/scripts/ledger_write.py --config <cfg> enrich \
    --id <id> --note "<what changed and why>" [--expect-by YYYY-MM-DD] \
    [--verify-status verified-open] [--verify-reason "..."]
```

Pass `--dry-run` first if you want to validate without writing. What it enforces
so you do not have to:

- **The reality gate.** A record without a named `owner`, a concrete `what`, and
  an `expectBy` is refused. If a candidate cannot clear that bar, it is not a
  promise - surface it to the user as a candidate to confirm, do not force it in.
- **The schema.** Bad enum values, invented fields, and deprecated field names
  are refused at write time rather than reported by `doctor` days later.
- **Dedup against the FULL union, notes included.** A candidate whose
  `source.url` a note already owns is refused with the id that owns it; enrich
  that instead. This is not theoretical: writing it anyway creates a record the
  Query collapses on every read, so it never shows on the board and lives in the
  file forever.
- **Append-only history**, an atomic write, a visible backup, and a rollback if
  the result would be worse than what it replaced.
- **Concurrent writers.** If a desktop session or another run wrote while you
  were preparing, the write is refused rather than clobbering theirs. Re-run.

Set `source.url` to the swept item's **canonical permalink** - the issue URL, the
chat permalink (channel id + message ts), the email thread, or the CRM record URL
- never a paraphrase or a search query. Link, never paste. When the source
implies a date (SLA/priority tier, a go-live, a due field) use it and say in the
history line that it is an estimate to confirm. `stakes` is computed at read
time; do not hand-set it.

## Finish

Stamp the run through the same write path, which also records per-source results
so `doctor` can tell a quiet source from a broken one:

```
echo '{"chat(slack)":"ok","email(gmail)":"ok - 3 candidates","issues(jira)":"connector unavailable"}' \
  | python3 <plugin-root>/scripts/ledger_write.py --config <cfg> record-sweep
```

Report the **pre-sweep freshness** - how stale the ledger was before this run -
so a caller can lead with "what changed since the last sweep" (see
`reference/verification-discipline.md` Rule 3 and `daily-run`'s session-start
refresh). The resulting promises feed `chase-in`, `drift`, and `panic`; sweep
surfaces nothing customer-facing and sends nothing.

## Guardrails

- Never auto-send, never auto-post, never auto-create tasks elsewhere. Drafts
  and ledger records only.
- **Never `capture` or `promote`.** Those create a note, which requires an
  explicit human action; the script refuses without `--confirmed` precisely so
  an unattended pass cannot create notes by accident. A sweep-found stall goes
  to `state.json` via `add`, and becomes a note only when the user approves a
  promotion.
- Verify every candidate through the shared `reconcile` adapters before
  flagging; a ping (or a bare mention/keyword search hit) is only a candidate.
- Count quiet windows in business days; never call something stale across a
  weekend or known OOO stretch.
- Dedup hard; enrich existing promises rather than duplicating.
- Hide raw feeds - link, never paste. No hidden files. Single writer: every
  write goes through `scripts/ledger_write.py`, which refuses anything that
  fails the reality gate or the schema and rolls back a write that would leave
  the ledger worse than it found it.
