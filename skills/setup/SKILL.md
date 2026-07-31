---
name: setup
description: >
  Guided, conversational onboarding that builds or updates the ADHDecoder
  instance config.json (and initializes state.json), so a new user gets to a
  working setup without hand-editing JSON. Use when the user says things like
  "set me up", "set up ADHDecoder", "onboard me", "configure ADHDecoder", "get
  me started", "add a source", "change my config", or "reconfigure". Idempotent:
  safe to re-run; it edits, never clobbers without confirmation, and asks one
  thing at a time. Writes only config.json + state.json in the instance layer;
  reads sources read-only during optional discovery; never writes the repo,
  never auto-sends or auto-posts.
---

# Setup (onboarding)

Turn config from a hand-edited JSON file into a guided conversation. Read
`reference/onboarding.md` (the full flow) and `reference/ledger-schema.md` (the
config + state shapes) before running. Work from the templates at
`config/decoder.config.example.json` and `config/state.example.json` - never
invent config keys that are not in the template.

Core principle: **one question at a time, confirm before every write, assume
nothing** (the plugin's ADHD ethos). Idempotent - safe to re-run.

## What this does / does not do

- **Builds config, conversationally.** Collects each field through a short
  exchange, not a wall of questions. Fills the config template; leaves unused
  keys at their template defaults.
- **Idempotent and non-destructive.** If a `config.json` already exists, offer to
  review/extend it. Never overwrite a populated config without an explicit
  confirm; edit in place.
- **Writes only the instance layer.** `config.json` + `state.json` under
  `storage.instancePath`, atomic temp-then-replace, visible filenames only. Never
  writes the repo, a source, or a knowledge-base note.
- **Reads sources read-only.** Any auto-detection / discovery step only reads;
  it never posts, sends, or creates anything.

## The flow (ask one thing at a time)

0. **Instance location.** Resolve `storage.instancePath` - the visible folder
   that will hold `config.json` + `state.json`. Ask if it is not already known.
   **If the path resolves inside this plugin repo, warn and steer elsewhere** -
   the instance layer must live outside the repo (three-bucket rule); suggest a
   folder in the user's vault or home. Set `storage.adapter: "filesystem"`.
1. **Detect existing config.** Look for `config.json` at that path. If present,
   summarize what it has and offer to review/extend rather than overwrite.
   Proceed field-by-field only where the user wants changes.
2. **Sources.** Ask which categories they use (chat / email / issue tracker /
   CRM / docs / calls / calendar). For each used one, add/enable a `sources[]`
   entry (`enabled: true`, `type`, its `~~category` from `CONNECTORS.md`). Then
   ask priority - "which matters most / should I hit first?" - and set `weight`
   (`high|medium|low`) and `cadence` (`every-run|daily|hourly`) per source.
   Leave unused categories `enabled: false`.
3. **Identity.** Ask their handle per enabled source (`identity.handles.chat`,
   `identity.handles.crm`, …), `identity.email`, and `identity.name`.
   Auto-detect from a connector where possible, but always show it and confirm.
4. **Storage / backend.** Default `ledger.backend: "builtin"` (writes
   `state.json`) - nothing more needed. Ask "do you already keep tasks as notes
   in a folder?" If yes, offer the optional note-backed adapter:
   collect `storage.knowledgePath` + `storage.overrides.tasksDir` and set
   `ledger.backend` to the adapter name (resolved as `ledger-<backend>`, per
   `reference/ledger-backend-interface.md`). Only offer a backend whose
   `ledger-<backend>` skill is present. Default `ledger.writeMode: "readonly"`
   and do NOT offer readwrite during first-time setup - cutover is a later,
   deliberate step (`reference/cutover.md`). Only when the user explicitly asks
   to cut over ("make ADHDecoder the writer", "enable write-back"): confirm the
   old writer is disabled, restate what they are confirming ("nothing else
   writes these files anymore"), then set `writeMode: "readwrite"` +
   `cutover: { singleWriterConfirmed: true, date: <today> }` and point them at
   `doctor`.
5. **Schedule + board.** Ask for `schedule.pivots` (run times, e.g.
   `["08:30","12:30","16:00"]`), `schedule.timezone` (IANA), and
   `schedule.boardPath` (where the refreshed board is written each run; leave
   unset for chat-only). See `reference/scheduling.md`.
6. **Contexts (optional auto-discovery).** Ask "do you group work by customer /
   client / project? Want me to scan your chat for the channels you're active in
   and the people in them?" If yes, run **read-only** discovery, then **show what
   was found and confirm before writing** into `config.contacts` +
   `state.knownChannels`; also offer to seed `config.watchlist` (customers /
   projects / people that raise stakes). Assume nothing - skip silently if they
   decline.
7. **Connector check + summary + write.** Confirm each enabled source's connector
   is present (hand off to `doctor`'s presence check, or do the same probe). Show
   a summary of everything about to be written. On confirm: write `config.json`,
   then initialize `state.json` from `config/state.example.json` shape (all-empty,
   `schemaVersion: 1`, `lastSwept: null`) if it does not already exist. Finish by
   pointing them at `help` and a first "what's slipping".

## Guardrails

- **Writes only `config.json` + `state.json`**, in the instance layer, atomically,
  visible filenames only. Never writes the repo, a source, or a note.
- **Reads sources read-only** during any detection/discovery. Never auto-send,
  auto-post, or auto-create a task.
- **Never clobber.** An existing populated config is edited on confirm, never
  overwritten blind.
- **No invented keys.** Only fields present in `config/decoder.config.example.json`.
- **Keep generic in the repo.** Real names / ids / rosters live in the user's
  instance config, never here.
