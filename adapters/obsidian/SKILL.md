---
name: ledger-obsidian
description: >
  Obsidian ledger backend for ADHDecoder. Applies when config.ledger.backend is
  "obsidian" (default is builtin state.json); also accepts the deprecated alias
  "tasknotes" for existing configs. Reads the user's Obsidian notes
  (storage.knowledgePath + overrides.tasksDir) - Markdown with YAML
  frontmatter, as written by the Obsidian TaskNotes plugin - maps each to a
  promise, and serves the ledger's read/Query operations so chase-in, drift,
  and panic run unchanged against real tasks. Read-only by default: mark-met /
  log-update actions become drafts for the user to apply. When
  config.ledger.writeMode is "readwrite" AND cutover.singleWriterConfirmed is
  true, it also serves deliberate writes (mark met, approved updates, approved
  promotions) directly to the notes. Usually invoked via the ledger's backend
  selection, not directly.
---

# Ledger backend: Obsidian

An OPTIONAL ledger backend. Serves the ledger's **read/Query** operations from
the user's existing Obsidian notes instead of `state.json`, without a second
store. Read `adapters/obsidian/reference.md` (the full spec + field mapping)
and `reference/ledger-schema.md` (the promise shape the read-side skills
expect) before running.

Active only when `config.ledger.backend == "obsidian"`. **Deprecated alias:** a
legacy `config.ledger.backend == "tasknotes"` still activates this adapter -
treat it as `obsidian` and surface a one-line note ("ledger backend renamed
`tasknotes` -> `obsidian`; update your config at your convenience"). The default
`builtin` (state.json) is unaffected.

**Capability comes from config** (`reference/ledger-backend-interface.md`):
`config.ledger.writeMode: "readonly"` (default) -> read-only, writes are
drafts. `"readwrite"` AND `config.ledger.cutover.singleWriterConfirmed: true`
-> writable (see Write-back below). `readwrite` WITHOUT that confirmation ->
stay read-only and warn once, pointing at `reference/cutover.md`.

The notes are Markdown with YAML frontmatter, as written by the Obsidian
**TaskNotes** plugin - that is the note format this adapter reads, not its name.

## Locate

- `tasksDir = storage.knowledgePath + "/" + storage.overrides.tasksDir` (e.g.
  `.../Work/Tasks/`).
- Enumerate `*.md` in `tasksDir`. Skip `Archive/` unless the user asks for it.
- Read each note's frontmatter + body. Never open a file with intent to write.

## Parse frontmatter (real YAML, never line-grab)

Parse each note's frontmatter with a **real YAML parser**, never line-by-line
string matching. An empty or missing key (e.g. a blank `due:`) is **absent** -
never read as the next line's value. Confirmed needed on real data: notes
routinely have blank `due:` and `customer:` fields, and a naive line-grab
misreads the following line as that field's value. Treat a key that is present
but empty (`due:`, `due: ""`, `due: null`) identically to the key being missing
entirely.

## Map each note to a promise

Per the field table in `adapters/obsidian/reference.md`:

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
| `deadlineType` | real `due` present -> `hard`; `ongoing` tag (or `scheduled` without `due`) -> `soft`; else default `hard`. An `itemMeta` override wins. |
| `why` | a note `why`/`why:` field if present, else the `itemMeta` overlay, else null |
| `lastVerified` | `dateModified` (or the `itemMeta` verify timestamp if newer) |
| `source` | the best ACTIONABLE ref extracted from the note (see below), else the note link with `noteOnly: true`. An `itemMeta` reconcile-enriched source wins. |
| `noteRef` | `{ url }` = the `obsidian://` link to the note itself |
| `noteOnly` | `true` only when no actionable ref was found and `source` fell back to the note link |
| `history` | the body's `update <ISO> - ...` lines, read verbatim (never modified) |

**Extract the actionable source** from the note's frontmatter/body, most
relevant wins: an issue key (e.g. an `ISSUE-123` pattern) -> the tracker issue
URL; a chat permalink / archive URL in the body; an email/thread id; a doc/wiki
URL; a CRM case number -> its canonical URL. Set `source` to that and `noteRef`
to the `obsidian://` note link. If none is found, `source` = the note link and
`noteOnly: true`. Link, never paste the note body.

Same verify spirit as the sweep: `status: done` is closed - never chase it.

## Overlay the itemMeta companion (read time)

An Obsidian note is read-only, so ADHDecoder-owned overlay fields live in the
`state.json` `itemMeta` companion keyed by the note's item id, NEVER in the
note. At read time, overlay `itemMeta[<id>]` onto the derived promise:
`snoozedUntil`, a `deadlineType` override, verify metadata
(`verifyStatus`/`verifyReason`/`lastVerified`), and a reconcile-enriched
`source` (with `noteOnly` cleared). This is what lets snooze, mark-ongoing, and
reconcile's discovered source link persist for a note the plugin will not
touch.

## Query (the read contract chase-in / drift / panic call)

Return promises in the exact shape `reference/ledger-schema.md` defines, so the
read-side skills need no change:

- Recompute `overdue` (`expectBy` < today and open) and `stakes` at read time.
  An item with no `due` can never be overdue - it stays visible but off the
  chase board.
- The board is the **union** of: open Obsidian notes (mostly `i-owe-them`) + any
  `state.json` promises from the builtin companion (sweep-found `they-owe-me`
  that were never promoted to a note). Read both; do not merge the stores.
  If an item appears in both (same `source` link), prefer the note and drop
  the duplicate.
- Group and sort exactly as the builtin Query: They owe me / I owe them, overdue
  first, high-stakes flagged.

Full unification of the two stores is deferred; v1 just reads the union.

## Read-only mode (default - never touches the vault)

- Never write, create, rename, move, or modify any note or Radar file.
- Never auto-create a note (including for sweep-found `they-owe-me` items -
  those stay in the builtin `state.json` companion).
- When the user acts on a board item ("mark met", "handled", "log an update",
  "flip to they-owe on delivery"), produce a **draft edit or instruction** for
  the user to apply by hand, or let their existing Decoder handle the write.
- **Snooze / mark-ongoing / verify metadata go to the `itemMeta` companion**
  (`state.json`), keyed by the note's item id - never the note. A delivery flip
  registers a new they-owe follow-up in `state.json` (plus a draft to update the
  note), rather than rewriting the note's direction.

## Write-back (readwrite mode, post-cutover only)

Active ONLY when `writeMode == "readwrite"` AND
`cutover.singleWriterConfirmed == true` (see `reference/cutover.md`). Then the
adapter serves these write operations, each **only from an explicit user action
in the conversation** - never from a sweep or a non-interactive `daily-run`:

- **markMet(id).** Set `status: done`, `completedDate: <YYYY-MM-DD>`, refresh
  `dateModified` (ISO 8601); append one body line
  `update <ISO> - marked met via ADHDecoder`.
- **update(promise).** Map changed promise fields back to their frontmatter
  keys (`due`, `priority`, `status`, `projects`, `customer`, `requester`);
  refresh `dateModified`; append one `update <ISO> - ...` body line describing
  the change. Show the diff as a draft first; write on approval.
- **promote(promise).** Create a NEW note in `tasksDir` from an approved
  promotion draft, canonical TaskNotes frontmatter (`title`, `status: todo`,
  `priority`, `due` when known, `dateCreated`/`dateModified`, `projects`,
  `customer`, `requester`, `tags` including `task`), body opening with a
  `> **Summary:**` blockquote and the source link. Then cross-link per
  `reference/promotion.md`. Never from a sweep.

**Write rules (hard):**

- Round-trip the frontmatter with a real YAML parser; **preserve every key you
  do not understand** and the body verbatim except the one appended line.
- Atomic write (write temp, replace). One file per operation.
- Write only TaskNotes-canonical fields into the note. ADHDecoder-owned
  metadata (`snoozedUntil`, `deadlineType` override, verify results, enriched
  source links) STAYS in the `itemMeta` companion even in readwrite - notes
  hold task truth, not decoder bookkeeping.
- Never rename or move a note (the file path is the promise id).
- Never delete; `done` + `completedDate` is the close.
- Non-interactive runs never write a note, regardless of mode.

## Coexistence

In the default read-only mode there is no writer conflict: the user's existing
Decoder keeps maintaining these files on its schedule while ADHDecoder reads
them. Do not ask the user to disable their scheduled Decoder while read-only.
At **cutover** (`reference/cutover.md`) the old writer is retired first, the
user confirms single-writer in config, and only then does readwrite activate.

## Guardrails

- Read-only by default: zero vault writes until cutover is confirmed in config.
- In readwrite: writes only on explicit user action; never auto-create notes
  from a sweep; promotion is always an approved draft.
- Hide raw feeds: link via `obsidian://`, never copy note bodies into another
  store.
- Stakes computed at read time; honor `stakesOverride` if present.
