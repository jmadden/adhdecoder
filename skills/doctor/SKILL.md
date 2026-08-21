---
name: doctor
description: >
  Read-only health check for an ADHDecoder setup: confirms config.json parses
  and required fields are present, the active ledger backend resolves and its
  paths are writable, and each enabled source's connector is available. Use when
  the user says things like "check my setup", "adhdecoder doctor", "is this
  configured right", "diagnose ADHDecoder", or "why isn't the decoder working".
  Reports OK vs each gap with a one-line fix. Presence-only (no live calls to
  sources); writes nothing, sends nothing.
---

# Doctor (health check)

Tell the user in one pass whether their setup is sound, and for anything wrong,
the single fix. Read `reference/onboarding.md` (the checks) and
`reference/ledger-backend-interface.md` (backend resolution) before running.
This skill is **read-only**: it writes nothing and makes no live calls to sources.

## What this does / does not do

- **Validates, never repairs.** Reports gaps + fixes; it does not edit config
  (that is `setup`'s job) and does not write state.
- **Presence-only.** Connector checks confirm availability in the session; no
  read/write call is made to any source.
- **Writability by metadata.** Path checks use filesystem metadata (exists +
  writable), never a trial write.

## The checks

Run each and report OK or a gap. Match field names to
`config/decoder.config.example.json` exactly.

0. **Runtime present.** Report this FIRST, because several later checks run
   scripts and would otherwise fail for a reason that looks like a config
   problem:

   ```
   python3 --version
   python3 <plugin-root>/scripts/ledger_query.py --help
   ```

   - Both succeed -> OK, name the version.
   - `python3` not found -> gap: "install Python 3 and make sure `python3`
     resolves; nothing needs installing with it." A plugin cannot prompt for a
     runtime at install time, so this check is the only place a missing one
     surfaces before it breaks a task.
   - The script errors -> report the message verbatim. It should never be a
     missing module: the scripts are **stdlib only** by hard rule. An
     `ImportError` means someone reintroduced a dependency, which is a bug in the
     plugin, not in the user's setup.

1-3, 5. **Config, backend, write mode, record store.** One command; do not
   re-derive any of it:

   ```
   python3 <plugin-root>/scripts/doctor_check.py --config <instance config.json>
   ```

   It reports each as `OK`, `GAP` (with a one-line fix) or `note`, and exits 1
   if any gap was found, 2 if the config could not be read at all. Relay its
   findings verbatim - especially the record-store ones, which name each failing
   file and its exact symptom ("frontmatter never closes", "missing the `task`
   tag", "block scalar (|) in key 'summary' is not supported"). Paraphrasing
   loses the fix.

   What it covers, and why each matters:
   - **config** parses and has `storage.instancePath` + `identity` + either an
     enabled source or a backend.
   - **backend** resolves to a `ledger-<X>` skill this plugin actually ships,
     and its paths exist and are writable. The deprecated `tasknotes` alias
     still resolves, and is flagged rather than passing silently.
   - **write mode** is coherent: `readwrite` without
     `cutover.singleWriterConfirmed` is a gap, because that combination silently
     stays read-only. On `builtin` it is a harmless note - builtin is always
     writable.
   - **record store**: every note parses and is visible. An unparseable record
     is **silently invisible** - not a promise, not on the board, not in any
     count - so a single malformed file can hide real work indefinitely. A note
     that parsed but is ambiguous (a duplicate key, a non-canonical value)
     reports as a note, not a gap.

   Validate, never repair. The fixes are the user's call, or `setup`'s.

4. **Connectors present.** This one is **yours**, and the script says so: it
   reports connectors as `unchecked` and lists the enabled sources, because a
   subprocess cannot see which MCP connectors the running session has attached.
   A false all-clear here would be worse than saying nothing.

   For each enabled source, confirm the mapped `~~category` connector (per
   `CONNECTORS.md`) is actually available in this session. `~~knowledge` is a
   filesystem path (`storage.knowledgePath`), already covered by the script, not
   a connector.
   - Gap -> "chat enabled but no chat connector -> connect it or disable the
     source."

6. **Schema integrity** (`reference/ledger-schema.md`). Run the validator rather
   than eyeballing the file:

   ```
   python3 <plugin-root>/scripts/validate-state.py --config <instance config.json>
   ```

   It reports the declared `schemaVersion`, then every field the schema does not
   define, at every level the schema defines (top level, promise record, itemMeta
   entry, project record, `suppressed` entry):
   - **unknown key -> a gap.** A field no schema version defines is a run that
     invented vocabulary. Report it with "name it in `ledger-schema.md` or remove
     it by hand."
   - **deprecated key -> a note** naming its replacement (e.g. `createdAt` ->
     `created`). Not a gap: an old file is old, not broken.
   - Exit status is 1 when gaps exist, 0 when only notes do.

   This check exists because the schema was prose, so each session invented its
   own names and two fields ended up meaning "this note is malformed" under
   different spellings. One of them was written and never read: a run recorded a
   damaged note and nothing surfaced it for weeks.
   - **Validate, never repair.** Do not rename a field, do not remove one, and
     do not bump `schemaVersion`. Report the edit; the user applies it.

7. **Suppressions and sweep results** (`state.json`). The board recap carries a
   bare `suppressed N` count and `sweepLog` has no surface at all, so this is
   where either is actually accounted for. The **mechanical** half is in the same
   validator run as check 6: a `suppressed` entry with no `reason` reports as a
   gap, an undefined key on one reports as a gap, and a malformed or over-cap
   `sweepLog` reports as a note. Relay those.

   The **reading** half is yours, and it is why this check is not only code:
   - Report each suppression's `reason` in one line, with its `ts` when it has
     one, so a suppressed ref stays accountable rather than becoming permanent by
     default. An old suppression with no reason anyone still recognises is the
     thing to raise. Clearing one is `ledger_write.py suppress --ref REF
     --unsuppress`; never hand-edit the list.
   - Read the most recent `sweepLog` entry's per-source results and say whether
     any source is **responding but returning nothing**. A presence-only
     connector check (check 4) scores such a source OK, so this is the only place
     it surfaces. Judging it needs to know what that source's silence means (a
     quiet day versus a broken query), which is a reading task, not a
     mechanical one: compare against the surrounding runs and say which it looks
     like rather than asserting a fault.

## Report shape

A short list: each check as **OK** or a **gap** with its one-line fix, most
important first (runtime -> config -> backend -> record-store integrity ->
schema -> connectors -> suppressions/sweep results). If
everything passes, say so plainly and point at a first "what's slipping." If
config is entirely missing, skip straight to "run `setup`."

## Guardrails

- Read-only. Writes no config/state, makes no live source calls, sends nothing.
- No invented fields; validate only what the config template and
  `reference/ledger-schema.md` define.
- Advisor by default: report and prescribe the fix; let `setup` apply it.
