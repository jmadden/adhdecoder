# ADHDecoder — Repo Guide

Guidance for any Claude working in THIS repo. This is not the operational spec
(the operational brain lives in `skills/` and `reference/method.md`). This file
is developer/maintainer orientation. Keep it free of personal or company data.

## What this repo is

The **portable Core** of ADHDecoder: the method, formats, and skills. Zero
personal or company data. It installs into any Claude Code / Cowork instance.

## The three-bucket architecture

1. **This repo (the plugin) = the method.** Portable, versioned, no data.
2. **Instance layer = a user's `config.json` + `state.json`.** Lives OUTSIDE
   this repo, at a path the user chooses. Company/personal-bound, disposable.
3. **Knowledge base = the user's files** (Radar, tasks, dashboard) in a folder
   the plugin points at.

Never let bucket 2 or 3 content leak into this repo.

## Layout

```
.claude-plugin/plugin.json   manifest (name: adhdecoder); version bumped per
                              change; `skills` lists extra discovery paths
skills/<name>/SKILL.md        core skills (instructions FOR Claude)
adapters/<name>/              optional backend adapters (SKILL.md + reference.md),
                              e.g. adapters/obsidian; registered in plugin.json
scripts/frontmatter.py        the note-frontmatter parser. Stdlib only; parses the
                              subset real notes use and RAISES on anything else,
                              so it can never silently misread. Owns
                              duplicate_frontmatter_keys(), shared by the read
                              path (ledger_query.py) and the write guard
scripts/verify_note_write.py  post-write guard: re-parses a just-written note and
                              restores it from backup if the write introduced
                              damage (a duplicate key, a broken fence, a dropped
                              tag). Required after every markMet/update/promote
scripts/ledger_schema.py      the schema as data (field sets, enums, the reality
                              gate). Imported by BOTH the validator and the write
                              path, so a field cannot be legal to write but
                              unknown to `doctor`
scripts/ledger_write.py       THE write path. state.json ops (reality gate, schema
                              check, dedup against the full union, append-only
                              history, atomic write + backup + rollback, a
                              concurrent-writer guard) PLUS note creation:
                              `capture` (add a task where the user works) and
                              `promote` (state.json promise -> note, then
                              collapse). Note ops need --confirmed, so no
                              unattended run can create one
scripts/sweep_plan.py         which sources a run sweeps (weight order, cadence,
                              the once-per-day guarantee). Read-only arithmetic
scripts/doctor_check.py       doctor's mechanical checks (config, backend, write
                              mode, record store). Reports connector presence as
                              `unchecked` rather than guessing: a subprocess
                              cannot see the session's connectors
scripts/reconcile_plan.py     reconcile's TTL cache decision, working order, and
                              the (advisory) mis-attribution signal. The verdicts
                              themselves stay prose: they need a live source
scripts/ledger_query.py       THE ledger read: backend resolution, the union +
                              one-way dedup, itemMeta overlay, all derived state,
                              and the selectors the read-side skills ask for.
                              Read-only, no write path. Underscored (not
                              kebab-case) because it is the one importable module
scripts/render-board.py       the board renderer; implements reference/dashboard.md
                              (pure: config + ledger + clock in, HTML out).
                              Imports ledger_query; owns only grouping + HTML
scripts/validate-state.py     schema validator; reports undefined + deprecated
                              fields at all three levels. Called by `doctor`.
                              Validates, never repairs
scripts/tests/                fixture test + invented fixture ledger. The fixture
                              state file is `fixtures/ledger/fixture-state.json`,
                              NOT `state.json`, so .gitignore's instance-data
                              guards stay intact
reference/method.md           the durable method (the brain)
reference/ledger-schema.md    promise record shape + itemMeta companion
reference/*.md                per-capability specs (sweep, reconciliation,
                              radiate-out, handoff-followups)
config/*.example.json         TEMPLATES only, no real data
CONNECTORS.md                 tool-category placeholders (~~category)
```

## Conventions

- kebab-case for files and directories.
- Skills are **instructions for Claude**, imperative voice, not user docs.
- Progressive disclosure: lean `SKILL.md`, detail in `reference/`.
- Skill `description` frontmatter is third-person with concrete trigger phrases.

## Commits

Conventional Commits. Allowed scopes:

`skills` · `adapters` · `reference` · `config` · `plugin` · `connectors` · `docs`

Repo-specific rules:

- A `plugin.json` version bump that accompanies a skill or reference
  edit belongs in the SAME commit, not a separate `chore`. The bump is
  part of shipping that change (see Shipping a change).
- Never reference instance-layer or knowledge-base content in a commit
  message. Same hard rule as the code.

## Hard rules (do not violate)

- **Stdlib only. No installable dependencies, ever.** Scripts may use Python 3
  and its standard library and nothing else: no `pip install`, no lockfile, no
  vendored wheel. A plugin cannot prompt for a dependency at install time, so an
  import that needs installing becomes a failure at first use for every new
  user - and the install command may not even work (PEP 668 rejects a plain
  `pip install` on a Homebrew Python). Must run under Apple's `/usr/bin/python3`
  (3.9) with an empty site-packages; `scripts/tests/` is the proof. If a task
  seems to need a library, write the subset you need and make it **refuse** what
  it cannot handle (see `scripts/frontmatter.py`).
- **No personal or company data in this repo.** Rosters, ids, channels,
  incident history all belong to the instance layer.
- **No hidden files** for state or knowledge. Visible names only.
- **Single writer** for instance state.
- **Never auto-send, never auto-post, never auto-create tasks.** Drafts only;
  promotion is deliberate.
- **Verified-only** to any customer-facing surface.

## Storage adapters

- **Filesystem (built):** real, always-present local files (local, Obsidian
  Sync, Syncthing, git, pinned Dropbox/OneDrive). Set `instancePath` +
  `knowledgePath`.
- **Connector (spec'd, not shipped):** cloud-native stores that serve
  placeholders. Reads/writes via connector tools, not a path. Contract:
  `reference/connector-adapters.md`.

## Ledger backends

Separate axis from storage adapters. `config.ledger.backend` selects the promise
store, read via the `ledger` skill's Query so read-side skills are
backend-agnostic:

- **builtin** (default): `state.json` in the instance layer. Always writable.
- **obsidian:** overlay of the user's Obsidian notes (Markdown + YAML
  frontmatter). **Read-only by default** (`ledger.writeMode: "readonly"`):
  never writes the note; ADHDecoder-owned metadata (snooze, `deadlineType`
  override, verify results) goes to the `state.json` `itemMeta` companion keyed
  by item id. **Write-back post-cutover:** `writeMode: "readwrite"` +
  `cutover.singleWriterConfirmed: true` makes it writable for deliberate user
  actions only (mark met, approved updates, approved promotions); sweeps and
  non-interactive runs never write notes in any mode. See
  `reference/cutover.md` + `reference/promotion.md`. Lives in
  `adapters/obsidian/`, which also accepts any deprecated legacy backend value
  as an alias.

## What's built

The full loop plus a cross-cutting verification layer. Each is a skill under
`skills/<name>/`:

- **ledger** (Phase 1): the promise store + Query interface every read-side skill
  calls. Backend-aware (see Ledger backends).
- **set-the-clock** (Phase 2): capture promises as work flows in/out, incl.
  outbound handoffs (they-owe + confirm-by + `why`).
- **chase-in** (Phase 3): surface slips as tiered, ready-to-send nudges.
- **radiate-out** (Phase 4): publish per-context status, verified-only.
- **panic** + **drift**: reactive spiral-breaker + passive staleness flag.
- **sweep**: source-facing pass that populates the ledger from configured
  sources; verifies via the reconcile adapters.
- **reconcile** (cross-cutting): cross-check a promise against its live source
  before any skill chases/publishes. One verification path — chase-in /
  radiate-out / drift / panic / sweep all call it.
- **ledger-obsidian**: the optional Obsidian backend (in `adapters/obsidian/`,
  not `skills/`). Read-only by default; write-back gated behind cutover.

Refinements layered on: `why` / `deadlineType` (hard/soft/none) / `snoozedUntil`
promise fields; handoff follow-ups; delivery-flip (i-owe → they-owe) in
reconcile; `writeMode`/cutover gating (`reference/cutover.md`); deliberate
promotion of `state.json` promises into backend records with `promoted`/
`promotedTo` collapse (`reference/promotion.md`); connector storage adapter
contract (`reference/connector-adapters.md`, spec only); `markMetDraft` /
`updateDraft` / `appliedMarkMet` in `itemMeta` plus the board's **Ready to
close** group, so a parked decision is always visible.

**No prose-only behaviour.** `reference/dashboard.md` was a prose spec with no
implementation, so every render re-improvised it and a three-group render survived
a four-group spec. The render now lives in `scripts/render-board.py`; skills call
it. When behaviour is deterministic enough to be code, make it code, and change
the spec and the script in the same commit.

**One read, one answer.** The ledger read lives in `scripts/ledger_query.py` and
nowhere else. A skill that re-derives `overdue`, staleness, snooze or
ready-to-close from prose produces a second answer, and the two disagree exactly
where it matters: a soft deadline chased as though it were hard aims a false nudge
at a real person. Read-side skills call the Query and supply only judgment
(tiering, copy, tone). The split to hold: **mechanical selection is code,
judgment is prose.**

**No write-only fields.** If a run can write a field into `state.json` (an
`itemMeta` overlay field, a top-level map, a promise field), a surface must
render it, in the same change. Broadened from drafts in schemaVersion 2: the
failure mode never depended on the field being a draft.

- A draft nothing displays is invisible drift: the record keeps reading open,
  the board keeps showing finished work as the user's move, and the counts stop
  being trustworthy.
- A `frontmatterWarning` nothing displays left a damaged note unfindable for
  weeks.
- A recorded pronoun nothing reads means misgendering a real person again on the
  next run. `people` is read by every skill that writes person-referring copy.

Adding a field means adding its surface. `scripts/validate-state.py` reports any
field the schema does not define, so the next invented name is caught by
`doctor` rather than by a hand audit.

When adding sweep/source skills, port the _technique_ (how to query a category),
never the specific ids or rosters.

## Shipping a change (gotcha)

Edits to skills/reference do NOT take effect in an installed instance until:

1. Bump `.claude-plugin/plugin.json` version (the cache is version-keyed; same
   version = stale cache served).
2. Reinstall from the **local path**, not the GitHub marketplace (the
   GitHub-backed marketplace clone can lag): `/plugin marketplace remove
adhdecoder` → `/plugin marketplace add <repo path>` → `/plugin install
adhdecoder@adhdecoder` → `/reload-plugins`.
