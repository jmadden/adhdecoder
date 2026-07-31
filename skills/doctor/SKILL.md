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

## Report shape

A short list: each check as **OK** or a **gap** with its one-line fix, most
important first (config -> backend -> connectors). If everything passes, say so
plainly and point at a first "what's slipping." If config is entirely missing,
skip straight to "run `setup`."

## Guardrails

- Read-only. Writes no config/state, makes no live source calls, sends nothing.
- No invented fields; validate only what the config template defines.
- Advisor by default: report and prescribe the fix; let `setup` apply it.
