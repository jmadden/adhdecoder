# ADHDecoder — Onboarding & Setup (spec)

The barrier to using ADHDecoder is **config, not install**. This is the durable
brain for getting a new user from installed-plugin to a working setup without
hand-editing JSON: a guided `setup` conversation, a `help` orientation, a
`doctor` health check, and a first-run gate so a missing config fails gracefully
instead of returning a confusing empty board. The `setup` / `help` / `doctor`
skills reference this doc. Generic; no personal or company data.

Related: `CONNECTORS.md` (category placeholders), `reference/ledger-backend-interface.md`
(backend resolution), `reference/scheduling.md` (weight/cadence/board),
`reference/ledger-schema.md` (config + state shapes). Templates live at
`config/decoder.config.example.json` and `config/state.example.json`.

## What onboarding writes (and never writes)

- Writes ONLY the instance layer: `config.json` + `state.json`, at
  `<storage.instancePath>/…`. Visible filenames only; atomic temp-then-replace;
  single writer (same discipline as the `ledger` skill).
- Never writes the repo, a source, or a knowledge-base note. Discovery reads
  sources READ-ONLY. Never auto-sends, auto-posts, or auto-creates a task.
- `setup` is the only skill allowed to create/rewrite `config.json`; `state.json`
  is initialized from `config/state.example.json` shape (all-empty, `schemaVersion: 1`).

## The setup flow (one question at a time)

Idempotent: safe to re-run; it edits, it never clobbers without confirmation.
Ask ONE thing at a time (the plugin's ADHD ethos). Assume nothing; confirm before
every write.

0. **Instance location.** Resolve `storage.instancePath` - the visible folder
   holding `config.json` + `state.json`. Ask if unknown. **Warn if it resolves
   inside this repo tree** (the instance layer must live outside the plugin, per
   the three-bucket rule) and suggest a folder in the user's vault / home.
1. **Detect existing config.** If a `config.json` is already there, offer to
   review/extend it rather than overwrite. Never clobber without an explicit
   confirm.
2. **Sources.** Which categories do they use (chat / email / issue tracker / CRM
   / docs / calls / calendar)? Enable those (`sources[].enabled: true`, map each
   to its `~~category`). Then priority: "which matters most / hit first?" -> set
   `weight` (`high|medium|low`) + `cadence` (`every-run|daily|hourly`) per source.
3. **Identity.** Their handle per source (`identity.handles.chat`, `.crm`, …),
   `identity.email`, `identity.name`. Auto-detect where a connector exposes it;
   always confirm before writing.
4. **Storage / backend.** Default `ledger.backend: "builtin"` (`state.json`)
   needs nothing more. Ask: "do you already keep tasks as notes in a folder?" If
   yes, offer the optional read-only note-backed adapter, collect
   `storage.knowledgePath` + `storage.overrides.tasksDir`, and set
   `ledger.backend` to that adapter's name (resolved as `ledger-<backend>`, per
   `reference/ledger-backend-interface.md`).
5. **Schedule + board.** `schedule.pivots` (the run times), `schedule.timezone`
   (IANA), and `schedule.boardPath` (where the refreshed board is written each
   run; unset = print to chat only). See `reference/scheduling.md`.
6. **Contexts (optional auto-discovery).** "Do you group work by customer /
   client / project? Want me to scan your chat for the channels you're active in
   and the people in them?" If yes, run READ-ONLY discovery and populate
   `config.contacts` + `state.knownChannels`; also seed `config.watchlist`
   (customers / projects / people that raise stakes). **Always show what was
   found and confirm before writing.** Assume nothing.
7. **Connector check + summary.** Confirm each enabled source's connector is
   present (see doctor's presence check). Show a summary of everything to be
   written, then on confirm write `config.json` and initialize `state.json`.

## First-run gate (shared rule)

Before doing work, every surfacing/action skill checks that config is present and
minimally complete: **at least one enabled source, OR a backend + identity.** If
not, it says "ADHDecoder isn't set up yet - want to run `setup`?" and routes to
`setup`. Never grind against an empty config or return a confusing empty board.

- The authoritative check is the `ledger` skill's Locate step (the chokepoint):
  if `config.json` is absent or unparseable, route to `setup`. Read-side skills
  inherit this through the ledger's Query.
- Non-interactive `daily-run` CANNOT prompt: on a missing/thin config it prints a
  clear "not set up; run `setup`" recap line and exits cleanly (no hang, no empty
  board).

## Doctor (read-only health check)

Reports OK vs gaps, each gap with its one-line fix. Writes nothing; makes no live
calls to sources (presence-only).

- **Config parses + required fields present.** `config.json` is valid JSON and
  has `storage.instancePath`, an `identity`, and at least one enabled source or a
  backend+identity.
- **Backend resolves + paths OK.** `builtin` -> `state.json` path composes and
  its directory exists / is writable (checked via filesystem metadata, not by
  writing). A non-builtin backend `X` -> a `ledger-X` skill exists, and its paths
  (e.g. `knowledgePath` + `tasksDir` for a note backend) resolve.
- **Connectors present.** For each `sources[].enabled` entry, the mapped
  `~~category` connector is available in the session (presence-only). `~~knowledge`
  is validated as a filesystem path, not a connector.
- **Report.** List each check as OK or a gap; for a gap give the single fix
  (e.g. "chat enabled but no chat connector -> connect it or disable the source",
  "instancePath missing -> run `setup`").

## Command cheat-sheet (also in help + README)

- "what's slipping" / "who do I chase" -> chase-in
- "what's drifting / gone quiet" -> drift
- "panic" / "I'm overwhelmed" -> panic
- "where do things stand for <context>" -> radiate-out
- "show my board" / "refresh the dashboard" -> board
- "is this still open / reconcile this" -> reconcile
- "<someone> owes me <X> by <date>" / replying to an ask -> set-the-clock
- "run a sweep" / "daily run" -> sweep / daily-run
- "help" / "set me up" / "check my setup" -> help / setup / doctor

## Guardrails

- Writes only `config.json` + `state.json` in the instance layer; never the repo,
  a source, or a note. Discovery reads sources read-only.
- Never auto-send / auto-post / auto-create tasks. Every outward artifact is a
  draft the user approves.
- No hidden files; visible names only. Single writer; atomic writes.
- Keep generic: placeholders and categories, never real names / ids / rosters.
