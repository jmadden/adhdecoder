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

## Write mode (how an adapter's capability is selected)

Some adapters can serve both capabilities. Which one is active comes from
config, never from the adapter's mood:

- `config.ledger.writeMode`: `"readonly"` (default) or `"readwrite"`.
- `builtin` ignores `writeMode`; it is always writable.
- An adapter that supports write-back declares **read-only** under `readonly`
  and **writable** under `readwrite` — but `readwrite` only takes effect when
  `config.ledger.cutover.singleWriterConfirmed` is `true`. If `writeMode` is
  `readwrite` without that confirmation, the adapter MUST stay read-only and
  surface a one-line warning pointing at `reference/cutover.md`. This is the
  single-writer rule enforced in config: two writers on the same files is how
  stores corrupt.
- An adapter that cannot write (or has no write-back implemented) ignores
  `writeMode` and stays read-only.

**Writes stay deliberate even when writable.** A writable external-store
backend writes its underlying records only on an explicit user action in the
conversation (mark met, approve a promotion draft, approve a field update).
Non-interactive runs (`daily-run`, sweeps) never write an external store's
records regardless of `writeMode`; they write only `state.json` and the board.
See `reference/cutover.md` for the flip procedure and
`reference/promotion.md` for the create-on-promotion flow.

## Operations (the contract core calls)

- **locate()** — resolve where the ledger lives, from config.
- **query() / read()** — return the current promise set (open + relevant),
  each promise shaped per `ledger-schema.md`.
  **Implemented once, in `scripts/ledger_query.py`.** Both operations live there:
  it resolves the ledger location from config, reads the promise set (for a
  read-only note-backed backend, the union with the builtin companion), overlays
  `itemMeta`, and recomputes derived state. Core skills call that script rather
  than re-deriving the read, because a second derivation of `overdue` is a second
  answer, and the two disagree on precisely the cases the schema exists to get
  right: an overridden `deadlineType`, a live snooze, a dismissal that a pending
  draft outranks. The script is read-only and has no write path; every operation
  below stays with the skills and the active backend.
- **recordVerify(id, verifyStatus, reason, lastVerified)** — persist reconcile
  metadata (writable: on the record; read-only: into `itemMeta[<id>]`).
- **setSnooze(id, until, reason)** — persist a snooze (same backend-scoped rule).
  `reason` is required, not an optional note: on a read-only backend the overlay
  carries no history, so it is the only audit trail the snooze has. Implemented by
  `ledger_write.py snooze`; `--unsnooze` clears it.
- **Not in this interface: suppressing a source ref.** `ledger_write.py suppress`
  writes the top-level `state["suppressed"]` list, which is keyed by source ref
  rather than by promise id and is not per-item metadata at all - so there is no
  backend-scoped variant of it and no `setSuppressed(id, ...)` to implement. It
  acts before a promise exists; every operation here acts on one that does.
- **recordSourceLink(id, source)** — persist an enriched source link (same rule).
- **write(promise) / update(promise)** — create or update a promise. Writable
  backends only; a read-only backend instead returns a draft/instruction and
  mutates nothing.
- **markMet(id, completedDate?)** — close a promise as delivered/received.
  Writable: on the record (an external note-backed store sets its own canonical
  done fields). Read-only: a draft/instruction, plus bookkeeping in
  `itemMeta[<id>]`.
- **promote(promise)** — create a real record in the backend's store from a
  `state.json`-resident promise, then cross-link the two (see
  `reference/promotion.md`). Writable backends only, and only ever from an
  explicit approved draft — never from a sweep.

## Rule for core skills

Reference "the active backend" / "a read-only backend" / "the writable backend"
by capability. Never say the name of a specific adapter in a core skill or a
core reference doc. If an example helps, name it once as "e.g. an external
note-backed store" and move on.
