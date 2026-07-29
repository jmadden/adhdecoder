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

## Hard rules (do not violate)

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
- **Connector (later):** cloud-native stores that serve placeholders (Google
  Drive). Reads/writes via API, not a path.

## Ledger backends

Separate axis from storage adapters. `config.ledger.backend` selects the promise
store, read via the `ledger` skill's Query so read-side skills are
backend-agnostic:

- **builtin** (default): `state.json` in the instance layer. The only store
  ADHDecoder writes.
- **obsidian:** read-only overlay of the user's Obsidian notes (Markdown + YAML
  frontmatter). Never writes the note; ADHDecoder-owned metadata (snooze,
  `deadlineType` override, verify results) goes to the `state.json` `itemMeta`
  companion keyed by item id. Lives in `adapters/obsidian/`, which also accepts
  any deprecated legacy backend value as an alias.

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
- **ledger-obsidian**: the optional read-only Obsidian backend (in
  `adapters/obsidian/`, not `skills/`).

Refinements layered on: `why` / `deadlineType` (hard/soft/none) / `snoozedUntil`
promise fields; handoff follow-ups; delivery-flip (i-owe → they-owe) in reconcile.

When adding sweep/source skills, port the *technique* (how to query a category),
never the specific ids or rosters.

## Shipping a change (gotcha)

Edits to skills/reference do NOT take effect in an installed instance until:

1. Bump `.claude-plugin/plugin.json` version (the cache is version-keyed; same
   version = stale cache served).
2. Reinstall from the **local path**, not the GitHub marketplace (the
   GitHub-backed marketplace clone can lag): `/plugin marketplace remove
   adhdecoder` → `/plugin marketplace add <repo path>` → `/plugin install
   adhdecoder@adhdecoder` → `/reload-plugins`.
