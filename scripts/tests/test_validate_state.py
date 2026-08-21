#!/usr/bin/env python3
"""Fixture test for scripts/validate-state.py.

Run: python3 scripts/tests/test_validate_state.py

Asserts the section-2 contract: unknown keys report as gaps at all three levels,
deprecated keys report as notes naming their replacement, the declared
schemaVersion is reported, and nothing is ever written. Shares the invented
fixture ledger with the render test.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = REPO / "scripts" / "validate-state.py"
FIXTURE = HERE / "fixtures" / "ledger" / "fixture-state.json"

FAILURES = []


def check(condition, label):
    print("%s %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def run(state_path, extra=()):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--state", str(state_path), *extra],
        capture_output=True,
        text=True,
    )
    return result


def main():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        state = tmp / "state.json"
        shutil.copyfile(FIXTURE, state)
        before = state.read_bytes()

        result = run(state)
        out = result.stdout
        print(out)

        # --- gaps: unknown keys at each level ------------------------------
        check(result.returncode == 1, "exit status is 1 when unknown keys exist")
        check(
            "GAP  top level.unknownTopLevelField" in out,
            "an unknown top-level key reports as a gap",
        )
        check(
            "GAP  itemMeta entry.inventedOverlayField" in out,
            "an unknown itemMeta key reports as a gap",
        )

        # --- notes: deprecated keys name their replacement -----------------
        check(
            "note promise record.createdAt (on 1): deprecated -> use created" in out,
            "a deprecated promise key reports as a note with its replacement",
        )
        check(
            "note itemMeta entry.resolvedNotDropped (on 1): deprecated -> use markMetDraft" in out,
            "a deprecated itemMeta key reports as a note with its replacement",
        )
        check(
            "GAP" not in out.split("note promise record.createdAt")[-1].split("\n")[0],
            "a deprecated key is never reported as a gap",
        )

        # --- version reporting ---------------------------------------------
        check("schemaVersion: 1 (current is 3" in out, "the declared version is reported")

        # --- machine-readable form -----------------------------------------
        as_json = json.loads(run(state, ["--json"]).stdout)

        # --- survivors defined in the current schema are silent -------------
        # assert on structured keys, not the text: the report's own "note " prefix
        # collides with the `note` field name
        flagged = {f["key"] for f in as_json["gaps"] + as_json["notes"]}
        for survivor in ("people", "sweepLog", "suppressed", "relatedRefs", "note",
                         "deadlineTypeReason", "dismissedFromBoard",
                         "completedDate", "promotedTo", "projects"):
            check(
                survivor not in flagged,
                "a field defined in the current schema is not flagged: %s" % survivor,
            )
        check(
            as_json["expectedSchemaVersion"] == 3 and as_json["schemaVersion"] == 1,
            "--json reports declared and expected versions",
        )
        check(
            {f["key"] for f in as_json["gaps"]}
            == {"unknownTopLevelField", "inventedOverlayField"},
            "--json lists exactly the unknown keys as gaps",
        )
        check(
            {f["key"] for f in as_json["notes"]}
            == {"createdAt", "resolvedNotDropped", "frontmatterWarning"},
            "--json lists exactly the fixture's deprecated keys as notes",
        )
        check(
            any(
                f["key"] == "frontmatterWarning" and "detected live" in f.get("message", "")
                for f in as_json["notes"]
            ),
            "a stored frontmatterWarning is reported as deprecated, so a user "
            "carrying one in live state is told rather than left with a lint "
            "that reads current and is never re-checked",
        )

        # --- suppressed / sweepLog structural checks -----------------------
        check(
            "suppressed: 1 entry | sweepLog: 1 run" in out,
            "the report surfaces the suppression and sweep-log counts",
        )
        unreasoned = json.loads(FIXTURE.read_text())
        unreasoned["suppressed"].append({"ref": "ISSUE-001", "source": "issues"})
        unreasoned["sweepLog"].append({"sources": {"issues(tracker)": "ok"}})
        probe = tmp / "probe.json"
        probe.write_text(json.dumps(unreasoned))
        probe_out = json.loads(run(probe, ["--json"]).stdout)
        check(
            any(f["key"] == "suppressed[1]" for f in probe_out["gaps"]),
            "a suppression with no reason reports as a gap",
        )
        # The hole this closes: `validate_state` type-checks the `suppressed`
        # container and never its entries, so before SUPPRESSED was declared an
        # invented key was legal to write and invisible to `doctor`. That is
        # exactly how a `ts` field reached a real ledger unnoticed.
        invented = json.loads(FIXTURE.read_text())
        invented["suppressed"].append({"ref": "ISSUE-002", "reason": "r",
                                       "inventedSuppressionField": True})
        probe2 = tmp / "probe2.json"
        probe2.write_text(json.dumps(invented))
        probe2_out = json.loads(run(probe2, ["--json"]).stdout)
        check(
            any(f["key"] == "inventedSuppressionField" and f["level"] == "suppressed"
                for f in probe2_out["gaps"]),
            "an undefined key on a suppression entry reports as a gap, so the next "
            "invented field is caught by `doctor` rather than by a hand audit",
        )
        check(
            not any(f["level"] == "suppressed" for f in as_json["gaps"]),
            "...and the fixture's own well-formed entry is not flagged, nor is a "
            "declared `ts`",
        )
        check(
            any(f["key"] == "sweepLog[1]" for f in probe_out["notes"]),
            "a sweepLog entry with no ts reports as a note",
        )

        # --- a clean file passes -------------------------------------------
        clean = json.loads(FIXTURE.read_text())
        clean.pop("unknownTopLevelField")
        clean["itemMeta"]["Tasks/Follow up with Beta Co on the SSO answer.md"].pop(
            "inventedOverlayField"
        )
        clean_path = tmp / "clean.json"
        clean_path.write_text(json.dumps(clean))
        clean_result = run(clean_path)
        check(
            clean_result.returncode == 0,
            "exit status is 0 when only deprecated keys remain (notes do not fail)",
        )

        # --- guardrail: validates, never repairs ---------------------------
        check(state.read_bytes() == before, "the ledger is byte-unchanged (never repaired)")

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
