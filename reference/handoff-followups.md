# ADHDecoder — Handoff Follow-ups, Delivery Flip, Ongoing Items (build spec)

Build input for the three linked backlog refinements. Dropped into the repo as
`reference/handoff-followups.md`. Written 2026-07-27 from live beta. (Proven-case
names genericized to placeholders per this repo's no-personal-data rule.)

## Schema additions (reference/ledger-schema.md)

Three optional promise fields:

- **`why`** (string): what this promise unblocks / why it matters, e.g. "test SIP
  inbound + outbound before the go-live." Feeds stakes and the nudge copy.
- **`deadlineType`** (`hard` | `soft` | `none`, default `hard`): `hard` = a real
  due date, chase overdue as today. `soft` / `none` = ongoing, do NOT chase by
  date; rely on staleness (drift) only.
- **`snoozedUntil`** (ISO date): the per-item dismiss valve. While set, keep the
  record but do not surface it as a chase. Distinct from `dismissedFromBoard`
  (permanent removal); snooze is temporary and never deletes.

**Backend-scoped writes:** for the read-only TaskNotes backend, `snoozedUntil`
and any verify metadata live in the `state.json` companion (`itemMeta`) keyed by
the item id, never written into the note.

## 1. Handoff follow-up (the "both" direction)

When the user hands a counterparty an action (delivers config, sends a request,
asks them to do X), the item is `they-owe-me` (they owe the action) but it stays
the user's to DRIVE to confirmation. Since `they-owe-me` already means "your move
is to chase them," this is modeled as a they-owe-me promise the user drives:

- `owner` = the counterparty contact(s)
- `what` = "confirm/complete <the action>"
- `expectBy` = a confirm-by date (set the clock; ask the user if not inferable)
- `why` = what it unblocks

**Keep in sight, dismissible.** Surface it as the user's chase (chase-in), but
offer "no follow-up needed this time" -> set `snoozedUntil`, kept not deleted.

Weight `stakes` by `why`: a go-live / deadline dependency = high.

## 2. Direction flips on delivery (reconcile email + chat adapters)

Reconcile's email and chat adapters should detect that the user **delivered** a
deliverable or handed the counterparty an action in a sent message, and:

- If a matching `i-owe-them` promise exists -> **flip it to `they-owe-me`**, set
  `owner` = the recipients, `what` = confirm/complete the action, prompt for a
  confirm-by date + `why`.
- If none exists -> register a NEW they-owe-me handoff follow-up (so it is not
  lost).

Proven case: a "Configure X" task was still tagged i-owe, but the user had
already sent the DNS + SIP settings to the counterparty contacts -> it was already
they-owe-me (the customer/vendor owe confirmation). Reality gate still applies
(owner + concrete what + a date, or the user's confirm).

## 3. Ongoing / no-hard-deadline items

A placeholder due date on an ongoing project causes false overdue-chasing. Use
`deadlineType`:

- **chase-in** computes overdue ONLY for `deadlineType: hard`. `soft` / `none`
  items never show as overdue.
- They still surface via **drift staleness** if they go quiet.
- **Adapter mapping (TaskNotes):** a note with a real `due` -> `hard`. A note
  tagged `ongoing` (or carrying `scheduled` but no `due`) -> `soft`. Give the user
  a simple way to mark an item ongoing.

Proven case: an ongoing "Finalize telephony playbook" whose due kept getting
pushed; its `due` is now removed.

## Integration

- **set-the-clock:** when capturing an outbound handoff, set `direction:
  they-owe-me`, a confirm-by `expectBy`, and `why`.
- **chase-in / radiate-out / drift:** honor `deadlineType` and `snoozedUntil`.
- **reconcile:** implement delivery detection in the email + chat adapters.

## Guardrails

Never auto-send / auto-post / auto-create tasks. Read-only on TaskNotes (snooze
and verify metadata go to the `state.json` `itemMeta` companion only). Everything
outward is a draft.
