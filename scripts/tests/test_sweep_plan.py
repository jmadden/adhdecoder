#!/usr/bin/env python3
"""Tests for scripts/sweep_plan.py, the mechanical "what do I sweep" decision.

Run: python3 scripts/tests/test_sweep_plan.py

The rule that matters most here is the once-per-day guarantee: a low-weight
`daily` source must still be swept if it has not been covered today, because the
whole point is that nothing is silently ignored. These pin that, plus weight
ordering and cadence behaviour.
"""

import importlib.util
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = REPO / "scripts" / "sweep_plan.py"

spec = importlib.util.spec_from_file_location("sweep_plan", SCRIPT)
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)

FAILURES = []


def check(condition, label):
    print("%s %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


class FakeConfig:
    def __init__(self, sources):
        self.raw = {"sources": sources}


SOURCES = [
    {"type": "issues", "provider": "jira", "enabled": True, "weight": "low", "cadence": "daily"},
    {"type": "chat", "provider": "slack", "enabled": True, "weight": "high", "cadence": "every-run"},
    {"type": "email", "provider": "gmail", "enabled": True, "weight": "medium", "cadence": "hourly"},
    {"type": "crm", "provider": "salesforce", "enabled": False, "weight": "high", "cadence": "every-run"},
]


def keys(entries):
    return [e["key"] for e in entries if e["include"]]


def main():
    now = datetime.fromisoformat("2026-08-14T14:00:00")
    config = FakeConfig(SOURCES)

    # --- nothing swept yet today -----------------------------------------
    empty = {"sweepLog": []}
    decided = sp.plan(config, empty, now)
    check(
        keys(decided) == ["chat(slack)", "email(gmail)", "issues(jira)"],
        "all enabled sources are included and ordered high -> medium -> low",
    )
    check(
        "crm(salesforce)" not in [e["key"] for e in decided],
        "a disabled source never appears at all",
    )

    # --- the once-per-day guarantee ---------------------------------------
    swept_earlier_today = {"sweepLog": [
        {"ts": "2026-08-14T08:00:00", "sources": {"issues(jira)": "ok", "chat(slack)": "ok",
                                                  "email(gmail)": "ok"}},
    ]}
    decided = sp.plan(config, swept_earlier_today, now)
    check(
        "issues(jira)" not in keys(decided),
        "a daily source already swept today is skipped",
    )
    check(
        "chat(slack)" in keys(decided),
        "an every-run source is swept again regardless",
    )
    check(
        "email(gmail)" in keys(decided),
        "an hourly source swept 6h ago is due again",
    )

    swept_yesterday = {"sweepLog": [
        {"ts": "2026-08-13T08:00:00", "sources": {"issues(jira)": "ok"}},
    ]}
    decided = sp.plan(config, swept_yesterday, now)
    included = [e for e in decided if e["include"]]
    daily = next(e for e in included if e["key"] == "issues(jira)")
    check(
        "once-per-day guarantee" in daily["reason"],
        "a LOW-weight DAILY source not swept today is still included - the "
        "guarantee that nothing is silently ignored",
    )

    # --- hourly within the hour -------------------------------------------
    just_swept = {"sweepLog": [
        {"ts": "2026-08-14T13:40:00", "sources": {"email(gmail)": "ok", "issues(jira)": "ok"}},
    ]}
    decided = sp.plan(config, just_swept, now)
    check(
        "email(gmail)" not in keys(decided),
        "an hourly source swept 20 minutes ago is skipped",
    )

    # --- scopes -------------------------------------------------------------
    light = sp.plan(config, just_swept, now, scope="every-run")
    check(
        keys(light) == ["chat(slack)"],
        "scope=every-run is a light pass: only every-run sources",
    )
    forced = sp.plan(config, just_swept, now, scope="all")
    check(
        len(keys(forced)) == 3,
        "scope=all forces every enabled source regardless of cadence",
    )

    # --- freshness is per-source, not global --------------------------------
    mixed = {"sweepLog": [
        {"ts": "2026-08-14T08:00:00", "sources": {"chat(slack)": "ok"}},
        {"ts": "2026-08-13T08:00:00", "sources": {"issues(jira)": "ok"}},
    ]}
    decided = sp.plan(config, mixed, now)
    jira = next(e for e in decided if e["key"] == "issues(jira)")
    check(
        jira["lastSwept"] == "2026-08-13T08:00:00" and jira["include"],
        "per-source freshness comes from the newest sweepLog entry naming it, "
        "not from the global lastSwept",
    )

    # --- defaults -----------------------------------------------------------
    bare = FakeConfig([{"type": "docs", "enabled": True}])
    decided = sp.plan(bare, {"sweepLog": []}, now)
    check(
        decided[0]["weight"] == "medium" and decided[0]["cadence"] == "every-run",
        "a source with no weight/cadence defaults to medium + every-run",
    )
    check(decided[0]["key"] == "docs", "a source with no provider keys on type alone")

    # --- the CLI runs -------------------------------------------------------
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        instance = tmp / "instance"
        instance.mkdir()
        (instance / "state.json").write_text(json.dumps({
            "schemaVersion": 2, "promises": [], "sweepLog": [],
            "suppressed": [{"ref": "ISSUE-000", "source": "issues",
                            "context": "Sigma Partners",
                            "reason": "Self-created by an earlier run."}],
        }))
        cfg = tmp / "config.json"
        cfg.write_text(json.dumps({
            "identity": {"name": "t"},
            "storage": {"instancePath": str(instance), "knowledgePath": str(tmp / "vault"),
                        "overrides": {"stateFile": "state.json", "tasksDir": "Tasks"}},
            "ledger": {"backend": "builtin"},
            "sources": SOURCES,
            "schedule": {},
        }))
        import subprocess
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(cfg), "--now",
             "2026-08-14T14:00:00", "--json"],
            capture_output=True, text=True,
        )
        payload = json.loads(result.stdout)
        check(
            result.returncode == 0 and len(payload["sweep"]) == 3,
            "--json emits a machine-readable plan the skill can act on",
        )
        # The plan is where a sweep is TOLD what it must not raise. Before this,
        # `suppressed` had no reader anywhere, so obeying it depended on a model
        # remembering the field existed.
        refs = {e["ref"] for e in payload["suppressedRefs"]}
        check(
            refs == {"ISSUE-000"},
            "a suppressed ref is reported in the plan, and an unsuppressed one "
            "is not",
        )
        check(
            "suppressed" not in payload,
            "the key is `suppressedRefs`: `suppressed` already means the derived "
            "board term everywhere else in the JSON contract",
        )

    print()
    if FAILURES:
        print("%d check(s) failed:" % len(FAILURES))
        for label in FAILURES:
            print("  - %s" % label)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
