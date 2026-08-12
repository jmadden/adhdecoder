#!/usr/bin/env python3
"""Validate an ADHDecoder state.json against reference/ledger-schema.md.

Reports unknown keys as gaps and deprecated keys as notes, at all three levels
(top level / promise record / itemMeta entry). Read-only by contract: it never
edits state.json, never renames a field, and never bumps schemaVersion. Doctor
validates and prescribes; the user applies.

This exists because the schema was prose, so each session invented its own
vocabulary and the duplicates were only found by hand-auditing the file.

Usage:
    validate-state.py --config <instance config.json> [--json] [--quiet]
    validate-state.py --state <path to state.json> [--json] [--quiet]

Exit status: 0 when there are no gaps (notes alone do not fail), 1 when unknown
keys were found, 2 on a usage or parse error.

Generic by construction: field names only, never a user's values.
"""

import argparse
import json
import sys
from pathlib import Path

SCHEMA_VERSION = 2
SWEEP_LOG_CAP = 10

# --- what schemaVersion 2 defines -----------------------------------------
TOP_LEVEL = {
    "schemaVersion", "lastSwept", "promises", "dedup", "knownChannels",
    "watchedThreads", "dismissedFromBoard", "suppressed", "people", "sweepLog",
    "itemMeta",
}
PROMISE = {
    "id", "title", "context", "direction", "what", "owner", "expectBy", "status",
    "stakes", "stakesOverride", "source", "noteRef", "noteOnly", "created",
    "lastVerified", "verifyStatus", "verifyReason", "why", "deadlineType",
    "snoozedUntil", "driftClearedUntil", "history", "promotedTo", "note",
    "completedDate", "relatedRefs",
}
ITEM_META = {
    "snoozedUntil", "deadlineType", "deadlineTypeReason", "verifyStatus",
    "verifyReason", "lastVerified", "source", "noteOnly", "dismissedFromBoard",
    "frontmatterWarning", "markMetDraft", "updateDraft", "appliedMarkMet",
}

# --- deprecated: recognised, reported as a note, never written again ------
DEPRECATED = {
    "promise": {
        "createdAt": "created",
        "counterparty": "owner (+ note for the nuance)",
    },
    "itemMeta": {
        "resolvedNotDropped": "markMetDraft",
        "closedBy": "appliedMarkMet.by",
        "recommendation": "updateDraft",
        "parseError": "nothing; parse failures are detected live, never stored",
    },
}

LEVEL_KEYS = {"top": TOP_LEVEL, "promise": PROMISE, "itemMeta": ITEM_META}


def collect(state):
    """Return (gaps, notes). Field names only: never echo a user's values."""
    gaps, notes = [], []

    def scan(level, keys, where):
        known = LEVEL_KEYS[level]
        deprecated = DEPRECATED.get(level, {})
        for key in sorted(keys):
            if key in known:
                continue
            if key in deprecated:
                notes.append(
                    {
                        "level": level,
                        "key": key,
                        "where": where,
                        "message": "deprecated -> use %s" % deprecated[key],
                    }
                )
            else:
                gaps.append(
                    {
                        "level": level,
                        "key": key,
                        "where": where,
                        "message": "unknown key, not in schemaVersion %d" % SCHEMA_VERSION,
                    }
                )

    scan("top", state.keys(), "top level")

    # aggregate by key so one invented field on 11 records is one finding
    promise_keys = {}
    for promise in state.get("promises") or []:
        if not isinstance(promise, dict):
            continue
        for key in promise:
            promise_keys.setdefault(key, 0)
            promise_keys[key] += 1
    scan("promise", promise_keys, "promise record")

    meta_keys = {}
    item_meta = state.get("itemMeta") or {}
    if isinstance(item_meta, dict):
        for entry in item_meta.values():
            if not isinstance(entry, dict):
                continue
            for key in entry:
                meta_keys.setdefault(key, 0)
                meta_keys[key] += 1
    scan("itemMeta", meta_keys, "itemMeta entry")

    counts = {"promise": promise_keys, "itemMeta": meta_keys}
    for finding in gaps + notes:
        level = finding["level"]
        if level in counts:
            finding["seen_on"] = counts[level].get(finding["key"], 0)

    gaps.extend(check_suppressed(state))
    notes.extend(check_sweep_log(state))
    return gaps, notes


def check_suppressed(state):
    """Every suppression needs a reason.

    An unexplained suppression is indistinguishable from a bug: the ref stops
    producing promises and nothing says why, so a real ask can sit suppressed
    forever looking like a quiet source.
    """
    gaps = []
    entries = state.get("suppressed") or []
    if not isinstance(entries, list):
        return [
            {
                "level": "top",
                "key": "suppressed",
                "where": "top level",
                "message": "must be a list of { ref, recordId, source, context, reason }",
            }
        ]
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not str(entry.get("reason") or "").strip():
            gaps.append(
                {
                    "level": "top",
                    "key": "suppressed[%d]" % index,
                    "where": "top level",
                    "message": "suppressed with no reason -> add one or remove the entry",
                }
            )
    return gaps


def check_sweep_log(state):
    """Structural checks only on sweepLog.

    Deliberately NOT judging the result strings: "responding but returning
    nothing" depends on what a given source's silence means, which is a reading
    task for `doctor`, not a mechanical one. What is mechanical: the log has a
    shape, and it is capped.
    """
    notes = []
    entries = state.get("sweepLog") or []
    if not isinstance(entries, list):
        return [
            {
                "level": "top",
                "key": "sweepLog",
                "where": "top level",
                "message": "must be a list of { ts, sources }",
            }
        ]
    if len(entries) > SWEEP_LOG_CAP:
        notes.append(
            {
                "level": "top",
                "key": "sweepLog",
                "where": "top level",
                "message": "%d entries, cap is %d -> trim the oldest; it is a log, not a store"
                % (len(entries), SWEEP_LOG_CAP),
            }
        )
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("ts") or not isinstance(
            entry.get("sources"), dict
        ):
            notes.append(
                {
                    "level": "top",
                    "key": "sweepLog[%d]" % index,
                    "where": "top level",
                    "message": "entry needs a ts and a sources map",
                }
            )
    return notes


def declared_version(state):
    version = state.get("schemaVersion")
    return version if isinstance(version, int) else None


def report(state, gaps, notes, stream=sys.stdout):
    version = declared_version(state)
    if version is None:
        print("schemaVersion: absent (expected %d)" % SCHEMA_VERSION, file=stream)
    elif version != SCHEMA_VERSION:
        print(
            "schemaVersion: %d (current is %d; the file is served normally, the "
            "version only records which vocabulary it was written against)"
            % (version, SCHEMA_VERSION),
            file=stream,
        )
    else:
        print("schemaVersion: %d, current" % version, file=stream)

    print(
        "suppressed: %d entr%s | sweepLog: %d run%s"
        % (
            len(state.get("suppressed") or []),
            "y" if len(state.get("suppressed") or []) == 1 else "ies",
            len(state.get("sweepLog") or []),
            "" if len(state.get("sweepLog") or []) == 1 else "s",
        ),
        file=stream,
    )

    if not gaps and not notes:
        print("schema: OK, no unknown or deprecated fields", file=stream)
        return

    for finding in gaps:
        seen = finding.get("seen_on")
        suffix = " (on %d)" % seen if seen else ""
        print(
            "GAP  %s.%s%s: %s" % (finding["where"], finding["key"], suffix, finding["message"]),
            file=stream,
        )
    for finding in notes:
        seen = finding.get("seen_on")
        suffix = " (on %d)" % seen if seen else ""
        print(
            "note %s.%s%s: %s" % (finding["where"], finding["key"], suffix, finding["message"]),
            file=stream,
        )
    if gaps:
        print(
            "\n%d unknown field(s). Report only: nothing here is repaired "
            "automatically. Name them in the schema or remove them by hand."
            % len(gaps),
            file=stream,
        )


def resolve_state_path(args):
    if args.state:
        return Path(args.state).expanduser()
    config_path = Path(args.config).expanduser()
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)
    storage = config.get("storage") or {}
    overrides = storage.get("overrides") or {}
    return Path(storage.get("instancePath", "")).expanduser() / overrides.get(
        "stateFile", "state.json"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--config", help="instance config.json; resolves the state file")
    group.add_argument("--state", help="path to state.json directly")
    parser.add_argument("--json", action="store_true", help="machine-readable findings")
    parser.add_argument("--quiet", action="store_true", help="exit status only")
    args = parser.parse_args(argv)

    try:
        state_path = resolve_state_path(args)
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError, KeyError) as error:
        print("cannot read the ledger: %s" % error, file=sys.stderr)
        return 2
    if not isinstance(state, dict):
        print("cannot read the ledger: top level is not an object", file=sys.stderr)
        return 2

    gaps, notes = collect(state)
    if args.json:
        json.dump(
            {
                "state": str(state_path),
                "schemaVersion": declared_version(state),
                "expectedSchemaVersion": SCHEMA_VERSION,
                "gaps": gaps,
                "notes": notes,
            },
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        print()
    elif not args.quiet:
        report(state, gaps, notes)
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
