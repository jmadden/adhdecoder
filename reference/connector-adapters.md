# ADHDecoder — Connector Storage Adapters (design spec)

Written 2026-07-31. Design input for the second storage-adapter family. Not yet
shipped as an adapter; this doc pins the contract so a `storage/<name>/`
adapter can be added without touching core.

## The gap this fills

The v0.1 **filesystem** adapter requires real files physically present on the
machine that runs sweeps (`instancePath` / `knowledgePath`). Cloud-native
stores (the `~~docs`-style drive services) serve **placeholders**: the path
exists but the bytes live behind an API. Reading a placeholder as a file gets
garbage or a stub. A **connector adapter** reads and writes through the
service's connector tools instead of a path.

## Scope

Storage adapters answer "WHERE do the instance layer and knowledge base
live" - a different axis from ledger backends (WHICH store holds promises).
A connector storage adapter must serve the same things filesystem does:

- the instance layer: `config.json` + `state.json`
- the knowledge base files: Radar, archive, the board file

## Config shape

```json
"storage": {
  "adapter": "<connector adapter name>",
  "connector": { "category": "~~docs", "rootRef": "<folder id or share URL>" },
  "overrides": { "stateFile": "state.json", "radarFile": "Radar.md", "...": "..." }
}
```

- `adapter` selects the storage adapter (today only `"filesystem"` ships).
- `connector.rootRef` replaces `instancePath`/`knowledgePath`: an opaque
  reference (folder id, share URL) the connector tools resolve. Never assume it
  is a filesystem path.
- `overrides` keep meaning "what each file is called," now relative to
  `rootRef`.

## Operations contract

Mirror filesystem semantics through connector tools:

- **read(name)** — fetch the file's content by resolving `rootRef` + name via
  the connector's search/get tools. Treat "not found" as absent, same as a
  missing file.
- **write(name, content)** — create or update. Atomicity is the service's
  version model; on services without atomic replace, upload-new-then-rename is
  the fallback. Never leave a partial state file as the latest version.
- **list(dirName)** — enumerate children of a folder ref (for tasksDir-style
  enumeration).

## Rules carried over unchanged

- **No hidden files.** Same rule, connector edition: visible names only.
- **Single writer.** One machine/session sweeps a given `rootRef`. The
  service's revision history is a bonus, not an excuse for concurrent writers.
- **The three buckets stay separate.** The plugin never stores data; the
  instance layer and knowledge base merely relocate behind the connector.
- **Guardrails intact.** A connector adapter moves ADHDecoder's OWN files. It
  grants zero new license to write anything else in the user's drive.

## Failure posture

Connector unavailable at run time -> the run degrades exactly like a missing
path: `doctor` reports it, `daily-run` skips with a one-line recap note, no
partial writes. Never fall back to a local shadow copy silently (that creates
a second writer).

## Non-goals (v1 of this family)

- No offline cache/sync layer.
- No multi-root federation (one `rootRef` per instance).
- No migration tool; moving stores is a manual copy + `setup` edit.
