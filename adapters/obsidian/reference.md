# ADHDecoder — Obsidian Adapter Spec

Build input. Drop into the plugin repo as `adapters/obsidian/reference.md`.
Written 2026-07-27; write-back added 2026-07-31. This is an OPTIONAL ledger
backend, not core. The default backend stays `state.json`; this one is opt-in
for a user who already keeps tasks as Markdown notes with YAML frontmatter
(the format the Obsidian **TaskNotes** plugin writes - that is the note
format, not the adapter's name).

## Purpose

Let chase-in / drift / panic run on the user's **real existing tasks** instead
of a throwaway `state.json`, WITHOUT a second store. Two modes:

- **Read-only (default):** prove ADHDecoder reads real work correctly and
  produces a true board, touching nothing.
- **Readwrite (post-cutover):** ADHDecoder is the single owner and serves
  deliberate writes (mark met, approved updates, approved promotions) directly
  to the notes. Gated hard; see Write-back below and `reference/cutover.md`.

## Why read-only is the default

The user's existing Decoder (or any other writer) may still write these notes
on a schedule. Two writers on the same files = conflicts. Read-only means
**zero conflict**: the existing writer keeps maintaining the files, ADHDecoder
just reads them. They coexist. Write-back activates only at cutover, after the
old writer is retired and the user confirms single-writer in config.

## Config

- Ledger backend selector in `config.json`, e.g.
  `"ledger": { "backend": "obsidian", "writeMode": "readonly" }` (default
  backend `"builtin"` = `state.json`; default `writeMode` `"readonly"`).
  A legacy `"backend": "tasknotes"` is accepted as a **deprecated alias** for
  `obsidian` - the adapter treats it identically and surfaces a one-line rename
  note.
- Write-back requires BOTH `"writeMode": "readwrite"` AND
  `"cutover": { "singleWriterConfirmed": true }` in the `ledger` block.
  `readwrite` without the confirmation stays read-only + one warning.
- Note location comes from existing config: `storage.knowledgePath` +
  `storage.overrides.tasksDir` (e.g. `.../Work/Tasks/`).

## Read (the main thing it does)

Enumerate `*.md` in `tasksDir` (skip `Archive/` unless asked). Parse each
note's frontmatter + body and map to a promise via the ledger interface:

| Promise field           | Derived from                                                                                                                                                                                                                                    |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                    | the file path (stable)                                                                                                                                                                                                                          |
| `title`                 | `title` / filename                                                                                                                                                                                                                              |
| `context`               | `customer` (fall back to `projects`)                                                                                                                                                                                                            |
| `direction`             | infer from the title verb: "chase / follow up / waiting on / get X from" => `they-owe-me`; "deliver / provide / send / build / answer / set up / configure" => `i-owe-them`. Default `i-owe-them` (these notes are mostly the user's own to-dos). |
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
the next line's value. Confirmed needed: real notes have blank `due:` and
`customer:` fields, and a naive line-grab mis-read them.

**No-due staleness fallback (fix, 2026-07-27).** On real data ~60% of open
notes have no `due` date, many of them blocked / high-priority (the
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

**Source links (fix, 2026-07-28).** The `source` row above is superseded: do
not default `source` to the `obsidian://` note link. Instead EXTRACT the
underlying actionable ref from the note (an issue key -> tracker URL; a chat
permalink; an email/thread id; a doc/wiki URL; a CRM case number -> its
canonical URL) and set `source` to the most relevant, with `noteRef` = the
`obsidian://` note link. If none is found, `source` falls back to the note link
with `noteOnly: true`. A reconcile-discovered source link is persisted to the
`itemMeta` companion (never the note) and overlaid at read time. See
`reference/source-links.md`.

## Never (hard, read-only mode - the default)

- Never write, create, rename, move, or modify any note or Radar file.
- Never auto-create notes.
- When the user acts on a board item ("mark met", "handled", "log an update"),
  produce a **draft / instruction** for the user to apply (or let the existing
  Decoder handle the write). ADHDecoder writes nothing to the vault while
  read-only.

**Drafts must be persisted AND surfaced.** A mark-met or update draft goes to
the `state.json` `itemMeta` companion as `markMetDraft` / `updateDraft` (never
into the note), and the board renders it in the **Ready to close** group until
the user acts. In read-only mode these accumulate by design - that is the whole
point of the mode - so the group is the only thing keeping the note store and
reality from drifting apart. A draft that is written but never rendered is a
silent regression: the note still says `todo`, the board still paints it as the
user's move, and completed work looks outstanding for as long as nobody asks.
See `reference/ledger-schema.md` and `reference/dashboard.md`.

On apply (readwrite), replace `markMetDraft` with **`appliedMarkMet`**
(`{ ts, completedDate, reason }`) so the companion keeps the audit trail of what
was closed and why.

## Write-back (readwrite mode, post-cutover)

Added 2026-07-31. Gate: `writeMode == "readwrite"` AND
`cutover.singleWriterConfirmed == true`, else stay read-only and warn once.
Every write below happens **only from an explicit user action in the
conversation**; a sweep or non-interactive `daily-run` never writes a note in
any mode.

| Operation | Note effect |
|---|---|
| `markMet(id)` | `status: done`, `completedDate` today, refresh `dateModified`; append `update <ISO> - marked met via ADHDecoder` to the body |
| `update(promise)` | map changed fields to frontmatter (`due`, `priority`, `status`, `projects`, `customer`, `requester`); refresh `dateModified`; append one `update <ISO> - ...` line. Draft the diff first, write on approval |
| `promote(promise)` | create a NEW note from an approved promotion draft (see `reference/promotion.md`): canonical TaskNotes frontmatter incl. `tags: [task, ...]`, `status: todo`, `dateCreated`/`dateModified`, `requester`, `due` when known; body opens `> **Summary:**` with a `Report to:` line and the source link |
| delivery flip | with write-back the flip may (on approval) update the note itself: retitle intent stays, but since renames are forbidden, write the flip as frontmatter/status change + history line, and register the they-owe follow-up per the ledger |

Hard rules: real-YAML round-trip preserving unknown keys and the body verbatim
(except the appended line); atomic write; never rename/move (path = id); never
delete; TaskNotes-canonical fields only - `snoozedUntil`, `deadlineType`
override, verify metadata, enriched source links STAY in the `itemMeta`
companion even in readwrite.

## Interface (why the other skills don't change)

Implement the ledger's read/Query operations against the notes so `chase-in`,
`drift`, and `panic` call the ledger interface unchanged. Only the backend
swaps; the read-side skills are backend-agnostic.

## They-owe / sweep items (scope note)

These notes are mostly the user's own (`i-owe-them`) work. Sweep-found
`they-owe-me` stalls that the user has NOT promoted to a note must NOT be
auto-created as notes (guardrail, both modes). They live in the builtin
`state.json` companion. So with the Obsidian backend active, the board is the
UNION of: open notes (mostly i-owe) + any `state.json` promises (sweep-found
they-owe), deduped by source link. Unification happens through **deliberate
promotion** (`reference/promotion.md`): the user approves a promotion draft,
readwrite creates the note, and the `state.json` record collapses to a
cross-reference.

## Coexistence and cutover

Read-only => no writer conflict. The existing Decoder keeps running and keeps
the user covered. Do NOT ask the user to turn off their scheduled Decoder runs
while read-only; that happens at **cutover** (`reference/cutover.md`), when
ADHDecoder is at parity, the old writer is retired, the user confirms
single-writer in config, and readwrite activates.

## Test (do in Cowork, live data)

1. Set `config.ledger.backend = "obsidian"` (a legacy `"tasknotes"` still works
   as a deprecated alias).
2. Run `chase-in` and `panic`; confirm they produce a real board from the actual
   notes (mostly i-owe items, with due dates driving overdue).
3. Confirm ZERO writes: note file mtimes and `git status` unchanged after.
