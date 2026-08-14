# Projects

A **project** is a declared grouping of promises that already exist: a multi-week
effort that outlives any one of its items. It exists so work assigned over weeks
has something that notices when it goes quiet, instead of surviving only as a
shared string in a `customer` field.

A project **never owns** a promise, never changes one, and never introduces a
second definition of any per-promise state. It is a lens over the ledger.

Implemented by `projects()` in `scripts/ledger_query.py` (the read),
`project-set` in `scripts/ledger_write.py` (the write), and the Projects tab +
Board-tab block in `scripts/render-board.py`. This file is the spec those three
share; the numbers below are stated here **once**.

## The record

Lives in the `projects` array of `state.json` (schemaVersion 3). Field set and
validation in `scripts/ledger_schema.py`.

| Field | Meaning | Surface |
|---|---|---|
| `id` | stable slug; `--project <id>` filters to its members | card anchor, CLI |
| `name` | display name | card heading, lagging row |
| `status` | `active` or `done` | `done` renders in a **Closed** section |
| `aliases` | context spellings that make a promise a member | chip row on the card |
| `include` | promise ids pinned in regardless of context | `pinned` chip per member |
| `targetDate` | the project's own date, if it has one | badge; drives date-slipping |
| `snoozedUntil` | quiet until this date | badge; suppresses lagging |
| `note` | one line of context | card body |
| `updated` | last write | card footer |

**There is no `paused` status.** `snoozedUntil` already means "quiet, and it
comes back" everywhere else in this schema, and `done` means permanent. A third
vocabulary would be a second off-switch to keep consistent, and a paused project
is one more thing that silently drops out of view.

**There is no project `history`.** Members carry append-only history already; a
registry history nothing renders is a place a correction goes to die.

**`targetDate` is scoped.** It drives the project-level signal below and renders
on the card. It must never reach `decorate()` or influence any promise's
`overdue`. A second definition of overdue is how the board starts disagreeing
with itself; deadlines stay per promise.

## Membership

Checked in this order, per promise:

1. its id is in `include` — a **pinned** member, whatever its context
2. `canonical(context)` matches a `canonical(alias)`
3. otherwise not a member

`canonical()` folds case, whitespace and wikilink brackets, so `[[Acme CU]]`,
`Acme CU` and `acme cu` are one alias.

**Aliases alone cannot split one customer into two workstreams.** Two efforts
for the same client carry the same `customer`, so they canonicalise to the same
string and no alias set separates them. `include` is the only mechanism that
can, which is why the bootstrap exists: it surfaces the id-slug clusters already
present in the user's own promise ids and prints a ready-to-paste declare
command, so pinning is a one-time confirmation rather than ongoing bookkeeping.

An alias claimed by another project is **refused at write time** — otherwise
membership would depend on the order of the `projects` array.

`openCount` counts members that are open and not dismissed. A *snoozed* member
still counts (it comes back); a *dismissed* one does not.

## Movement, and the two signals

```
lastMovement = the latest of, across ALL members:
                 completedDate | created | the note's own dateModified | history[].ts
movementDays = business days from lastMovement to today
PROJECT_QUIET_DAYS = 10   # two working weeks
```

**`lastVerified` is deliberately not movement.** It records when the system last
*looked*, and a sweep refreshes it on everything it touches. Counting it would
mean a swept ledger can never go quiet: the automated pass meant to notice a
stalled project would be the very thing keeping it looking alive. Movement means
a human did something — closed an item, edited the note, logged an update, or
added new work.

- **quiet** — `status: active`, not snoozed, at least one member, and
  `movementDays >= PROJECT_QUIET_DAYS`.
- **date-slipping** — `status: active`, not snoozed, and `targetDate` is past or
  within `DUE_SOON_DAYS`.

Two properties worth keeping:

- **Quiet does not require open work.** A project whose members are all closed
  but which was never marked `done` has nothing left to surface it, and that is
  exactly the effort that falls out of view. Requiring open members would make
  it permanently silent.
- **A project that just closed its last item moved today**, so it stays quiet-free
  on its own. No grace period is needed, and none exists.

`memberCount >= 1` is load-bearing: a just-declared project with nothing tagged
must be silent, not instantly lagging.

**Do not reuse the `STALE_DAYS_*` constants.** Those are 2/5/10 business days,
calibrated for a single promise. A seven-week effort flagged after two quiet days
is a nag, and a nagging surface gets turned off.

## Off-switches

`snoozedUntil` first (temporary, returns), then `status: done` (permanent, still
rendered). Nothing else — a per-project threshold would mean no surface could
state one number, and this repo has already paid for a threshold that lived in
two places and disagreed.

## Surfaces

- **Projects tab** — every declared project, lagging first, Closed in its own
  section.
- **Board tab** — a "Projects worth a look" block **only when something lags**,
  and nothing at all otherwise. The injection point in the template is
  unconditional and the renderer returns an empty string; removing the marker
  turns a calm board into a hard error, which is the opposite of the intent.
- The headline count gains a lagging clause only when non-zero.

## Bootstrap

`ledger_query.py --projects --candidates` clusters undeclared contexts and prints
member counts, date spans, the **spellings seen**, any id-slug clusters that
suggest a split, and the `project-set` command to declare it. Read-only; it
prints and nothing else.

Near-duplicate spellings are merged into one suggestion on two conservative
signals: a shared first non-org-type token (`Acme CU` + `Acme Credit Union`), and
a bare acronym matching a spelled-out name's initials (`ACU` → `Acme Credit
Union`, 3+ letters only). Two spelled-out names never merge by initials — one
real pair of different customers both initial to the same two letters, and
filing one customer's work under another customer's name is worse than any
convenience. Everything merged is printed, so a wrong grouping is visible before
anything is declared.

## Guardrails

- `project-set` writes `state.json` only and never a note, so it takes no
  `--confirmed` (that flag exists for vault writes).
- A project never changes a promise. Nothing here writes to a member.
- Non-interactive runs may render projects; they never declare one.
