# ADHDecoder

Decode scattered work noise into **"here is your move."**

ADHDecoder sweeps the places people point things at you (chat, email, issues,
calendar, CRM, calls), decodes each new item into a short brief, tracks the
**promises** flowing in both directions, and surfaces the **one time-sensitive
thing** you are most at risk of dropping. It is built for ADHD brains: reduce
cognitive load, never add to it.

It does not collect raw feeds. It does not create tasks on its own. It closes
the loop.

## The three-part architecture (portability)

ADHDecoder is deliberately split so it can follow you anywhere: a new job, a
job hunt, home life.

1. **The plugin (this repo) = the method.** Skills, formats, guardrails. Zero
   personal or company data. Portable, versioned, install anywhere. This is
   what you keep forever.
2. **The instance layer = your config + state.** A `config.json` and a
   `state.json` that live at a path you choose (local, or inside a synced
   folder). Company-bound and disposable. See `config/decoder.config.example.json`.
3. **The knowledge base = your files.** Radar, tasks, dashboard, as plain
   Markdown/HTML in a folder you point at (e.g. an Obsidian vault).

Leaving a context = drop the instance, keep the method.

## Storage: bring your own

The plugin talks to storage through an adapter, not a hardcoded location.

- **Filesystem adapter (built now):** for storage that keeps **real files
  physically present** on the machine that runs sweeps: local disk, Obsidian
  Sync, Syncthing, git, or pinned Dropbox/OneDrive folders. You set two paths:
  `instancePath` and `knowledgePath`.
- **Connector adapters (later):** for cloud-native stores that serve
  placeholders instead of real files (Google Drive especially). These will
  read/write via the service API. Not built in v0.1.

**Rules that matter:**

- **No hidden files.** Everything ADHDecoder writes is visible (e.g. a
  `_decoder/` folder holding `config.json` and `state.json`). Never dot-prefixed.
- **Single writer.** Run sweeps on one machine at a time, or synced state can
  conflict.

## Install (Claude Code)

1. Clone this repo, or add it to a plugin marketplace.
2. Install the plugin into Claude Code.
3. Copy `config/decoder.config.example.json` to your instance folder as
   `config.json` and fill in your paths, identity, watchlist, and sources.
4. Point `instancePath` at that folder and `knowledgePath` at your vault.

## Build phases

ADHDecoder ships value in phases; each stands on its own.

- **Phase 1 (this version): the ledger.** The promise store: one record per
  promise (expect-by / who-owes / direction), read, written, and queried. See
  `skills/ledger/` and `reference/ledger-schema.md`.
- **Phase 2: set the clock.** Capture promises as work flows in and out.
- **Phase 3: chase in.** Surface slips as loud, timely, ready-to-send nudges.
- **Phase 4: radiate out.** Publish status so people stop chasing you.
- **Panic button + drift** ride alongside, reactive and passive.

Full design lives in the author's notes: "Decoder — Closing the Loop" and
"Decoder — Portability."

## Guardrails

- Never auto-send. Never auto-post. All replies are drafts.
- Never auto-create tasks. Promotion is always deliberate.
- Never flood. Dedup hard.
- Flag the sensitive and the "bigger than it looks."
