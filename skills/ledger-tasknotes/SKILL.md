---
name: ledger-tasknotes
description: >
  Read-only TaskNotes ledger backend for ADHDecoder. Applies only when
  config.ledger.backend is "tasknotes" (default is builtin state.json). Reads
  the user's Obsidian TaskNotes (storage.knowledgePath + overrides.tasksDir),
  maps each to a promise, and serves the ledger's read/Query operations so
  chase-in, drift, and panic run unchanged against real tasks. Never writes,
  creates, renames, or modifies any vault file; mark-met / log-update actions
  become drafts for the user to apply. Usually invoked via the ledger's backend
  selection, not directly.
---

# Ledger backend: TaskNotes (read-only v1)

An OPTIONAL ledger backend. Serves the ledger's **read/Query** operations from
the user's existing Obsidian TaskNotes instead of `state.json`, without a second
store and without touching a single vault file. Read
`reference/adapter-tasknotes.md` (the full spec + field mapping) and
`reference/ledger-schema.md` (the promise shape the read-side skills expect)
before running.

Active only when `config.ledger.backend == "tasknotes"`. The default `builtin`
(state.json) is unaffected. Writes are never served here (see Read-only).

## Locate

- `tasksDir = storage.knowledgePath + "/" + storage.overrides.tasksDir` (e.g.
  `.../Work/Tasks/`).
- Enumerate `*.md` in `tasksDir`. Skip `Archive/` unless the user asks for it.
- Read each note's frontmatter + body. Never open a file with intent to write.

## Parse frontmatter (real YAML, never line-grab)

Parse each note's frontmatter with a **real YAML parser**, never line-by-line
string matching. An empty or missing key (e.g. a blank `due:`) is **absent** -
never read as the next line's value. Confirmed needed on real data: TaskNotes
routinely have blank `due:` and `customer:` fields, and a naive line-grab
misreads the following line as that field's value. Treat a key that is present
but empty (`due:`, `due: ""`, `due: null`) identically to the key being missing
entirely.

## Map each TaskNote to a promise

Per the field table in `reference/adapter-tasknotes.md`:

| Promise field | From |
|---|---|
| `id` | the file path (stable) |
| `title` | `title` / filename |
| `context` | `customer` if present and non-empty (fall back to `projects`) |
| `direction` | title verb: chase / follow up / waiting on / get X from -> `they-owe-me`; deliver / provide / send / build / answer / set up / configure -> `i-owe-them`. Default `i-owe-them`. |
| `owner` | `requester` and/or `customer` (who is waiting) |
| `expectBy` | `due` if present and non-empty. Blank/missing `due` -> open, no date: visible but NOT a chase candidate (no overdue) - see `drift`'s no-due staleness fallback instead. |
| `status` | `todo`/`in-progress`/`blocked` -> open; `done` -> closed (skip chases; may show under "recently done"), use `completedDate` |
| `stakes` | `priority` (high/medium/low) + standard auto-signals (roster customer, go-live, ...) |
| `lastVerified` | `dateModified` |
| `source` | an `obsidian://` link to the file |
| `history` | the body's `update <ISO> - ...` lines, read verbatim (never modified) |

Same verify spirit as the sweep: `status: done` is closed - never chase it.

## Query (the read contract chase-in / drift / panic call)

Return promises in the exact shape `reference/ledger-schema.md` defines, so the
read-side skills need no change:

- Recompute `overdue` (`expectBy` < today and open) and `stakes` at read time.
  An item with no `due` can never be overdue - it stays visible but off the
  chase board.
- The board is the **union** of: open TaskNotes (mostly `i-owe-them`) + any
  `state.json` promises from the builtin companion (sweep-found `they-owe-me`
  that were never promoted to a TaskNote). Read both; do not merge the stores.
  If an item appears in both (same `source` link), prefer the TaskNote and drop
  the duplicate.
- Group and sort exactly as the builtin Query: They owe me / I owe them, overdue
  first, high-stakes flagged.

Full unification of the two stores is deferred; v1 just reads the union.

## Read-only (hard - v1 never touches the vault)

- Never write, create, rename, move, or modify any TaskNote or Radar file.
- Never auto-create a TaskNote (including for sweep-found `they-owe-me` items -
  those stay in the builtin `state.json` companion).
- When the user acts on a board item ("mark met", "handled", "log an update"),
  produce a **draft edit or instruction** for the user to apply by hand, or let
  their existing Decoder handle the write. ADHDecoder writes nothing to the
  vault in v1.

## Coexistence

Read-only means no writer conflict: the user's existing Decoder keeps
maintaining these files on its schedule while ADHDecoder reads them. Do not ask
the user to disable their scheduled Decoder; that happens later at cutover, when
ADHDecoder becomes the single read-write owner.

## Guardrails

- Read-only: zero vault writes, ever, in v1.
- Never auto-create tasks; write actions are drafts.
- Hide raw feeds: link via `obsidian://`, never copy note bodies into another
  store.
- Stakes computed at read time; honor `stakesOverride` if present.
