# ADHDecoder — Scheduling + Source Priority (build spec)

Build input. Drop into the repo as `reference/scheduling.md`. Written
2026-07-27. Generic; no personal or company data. These two are one concern:
"when, how often, and how heavily do we hit each source."

## Why together

Scheduling makes ADHDecoder run without the user remembering to invoke it.
"Hit chat early and often, email next, issues least" is a source-priority
statement AND a frequency statement. So source weight + cadence feed the
scheduler.

## Config

Extend `sources` entries and add board output to `schedule`:

```json
"schedule": {
  "pivots": ["08:30", "12:30", "16:00"],
  "timezone": "America/Los_Angeles",
  "boardPath": "<path where the refreshed board file is written each run>"
},
"sources": [
  { "type": "chat",   "enabled": true, "category": "~~chat",          "weight": "high",   "cadence": "every-run" },
  { "type": "email",  "enabled": true, "category": "~~email",         "weight": "medium", "cadence": "every-run" },
  { "type": "issues", "enabled": true, "category": "~~issue tracker", "weight": "low",    "cadence": "daily" }
]
```

- **`weight`** (`high` | `medium` | `low`, default `medium`): emphasis. Sets
  sweep order/depth and is a **tiebreak** in surfacing.
- **`cadence`** (`every-run` | `daily` | `hourly`, default `every-run`): how
  often this source is swept.
- **`boardPath`**: where each run writes a refreshed, read-only board the user
  can open (scheduled runs are non-interactive, so there must be a durable place
  to look). If unset, the run only prints to chat.

## The scheduled run routine

A routine the scheduler triggers (e.g. a `daily-run` skill orchestrating the
existing skills). Each run:

1. **Sweep** enabled sources, **ordered by weight** (high first, deepest
   coverage), honoring **cadence** for this run: always include `every-run`
   sources; include cadence-due sources; and **guarantee every enabled source is
   swept at least once per day** (none ignored, even `low`/`daily`).
2. **Reconcile** new / aging / about-to-surface items (verify before flagging).
3. **Update the ledger** (dedup, promises, source links).
4. **Refresh the board file** at `boardPath`: a read-only view (chase-in +
   drift + handoff follow-ups, with source links). Overwrite in place.
5. **Recap**: one line (what changed, what's newly slipping).

Never auto-send, never auto-post. A run drafts, updates the ledger, and
refreshes the board, nothing leaves for a customer.

## Surfacing weight (the guardrail)

Source `weight` is **secondary to urgency**. Ranking order:

1. stakes (S1/S2, high priority, go-live, PCI/security)
2. time (overdue > due-soon; staleness)
3. **then** source weight, as a tiebreak between otherwise-equal items.

A genuine emergency from a `low`-weight source (e.g. an S1 in the issue tracker)
**must still surface**. Weight shapes attention and frequency; it never buries
something urgent. This is how "none should be ignored" holds.

## Setup (how the schedule gets wired)

The plugin describes the run routine; the **user wires the host scheduler** to
invoke it at the `pivots` (in Cowork, via scheduled tasks). Document this in the
README. For "early and often," the user can add extra light runs (e.g. hourly)
that sweep only `every-run` / high-weight sources.

## Guardrails

- Read-only against TaskNotes and sources; only `state.json` and the board file
  get writes. Never auto-send / auto-post / auto-create tasks elsewhere.
- Weight is secondary to urgency; every enabled source swept >= once/day.
- Board file is a generated view (link, never paste raw feeds). No hidden files.

## Build scope (v1)

- Config: `weight` + `cadence` on sources; `boardPath` on schedule.
- `daily-run` routine skill: sweep(weighted, cadence-aware, all-sources-once/day)
  -> reconcile -> ledger update -> refresh board file -> recap.
- Sweep: honor weight (order/depth) + cadence.
- Surfacing (chase-in/drift/panic/radiate-out): weight as tiebreak only, under
  stakes + time.
- README: how to wire the host scheduler to the run routine at the pivots.
