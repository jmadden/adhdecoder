---
name: set-the-clock
description: >
  Capture promises at the moment work flows in or out, so the follow-up loop
  never leaks. Two triggers. (1) Decode replies: whenever a reply to an incoming
  ask is drafted, end it with a clock-setting question (who owes what back, by
  when). (2) Outbound watch: when the user gives info out with no return date on
  a go-live or high-stakes thread — "let them know", "I'll send them X", "told
  them I'd...", "just replied", "sent the update", "answered <person>" — prompt
  to set the clock. Never auto-logs; prompts only. Writes confirmed promises via
  the ledger skill. This is Phase 2 of ADHDecoder.
---

# Set the clock (Phase 2)

Capture the promised-by date as work moves, then hand it off. Read
`reference/method.md` ("Set the clock", "The promise triple", "Stakes") and
`reference/ledger-schema.md` before logging anything. Persistence is the
`ledger` skill's job — never write `state.json` from here.

## What this does / does not do

- **First run.** If ADHDecoder isn't set up (no config / no backend), offer
  `setup` before logging a promise. See `reference/onboarding.md`.
- **Prompts, never auto-logs. Drafts, never auto-sends.** The user always
  confirms before a promise is written or a reply goes out.
- Does **not** sweep sources (later phases). It fires on what is in front of
  you: a reply you are drafting, or info the user is giving out in conversation.

## Trigger 1 — baked into decode replies (always)

Whenever a decode draft reply is produced (by you here, or a future decode
skill), it MUST end with a clock-setting question — the "SET THE CLOCK" field of
the decode format, made active. Pick by direction:

- **they-owe-me** (waiting on them): ask them to commit a date. Restate the ask,
  name what is needed, then: "When can you have <deliverable> back to me?"
- **i-owe-them** (user owes them): state the date the user commits. If unknown,
  ask the user for it, and include a holding line so nobody is left chasing:
  "I'll have <deliverable> to you by <date>."

One question, concrete, tied to a single deliverable. Never auto-send the reply.

## Trigger 2 — outbound watch (narrow: high-stakes only)

Watch for the user giving info OUT with no return date attached. Fire ONLY when
the thread is **high-stakes** per `method.md`: go-live within ~2 weeks, S1/S2 or
T1/T2, priority High or above, a PCI/security flag, a watchlist customer, or an
expect-by within ~2 days. On lower-stakes threads, stay silent (No flood).

Cues the user is sending info out: "let them know", "I'll send…", "told them
I'd…", "just replied to…", "sent the update", "answered <person>".

When it fires: one small prompt, not a nag — "Want to set the clock on this? Who
owes what back, by when?" If the user declines or it is not a real promise, drop
it; do not re-prompt the same thread.

## Reality gate (before anything is written)

Write a promise ONLY with all three: a named **owner**, a concrete **what** (one
deliverable, not "an update"), and an **expectBy** date — OR the user's explicit
confirmation to log it. If any is missing:

- Ask for the missing piece once.
- If still vague ("I'll find out X", no owner or date), do NOT log. Offer to keep
  it as a note instead. Vague "go find out X" never enters the ledger.

## Direction rules

- **they-owe-me** → goal is a committed date from them; log when they give one
  (or the user confirms on their behalf).
- **i-owe-them** → goal is the user's committed date; if they cannot commit yet,
  draft a holding status ("I'll get you <thing> by <when>") and log only once a
  date exists. Never log a dateless "I owe."
- **outbound handoff (the "both" case)** → when the user has just *handed a
  counterparty an action* (delivered config, sent a request, asked them to do X),
  the ball is now in their court but the user still drives it to confirmation.
  Capture it as `direction: they-owe-me` with `owner` = the counterparty,
  `what` = "confirm/complete <the action>", `expectBy` = a confirm-by date (ask
  if not inferable), and `why` = what it unblocks. See
  `reference/handoff-followups.md`. This is the capture-time twin of `reconcile`'s
  delivery detection.

## Hand off to the ledger

When the reality gate passes and the user confirms, invoke the `ledger` skill's
**Add a promise** operation with `direction`, `what`, `owner`, `expectBy`,
`source` ({ type, ref, url } for the thread/item), and, when known, `why` (what
it unblocks - feeds stakes and nudge copy). `deadlineType` defaults to `hard`;
set `soft`/`none` only for a genuinely ongoing item. The ledger builds the record
per `reference/ledger-schema.md`, sets `status: pending`, stamps timestamps,
seeds `history` with "Promise captured.", and writes `state.json` atomically. Do
not duplicate that logic; do not touch `state.json` directly.

## Guardrails

- Never auto-send a reply, never auto-post. Replies are drafts to approve.
- Never auto-log a promise, never auto-create a task. Prompt; the user confirms.
- No hidden files. The ledger's single visible `state.json` is the only store.
- No flood. One clock question per item; do not re-prompt a declined thread.
- Advisor by default: help set the date, never invent it.
