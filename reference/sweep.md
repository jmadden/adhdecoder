# ADHDecoder — Sweep & Stall-Signal Spec

Build input for the generic sweep skill. Drop this into the plugin repo as
`reference/sweep.md`. Written 2026-07-27 from a live prototype against real
Slack / email / Jira data.

**The mechanical half of this spec is now code** (2026-08-14). Read this to
understand or change the behaviour; change the script in the same commit:

- **which sources a run covers** (weight order, cadence, the once-per-day
  guarantee) is `scripts/sweep_plan.py`
- **every write** (reality gate, schema, dedup against the full union,
  append-only history, atomic write, rollback, concurrent-writer guard) is
  `scripts/ledger_write.py`

What stays prose, because it needs reading rather than string equality: finding
candidates in each source, deciding whether the user owes the next move, and
matching a candidate to an existing promise by context + topic when the refs
differ. The split to hold is the same one as everywhere else in this repo:
**mechanical selection is code, judgment is prose.**

## Architecture context (decided with the user, 2026-07-27)

- **Generic-first.** The plugin is source-agnostic and store-agnostic. It knows
  nothing about any specific note store or dashboard.
- **Pluggable ledger backend.** Default = `state.json` (what every user gets).
  An OPTIONAL adapter lets a user with an existing task store (e.g. the Obsidian
  adapter) point the plugin at it instead, so the sweep enriches rather than
  duplicates. Adapters come later; build and prove everything on `state.json`.
- **Source priority is config, not code.** One user lives in chat, another in
  email. The sweep reads the enabled sources and their order from config.

## What the sweep is

A source-agnostic pass that, for each configured source, finds items pointed at
the user, detects the ones that are **stalling**, and writes/updates promises in
the ledger backend. It never sends, never auto-posts, never auto-creates tasks
in the user's other systems. It maintains the ledger and drafts only.

## The stall signal (core definition)

An item is a **stall** when all of these hold:

1. **The user owes the next move** (a reply, an answer, an escalation, a
   deliverable). Direction matters (they-owe-me vs i-owe-them).
2. **It is genuinely still open**, verified against the source of truth, not
   just inferred from a ping.
3. **No visible movement from the user in N days** (it has gone quiet).
4. **Someone is waiting**: a customer/context or a named person.

In-flight items the user OWNS deserve an earlier tripwire than things others owe
the user (that is the "worked it partway then got distracted" failure).

## Hard rules learned from the live POC (do not skip)

- **Verify before flagging.** A Slack/email ping is a CANDIDATE, not a stall.
  Cross-check the underlying issue/case status (or the thread's latest state)
  before surfacing. Proof: an issue (ISSUE-123) looked like a hot stall in chat
  (people chasing "close this today") but was already Done in the issue tracker.
  Never chase a closed item.
- **Email `is:unread` is noise.** It is full of automated senders (meal
  reminders, digests, calendar invites). The real signal is "the last message
  is from someone else, addressed to me, and I have not replied," with
  automated / no-reply senders filtered out.
- **Dedup, never duplicate.** Read the ledger backend (and any adapter-backed
  store) first; attach/enrich an existing item instead of creating a second one.
- **Hide raw feeds.** Link to the source; never paste raw thread/email content
  into the ledger.
- **Always read the full thread; never trust a mention/keyword search alone.**
  (Validated 2026-07-27: a concise mention search showed one customer's SSO
  question and another customer's "we need Eng help" ping as unanswered, but
  opening the threads showed the user had already replied and acted the same
  day. Both were false alarms.) Before flagging, open the thread and check the
  user's OWN latest activity in it.
- **Weekend / business-day-aware quiet windows.** Count business days, not
  calendar days. Fri -> Mon is ~1 business day, not 3. Do not call something
  stale across a weekend or a known OOO stretch.

## Per-source patterns (generic; exact mechanics live in each source adapter)

The sweep core just asks each enabled source: "items pointed at me, changed
since lastSwept, still open." Adapter specifics:

- **Chat (e.g. Slack):** threads the user engaged in that went quiet after their
  last message; @mentions/pings not yet answered; DMs awaiting reply. Search can
  be unreliable, so back it with a registry of channels the user is active in.
- **Email:** threads addressed to the user awaiting their reply; filter
  automated / no-reply senders; do not rely on unread.
- **Issue tracker (e.g. Jira):** open issues the user is involved in (assignee,
  reporter, commenter, watcher, or an external-dependency-on-user field) that
  have gone quiet; pull priority + status; confirm still open.
- **CRM / docs / calls:** as configured; lower priority for most users.

## Output

- New or changed stalls become promises in the ledger (owner, what, expect-by,
  direction, stakes, source link, lastVerified), via the active backend.
- Those feed chase-in, drift, and the panic button.
- Never auto-send, never auto-post. Drafts only. Promotion stays deliberate.

## Deferred (not this build)

- The optional external-store adapter (e.g. the Obsidian adapter) for users who
  already have a task system.
- Source-based auto-close (mark a promise met when the source shows it resolved),
  the natural extension of the "verify against source of truth" rule.
