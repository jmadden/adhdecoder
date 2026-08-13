#!/usr/bin/env python3
"""Tests for scripts/doctor_check.py, the mechanical half of `doctor`.

Run: python3 scripts/tests/test_doctor_check.py

A health check is only worth anything if it fails when the setup is actually
broken, so most of these stage a specific breakage (missing identity, a backend
with no adapter, readwrite without cutover, a vanished notes directory) and
assert the gap is reported with a fix. The last check is the important one for
honesty: connector presence must come back `unchecked`, never `OK`, because a
subprocess cannot see the session's connectors and a false all-clear is worse
than silence.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = REPO / "scripts" / "doctor_check.py"
FIXTURES = HERE / "fixtures"

FAILURES = []


def check(condition, label):
    print("%s %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


CLEAN_NOTE = """---
title: A well-formed task
status: todo
priority: medium
due: 2026-08-20
dateCreated: 2026-08-01T09:00:00-07:00
dateModified: 2026-08-05T09:00:00-07:00
customer: Acme Corp
requester:
  - A. Contact
tags:
  - task
---

> **Summary:** Nothing wrong with this one.

- Source: [Doc](https://docs.example.com/clean)
"""


def build(tmp, clean_vault=False, **overrides):
    """A working instance, then apply overrides to break it on purpose.

    The shared fixture vault deliberately contains malformed notes (that is what
    the parser tests need), so it is NOT a healthy setup - a vault with
    unparseable notes is a real gap, and doctor is right to say so.
    `clean_vault=True` builds a small purpose-made vault instead, so the
    all-clear path can be asserted without sanitising the shared fixture with
    fragile heuristics.
    """
    instance = tmp / "instance"
    if not instance.exists():
        instance.mkdir()
        shutil.copyfile(FIXTURES / "ledger" / "fixture-state.json", instance / "state.json")

    if clean_vault:
        vault = tmp / "vault-clean"
        if not vault.exists():
            (vault / "Tasks").mkdir(parents=True)
            (vault / "Tasks" / "A well-formed task.md").write_text(CLEAN_NOTE)
        instance = tmp / "instance-clean"
        if not instance.exists():
            instance.mkdir()
            # a minimal ledger: no itemMeta warnings to report
            (instance / "state.json").write_text(json.dumps(
                {"schemaVersion": 2, "promises": [], "itemMeta": {}, "sweepLog": []}, indent=2))
    else:
        vault = tmp / "vault"
        if not vault.exists():
            shutil.copytree(FIXTURES / "vault", vault)
    config = {
        "identity": {"name": "Test User", "email": "test@example.com"},
        "storage": {
            "adapter": "filesystem",
            "instancePath": str(instance),
            "knowledgePath": str(vault),
            "overrides": {"stateFile": "state.json", "tasksDir": "Tasks"},
        },
        "ledger": {"backend": "obsidian", "writeMode": "readonly"},
        "sources": [{"type": "chat", "provider": "slack", "enabled": True}],
        "schedule": {},
    }
    for path, value in overrides.items():
        cursor = config
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        if value is None:
            cursor.pop(parts[-1], None)
        else:
            cursor[parts[-1]] = value
    path = tmp / ("config-%d.json" % len(list(tmp.glob("config-*.json"))))
    path.write_text(json.dumps(config, indent=2))
    return path


def run(config_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(config_path), "--json"],
        capture_output=True, text=True,
    )
    return result, json.loads(result.stdout) if result.stdout.strip() else {}


def find(payload, name):
    return [f for f in payload.get("findings", []) if f["check"] == name]


def statuses(payload, name):
    return {f["status"] for f in find(payload, name)}


def main():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)

        # --- a healthy setup --------------------------------------------------
        result, payload = run(build(tmp, clean_vault=True))
        check(result.returncode == 0, "a fully healthy setup exits 0")
        check(statuses(payload, "config") == {"OK"}, "config check passes")
        check(statuses(payload, "backend") == {"OK"}, "backend resolves to its adapter")
        check(statuses(payload, "writeMode") == {"OK"}, "readonly write mode is OK")
        check(
            statuses(payload, "recordStore") == {"OK"},
            "a vault of well-formed notes reports no record-store gaps",
        )

        # --- a vault with malformed notes is NOT healthy -----------------------
        result, payload = run(build(tmp))
        check(
            result.returncode == 1 and "GAP" in statuses(payload, "recordStore"),
            "a vault containing unparseable notes exits 1 - an invisible record "
            "is a real problem, not a cosmetic one",
        )

        # --- the honesty check ------------------------------------------------
        connectors = find(payload, "connectors")
        check(
            len(connectors) == 1 and connectors[0]["status"] == "unchecked",
            "connector presence reports `unchecked`, never OK - a subprocess "
            "cannot see the session's connectors and a false all-clear is worse "
            "than saying nothing",
        )
        check(
            connectors and connectors[0]["fix"],
            "the unchecked finding tells the skill what it must do itself",
        )

        # --- broken: identity --------------------------------------------------
        result, payload = run(build(tmp, **{"identity": None}))
        check(
            result.returncode == 1 and "GAP" in statuses(payload, "config"),
            "a missing identity is a gap",
        )

        # --- broken: unknown backend --------------------------------------------
        result, payload = run(build(tmp, **{"ledger.backend": "notion"}))
        gap = [f for f in find(payload, "backend") if f["status"] == "GAP"]
        check(
            result.returncode == 1 and gap and "ledger-notion" in gap[0]["message"],
            "a backend with no matching adapter is a gap, naming the skill it wanted",
        )

        # --- the deprecated alias still resolves ---------------------------------
        result, payload = run(build(tmp, **{"ledger.backend": "tasknotes"}))
        check(
            "GAP" not in statuses(payload, "backend"),
            "the deprecated `tasknotes` alias still resolves to the obsidian adapter",
        )
        check(
            "note" in statuses(payload, "backend"),
            "...and is flagged as deprecated rather than passing silently",
        )

        # --- broken: readwrite without cutover ------------------------------------
        result, payload = run(build(tmp, **{"ledger.writeMode": "readwrite"}))
        gap = [f for f in find(payload, "writeMode") if f["status"] == "GAP"]
        check(
            result.returncode == 1 and gap and "cutover" in gap[0]["message"],
            "readwrite without singleWriterConfirmed is a gap (the single-writer rule)",
        )

        result, payload = run(build(tmp, **{
            "ledger.writeMode": "readwrite",
            "ledger.cutover": {"singleWriterConfirmed": True},
        }))
        check(
            "GAP" not in statuses(payload, "writeMode"),
            "readwrite WITH the cutover confirmation passes",
        )

        # --- readwrite on builtin is noise, not a gap -----------------------------
        result, payload = run(build(tmp, **{
            "ledger.backend": "builtin", "ledger.writeMode": "readwrite",
        }))
        check(
            "note" in statuses(payload, "writeMode") and "GAP" not in statuses(payload, "writeMode"),
            "readwrite on builtin is a note, not a gap - builtin is always writable",
        )

        # --- broken: notes directory gone -----------------------------------------
        result, payload = run(build(tmp, **{
            "storage.overrides": {"stateFile": "state.json", "tasksDir": "NoSuchDir"},
        }))
        gap = [f for f in find(payload, "backend") if f["status"] == "GAP"]
        check(
            result.returncode == 1 and gap and "does not exist" in gap[0]["message"],
            "a missing notes directory is a gap",
        )

        # --- record-store failures are named individually --------------------------
        result, payload = run(build(tmp))
        store = find(payload, "recordStore")
        failures = [f for f in store if f["status"] == "GAP"]
        check(
            any("Broken frontmatter for Theta.md" in f["message"] for f in failures),
            "an unparseable note is named by filename, so it cannot stay invisible",
        )
        check(
            any("Summarize the Sigma rollout.md" in f["message"] for f in failures),
            "a note using a construct the parser refuses is named too",
        )
        check(
            any(f["status"] == "note" and "duplicate frontmatter key" in f["message"]
                for f in store),
            "an ambiguous-but-readable note is a note, not a gap",
        )

        # --- an unreadable config is fatal, not a crash -----------------------------
        broken = tmp / "not-json.json"
        broken.write_text("{ this is not json")
        result, payload = run(broken)
        check(result.returncode == 2, "an unparseable config exits 2 (fatal), not 1")
        check(
            any("run `setup`" in (f.get("fix") or "") for f in payload.get("findings", [])),
            "...and points at setup rather than a stack trace",
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
