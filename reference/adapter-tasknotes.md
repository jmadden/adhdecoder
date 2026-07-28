# ADHDecoder — TaskNotes Adapter (read-only v1) Spec

Build input. Drop into the plugin repo as `reference/adapter-tasknotes.md`.
Written 2026-07-27. This is an OPTIONAL ledger backend, not core. The default
backend stays `state.json`; this one is opt-in for a user who already keeps
tasks as Markdown notes (the user's Obsidian TaskNotes).

## Purpose

Let chase-in / drift / panic run on the user's **real existing tasks** instead
of a throwaway `state.json`, WITHOUT a second store and WITHOUT modifying any of
the user's files. Read-only v1: prove ADHDecoder reads real work correctly and
produces a true board, touching nothing.

## Why read-only (v1)

The user's existing Decoder already writes these TaskNotes on a schedule. Two
writers on the same files = conflicts. Read-only means **zero conflict**: the
existing Decoder keeps maintaining the files, ADHDecoder just reads them. They
coexist. Write-back is a later, deliberate step at cutover, not now.

## Config

- Ledger backend selector in `config.json`, e.g.
  `"ledger": { "backend": "tasknotes" }` (default `"builtin"` = `state.json`).
- TaskNotes location comes from existing config: `storage.knowledgePath` +
  `storage.overrides.tasksDir` (e.g. `.../Work/Tasks/`).

## Read (the only thing it does)

Enumerate `*.md` in `tasksDir` (skip `Archive/` unless asked). Parse each
TaskNote's frontmatter + body and map to a promise via the ledger interface:

| Promise field           | Derived from                                                                                                                                                                                                                                    |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                    | the file path (stable)                                                                                                                                                                                                                          |
| `title`                 | `title` / filename                                                                                                                                                                                                                              |
| `context`               | `customer` (fall back to `projects`)                                                                                                                                                                                                            |
| `direction`             | infer from the title verb: "chase / follow up / waiting on / get X from" => `they-owe-me`; "deliver / provide / send / build / answer / set up / configure" => `i-owe-them`. Default `i-owe-them` (TaskNotes are mostly the user's own to-dos). |
| `owner` / who's waiting | `requester` and/or `customer`                                                                                                                                                                                                                   |
| `expectBy`              | `due` if present. If absent: the item is "open, no date" — visible but NOT a chase candidate (can't compute overdue).                                                                                                                           |
| `status`                | `todo` / `in-progress` / `blocked` => open; `done` => closed (skip from chases; may show under "recently done"); use `completedDate`                                                                                                            |
| `stakes`                | `priority` (high/medium/low) plus the standard auto-signals (roster customer, go-live, etc.)                                                                                                                                                    |
| `lastVerified`          | `dateModified`                                                                                                                                                                                                                                  |
| `source`                | an `obsidian://` link to the file                                                                                                                                                                                                               |
| `history`               | read the body's `update <ISO> - ...` lines (do not modify them)                                                                                                                                                                                 |

Same verify spirit as the sweep: `status: done` is closed, never chase it.

**Robust parsing (fix, 2026-07-27).** Parse frontmatter with a real YAML
parser. An empty or missing key (e.g. a blank `due:`) is ABSENT, never a grab of
the next line's value. Confirmed needed: real TaskNotes have blank `due:` and
`customer:` fields, and a naive line-grab mis-read them.

**No-due staleness fallback (fix, 2026-07-27).** On real data ~60% of open
TaskNotes have no `due` date, many of them blocked / high-priority (the
silent-rot zone). Date-based chasing misses all of them. So for an OPEN promise
with no `expectBy`, drift uses a **staleness** signal instead: days since
`lastVerified` (from `dateModified`), counted in BUSINESS days. Surface it when:

- `blocked` or high-stakes AND untouched >= ~2 business days, or
- any open item untouched >= ~5 business days.

Framed observationally ("hasn't moved in N business days"), respecting
`dismissedFromBoard` and `driftClearedUntil`. This makes no-due high/blocked
items visible instead of invisible. It is generic (any backend); the adapter
just supplies `lastVerified` = `dateModified`, and the drift skill implements
the rule.

**deadlineType mapping + itemMeta overlay (fix, 2026-07-27).** Map
`deadlineType` from the note: a real `due` -> `hard`; a note tagged `ongoing`
(or carrying `scheduled` but no `due`) -> `soft`; otherwise default `hard`. This
stops false overdue-chasing on ongoing work (chase-in only date-chases `hard`;
`soft`/`none` surface via drift staleness). ADHDecoder-owned overlay fields for a
read-only note - `snoozedUntil`, a `deadlineType` override, `why`, and verify
metadata - live in the `state.json` `itemMeta` companion keyed by the note's item
id, NEVER written into the note. The Query overlays them at read time.

## Never (hard, read-only)

- Never write, create, rename, move, or modify any TaskNote or Radar file.
- Never auto-create TaskNotes.
- When the user acts on a board item ("mark met", "handled", "log an update"),
  produce a **draft / instruction** for the user to apply (or let the existing
  Decoder handle the write). ADHDecoder writes nothing to the vault in v1.

## Interface (why the other skills don't change)

Implement the ledger's read/Query operations against TaskNotes so `chase-in`,
`drift`, and `panic` call the ledger interface unchanged. Only the backend
swaps; the read-side skills are backend-agnostic.

## They-owe / sweep items (scope note)

TaskNotes are mostly the user's own (`i-owe-them`) work. Sweep-found
`they-owe-me` stalls that the user has NOT promoted to a TaskNote must NOT be
auto-created as TaskNotes (guardrail). For v1 they continue to live in the
builtin `state.json` companion. So with the TaskNotes backend active, the board
is the UNION of: open TaskNotes (mostly i-owe) + any `state.json` promises
(sweep-found they-owe). Full unification is deferred.

## Coexistence

Read-only => no writer conflict. The existing Decoder keeps running and keeps
the user covered. Do NOT ask the user to turn off their scheduled Decoder runs
for this; that only happens later at cutover, when ADHDecoder is at parity and
becomes the single read-write owner.

## Test (do in Cowork, live data)

1. Set `config.ledger.backend = "tasknotes"`.
2. Run `chase-in` and `panic`; confirm they produce a real board from the actual
   TaskNotes (mostly i-owe items, with due dates driving overdue).
3. Confirm ZERO writes: TaskNote file mtimes and `git status` unchanged after.
