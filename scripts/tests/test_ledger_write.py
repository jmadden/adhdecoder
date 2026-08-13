#!/usr/bin/env python3
"""Tests for scripts/ledger_write.py, the validated write path.

Run: python3 scripts/tests/test_ledger_write.py

sweep runs unattended three times a day and this is the only thing standing
between it and the ledger. So most of these tests are deliberate attempts to
corrupt the file - a phantom promise with no owner, a bad enum, a rewritten
history, a duplicate of a note's url, a concurrent writer - and assert that each
one is refused with the file left exactly as it was.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = REPO / "scripts" / "ledger_write.py"
FIXTURES = HERE / "fixtures"
NOW = "2026-08-14T09:00:00"

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
        json.dumps({
            "identity": {"name": "Test User", "email": "test@example.com"},
            "storage": {
                "adapter": "filesystem",
                "instancePath": str(instance),
                "knowledgePath": str(vault),
                "overrides": {"stateFile": "state.json", "tasksDir": "Tasks"},
            },
            "ledger": {"backend": "obsidian", "writeMode": "readonly"},
            "schedule": {},
        }, indent=2),
        encoding="utf-8",
    )
    return config_path, instance / "state.json"


def run(config_path, op_args, stdin=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(config_path), "--now", NOW, *op_args],
        capture_output=True, text=True, input=stdin,
    )


GOOD = {
    "id": "ISSUE-999:acme-new-stall",
    "title": "Acme rollout question",
    "context": "Acme Corp",
    "direction": "i-owe-them",
    "what": "Answer the rollout sequencing question on the ticket",
    "owner": "A. Contact (Acme Corp)",
    "expectBy": "2026-08-20",
    "source": {"type": "issues", "ref": "ISSUE-999",
               "url": "https://tracker.example.com/browse/ISSUE-999"},
}


def main():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config_path, state_path = build_instance(tmp)

        # --- the happy path -------------------------------------------------
        result = run(config_path, ["add"], stdin=json.dumps(GOOD))
        check(result.returncode == 0 and "added" in result.stdout, "a well-formed promise is added")
        state = json.loads(state_path.read_text())
        added = [p for p in state["promises"] if p["id"] == GOOD["id"]]
        check(len(added) == 1, "the promise is in the file exactly once")
        check(
            added and added[0]["history"] and added[0]["history"][0]["note"] == "Promise captured.",
            "history is seeded with one captured line",
        )
        check(GOOD["id"] in state["dedup"]["seen"], "the id is recorded in dedup.seen")

        # --- the reality gate ------------------------------------------------
        for missing, label in (
            ("owner", "a promise with no owner is refused (phantom chase)"),
            ("what", "a promise with no `what` is refused"),
            ("expectBy", "a promise with no expectBy is refused"),
        ):
            payload = dict(GOOD, id="ISSUE-000:gate-%s" % missing)
            payload.pop(missing)
            result = run(config_path, ["add"], stdin=json.dumps(payload))
            check(result.returncode == 1 and "reality gate" in result.stderr, label)

        vague = dict(GOOD, id="ISSUE-000:vague", what="SSO")
        result = run(config_path, ["add"], stdin=json.dumps(vague))
        check(
            result.returncode == 1 and "too vague" in result.stderr,
            "a one-word `what` is refused as too vague to chase",
        )

        # --- schema enforcement ----------------------------------------------
        bad_direction = dict(GOOD, id="ISSUE-000:dir", direction="sideways")
        result = run(config_path, ["add"], stdin=json.dumps(bad_direction))
        check(
            result.returncode == 1 and "`direction` must be one of" in result.stderr,
            "an invalid direction is refused, not silently stored",
        )
        unknown_field = dict(GOOD, id="ISSUE-000:unknown", counterparty="someone")
        result = run(config_path, ["add"], stdin=json.dumps(unknown_field))
        check(
            result.returncode == 1 and "deprecated field" in result.stderr,
            "a deprecated field name is refused at write time, not just reported later",
        )
        invented = dict(GOOD, id="ISSUE-000:invented", vibes="high")
        result = run(config_path, ["add"], stdin=json.dumps(invented))
        check(
            result.returncode == 1 and "unknown field `vibes`" in result.stderr,
            "an invented field is refused - the schema drift this project keeps fixing",
        )
        bad_date = dict(GOOD, id="ISSUE-000:date", expectBy="next Tuesday")
        result = run(config_path, ["add"], stdin=json.dumps(bad_date))
        check(
            result.returncode == 1 and "YYYY-MM-DD" in result.stderr,
            "a non-ISO expectBy is refused",
        )

        # --- dedup, including against NOTES the Query can see -----------------
        dupe_id = dict(GOOD)
        result = run(config_path, ["add"], stdin=json.dumps(dupe_id))
        check(
            result.returncode == 1 and "already exists" in result.stderr,
            "a duplicate id is refused",
        )
        note_url = dict(
            GOOD, id="ISSUE-000:note-dupe",
            source={"type": "issues", "ref": "ISSUE-123",
                    "url": "https://tracker.example.com/browse/ISSUE-123"},
        )
        result = run(config_path, ["add"], stdin=json.dumps(note_url))
        check(
            result.returncode == 1 and "already owned by" in result.stderr,
            "a candidate whose url an Obsidian NOTE already owns is refused (the "
            "accumulation bug: the Query would collapse it on every read, so it "
            "would never show on the board but would live in the file forever)",
        )

        # --- enrich is append-only -------------------------------------------
        before = json.loads(state_path.read_text())
        target = next(p for p in before["promises"] if p["id"] == GOOD["id"])
        history_before = list(target["history"])
        result = run(config_path, [
            "enrich", "--id", GOOD["id"], "--note", "Customer replied, moved the date.",
            "--expect-by", "2026-08-25",
        ])
        check(result.returncode == 0, "enrich succeeds on an existing promise")
        after = json.loads(state_path.read_text())
        target_after = next(p for p in after["promises"] if p["id"] == GOOD["id"])
        check(
            target_after["history"][: len(history_before)] == history_before,
            "prior history entries are preserved byte-for-byte",
        )
        check(len(target_after["history"]) == len(history_before) + 1, "exactly one line appended")
        check(target_after["expectBy"] == "2026-08-25", "expectBy was updated")
        check(
            target_after["lastVerified"].startswith("2026-08-14"),
            "lastVerified was refreshed to the run clock",
        )

        result = run(config_path, ["enrich", "--id", "does-not-exist", "--note", "x"])
        check(
            result.returncode == 1 and "no promise with id" in result.stderr,
            "enriching an unknown id is refused",
        )
        result = run(config_path, ["enrich", "--id", "ISSUE-654:lambda-old-ask", "--note", "x"])
        check(
            result.returncode == 1 and "promoted" in result.stderr,
            "enriching a promoted (collapsed) record is refused, never resurrected",
        )

        # --- sweep bookkeeping ------------------------------------------------
        result = run(config_path, ["record-sweep"],
                     stdin=json.dumps({"chat(slack)": "ok", "email(gmail)": "ok"}))
        check(result.returncode == 0, "record-sweep succeeds")
        state = json.loads(state_path.read_text())
        check(state["lastSwept"].startswith("2026-08-14"), "lastSwept was stamped")
        check(
            state["sweepLog"][-1]["sources"] == {"chat(slack)": "ok", "email(gmail)": "ok"},
            "the sweepLog entry records per-source results",
        )

        for _ in range(14):
            run(config_path, ["record-sweep"], stdin=json.dumps({"chat(slack)": "ok"}))
        state = json.loads(state_path.read_text())
        check(len(state["sweepLog"]) <= 10, "sweepLog is capped, so a log cannot grow forever")

        # --- record-verify routes correctly ------------------------------------
        # This branch is what keeps a read-only backend read-only: a note-backed
        # id must land in itemMeta and NEVER on the note.
        note_id = "Tasks/Deliver the staging redirect fix to Acme.md"
        note_mtimes = {p: p.stat().st_mtime_ns
                       for p in sorted((tmp / "vault").rglob("*.md"))}
        result = run(config_path, ["record-verify", "--id", note_id,
                                   "--status", "verified-open", "--reason", "Still open"])
        check(
            result.returncode == 0 and "-> itemMeta" in result.stdout,
            "a note-backed id routes its verify metadata to itemMeta",
        )
        state = json.loads(state_path.read_text())
        check(
            state["itemMeta"][note_id]["verifyReason"] == "Still open",
            "...and the verdict actually landed there",
        )
        check(
            {p: p.stat().st_mtime_ns for p in sorted((tmp / "vault").rglob("*.md"))}
            == note_mtimes,
            "NO note file was written - the read-only guarantee holds",
        )

        result = run(config_path, ["record-verify", "--id", GOOD["id"],
                                   "--status", "resolved", "--reason", "Closed upstream"])
        check(
            result.returncode == 0 and "-> record" in result.stdout,
            "a state.json promise routes its verify metadata onto the record",
        )

        result = run(config_path, ["record-verify", "--id", "nothing-knows-this",
                                   "--status", "verified-open"])
        check(
            result.returncode == 1 and "Query cannot see" in result.stderr,
            "an id nothing can see is refused, so orphaned itemMeta cannot accumulate",
        )
        result = run(config_path, ["record-verify", "--id", GOOD["id"], "--status", "wat"])
        check(
            result.returncode == 1 and "--status must be one of" in result.stderr,
            "an invalid verify status is refused",
        )

        # --- the source link reconcile found is kept ----------------------------
        run(config_path, ["record-verify", "--id", note_id, "--status", "verified-open",
                          "--source-url", "https://tracker.example.com/browse/FOUND-1",
                          "--source-type", "issues", "--source-ref", "FOUND-1"])
        state = json.loads(state_path.read_text())
        check(
            state["itemMeta"][note_id]["source"]["url"].endswith("FOUND-1")
            and state["itemMeta"][note_id]["noteOnly"] is False,
            "a discovered source link is persisted and clears noteOnly, rather "
            "than being found and thrown away",
        )

        # --- draft-mark-met is only for records this cannot write ----------------
        result = run(config_path, ["draft-mark-met", "--id", GOOD["id"],
                                   "--reason", "looks done"])
        check(
            result.returncode == 1 and "lives in state.json" in result.stderr,
            "parking a draft on a writable record is refused - drafts exist for "
            "records ADHDecoder cannot write",
        )
        result = run(config_path, ["draft-mark-met", "--id", note_id,
                                   "--reason", "Source says it shipped"])
        check(result.returncode == 0, "a note-backed record accepts a mark-met draft")
        state = json.loads(state_path.read_text())
        check(
            state["itemMeta"][note_id]["markMetDraft"]["reason"] == "Source says it shipped",
            "...parked in itemMeta, where the board renders it in Ready to close",
        )
        check(
            {p: p.stat().st_mtime_ns for p in sorted((tmp / "vault").rglob("*.md"))}
            == note_mtimes,
            "parking a draft still writes no note",
        )

        applied_id = "Tasks/Follow up with Beta Co on the SSO answer.md"
        state = json.loads(state_path.read_text())
        state["itemMeta"].setdefault(applied_id, {})["appliedMarkMet"] = {
            "ts": NOW, "completedDate": "2026-08-01", "reason": "closed earlier"}
        state_path.write_text(json.dumps(state, indent=2))
        result = run(config_path, ["draft-mark-met", "--id", applied_id, "--reason", "again"])
        check(
            result.returncode == 1 and "already has an appliedMarkMet" in result.stderr,
            "a draft is refused over an already-completed close, so an audit "
            "trail cannot be quietly reopened",
        )

        # --- dry run touches nothing -----------------------------------------
        before_bytes = state_path.read_bytes()
        dry = dict(
            GOOD, id="ISSUE-000:dry",
            source={"type": "issues", "ref": "ISSUE-000",
                    "url": "https://tracker.example.com/browse/ISSUE-000"},
        )
        result = run(config_path, ["--dry-run", "add"], stdin=json.dumps(dry))
        check(
            result.returncode == 0 and "DRY RUN" in result.stdout
            and state_path.read_bytes() == before_bytes,
            "--dry-run validates and writes nothing",
        )

        # --- refused writes leave the file untouched --------------------------
        before_bytes = state_path.read_bytes()
        run(config_path, ["add"], stdin=json.dumps({"id": "x", "direction": "nope"}))
        check(
            state_path.read_bytes() == before_bytes,
            "a refused write leaves the ledger byte-identical",
        )

        # --- a backup exists for every applied write --------------------------
        backups = sorted((tmp / "instance" / "ledger-backups").glob("state.*.json"))
        check(len(backups) >= 1, "each applied write leaves a visible backup")

        # --- concurrency: another writer lands mid-operation --------------------
        # Unit-level, because the race cannot be staged reliably through the CLI:
        # take a digest, let "another session" write, then try to commit against
        # the stale digest exactly as a slow operation would.
        import importlib.util
        spec = importlib.util.spec_from_file_location("ledger_write", SCRIPT)
        lw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lw)

        stale = lw.digest(state_path)
        state_now = json.loads(state_path.read_text())
        state_now["lastSwept"] = "2026-08-14T23:59:59"   # the other session's write
        state_path.write_text(json.dumps(state_now, indent=2))
        after_other = state_path.read_bytes()

        raised = None
        try:
            lw.write_atomic(state_path, {"schemaVersion": 2, "promises": []}, stale)
        except lw.Refused as error:
            raised = str(error)
        check(
            raised is not None and "another session wrote the ledger" in raised,
            "a concurrent write is detected and refused, not silently clobbered",
        )
        check(
            state_path.read_bytes() == after_other,
            "the other session's write survives intact after the refusal",
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
