# ADHDecoder — Dashboard Renderer (spec)

The one render procedure that turns the ledger into the multi-tab HTML board.
Two entry points follow it: the scheduled `daily-run` (its board step) and the
on-demand `board` skill ("show my board" / "refresh the dashboard"). Written
2026-07-28. Generic; no personal or company data.

**This spec is implemented by `scripts/render-board.py`.** Both entry points call
that script rather than re-deriving a render from this prose, which is what let a
three-group render survive a four-group spec. Read this file to understand or
change the behaviour; change the script in the same commit. The script is a pure
function of (config, ledger, clock): same inputs, byte-identical HTML out, writes
only `config.schedule.boardPath`. Because it is offline and deterministic it does
**not** perform step 2's reconcile - the calling skill reconciles first, then
renders. `scripts/tests/test_render_board.py` pins the acceptance criteria against
an invented fixture ledger.

The repo ships a **data-free** template at `assets/dashboard-template.html`
(styling, 6 tabs, the state-color legend, tab-switch JS, `{{PLACEHOLDER}}` tokens,
`<!-- RENDER ... -->` injection points, and commented CARD TEMPLATES). The
renderer fills it from the user's ledger and writes the result to
`config.schedule.boardPath`. Only that rendered output holds data; the template
in the repo never does.

Read `reference/ledger-schema.md` (the promise shape), `reference/source-links.md`
(which link to show), and `reference/verification-discipline.md` (Rules 1 + 3)
before rendering.

## What this is

A **regenerated read-only VIEW** of the ledger, not a second store. Every run
rebuilds the whole board from current ledger state: no hand-maintained board
state, no append-only board bookkeeping. The ledger stays the single source of
truth. This is an **internal** board, so source links belong on it (the
radiate-out no-internal-links rule is customer-facing only and does not apply
here).

## Render procedure

### 1. Read the ledger (backend-agnostic)

Get the promise set via the `ledger` skill's **Query**, so any backend works
(builtin `state.json`, or a read-only adapter's union with the `state.json`
companion). Query already recomputes `overdue`/`stakes`, overlays `itemMeta`, and
exposes `snoozedUntil`. On the active tabs (Board / Waiting / Tomorrow):

- skip items whose `snoozedUntil` is in the future,
- skip `dismissedFromBoard` ids.

Closed items still appear in **Shipped** and **History** regardless of snooze.

### 2. Verify before rendering (Rule 1)

A card asserts a fact or an action, so it must carry a fresh verdict:

- Render each card's **`verifyStatus`** into its `c-task` chip
  (`verified-open` / `resolved` / `reassigned` / `mis-attributed` /
  `unverifiable`), with the `verifyReason` when it adds signal.
- If a to-be-rendered item's `verifyStatus` is `null` or its `lastVerified` is
  older than the TTL, **reconcile it first** (TTL-aware, read-only) — never render
  a stale or unverified item as a confident action.
- `unverifiable` renders as **"unverified — confirm"** with the reason, never as
  an asserted next move.
- `resolved`, or any `itemMeta.markMetDraft` / `updateDraft`, routes the card to
  the **Ready to close** group (step 3), never to "your move". A parked draft is
  a pending decision the user has not seen yet, not a closed item.

Reconcile only what is actually being rendered, honoring the TTL cache; never the
whole ledger.

### 3. Group promises into the 6 tabs

Reuse the existing surfacing logic (chase-in / drift / waiting / met-cleared),
just rendered into HTML. Nothing user-specific is hardcoded; every value comes
from the ledger + config.

| Tab (pane) | Card | Contents |
|---|---|---|
| **Board / Today** (`#pane-board`) | `.big` in `.today-group` / `.today-grid` | Open promises actionable now, grouped into up-to-four labeled color sections (below), each a 2-column grid. Leads with **Ready to close**. |
| **Waiting on Others** (`#pane-waiting .waitlist`) | `.waitrow` | Open `they-owe-me` promises. |
| **Shipped** (`#pane-shipped .wins`) | `.win` | `met` / `cleared` recently. |
| **Tomorrow's Headlines** (`#pane-tomorrow .today`) | `.big` | Due-soon / scheduled-ahead upcoming items (not yet actionable today). |
| **Projects** (`#pane-projects .projlist`) | `.proj` | Declared projects (`state.json` `projects`), lagging first, then a **Closed** section for `status: done`. Each card carries the rollup, the aliases it matches, and its members. |
| **History** (`#pane-history .histlist`) | `.hist` | All `met` / `cleared`, newest first. |

**Board / Today state color** (the template's `.big` variants). The four states
render as **separate stacked sections**, each a `.today-group` (label + colored
dot) wrapping a 2-column `.today-grid`. Fixed order top to bottom; **omit any
section that has no items entirely**:

1. **teal** (`.big.ready`) = **ready to close** — the record still reads open,
   but the source says it is done: `verifyStatus` is `resolved`, or `itemMeta`
   carries a `markMetDraft`. Label the group "Ready to close (confirm)" and put
   the draft's `reason` in the card body. See below.
2. **blue** (`.big`, default) = **your move** — an open item where the user owes
   the next action.
3. **purple** (`.big.waiting`) = **waiting, no clear action** — open but the ball
   is elsewhere / blocked.
4. **green** (`.big.done`) = **done today** — closed today, shown for the win.

**Ready to close comes first, and it is not optional.** A `resolved` item whose
record still reads open is the single most trust-destroying thing the board can
render: the user sees finished work presented as outstanding, and stops
believing the counts. It must never fall into "your move."

- Render it in its own group, above everything, with the reconcile `reason` as
  the card body and the source link as proof.
- The first action is the confirmation itself: "confirm and close" (readwrite),
  or the exact record edit to apply by hand (readonly).
- Exclude these from the "need your move" count in `{{COUNTS}}`; count them
  separately (e.g. "N ready to close"), so the headline number reflects real
  outstanding work.
- On a **readonly** backend these accumulate until the user acts, so the group
  is the only thing standing between a correct ledger and silent drift. If it
  is non-empty for more than a couple of runs, say so in `{{BOARD_NOTE}}`.

States 1 and 4 are both "nothing left to do here," but they are not the same
state: done-today is finished, ready-to-close is still waiting on the user's
confirmation. They shared `.big.done` originally, with only the group labels to
tell them apart, and at a glance the board read as more finished than it was.
Ready to close now has its own `.big.ready` teal variant. Still always emit the
group label.

**Projects worth a look** (the Board tab's one project surface). Rendered
immediately under `{{BOARD_NOTE}}`, and **only when a declared project is
lagging** - otherwise the renderer emits an empty string and the Board tab looks
exactly as it did before projects existed. That is the point: a permanent
projects section would be one more thing to scan daily, and the calm board is
what makes the loud one mean something. The template's injection marker is
UNCONDITIONAL - `render()` treats a missing injection point as a hard error, so
deleting the marker breaks the calm board, not the loud one. Signals and
thresholds: `reference/projects.md`.

Within a section, sort **flagged items first** (those carrying the orange
`c-flag` chip). **orange** stays the `c-flag` chip, added **only when a real flag
exists** (high stakes, or hard-`deadlineType` overdue) — never a decorative flag,
and never a section of its own.

`soft`/`none` deadlineType items are never "overdue"; they surface via drift
staleness, not as a hard flag.

### 4. Fill the placeholders

| Placeholder | Value |
|---|---|
| `{{LAST_SWEPT}}` | `lastSwept`, human-readable (e.g. "2h ago" or the date); "never" if null. |
| `{{COUNTS}}` | one-line tally, e.g. `<b>N</b> ready to close, <b>N</b> need your move, <b>N</b> waiting, <b>N</b> shipped`. Ready-to-close items are counted separately and excluded from "need your move". A `<b>N</b> projects lagging` clause is appended ONLY when N > 0, so a calm day's headline reads exactly as it always did. |
| `{{N_SHIPPED}}` | count of Shipped rows. |
| `{{N_WAITING}}` | count of Waiting-on-Others rows. |
| `{{N_TOMORROW}}` | count of Tomorrow cards. |
| `{{N_HISTORY}}` | count of History cards. |
| `{{N_PROJECTS}}` | count of declared projects (all of them, not just lagging). |
| `{{BOARD_NOTE}}` | one-line status for the `.calm` banner — a calm "nothing slipping" when the board is clear, else a short "N items need your move" summary. |

The Board tab button has no badge in the template — none is needed.

### 5. Emit the cards (per the template's CARD TEMPLATES)

Fill each template's tokens from the ledger record. On every card include, per
`reference/source-links.md`:

- the actionable **`source.url`** in the `source` link (add a small `(note)` hint
  when `noteOnly`),
- the record / **`noteRef`** in the `record` link (the `.task`-styled link),
- the **`verifyStatus`** chip (`c-task`), the `context` chip (`c-cust`), and the
  `c-flag` chip only when a real flag exists.

On the Board tab, wrap each non-empty state in its own `.today-group` (with the
matching `.group-label` + colored dot) and emit that state's `.big` cards into
the group's `.today-grid`; the per-card `.big` fill is otherwise unchanged.

`.big` cards render at a **uniform fixed size**; the template clips any overflow
and clicking a card opens its full content in a modal (both handled by the
template's CSS/JS, no renderer action needed). Emit the card content as normal —
do not pre-truncate `WHAT` or the action text; the template does the clamping.

Link, never paste raw feeds. Emit into the matching `<!-- RENDER ... -->` point in
each pane; leave a pane empty (or with a brief "nothing here" line) when it has no
items.

### 6. Write the board file

Write the filled HTML to `config.schedule.boardPath`, **atomically** (temp file,
then replace) and **overwrite in place**. If `boardPath` is unset, skip the file
and print the one-line summary to chat instead. The file is visible (no
hidden/dot-prefixed name).

## Guardrails

- **Read-only** against sources and notes. The render writes only the board file;
  any reconcile enrichment lands in `state.json` / `itemMeta`. Never write a note.
- **Only `state.json` + the board file** are ever written by a render.
- **Never auto-send / auto-post / auto-create tasks.** The board is a view.
- **Regenerated every run** from the ledger — never a hand-maintained second store.
- **Generic:** no customer/person/id or user terminology baked into the template
  or this renderer; all such values come from the user's own ledger + config.
