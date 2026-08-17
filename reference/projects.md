# Projects

A **project** is a multi-week effort the user declares, in their own words, and
then stops having to think about. They say what they're taking on and what
belongs in it; the project claims matching work from then on, including work that
arrives later.

**A customer is not a project.** People are pulled into engagements ad hoc, and
that is not an effort anyone owns. Nothing in ADHDecoder may infer a project from
a customer, a cluster, or any other signal. Projects are declared, full stop.

A project **never owns** a promise, never changes one, and never introduces a
second definition of any per-promise state. It is a lens over the ledger.

Implemented by `projects()` and `project_members()` in `scripts/ledger_query.py`
(the read), `project-set` in `scripts/ledger_write.py` (the write), the Projects
tab + Board-tab block in `scripts/render-board.py`, and the declare conversation
in `skills/projects/`. This file is the spec those share; the numbers below are
stated here **once**.

## The record

In the `projects` array of `state.json`. Field set and validation in
`scripts/ledger_schema.py`.

| Field | Meaning | Surface |
|---|---|---|
| `id` | stable slug; `--project <id>` filters to its members | card anchor, CLI |
| `name` | display name | card heading, lagging row |
| `status` | `active` or `done` | `done` renders in a **Closed** section |
| `note` | **the user's own sentence about what this is** | card, directly above the rules |
| `keywords` | words/phrases that claim an item | `Matches` chips; named in each member's reason |
| `aliases` | context spellings that claim an item | `Matches` chips |
| `sources` | narrows to items from these systems | `Matches` chips |
| `include` | promise ids pinned in regardless | member reason `pinned` |
| `exclude` | promise ids kicked out | its own **Excluded** block + the undo command |
| `targetDate` | the project's own date | badge; drives date-slipping |
| `checkInEvery` | days between check-ins | chip; drives due-for-check-in |
| `lastCheckIn` | reset by `--checked-in` | card meta, with the derived next date |
| `snoozedUntil` | quiet until this date | badge; suppresses lagging |
| `updated` | last write | card footer |

**`note` is the load-bearing field, not a comment.** It holds the sentence the
user actually said, and it renders **immediately above the rules that claim to
implement it**. The rules are a lossy translation of that sentence; putting the
two adjacent is what keeps the translation honest — "pull in tasks about tech
writing" sitting above a lone `integration` chip is a mismatch you can see in one
glance. Who a project is for or with goes in this sentence too.

**Deliberately not fields:** a separate `purpose` (that is `note`); a
`stakeholders` list (nothing would read it, and a name nothing reads is how a
person gets misgendered on the next run — see the `people` map); a `paused`
status (`snoozedUntil` already means "quiet, and it comes back"); project
`history` (members carry their own, and a history nothing renders is where a
correction goes to die).

**`targetDate` is scoped.** It drives the project-level slipping signal and
renders on the card, and that is all. It must never reach `decorate()` or
influence any promise's `overdue` — a second definition of overdue is how the
board starts disagreeing with itself.

## Membership

One sentence, and the card states it: **anything pinned in, plus anything whose
title or what matches a keyword, plus anything for one of these contexts —
narrowed to these sources if any are named, minus anything excluded.**

Checked in this order, per promise:

1. id in `exclude` → **not** a member, whatever else matches. A correction made
   by hand is never overridden by a rule.
2. id in `include` → member, reason `pinned`. This is the only way to split one
   customer into two workstreams, since both carry the same `customer`.
3. a keyword hit, or `canonical(context)` matching an alias.
4. if `sources` is named, the promise must also come from one of them.

**Every member carries the reason it is one**, rendered per member. A project
that cannot say why something is in it is a project that assumes.

An alias claimed by another project is **refused at write time** — otherwise
membership would depend on the order of the `projects` array. Keyword overlap
between projects is *fine* and is not refused: two efforts legitimately share a
word, and both cards render the member correctly. Only the per-promise
`_projectId` stamp picks a single owner, deterministically by sorted id; it is a
tiebreak for grouping, **not** a statement of ownership, and nothing renders it.

`openCount` counts members that are open and not dismissed. A *snoozed* member
still counts (it comes back); a *dismissed* one does not.

### Keyword matching

Word-boundary, against **`title` + `what` only**.

- **Not `note`** (the promise's). It is the latest-state summary, overwritten as
  reality changes, so matching it would make membership vary with prose churn: an
  item joins when someone writes "integration" into a status line and leaves when
  it is rewritten, taking its movement stamps with it and flipping `quiet` on and
  off with no user action. Membership must be stable. Measured, too: `note` is
  present on ~5% of real records and is the longest prose in them.
- **Not `context`.** That is exactly what `aliases` matches, canonically.
  Matching it again with looser semantics would let the keyword "integration"
  claim every promise for a customer called Integration Partners.
- **A phrase, not a bag of tokens.** "tech writing" must not match "writing the
  tech spec".
- **No stemming.** "integration" does not match "integrations". That is a real
  miss, and the answer is the preview showing it rather than a guess nobody can
  predict from the card. Under-matching is visible; over-matching invents a
  project's story.

`sources` is matched as a substring against `source.type` **and** `source.url`,
because the type alone cannot say where something came from — on a note-backed
ledger nearly every record is `note-extracted`, which records how the link was
found, not what system it points at. The URL does say: a wiki path separates a
wiki page from a ticket on the same host.

**The `reference/sweep.md` keyword warning does not apply here.** That rule
forbids a keyword hit as *evidence of a stall against a live source*, because a
mention search that never opened the thread produced false alarms aimed at real
people. Project membership is a lens over records already in the ledger and
already reconciled: a false positive puts a row on a card with a visible reason,
not a false nudge at a person. Different risk class.

### The preview is not optional

The words a user says are rarely the words in their ledger. Measured against a
real ledger of 100+ promises: "tech writing" matched **0**, "documentation"
matched **0**; what was actually written there was `doc`, `docs`, `Confluence
page`, `playbook`. A project declared in the user's phrasing would claim nothing
and sit empty forever, looking like it worked.

So `project-set` **always** computes and prints the members its rules would
claim, with reasons, before writing — and says so loudly when the answer is
zero. The declare conversation must show that preview and never write past an
unexamined empty one.

## Movement and the three signals

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
a human did something.

Per-promise staleness now uses the same rule and the same function
(`last_touched()` in `scripts/ledger_query.py`, which `last_movement()` maxes over
a project's members). One idea, two scopes, so a project and its members can
never disagree about what counts as progress.

In precedence order, `lag` staying a single value:

- **quiet** — active, not snoozed, at least one member, `movementDays >=
  PROJECT_QUIET_DAYS`, **and no check-in rhythm set**.
- **due-for-check-in** — `checkInEvery` set and `lastCheckIn + checkInEvery <=
  today`, where `lastCheckIn` falls back to the declare date.
- **date-slipping** — `targetDate` past or within `DUE_SOON_DAYS`.

**A check-in rhythm REPLACES the quiet threshold.** Stacking them would flag the
same silence twice, days apart, and force the card to state two numbers — the
exact harm the state-it-once rule exists to prevent. The user's explicit rhythm
wins; `PROJECT_QUIET_DAYS` stays the single stated default for every project
without one.

The accepted cost: a project whose members are three months dead reads healthy
while its owner keeps stamping check-ins. It is bounded by an existing surface —
the card always prints `last movement`, so dead members stay visible even when
nothing lags.

Check-in is **calendar** days, because "every 14 days" means two weeks; business
days would silently make it nearer three. That is a deliberate divergence from
`PROJECT_QUIET_DAYS`, which is business days because it measures working silence.

Two properties worth keeping:

- **Quiet does not require open work.** A project whose members are all closed
  but which was never marked `done` has nothing left to surface it, and that is
  exactly the effort that falls out of view.
- **A project that just closed its last item moved today**, so it stays silent on
  its own. No grace period is needed, and none exists.

`memberCount >= 1` for quiet, and a never-checked-in project dates from its
declare date rather than coming due immediately — a just-declared project must be
silent, not instantly lagging, and firing a check-in inside the conversation that
created it would be both annoying and dishonest.

**Do not reuse the `STALE_DAYS_*` constants** (2/5/10). Those are calibrated for
a single promise; a seven-week effort flagged after two quiet days is a nag.

## Off-switches

`snoozedUntil` first (temporary, returns), then `status: done` (permanent, still
rendered). Checking in resets the rhythm and needs no note — projects have no
`history` to append one to, and requiring one would force it to overwrite the
`note` sentence.

## Surfaces

- **Projects tab** — every declared project, lagging first, Closed in its own
  section. Each card: the sentence, the rules, every member with its reason, the
  excluded block, the dates.
- **Board tab** — a "Projects worth a look" block **only when something lags**,
  and nothing otherwise. The template's injection point is unconditional and the
  renderer returns an empty string; removing the marker turns a calm board into a
  hard error, which is the opposite of the intent.
- The headline count gains a lagging clause only when non-zero.

## The context-cluster helper

`ledger_query.py --projects --candidates` lists context clusters nobody has
claimed. It is **not** a list of candidate projects, and it must never be
presented as one — that framing is what made a customer look like a project. Its
job is narrow: finding ids to pin, and revealing the several spellings one
customer has accumulated. Offer it only when the user asks what could be grouped.

## Version

`projects` arrived in schemaVersion 3, and the rule fields were added to it
without a further bump: no file in existence had a `projects` array, so nothing
was ever written against the narrower vocabulary. `validate_project()` refuses
unknown fields, so an older plugin reading a newer file produces a `doctor`
report rather than a silent misread.

## Guardrails

- `project-set` writes `state.json` only and never a note, so it takes no
  `--confirmed` (that flag exists for vault writes).
- A project never changes a promise. Nothing here writes to a member.
- Non-interactive runs may render projects; they never declare one.
- Never infer a project. Never present a customer as one.
