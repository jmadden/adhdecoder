# ADHDecoder — Verification Discipline (spec)

Make "double-check before you present it" a **rule the plugin enforces**, not
something the operator remembers. Every item shown as a fact or an action must be
verified first, and the verification must be visible. This is the discipline that
sits on top of the `reconcile` engine (`reference/reconciliation.md`); it does
not add new fields (all live in `reference/ledger-schema.md`) or new source
logic. Generic; no personal or company data.

## Principle (hard, cross-cutting)

**Verified before surfaced.** Never present a promise as a settled fact or a
required action without a FRESH reconcile verdict, and always show that verdict
inline. A search snippet or preview is never enough: read the full source thread
and the backing note before asserting anything about status. (This is the
`method.md` guardrail of the same name; the rules below make it operational.)

## Rule 1 — show the verification on every surfaced item

Every item on an internal board (chase-in, drift, panic) carries, inline:

- its **`verifyStatus`** (`verified-open` | `resolved` | `reassigned` |
  `mis-attributed` | `unverifiable`) - a short tag, with the `verifyReason` when
  it adds signal,
- the actionable **`source.url`** (per `reference/source-links.md`; a small
  `(note)` hint when `noteOnly`), optionally `noteRef`,
- for a note-backed item, the note's **current status + latest update line**.

If an item has no verdict (`verifyStatus` is `null`) or its `lastVerified` is
older than the TTL, **reconcile it before surfacing** - do not show a stale or
unverified item as a confident action. If it genuinely can't be verified
(`unverifiable`), surface it explicitly as **"unverified, confirm"** with the
reason, never as an asserted action.

**radiate-out is the exception.** It is customer-facing and must never carry an
internal link or status tag in the outward draft. Its verification (verifyStatus,
source link, freshness) lives only on the internal "confirm before sending" list
and a freshness header. Anything null/stale routes to that list, never into the
draft. See `skills/radiate-out/SKILL.md`.

## Rule 2 — reconcile on reference (reactive)

Reconcile fires not only before a chase or a publish, but **whenever the user
references a specific tracked item or context in conversation.** Read its live
source (the full thread) + its note's current status FIRST, then state anything
about it. "What's the status of X?" -> reconcile X -> answer. Never answer about
an item's status from memory or a snippet. Still TTL-cached and read-only, so a
just-verified item reuses its cached verdict.

## Rule 3 — freshness + lead with changes

- Every surface reports **ledger freshness** (how long since `lastSwept`).
- On session start, or the first surfacing after a gap, if the ledger is stale,
  **run a refresh (sweep) first** and lead with "what changed since the last
  sweep," so the operator works from current reality, not memory. The sweep is
  read-only against sources and writes only `state.json` + the board, so this
  stays within the hard guardrails (no auto-send/post).
- Division of labor: scheduled runs keep breadth fresh in the background;
  on-reference reconcile keeps the specific item fresh in the foreground.

## Cost / guardrails

- Read-only against sources and notes; verify metadata only to `state.json`
  (on the record for builtin promises, in the `itemMeta` companion for a
  read-only backend). Never write a note.
- Cost-aware: honor the reconcile TTL cache; reconcile only what is actually
  being surfaced or referenced, never the whole ledger.
- Never auto-send / auto-post / auto-create tasks. No hidden files. Keep generic.

## Where this is wired

- `reference/method.md`: the "Verified before surfaced" guardrail.
- `skills/chase-in`, `skills/drift`, `skills/panic`: render `verifyStatus` +
  source link (+ note status) inline per item; a null/stale verdict is
  reconciled before surfacing; `unverifiable` shows as "confirm," never asserted.
- `skills/radiate-out`: verification on the internal confirm-list + freshness
  header only; never in the customer draft.
- `skills/reconcile` + `reference/reconciliation.md`: the on-reference trigger.
- `skills/daily-run`, `skills/sweep`: report freshness; the session-start
  refresh-then-lead-with-changes entry.
