# ADHDecoder — Ledger Backend Interface

The core depends on THIS interface, never on a concrete backend. A backend is a
pluggable store of promises. The plugin ships one built-in backend and supports
optional adapters; core skills call only the operations below and branch on a
backend's declared **capability**, never on which adapter it is.

Dependency direction: **adapter -> interface**, never core -> adapter. No core
file names a specific adapter's internals. The only places an adapter is named
are the user's config (`ledger.backend`) and that adapter's own files.

## Backends

- **`builtin`** (default): a self-contained, **writable** store (`state.json`).
- **Optional adapters**: register a name + capability. Example: a **read-only**,
  note-backed adapter that overlays an existing external task store. (One such
  adapter ships separately; see its own reference, core does not depend on it.)

Selected by `config.ledger.backend` (default `builtin`).

**Resolution (how core finds an adapter without naming one):** `builtin` uses
`state.json` directly, no adapter. Any other backend value `X` resolves to the
adapter skill named `ledger-X`, which declares its capability. Core routes by
this convention only, it never hardcodes a specific adapter's name or internals.

## Capability

- **writable** — the backend can create/update promise records and store
  metadata on the record itself.
- **read-only** — the backend's underlying records are not written by ADHDecoder.
  Any promise metadata ADHDecoder needs to persist (verify results, snooze,
  enriched source links) goes into the built-in `state.json` companion, keyed by
  item id (`itemMeta[<id>]`); the underlying record is never mutated, actions
  that would change it become drafts/instructions for the user.

Core branches on `writable` vs `read-only`, not on adapter identity.

## Operations (the contract core calls)

- **locate()** — resolve where the ledger lives, from config.
- **query() / read()** — return the current promise set (open + relevant),
  each promise shaped per `ledger-schema.md`.
- **recordVerify(id, verifyStatus, reason, lastVerified)** — persist reconcile
  metadata (writable: on the record; read-only: into `itemMeta[<id>]`).
- **setSnooze(id, until, note?)** — persist a snooze (same backend-scoped rule).
- **recordSourceLink(id, source)** — persist an enriched source link (same rule).
- **write(promise) / update(promise)** — create or update a promise. Writable
  backends only; a read-only backend instead returns a draft/instruction and
  mutates nothing.

## Rule for core skills

Reference "the active backend" / "a read-only backend" / "the writable backend"
by capability. Never say the name of a specific adapter in a core skill or a
core reference doc. If an example helps, name it once as "e.g. an external
note-backed store" and move on.
