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
.claude-plugin/plugin.json   manifest (name: adhdecoder)
skills/<name>/SKILL.md        skills (instructions FOR Claude)
reference/method.md           the durable method (the brain)
reference/ledger-schema.md    Phase 1 promise record shape
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

## Build phases

1. **Ledger (done):** the promise store. `skills/ledger/`.
2. **Set the clock:** capture promises in/out.
3. **Chase in:** surface slips as ready-to-send nudges, tiered by stakes.
4. **Radiate out:** publish status; ships last, verified-only.
5. **Panic button + drift:** reactive + passive, alongside.

When adding sweep skills, port the *technique* (how to query a category), never
the specific ids or rosters.
