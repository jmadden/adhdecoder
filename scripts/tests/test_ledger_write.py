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
QUERY = REPO / "scripts" / "ledger_query.py"
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


def build_rw(tmp):
    """The same instance, but with cutover confirmed so notes may be written."""
    config = json.loads((tmp / "config.json").read_text())
    config["ledger"] = {"backend": "obsidian", "writeMode": "readwrite",
                        "cutover": {"singleWriterConfirmed": True}}
    path = tmp / "config-rw.json"
    path.write_text(json.dumps(config, indent=2))
    return path


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

        # --- snooze: a hold the user set, on either backend --------------------
        # The whole point is that a snooze reaches a note-backed record WITHOUT
        # writing the note. `enrich` cannot (it walks state["promises"] only) and
        # `project-set --snooze` quiets a project rollup, not its members - which
        # is why the only route used to be hand-editing state.json.
        state_id = "ISSUE-789:acme-invoice-answer"
        note_id = "Tasks/Provide the Omicron domain list.md"
        note_mtimes = {p: p.stat().st_mtime_ns
                       for p in sorted((tmp / "vault").rglob("*.md"))}

        result = run(config_path, ["snooze", "--id", state_id,
                                   "--until", "2026-08-24", "--reason", "waiting on legal"])
        state = json.loads(state_path.read_text())
        record = next(p for p in state["promises"] if p["id"] == state_id)
        check(
            result.returncode == 0 and "-> record" in result.stdout,
            "a state.json promise snoozes on the record",
        )
        check(
            record["snoozedUntil"] == "2026-08-24"
            and record["snoozeReason"] == "waiting on legal",
            "...with both the date and the reason stored",
        )
        check(
            record["history"][-1]["note"] == "snoozed until 2026-08-24 - waiting on legal",
            "...and leaves a history line, so it counts as the user moving it",
        )

        result = run(config_path, ["snooze", "--id", note_id,
                                   "--until", "2026-08-24", "--reason", "de-dup check first"])
        state = json.loads(state_path.read_text())
        check(
            result.returncode == 0 and "-> itemMeta" in result.stdout,
            "a note-backed id snoozes in the itemMeta companion",
        )
        check(
            state["itemMeta"][note_id]["snoozedUntil"] == "2026-08-24"
            and state["itemMeta"][note_id]["snoozeReason"] == "de-dup check first",
            "...with the reason, which is the only audit trail an overlay has",
        )
        check(
            {p: p.stat().st_mtime_ns for p in sorted((tmp / "vault").rglob("*.md"))}
            == note_mtimes,
            "NO note file was written by a snooze - it is decoder bookkeeping, "
            "not task truth",
        )

        # the reader must agree, or the writer wrote somewhere nothing looks
        probe = subprocess.run(
            [sys.executable, str(QUERY), "--config", str(config_path), "--now", NOW,
             "--select", "snoozed", "--json"],
            capture_output=True, text=True,
        )
        snoozed_ids = {p["id"] for p in json.loads(probe.stdout)["promises"]}
        check(
            {state_id, note_id} <= snoozed_ids,
            "the Query's `snoozed` selector reports both, so writer and reader agree",
        )

        # --- unsnooze, both routes ---------------------------------------------
        run(config_path, ["snooze", "--id", note_id, "--unsnooze"])
        state = json.loads(state_path.read_text())
        check(
            "snoozedUntil" not in state["itemMeta"].get(note_id, {})
            and "snoozeReason" not in state["itemMeta"].get(note_id, {}),
            "unsnooze DELETES the overlay keys rather than nulling them - the "
            "Query skips a null overlay value, so a null would be dead weight",
        )

        # an entry that existed only to hold the snooze is an orphan
        # deliberately an id with NO pre-existing overlay entry, so the entry
        # under test is one the snooze itself created
        orphan_id = "Tasks/Provide the Mu quarterly summary.md"
        run(config_path, ["snooze", "--id", orphan_id,
                          "--until", "2026-08-24", "--reason", "parked"])
        run(config_path, ["snooze", "--id", orphan_id, "--unsnooze"])
        state = json.loads(state_path.read_text())
        check(
            orphan_id not in state["itemMeta"],
            "an itemMeta entry holding only a cleared snooze is pruned, not left "
            "behind as an orphan",
        )

        # THE silent-no-op case: a state.json record that ALSO carries an overlay
        # snooze. The Query overlays itemMeta ON TOP of the record, so clearing
        # only the record leaves the item still snoozed while the op reports
        # success.
        state = json.loads(state_path.read_text())
        state.setdefault("itemMeta", {}).setdefault(state_id, {})["snoozedUntil"] = "2026-09-30"
        state_path.write_text(json.dumps(state, indent=2))
        result = run(config_path, ["snooze", "--id", state_id, "--unsnooze"])
        state = json.loads(state_path.read_text())
        record = next(p for p in state["promises"] if p["id"] == state_id)
        check(
            record["snoozedUntil"] is None
            and "snoozedUntil" not in state["itemMeta"].get(state_id, {}),
            "unsnoozing a record ALSO clears a competing itemMeta value, or the "
            "overlay would re-apply over the None and nothing would change",
        )
        probe = subprocess.run(
            [sys.executable, str(QUERY), "--config", str(config_path), "--now", NOW,
             "--select", "snoozed", "--json"],
            capture_output=True, text=True,
        )
        check(
            state_id not in {p["id"] for p in json.loads(probe.stdout)["promises"]},
            "...and the Query agrees it is awake again",
        )

        # --- snooze refusals ----------------------------------------------------
        before_bytes = state_path.read_bytes()
        result = run(config_path, ["snooze", "--id", state_id,
                                   "--until", "2020-01-01", "--reason", "late"])
        check(
            result.returncode == 1 and "not in the future" in result.stderr,
            "a snooze date in the past is refused - it would read as an applied "
            "off-switch while changing nothing",
        )
        result = run(config_path, ["snooze", "--id", state_id,
                                   "--until", "next tuesday", "--reason", "vague"])
        check(
            result.returncode == 1 and "expects YYYY-MM-DD" in result.stderr,
            "a malformed date is refused HERE, because the itemMeta branch has no "
            "schema gate on the write path to catch it later",
        )
        result = run(config_path, ["snooze", "--id", state_id, "--until", "2026-08-24"])
        check(
            result.returncode == 1 and "requires --reason" in result.stderr,
            "a snooze with no reason is refused; an unexplained hold is "
            "indistinguishable from a bug three weeks later",
        )
        result = run(config_path, ["snooze", "--id", "Tasks/Not a real note.md",
                                   "--until", "2026-08-24", "--reason", "x"])
        check(
            result.returncode == 1 and "Query cannot see" in result.stderr,
            "an unknown id is refused rather than creating an orphaned overlay entry",
        )
        result = run(config_path, ["snooze", "--id", "ISSUE-321:kappa-handover",
                                   "--until", "2026-08-24", "--reason", "x"])
        check(
            result.returncode == 1 and "not open" in result.stderr,
            "snoozing a closed promise is refused - it is a no-op that looks like "
            "success",
        )
        check(
            state_path.read_bytes() == before_bytes,
            "every refused snooze left the ledger byte-identical",
        )
        result = run(config_path, ["--dry-run", "snooze", "--id", state_id,
                                   "--until", "2026-08-24", "--reason", "later"])
        check(
            result.returncode == 0 and "DRY RUN" in result.stdout
            and state_path.read_bytes() == before_bytes,
            "--dry-run reports and writes nothing",
        )
        check(
            {p: p.stat().st_mtime_ns for p in sorted((tmp / "vault").rglob("*.md"))}
            == note_mtimes,
            "not one note was touched across the whole snooze block",
        )

        # --- suppress: a source ref the sweep must never raise again ------------
        # The field was documented, schema-declared and doctor-validated with no
        # writer at all, so the only route was hand-editing state.json - and no
        # reader anywhere, so a ref marked dead came back on the next sweep.
        sup_mtimes = {p: p.stat().st_mtime_ns
                      for p in sorted((tmp / "vault").rglob("*.md"))}
        result = run(config_path, ["suppress", "--ref", "ISSUE-777",
                                   "--source", "issues", "--context", "Example CU",
                                   "--record-id", "rec-777",
                                   "--reason", "watcher-only ref; nobody has asked us anything"])
        state = json.loads(state_path.read_text())
        written = [e for e in state["suppressed"] if e["ref"] == "ISSUE-777"]
        check(
            result.returncode == 0 and len(written) == 1,
            "a suppression is appended to state['suppressed'] exactly once",
        )
        check(
            written and written[0]["reason"].startswith("watcher-only")
            and written[0]["ts"] == NOW
            and written[0]["source"] == "issues"
            and written[0]["recordId"] == "rec-777",
            "...carrying the reason, the clock, and the optional source fields",
        )
        check(
            written and set(written[0]) <= {"ref", "recordId", "source", "context",
                                            "reason", "ts"},
            "...and nothing outside ledger_schema.SUPPRESSED, which is the gate "
            "that an undeclared `ts` slipped past before it was declared",
        )

        # the reader must agree, or the writer wrote somewhere nothing looks
        probe = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "sweep_plan.py"),
             "--config", str(config_path), "--now", NOW, "--json"],
            capture_output=True, text=True,
        )
        plan_refs = {e["ref"] for e in json.loads(probe.stdout)["suppressedRefs"]}
        check(
            "ISSUE-777" in plan_refs,
            "the sweep plan reports it, so the sweep is told rather than trusted "
            "to remember",
        )

        before_bytes = state_path.read_bytes()
        result = run(config_path, ["suppress", "--ref", "issue-777",
                                   "--reason", "a second, different reason"])
        check(
            result.returncode == 0 and "already suppressed" in result.stdout
            and state_path.read_bytes() == before_bytes,
            "a repeat --ref is a case-folded no-op returning 0, and append-only "
            "means the original reason is left exactly as it was",
        )
        # The guard that makes a suppression structural rather than advisory:
        # `add` is the only way a promise is born, so this closes the resurrection
        # path even for a sweep that never read the plan.
        SUPPRESSED_ADD = dict(
            GOOD, id="ISSUE-777:example-watcher-only",
            source={"type": "issues", "ref": "ISSUE-777",
                    "url": "https://tracker.example.com/browse/ISSUE-777"},
        )
        result = run(config_path, ["add"], stdin=json.dumps(SUPPRESSED_ADD))
        check(
            result.returncode == 1 and "is suppressed" in result.stderr,
            "a promise whose source ref is suppressed is REFUSED by `add`, so no "
            "sweep can resurrect it whatever it read or skipped",
        )
        check(
            "--unsuppress" in result.stderr
            and "watcher-only ref" in result.stderr,
            "...and the refusal names the reason and how to clear it, so an "
            "over-broad suppression fails loudly instead of hiding a real ask",
        )
        # --dry-run so this probe does not claim the url it is built to carry,
        # which would then collide with the re-add check at the end of the block
        result = run(config_path, ["--dry-run", "add"], stdin=json.dumps(
            dict(SUPPRESSED_ADD, id="ISSUE-777b:url-only",
                 source={"type": "issues", "ref": "ISSUE-776",
                         "url": "https://tracker.example.com/browse/ISSUE-777"})))
        check(
            result.returncode == 0 and "DRY RUN" in result.stdout,
            "matching is exact on source.ref, never a scan of source.url for an "
            "id it happens to contain - a wrongly-matched suppression would "
            "silently hide a real ask",
        )

        before_bytes = state_path.read_bytes()
        result = run(config_path, ["suppress", "--ref", "ISSUE-888"])
        check(
            result.returncode == 1 and "requires --reason" in result.stderr,
            "a suppression with no reason is refused; validate-state.py already "
            "reports one as a gap, so writing it would fail `doctor` by construction",
        )
        result = run(config_path, ["suppress", "--ref", "ISSUE-888", "--unsuppress"])
        check(
            result.returncode == 1 and "not suppressed" in result.stderr,
            "un-suppressing a ref that is not suppressed is REFUSED, not a no-op - "
            "reporting success would hide a typo while a real suppression stayed",
        )
        check(
            state_path.read_bytes() == before_bytes,
            "every refused suppress left the ledger byte-identical",
        )
        result = run(config_path, ["--dry-run", "suppress", "--ref", "ISSUE-888",
                                   "--reason", "later"])
        check(
            result.returncode == 0 and "DRY RUN" in result.stdout
            and state_path.read_bytes() == before_bytes,
            "--dry-run reports and writes nothing",
        )
        result = run(config_path, ["suppress", "--ref", "ISSUE-777", "--unsuppress"])
        state = json.loads(state_path.read_text())
        check(
            result.returncode == 0
            and not [e for e in state["suppressed"] if e["ref"] == "ISSUE-777"],
            "--unsuppress removes the entry; it is the only op that may shorten "
            "the list",
        )
        check(
            any(e["ref"] == "ISSUE-000" for e in state["suppressed"]),
            "...and removes only that one, leaving the rest of the list intact",
        )
        result = run(config_path, ["add"], stdin=json.dumps(SUPPRESSED_ADD))
        check(
            result.returncode == 0,
            "once un-suppressed the same ref is addable again - the gate is the "
            "list, not a permanent blocklist baked into the code",
        )
        check(
            {p: p.stat().st_mtime_ns for p in sorted((tmp / "vault").rglob("*.md"))}
            == sup_mtimes,
            "not one note was touched across the whole suppress block - a "
            "suppression is ADHDecoder bookkeeping, not task truth",
        )

        # --- capture: create a task note where the user works -------------------
        vault_tasks = tmp / "vault" / "Tasks"
        before_count = len(list(vault_tasks.glob("*.md")))
        state_before = state_path.read_bytes()
        result = run(config_path, ["capture", "--confirmed", "--title",
                                   "Draft the rollout summary", "--customer", "Acme Corp"])
        check(
            result.returncode == 1 and "readwrite" in result.stderr,
            "capture is refused under readonly - ADHDecoder writes no vault file "
            "unless cutover says it may",
        )
        check(
            len(list(vault_tasks.glob("*.md"))) == before_count,
            "...and no note was created",
        )

        rw_config = build_rw(tmp)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(rw_config), "--now", NOW,
             "capture", "--confirmed", "--title", "Draft the rollout summary",
             "--customer", "Acme Corp", "--summary", "Pull numbers, write it up."],
            capture_output=True, text=True)
        check(result.returncode == 0 and "captured" in result.stdout,
              "capture creates a note when the backend is writable")
        created = vault_tasks / "Draft the rollout summary.md"
        check(created.is_file(), "the note exists at the expected path")
        check(
            state_path.read_bytes() == state_before,
            "capture writes NO state.json - the Query picks the note up on next read",
        )

        text = created.read_text(encoding="utf-8")
        check("tags:\n  - task" in text, "the note carries the `task` tag, so it is enumerable")
        check("> **Summary:** Pull numbers" in text, "the summary lands in the body")

        # --- capture round-trip: the Query must READ BACK what capture wrote ---
        # Writing a well-formed note is only half the job. Every check above can
        # pass while the note never reaches a surface - which is exactly how a
        # capture feature ships, looks correct, and leaves the user's task
        # invisible on their own board. So ask the real read path for it.
        read_back = subprocess.run(
            [sys.executable, str(QUERY), "--config", str(rw_config), "--now", NOW,
             "--select", "open", "--json"],
            capture_output=True, text=True)
        found = []
        if read_back.returncode == 0:
            payload = json.loads(read_back.stdout)
            found = [
                pr for pr in payload["promises"]
                if (pr.get("what") or pr.get("title")) == "Draft the rollout summary"
            ]
        check(
            read_back.returncode == 0 and len(found) == 1,
            "a captured note comes back from the Query as ONE open promise - the "
            "round trip, without which capture can pass every write check and "
            "still never appear on the board",
        )
        check(
            bool(found) and found[0]["context"] == "Acme Corp"
            and found[0]["direction"] == "i-owe-them",
            "and it carries the customer through as its context, owed by the user",
        )
        check(
            bool(found) and found[0]["derived"]["open"]
            and not found[0]["derived"]["overdue"],
            "a dateless capture reads open and is never overdue - it waits for "
            "drift staleness rather than firing a false chase",
        )

        # --- every flag reaches the frontmatter (previously untested) ----------
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(rw_config), "--now", NOW,
             "capture", "--confirmed", "--title", "Ship the Delta handover",
             "--due", "2026-08-18", "--priority", "high", "--requester", "R. Contact",
             "--project", "[[Delta]]"],
            capture_output=True, text=True)
        flagged = (vault_tasks / "Ship the Delta handover.md")
        flag_text = flagged.read_text(encoding="utf-8") if flagged.is_file() else ""
        check(
            result.returncode == 0
            and "due: 2026-08-18" in flag_text
            and "priority: high" in flag_text
            and "- R. Contact" in flag_text
            and "- \"[[Delta]]\"" in flag_text,
            "--due / --priority / --requester / --project each reach the note's "
            "frontmatter, in the canonical field shapes",
        )
        dated = subprocess.run(
            [sys.executable, str(QUERY), "--config", str(rw_config), "--now", NOW,
             "--select", "upcoming", "--json"],
            capture_output=True, text=True)
        check(
            dated.returncode == 0
            and "Ship the Delta handover" in
            {p.get("what") or p.get("title") for p in json.loads(dated.stdout)["promises"]},
            "and a captured task WITH a due date lands in `upcoming`, so the date "
            "the user gave is actually honoured by the read side",
        )

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(rw_config), "--now", NOW,
             "capture", "--confirmed", "--title", "Draft the rollout summary"],
            capture_output=True, text=True)
        check(
            result.returncode == 1 and "already exists" in result.stderr,
            "capture never overwrites an existing note",
        )

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(rw_config), "--now", NOW,
             "capture", "--title", "No confirmation given"],
            capture_output=True, text=True)
        check(
            result.returncode == 1 and "--confirmed" in result.stderr,
            "capture without --confirmed is refused, so a sweep cannot create notes",
        )

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(rw_config), "--now", NOW,
             "capture", "--confirmed", "--title", "x" * 200],
            capture_output=True, text=True)
        check(
            result.returncode == 1 and "headline" in result.stderr,
            "a paragraph-length title is refused, not truncated: it becomes the "
            "filename and the promise id too",
        )

        # --- the YAML the note writer emits must be readable by a REAL parser ----
        import importlib.util
        lw_spec = importlib.util.spec_from_file_location("ledger_write", SCRIPT)
        lw = importlib.util.module_from_spec(lw_spec)
        lw_spec.loader.exec_module(lw)
        try:
            import yaml
        except ModuleNotFoundError:
            print("SKIP PyYAML absent, cannot cross-check emitted YAML")
        else:
            nasty = ["Acme Corp: explain the options", "yes", "#urgent", "2026",
                     'He said "no"', "- leading dash", "ends with colon:"]
            all_ok = True
            for title in nasty:
                fields = {"title": title, "status": "todo", "priority": "medium",
                          "dateCreated": NOW, "dateModified": NOW,
                          "projects": [], "customer": title, "requester": title}
                block = lw._note_text(fields, "> **Summary:** x\n").split("---")[1]
                try:
                    all_ok = all_ok and yaml.safe_load(block).get("title") == title
                except Exception:
                    all_ok = False
            check(
                all_ok,
                "every emitted note parses in PyYAML and round-trips exactly - a "
                "title containing ': ' is valid to frontmatter.py but REJECTED by "
                "PyYAML and Obsidian, so unquoted output would write notes the "
                "user's own editor cannot open",
            )

        # --- promote: note first, then collapse ---------------------------------
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(rw_config), "--now", NOW,
             "promote", "--confirmed", "--id", "ISSUE-789:acme-invoice-answer",
             "--title", "Chase the invoice split answer"],
            capture_output=True, text=True)
        check(result.returncode == 0 and "promoted" in result.stdout, "promote succeeds")
        check(
            (vault_tasks / "Chase the invoice split answer.md").is_file(),
            "the note is created",
        )
        state = json.loads(state_path.read_text())
        original = next(p for p in state["promises"] if p["id"] == "ISSUE-789:acme-invoice-answer")
        check(original["status"] == "promoted", "the original collapses to `promoted`")
        check(
            original["promotedTo"] == "Tasks/Chase the invoice split answer.md",
            "...with promotedTo naming the new note, so a sweep enriches it "
            "rather than resurrecting the collapsed record",
        )
        check(
            len(original["history"]) >= 1
            and "Promoted into" in original["history"][-1]["note"],
            "the collapse leaves a history line",
        )

        # --- dry run touches nothing -----------------------------------------
        # Deliberately NOT ISSUE-000: that is the fixture's suppressed ref, and
        # `add` now refuses it outright, which would make this check fail for a
        # reason that has nothing to do with --dry-run.
        before_bytes = state_path.read_bytes()
        dry = dict(
            GOOD, id="ISSUE-555:dry",
            source={"type": "issues", "ref": "ISSUE-555",
                    "url": "https://tracker.example.com/browse/ISSUE-555"},
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

        # --- project-set ----------------------------------------------------
        # No --confirmed: this writes state.json only. That flag exists because
        # capture/promote create files in the user's vault, and using it here
        # would weaken the one place it means something.
        result = run(config_path, [
            "project-set", "--id", "acme", "--name", "Acme rollout",
            "--alias", "Acme Corp",
        ])
        check(
            result.returncode == 0 and "declared project acme" in result.stdout,
            "a project is declared with no --confirmed (state.json only)",
        )
        state = json.loads(state_path.read_text())
        declared = [p for p in state.get("projects", []) if p["id"] == "acme"]
        check(
            len(declared) == 1 and declared[0]["status"] == "active",
            "the project is in the file exactly once, active by default",
        )

        before_bytes = state_path.read_bytes()
        result = run(config_path, [
            "project-set", "--id", "rival", "--name", "Rival", "--alias", "acme corp",
        ])
        check(
            result.returncode == 1 and "already claimed" in result.stderr,
            "an alias another project claims is refused - first-wins would make "
            "membership depend on the order of the projects array",
        )
        result = run(config_path, ["project-set", "--id", "unreachable", "--name", "Empty"])
        check(
            result.returncode == 1 and "at least one" in result.stderr,
            "a project with no alias and no pinned id is refused: nothing could "
            "ever be a member of it",
        )
        result = run(config_path, [
            "project-set", "--id", "nowhere", "--name", "Ghost", "--include", "no-such-id",
        ])
        check(
            result.returncode == 1 and "cannot see" in result.stderr,
            "pinning an id the Query cannot see is refused",
        )
        result = run(config_path, ["project-set", "--id", "acme", "--snooze", "2020-01-01"])
        check(
            result.returncode == 1 and "not in the future" in result.stderr,
            "a snooze date in the past is refused rather than silently doing nothing",
        )
        check(
            state_path.read_bytes() == before_bytes,
            "every refused project write left the ledger byte-identical",
        )

        result = run(config_path, [
            "--dry-run", "project-set", "--id", "acme", "--name", "Renamed",
        ])
        check(
            result.returncode == 0 and "dry run" in result.stdout
            and state_path.read_bytes() == before_bytes,
            "--dry-run prints the record and writes nothing",
        )

        # --- declared rules and the preview ---------------------------------
        result = run(config_path, [
            "project-set", "--id", "kwtest", "--name", "KW", "--keyword", "invoice",
        ])
        check(
            result.returncode == 0 and "would claim 1 item" in result.stdout
            and "keyword \"invoice\"" in result.stdout,
            "declaring a project previews what it claims, with the reason, BEFORE "
            "the write - the words a user says are rarely the words in their "
            "ledger, and a silently-empty project looks like a working one",
        )
        result = run(config_path, [
            "project-set", "--id", "nomatch", "--name", "No", "--keyword", "zzzznothing",
        ])
        check(
            result.returncode == 0 and "NOTHING MATCHES" in result.stdout,
            "a rule set that claims nothing says so loudly",
        )
        result = run(config_path, [
            "project-set", "--id", "conflict", "--name", "C", "--keyword", "x",
            "--include", GOOD["id"], "--exclude", GOOD["id"],
        ])
        check(
            result.returncode == 1 and "both `include` and `exclude`" in result.stderr,
            "an id both pinned and excluded is refused rather than one silently winning",
        )
        result = run(config_path, ["project-set", "--id", "kwtest", "--checked-in"])
        check(
            result.returncode == 1 and "no check-in rhythm" in result.stderr,
            "resetting a check-in clock that does not exist is refused, not a no-op",
        )
        result = run(config_path, [
            "project-set", "--id", "kwtest", "--check-in-every", "14", "--checked-in", "2026-08-01",
        ])
        state = json.loads(state_path.read_text())
        kw = [p for p in state["projects"] if p["id"] == "kwtest"][0]
        check(
            result.returncode == 0 and kw["checkInEvery"] == 14
            and kw["lastCheckIn"] == "2026-08-01",
            "a check-in rhythm and its last reset are both recorded",
        )
        result = run(config_path, ["project-set", "--id", "kwtest", "--check-in-every", "0"])
        state = json.loads(state_path.read_text())
        kw = [p for p in state["projects"] if p["id"] == "kwtest"][0]
        check(
            result.returncode == 0 and kw["checkInEvery"] is None
            and kw["lastCheckIn"] is None,
            "clearing the rhythm clears the stale clock with it, so no orphan date "
            "is left behind to be rendered later",
        )

        result = run(config_path, [
            "project-set", "--id", "acme", "--status", "done", "--target-date", "2026-09-01",
        ])
        state = json.loads(state_path.read_text())
        declared = [p for p in state["projects"] if p["id"] == "acme"][0]
        check(
            result.returncode == 0 and declared["status"] == "done"
            and declared["targetDate"] == "2026-09-01"
            and declared["aliases"] == ["Acme Corp"],
            "an update amends only what was passed and keeps the rest",
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
