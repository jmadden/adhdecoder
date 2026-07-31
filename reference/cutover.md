# ADHDecoder — Cutover (read-only -> single read-write owner)

Written 2026-07-31. The deliberate, reversible procedure by which ADHDecoder
stops shadowing an existing task writer and becomes the single owner of a
note-backed ledger store. Generic: nothing here names a specific adapter; the
active backend just gains the writable capability per
`reference/ledger-backend-interface.md`.

## Preconditions (parity - do not cut over early)

All four, verified over at least ~5 business days of read-only coexistence:

1. **Board parity.** `chase-in`, `drift`, `panic`, and the board consistently
   reflect the real state of the notes - no misparsed frontmatter, no phantom
   overdue items, direction and stakes sensible. Spot-check against the old
   writer's output if one exists.
2. **Sweep parity.** Scheduled `daily-run` sweeps are populating `state.json`
   with real, verified they-owe items (no floods, dedup holding).
3. **Doctor clean.** `doctor` reports no gaps.
4. **The user trusts it.** Cutover is the user's call, never proposed as a
   default. If they hesitate, stay read-only; coexistence is cheap.

## The procedure (order matters)

1. **Retire the old writer FIRST.** The user disables the previous scheduled
   Decoder / automation that writes the notes. ADHDecoder must never share
   write ownership - two writers is how vaults corrupt. Confirm it is off.
2. **Confirm in config.** Set, in the `ledger` block:
   `"writeMode": "readwrite"` and
   `"cutover": { "singleWriterConfirmed": true, "date": "<YYYY-MM-DD>" }`.
   `setup` can do this conversationally; it must restate what the user is
   confirming ("nothing else writes these files anymore") before writing it.
3. **Doctor gate.** Run `doctor`. It must show the backend as writable with
   single-writer confirmed. `readwrite` without `singleWriterConfirmed` is a
   reported gap and the adapter stays read-only.
4. **First write, supervised.** The user marks one real item met from the
   board. Verify the record: canonical fields set, unknown frontmatter keys
   preserved, body intact plus one history line, file neither renamed nor
   moved.
5. **Resume schedule.** Scheduled runs continue unchanged - they still write
   only `state.json` + the board. Note writes remain conversation-only.

## What changes at cutover (and what does not)

| | Read-only (before) | Readwrite (after) |
|---|---|---|
| mark met / update / flip | draft for the user to apply | written to the record on the user's say-so |
| promotion (`reference/promotion.md`) | ready-to-paste draft | `promote()` creates the record |
| sweeps / daily-run | write `state.json` + board only | unchanged - still never write notes |
| snooze / verify / deadlineType override | `itemMeta` companion | unchanged - still `itemMeta`, never the note |
| auto-create tasks | never | still never |
| auto-send / auto-post | never | still never |

## Rollback

Flip `"writeMode"` back to `"readonly"` (leave the cutover block for the
record). Everything written so far is ordinary note edits - visible, in the
user's own format, nothing to undo structurally. Re-enable the old writer only
after the flip.

## Invariants

- Old writer off BEFORE `singleWriterConfirmed: true`. Never both running.
- The confirmation is the user's explicit statement, restated back to them -
  never inferred, never defaulted.
- Cutover changes WHO applies a decision the user already made. It never
  changes WHAT gets decided without them.
