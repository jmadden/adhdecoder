#!/usr/bin/env python3
"""Decide which sources this sweep run should cover. Stdlib only, read-only.

Pure scheduling arithmetic over `config.sources[]` (enabled / weight / cadence),
`state.json`'s `sweepLog`, and the clock. It was prose until now, which meant a
scheduled run re-derived it three times a day from a paragraph - and the rule it
had to get right is the one that guarantees nothing is silently ignored:

    every enabled source is swept at least once per calendar day,
    even a `low`-weight `daily` one.

Ordering is by weight (high first, then medium, then low), config array order
breaking ties, because weight sets depth-of-coverage for the run. Weight never
decides whether a source is swept, only how early and how hard - urgency
outranks it everywhere else in the system.

Usage:
    sweep_plan.py --config CFG [--now ISO] [--scope every-run|due|all] [--json]

Exit 0 always when the config reads; the plan is the output, not a verdict.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger_query as lq  # noqa: E402

WEIGHT_ORDER = {"high": 0, "medium": 1, "low": 2}
CADENCES = ("every-run", "hourly", "daily")


def last_swept_per_source(state):
    """Newest timestamp seen per source key, from the sweepLog.

    The log records `{ ts, sources: { "<type>(<provider>)": "<result>" } }`, so a
    source's own freshness is the newest entry that mentions it - not the global
    `lastSwept`, which only says when SOME sweep ran.
    """
    seen = {}
    for entry in state.get("sweepLog") or []:
        ts = entry.get("ts")
        if not ts:
            continue
        for key in (entry.get("sources") or {}):
            if key not in seen or ts > seen[key]:
                seen[key] = ts
    return seen


def source_key(source):
    """The sweepLog key for a source: `type(provider)`, provider optional."""
    provider = source.get("provider")
    return "%s(%s)" % (source["type"], provider) if provider else str(source["type"])


def hours_since(stamp, now):
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if when.tzinfo is not None and now.tzinfo is None:
        when = when.replace(tzinfo=None)
    elif when.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return (now - when).total_seconds() / 3600.0


def plan(config, state, now, scope="due"):
    """Return the ordered list of sources to sweep, each with why it is included."""
    sources = [s for s in (config.raw.get("sources") or []) if s.get("enabled")]
    freshness = last_swept_per_source(state)
    today = now.date().isoformat()

    decided = []
    for index, source in enumerate(sources):
        key = source_key(source)
        weight = str(source.get("weight") or "medium").lower()
        cadence = str(source.get("cadence") or "every-run").lower()
        last = freshness.get(key)
        age_hours = hours_since(last, now)
        swept_today = bool(last and str(last)[:10] == today)

        if cadence not in CADENCES:
            reason = "unknown cadence %r, treated as every-run" % cadence
            include = True
        elif cadence == "every-run":
            reason = "cadence every-run"
            include = True
        elif not swept_today:
            # the guarantee: nothing is ignored for a whole day, whatever its
            # weight or cadence
            reason = "not yet swept today (once-per-day guarantee)"
            include = True
        elif cadence == "hourly":
            include = age_hours is None or age_hours >= 1
            reason = (
                "hourly and %s" % ("never swept" if age_hours is None
                                   else "%.1fh since last" % age_hours)
                if include else "hourly, swept %.1fh ago" % age_hours
            )
        else:  # daily, already swept today
            include = False
            reason = "daily, already swept today"

        if scope == "every-run":
            include = include and cadence == "every-run"
            if cadence != "every-run":
                reason = "skipped: light run covers every-run sources only"
        elif scope == "all":
            include = True
            reason = "scope=all: forced"

        decided.append({
            "type": source.get("type"),
            "provider": source.get("provider"),
            "key": key,
            "category": source.get("category"),
            "weight": weight,
            "cadence": cadence,
            "lastSwept": last,
            "ageHours": round(age_hours, 2) if age_hours is not None else None,
            "include": include,
            "reason": reason,
            "_order": (WEIGHT_ORDER.get(weight, 1), index),
        })

    decided.sort(key=lambda entry: entry["_order"])
    for entry in decided:
        entry.pop("_order")
    return decided


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, help="instance config.json")
    parser.add_argument("--now", default=None, help="ISO 8601 clock override (tests)")
    parser.add_argument(
        "--scope", default="due", choices=("every-run", "due", "all"),
        help="'due' (default) honours cadence; 'every-run' is a light pass; "
             "'all' forces every enabled source",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable plan")
    args = parser.parse_args(argv)

    config = lq.Config(args.config)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now()
    state = {}
    if config.state_file.is_file():
        try:
            with open(config.state_file, encoding="utf-8") as handle:
                state = json.load(handle)
        except json.JSONDecodeError:
            state = {}

    decided = plan(config, state, now, args.scope)
    included = [d for d in decided if d["include"]]

    if args.json:
        json.dump(
            {"now": now.isoformat(), "scope": args.scope,
             "sweep": included, "skip": [d for d in decided if not d["include"]]},
            sys.stdout, indent=2, sort_keys=True,
        )
        print()
        return 0

    print("sweep %d of %d enabled source(s), in this order:" % (len(included), len(decided)))
    for entry in included:
        print("  %-22s weight=%-6s %s" % (entry["key"], entry["weight"], entry["reason"]))
    skipped = [d for d in decided if not d["include"]]
    if skipped:
        print("skip:")
        for entry in skipped:
            print("  %-22s %s" % (entry["key"], entry["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
