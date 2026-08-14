---
name: projects
description: >
  Declare and track a larger project: a multi-week effort the user takes on,
  which then claims matching work as it arrives. Use when the user says things
  like "start a new project", "I'd like to track X as a project", "I've been
  assigned X", "add this to my <name> project", "how are my projects", "check in
  on <project>", or "stop tracking <project>". Interviews the user one question
  at a time and always previews what a project would claim before writing it.
  Writes only state.json in the instance layer, never a note, and never infers a
  project from a customer or any other signal.
---

# Projects (declare an effort, then stop thinking about it)

A project is **declared, never inferred**. Read `reference/projects.md` for the
record, the membership rule and the three lag signals; do not restate the
thresholds here.

**The rule that matters most:** a customer is not a project. People get pulled
into an engagement ad hoc, and that is not an effort they own. Never propose a
project because a customer has a lot of items, never turn a context cluster into
one unprompted, and never answer "what are my projects?" with anything the user
did not declare.

## Declaring one (the main flow)

Triggered by "start a new project", "I'm taking on X", "track X as a project".
**One question at a time, never a wall.** Every question after the first two is
optional - offer it, accept "skip", and move on. Do not interrogate.

**1. What is it called?** Their words become `--name`; slug it for `--id`.

**2. What belongs in it?** Let them answer in their own words and keep that
sentence verbatim as `--note`. It renders directly above the rules on the board,
so the sentence and its translation stay side by side.

Then translate it into rules and say what you picked:

- `--keyword` for the words that would appear in an item's title. **Propose from
  their sentence, then check your own guess** - the words people say are usually
  not the words in their ledger.
- `--source` only if they named a system ("in Confluence", "from Slack"). Match
  it as a url fragment when a type would not do: on a note-backed ledger nearly
  every record has the same type, so a wiki path is what actually separates a
  wiki page from a ticket on the same host.
- `--alias` **only if they volunteer a customer** ("and everything for Acme").
  Never ask for it as a default question: a project that quietly swallows a whole
  customer is the premise this feature exists to reject.

**3. Preview, and do not skip this.** Run:

```
python3 <plugin-root>/scripts/ledger_write.py --config <cfg> --dry-run project-set \
    --id <slug> --name "<name>" --note "<their sentence>" [--keyword ...] [--source ...]
```

It prints every item the rules would claim **and why each one matched**. Show
that list. Three outcomes, all normal:

- **Nothing matches.** Extremely common on the first try, and the whole reason
  this step exists. Say so plainly, look at what the items are actually called,
  and try their vocabulary instead. Never write a project past an unexamined
  empty preview - it would sit there looking like it worked.
- **Too much matches.** A broad word drags in unrelated work. Narrow the keyword
  or add `--source`; do not reach for `--exclude` to paper over a bad rule.
- **About right.** Some strays are fine - `--exclude <id>` removes one and the
  card shows what was excluded.

**4-6. Then offer, one at a time, and let them skip any:** a target date
(`--target-date`); a check-in rhythm ("how often do you want to look at this?"
-> `--check-in-every <days>`); and who it is for or with, which goes into the
`--note` sentence rather than a field of its own.

**Then write it** by re-running without `--dry-run`. No `--confirmed`: this
writes `state.json` only, never a note.

## Adding and removing work by hand

- `--include <promise id>` pins something the rules miss. This is the only way to
  split one customer into two workstreams, since both carry the same context.
- `--exclude <promise id>` kicks out a wrong match. The card lists what was
  excluded with the undo command, so a mistake is findable.
- `--keyword` / `--unkeyword` adjust the rules afterwards. Preview again.

## Checking in

"Check in on <project>" -> show its members and what moved, then
`project-set --id <id> --checked-in` to reset the clock. No note is needed.

If the check-in is due but nothing has moved, say that plainly and offer the
snooze as readily as the chase - a project is often quiet for a good reason the
ledger cannot see.

## Status

"How are my projects?" -> `ledger_query.py --config <cfg> --projects`. Lead with
anything lagging, using `rollup.lagReason` as the fact and your own words for the
framing. A project with zero open items and no `done` status is a project with
nothing scheduled, not a finished one; say so.

`--project <id>` scopes any selector to one project's members.

## Ending one

`--status done` closes it permanently (it still renders, in a Closed section).
`--snooze <date>` quiets it temporarily.

## The context-cluster helper

`ledger_query.py --projects --candidates` lists contexts nobody has claimed.
**It is not a list of candidate projects.** Use it only when the user asks what
could be grouped, or to find ids to pin and spellings to alias. Never volunteer
it as an answer to "what should I be tracking".

## Guardrails

- Declared only. Never infer a project, never present a customer as one.
- Never write past an empty preview.
- `state.json` only; never a note, never an outward message.
- Non-interactive runs may render projects; they never declare one.
