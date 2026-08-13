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

1. **Config parses + required fields.** `config.json` (at
   `storage.instancePath`) is valid JSON and has `storage.instancePath`, an
   `identity`, and at least one enabled source OR a backend + identity.
   - Missing/invalid -> "config not found or unparseable -> run `setup`."
2. **Backend resolves + paths OK.**
   - `builtin`: `<storage.instancePath>/<storage.overrides.stateFile>` (default
     `state.json`) composes and its directory exists / is writable (metadata).
   - non-builtin `X`: a `ledger-X` skill exists, and its paths resolve (e.g. a
     note backend needs `storage.knowledgePath` + `storage.overrides.tasksDir`).
   - Gap -> "backend `<X>` has no `ledger-<X>` skill -> install it or set backend
     to `builtin`," or "state dir not writable -> fix the path / permissions."
3. **Write mode coherent** (`reference/ledger-backend-interface.md`).
   - `ledger.writeMode` absent or `readonly` -> OK (default).
   - `readwrite` + `ledger.cutover.singleWriterConfirmed: true` -> OK; report
     the backend as **writable (post-cutover)** and remind once: "confirm no
     other automation still writes these files."
   - `readwrite` WITHOUT the confirmation -> gap: "writeMode is readwrite but
     cutover isn't confirmed - the backend stays read-only. Follow
     `reference/cutover.md`, or set writeMode back to readonly."
   - `readwrite` on `builtin` -> harmless; note it is ignored (builtin is
     always writable).
4. **Connectors present.** For each `sources[].enabled: true`, the mapped
   `~~category` connector (per `CONNECTORS.md`) is available in the session.
   `~~knowledge` is validated as a filesystem path (`storage.knowledgePath`), not
   a connector.
   - Gap -> "chat enabled but no chat connector -> connect it or disable the
     source."
5. **Record-store integrity** (note-backed backends). Every record in the store
   parses and is visible to the ledger. For a note backend: each file in
   `tasksDir` has a well-formed frontmatter block (opening AND closing
   delimiter, valid YAML) and carries whatever marker the backend requires to
   be enumerated.
   - Gap -> name **every** failing file and its symptom: "`<file>`: frontmatter
     never closes -> add the closing delimiter," or "`<file>`: missing the
     required tag -> the backend cannot see this record," or a construct the
     parser refuses ("block scalar (|) in key 'summary' is not supported") ->
     rewrite that value as a plain or quoted scalar. The parser reports the
     construct and the key by name; relay it verbatim rather than paraphrasing.
   - Also relay any **frontmatter warning**: a record that parsed but is
     ambiguous, e.g. a duplicate key (the last value wins and the other is
     discarded) or a non-canonical field value.
   - This check exists because an unparseable record is **silently invisible**:
     it is not a promise, not on the board, not in any count, and nothing else
     in the system will ever mention it. A single malformed file can hide real
     work indefinitely. Report it here or it goes unreported.
   - Validate, never repair (repair is the user's call, or `setup`'s).

6. **Schema integrity** (`reference/ledger-schema.md`). Run the validator rather
   than eyeballing the file:

   ```
   python3 <plugin-root>/scripts/validate-state.py --config <instance config.json>
   ```

   It reports the declared `schemaVersion`, then every field the schema does not
   define, at all three levels (top level / promise record / itemMeta entry):
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

7. **Suppressions and sweep results** (`state.json`). Both are run-level facts no
   board renders, so this is their surface. The **mechanical** half is in the same
   validator run as check 6: a `suppressed` entry with no `reason` reports as a
   gap, and a malformed or over-cap `sweepLog` reports as a note. Relay those.

   The **reading** half is yours, and it is why this check is not only code:
   - Report each suppression's `reason` in one line, so a suppressed ref stays
     accountable rather than becoming permanent by default.
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
