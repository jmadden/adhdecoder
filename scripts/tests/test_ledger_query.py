#!/usr/bin/env python3
"""Fixture test for scripts/ledger_query.py.

Run: python3 scripts/tests/test_ledger_query.py

The Query is what every read-side skill calls, so what it selects IS what gets
chased. These checks pin the selectors against the shared invented fixture
ledger: that `slipping` never contains a soft or dateless item (a false overdue
chase aimed at a real person), that `drifting` catches the dateless items date
chasing misses, and that suppression and ready-to-close hold across all of them.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = REPO / "scripts" / "ledger_query.py"
FIXTURES = HERE / "fixtures"
NOW = "2026-08-12T09:15:00"

FAILURES = []


def check(condition, label):
    print("%s %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def build_instance(tmp):
    vault = tmp / "vault"
    instance = tmp / "instance"
    shutil.copytree(FIXTURES / "vault", vault)
    instance.mkdir()
    shutil.copyfile(FIXTURES / "ledger" / "fixture-state.json", instance / "state.json")
    config_path = tmp / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "identity": {"name": "Test User", "email": "test@example.com"},
                "storage": {
                    "adapter": "filesystem",
                    "instancePath": str(instance),
                    "knowledgePath": str(vault),
                    "overrides": {"stateFile": "state.json", "tasksDir": "Tasks"},
                },
                "ledger": {"backend": "obsidian", "writeMode": "readonly"},
                "schedule": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return config_path, vault


def q(config_path, selector, extra=()):
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--config", str(config_path),
            "--now", NOW, "--select", selector, "--json", *extra,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stdout, result.stderr)
        raise SystemExit("ledger_query.py --select %s exited %d" % (selector, result.returncode))
    return json.loads(result.stdout)


def whats(payload):
    return {p.get("what") or p.get("title") for p in payload["promises"]}


def main():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config_path, vault = build_instance(tmp)
        mtimes_before = {p: p.stat().st_mtime_ns for p in sorted(vault.rglob("*.md"))}

        # --- slipping: only real, passed hard dates ------------------------
        slipping = whats(q(config_path, "slipping"))
        check(
            "Deliver the staging redirect fix to Acme" in slipping,
            "slipping includes an overdue hard-deadline item",
        )
        check(
            "Maintain the Nu integration inventory" not in slipping,
            "slipping excludes a past SOFT date (a false overdue chase at a real person)",
        )
        check(
            {"Answer the Omicron header question", "Provide the Omicron domain list"} <= slipping,
            "slipping includes both notes that share one ticket (neither was deduped away)",
        )
        check(
            "Spec the header passthrough for Gamma" not in slipping,
            "slipping excludes ready-to-close items",
        )
        check(
            "Answer the Eta capacity question" not in slipping,
            "slipping excludes a snoozed item",
        )
        check(
            "Configure the Zeta test tenant" not in slipping,
            "slipping excludes a dismissed item with no draft",
        )
        check(
            "Provide the Mu quarterly summary" not in slipping,
            "slipping excludes a future-dated item",
        )

        # --- drifting: the dateless items date-chasing misses --------------
        drifting = whats(q(config_path, "drifting"))
        check(
            "Spec the header passthrough for Gamma" not in drifting,
            "drifting excludes ready-to-close items",
        )
        check(
            "Answer the Eta capacity question" not in drifting,
            "drifting excludes a snoozed item",
        )
        check(
            "Wait on Tau Bank for the SSO answer" not in drifting,
            "a blocked, high-stakes item untouched only 4 business days does NOT "
            "drift (the actual bug: blocked used to share the 2-day high-stakes "
            "threshold, so a note correctly parked as 'waiting on someone else' "
            "surfaced exactly as fast as something genuinely stuck on Jim)",
        )
        check(
            "Wait on Upsilon Bank for the vendor contact" in drifting,
            "a blocked item DOES eventually drift once untouched >= 10 business "
            "days - the fix is patience, not silence forever",
        )

        # --- ready-to-close matches the board's rule -----------------------
        ready = whats(q(config_path, "ready-to-close"))
        check(
            {"Spec the header passthrough for Gamma", "Review the Delta labeling recommendation"}
            <= ready,
            "ready-to-close holds both a markMetDraft and an updateDraft item",
        )
        check(
            "Spec the header passthrough for Gamma" in ready,
            "a draft outranks a dismissal in the Query, exactly as on the board",
        )

        # --- direction and context filters ---------------------------------
        waiting = whats(q(config_path, "waiting"))
        check(
            "Follow up with Beta Co on the SSO answer" in waiting,
            "waiting selects they-owe-me items",
        )
        check(
            "Deliver the staging redirect fix to Acme" not in waiting,
            "waiting excludes i-owe-them items",
        )
        scoped = q(config_path, "open", ["--context", "beta co"])
        check(
            scoped["count"] == 1 and "Beta Co" in str(whats(scoped)),
            "--context filters case-insensitively",
        )
        directed = q(config_path, "open", ["--direction", "they-owe-me"])
        check(
            all(p["direction"] == "they-owe-me" for p in directed["promises"]),
            "--direction filters",
        )

        # --- derived state is exposed, not re-derived by the caller --------
        payload = q(config_path, "open")
        sample = next(p for p in payload["promises"] if p["id"].endswith("Acme.md"))
        check(
            set(["open", "overdue", "readyToClose", "suppressed", "staleDays", "pronouns"])
            <= set(sample["derived"]),
            "each record exposes its derived state for the caller to use as-is",
        )
        check(
            not any(k.startswith("_") for k in sample),
            "private keys are not leaked into the JSON contract",
        )

        # --- what a surface must be able to report -------------------------
        check(
            {f["file"] for f in payload["parseFailures"]}
            == {"Broken frontmatter for Theta.md", "Untagged scratch note.md",
                "Summarize the Sigma rollout.md"},
            "parse failures ride along with every query",
        )
        check(
            "Draft the Xi migration summary.md"
            in {w["file"] for w in payload["frontmatterWarnings"]},
            "frontmatter warnings ride along with every query",
        )
        check(
            payload["collapsed"] and payload["collapsed"][0]["id"].startswith("ISSUE-123"),
            "cross-store collapses ride along with every query",
        )

        # --- a stored frontmatterWarning is ignored outright ---------------
        # both fixture entries carry one; neither note has anything wrong with it
        # now. A lint is a claim about the note's CURRENT content, so it is only
        # ever the live check. The stored field is deprecated: it had no writer in
        # code, and the timestamp gate that was supposed to expire it borrowed
        # `lastVerified`, which unrelated verify writes bump - so a verify seconds
        # after a note was FIXED carried a days-old warning forward as current.
        warned_files = {w["file"] for w in payload["frontmatterWarnings"]}
        check(
            "Configure the Zeta test tenant.md" not in warned_files,
            "a stored itemMeta.frontmatterWarning recorded before the note's "
            "dateModified is not shown",
        )
        check(
            "Follow up with Beta Co on the SSO answer.md" not in warned_files,
            "a stored itemMeta.frontmatterWarning recorded AFTER the note's "
            "dateModified is ALSO not shown - a fresh timestamp on a stored lint "
            "proves nothing about whether the lint still holds",
        )

        # --- a duplicate key parses cleanly but must not pass silently -----
        warned = {w["file"]: w["warning"] for w in payload["frontmatterWarnings"]}
        check(
            "Draft the Xi migration summary.md" in warned
            and "duplicate frontmatter key(s): dateModified" in warned["Draft the Xi migration summary.md"],
            "a duplicate frontmatter key is surfaced (a real YAML parser keeps the "
            "last value and discards the other, silently)",
        )
        check(
            "Draft the Xi migration summary" in whats(q(config_path, "open")),
            "the duplicate-key note still parses and still appears (a lint, not a failure)",
        )

        # --- an unsupported construct is refused, never half-read ----------
        refused = {f["file"]: f["symptom"] for f in payload["parseFailures"]}
        check(
            "block scalar (|)" in refused.get("Summarize the Sigma rollout.md", ""),
            "a construct outside the parser's subset is refused with a precise "
            "symptom, so the note is reported rather than silently misread",
        )
        check(
            "Summarize the Sigma rollout" not in whats(q(config_path, "all")),
            "a refused note produces no promise (it is reported, not guessed at)",
        )
        check(
            "Update the Rho onboarding tracker" in whats(q(config_path, "all")),
            "a note with a quoted scalar containing colons, escaped quotes and a "
            "URL fragment parses correctly",
        )

        # --- unknown selector fails loudly ---------------------------------
        bad = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(config_path), "--select", "nonsense"],
            capture_output=True, text=True,
        )
        check(bad.returncode != 0 and "unknown selector" in bad.stdout + bad.stderr,
              "an unknown selector fails loudly rather than returning nothing")

        # --- guardrail: read-only ------------------------------------------
        mtimes_after = {p: p.stat().st_mtime_ns for p in sorted(vault.rglob("*.md"))}
        check(mtimes_before == mtimes_after, "no note was written (mtimes unchanged)")
        source = SCRIPT.read_text()
        write_calls = [
            token for token in (
                '.write_text(', '.write(', '.writelines(', 'os.replace(',
                'NamedTemporaryFile', '.unlink(', '.mkdir(', 'shutil.',
                '"w"', "'w'", '"a"', "'a'",
            )
            if token in source
        ]
        check(not write_calls, "the module has no write path (found: %s)" % write_calls)

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
