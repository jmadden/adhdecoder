#!/usr/bin/env python3
"""THE write path for `state.json`. Stdlib only.

Every promise a sweep records goes through here. It exists because sweep runs
unattended three times a day and, until now, hand-wrote JSON from prose
instructions - the one place in ADHDecoder where a subtle bug could corrupt the
ledger with nobody watching. A malformed `direction`, a rewritten `history`, a
duplicate record, a half-written file: all silent, all only visible much later
as counts that stopped making sense.

What this guarantees, on every operation:

1. **The reality gate holds.** No promise is written without a named `owner`, a
   concrete `what`, and an `expectBy`. That rule is what keeps the ledger from
   filling with vague "go find out X" phantoms.
2. **The schema holds.** Field names and enum values are checked against
   `ledger_schema.py`, the same module the read-side validator uses, so a field
   can never be legal to write but unknown to `doctor`.
3. **Dedup is checked against the FULL union, not just state.json.** A candidate
   whose `source.url` an Obsidian note already owns is refused, because writing
   it creates a record the Query silently collapses on every read - a duplicate
   that never appears on the board but accumulates in the file forever.
4. **History is append-only.** No operation can rewrite or drop a prior entry.
5. **The write is atomic and checked afterwards.** Temp file then `os.replace`,
   then the whole file is re-validated; if the result would be invalid it is
   rolled back from the backup rather than left in place.
6. **Concurrent writers are detected.** The file is hashed before the mutation
   and re-hashed immediately before the replace; if another session (a desktop
   run, a scheduled run) wrote in between, this refuses rather than clobbering.

Usage:
    ledger_write.py --config CFG add            [--promise-json JSON] [--dry-run]
    ledger_write.py --config CFG enrich --id ID --note TEXT [--expect-by DATE]
                                                [--verify-status S] [--verify-reason R]
    ledger_write.py --config CFG record-verify --id ID --status S [--reason R]
                                                [--source-url URL]
    ledger_write.py --config CFG draft-mark-met --id ID --reason R
    ledger_write.py --config CFG record-sweep   [--sources-json JSON] [--now ISO]
    ledger_write.py --config CFG mark-seen --id ID [--id ID ...]

`add` and `record-sweep` read their JSON payload from stdin when the flag is
omitted. Exit 0 on success, 1 on a refused write (with the reason), 2 on usage.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger_query as lq  # noqa: E402
from ledger_schema import (  # noqa: E402
    SCHEMA_VERSION,
    SWEEP_LOG_CAP,
    VERIFY_STATUSES,
    reality_gate,
    validate_promise,
    validate_state,
)


class Refused(Exception):
    """A write that must not happen. The message is shown to the caller."""


# --------------------------------------------------------------------------
# file handling
# --------------------------------------------------------------------------

def digest(path):
    """Content hash, or None when the file does not exist."""
    path = Path(path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_state(path):
    path = Path(path)
    if not path.is_file():
        raise Refused("no ledger at %s - run `setup` first" % path)
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as error:
        raise Refused(
            "the ledger did not parse: %s\nRefusing to write on top of a file I "
            "cannot read; if another session is mid-write, re-run in a moment." % error
        )


def backup(path, instance_path):
    """Copy the pre-write file somewhere visible, and return its path."""
    backups = Path(instance_path) / "ledger-backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    target = backups / ("state.%s.json" % stamp)
    shutil.copy2(path, target)
    return target


def write_atomic(path, state, expected_digest):
    """Serialise, verify the file has not changed under us, then replace.

    The digest re-check is the concurrency guard: two ADHDecoder sessions can be
    live at once (a desktop app and a scheduled run have already overlapped in
    practice), and last-writer-wins would silently discard the other's work.
    """
    path = Path(path)
    if digest(path) != expected_digest:
        raise Refused(
            "another session wrote the ledger while this operation was preparing.\n"
            "Nothing was changed. Re-run to pick up their write and apply this on top."
        )
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=".ledger-write-",
        suffix=".tmp", delete=False,
    )
    try:
        json.dump(state, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(handle.name, 0o666 & ~umask)
        os.replace(handle.name, path)
    except BaseException:
        handle.close()
        if os.path.exists(handle.name):
            os.unlink(handle.name)
        raise


def commit(path, state, expected_digest, backup_path, problems_before):
    """Write, then re-validate; roll back if the write made things WORSE.

    Deliberately a delta check, not an absolute one. A real ledger carries
    legacy baggage - deprecated field names from before the schema was pinned,
    for instance - and refusing to write until the whole file is pristine would
    make this script unusable on exactly the data it exists to protect. The
    contract is "this write introduces no new problem", which is enforceable
    today; "the file is perfect" is a migration, and a separate decision.
    """
    write_atomic(path, state, expected_digest)
    try:
        written = read_state(path)
    except Refused:
        shutil.copy2(backup_path, path)
        raise Refused("the written ledger did not parse; restored from %s" % backup_path)
    introduced = [p for p in validate_state(written) if p not in problems_before]
    if introduced:
        shutil.copy2(backup_path, path)
        raise Refused(
            "the write would have introduced %d new schema problem(s), so it was "
            "rolled back from %s:\n  %s"
            % (len(introduced), backup_path, "\n  ".join(introduced[:10]))
        )


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------

def existing_union(config, now):
    """Every promise the system can currently see, notes included.

    Deliberately the Query and not just state.json: a candidate whose source url
    a note already owns must be refused here, or it becomes a state.json record
    the Query collapses on every read - invisible on the board, permanent in the
    file. That accumulation bug has already happened once.
    """
    promises, _meta = lq.query(config, now)
    return promises


def op_add(args, config, now):
    payload = args.promise_json if args.promise_json else sys.stdin.read()
    try:
        record = json.loads(payload)
    except json.JSONDecodeError as error:
        raise Refused("the promise payload is not valid JSON: %s" % error)
    if not isinstance(record, dict):
        raise Refused("the promise payload must be a single JSON object")

    record.setdefault("status", "pending")
    record.setdefault("created", now.isoformat(timespec="seconds"))
    record.setdefault("lastVerified", now.isoformat(timespec="seconds"))
    record.setdefault("history", [])
    if not record["history"]:
        record["history"] = [{"ts": now.isoformat(timespec="seconds"), "note": "Promise captured."}]

    problems = validate_promise(record)
    if problems:
        raise Refused("refusing to add this promise:\n  " + "\n  ".join(problems))

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    if any(p.get("id") == record["id"] for p in state.get("promises") or []):
        raise Refused(
            "a promise with id %r already exists - use `enrich` to update it, "
            "never a second record" % record["id"]
        )

    url = (record.get("source") or {}).get("url")
    if url and not record.get("noteOnly"):
        for existing in existing_union(config, now):
            existing_url = (existing.get("source") or {}).get("url")
            if existing_url == url and not existing.get("noteOnly"):
                raise Refused(
                    "source.url is already owned by %r (%s).\n"
                    "Enrich that record instead: a second record under a different "
                    "id is collapsed by the Query on every read, so it would never "
                    "show on the board but would live in the file forever."
                    % (existing.get("id"), existing.get("_origin", "state"))
                )

    seen = ((state.get("dedup") or {}).get("seen")) or []
    if record["id"] in seen:
        raise Refused(
            "id %r is already in dedup.seen - it was decoded before. Enrich the "
            "existing record rather than re-adding it." % record["id"]
        )

    if args.dry_run:
        print("DRY RUN: would add %s" % record["id"])
        return 0

    state.setdefault("promises", []).append(record)
    state.setdefault("dedup", {}).setdefault("seen", []).append(record["id"])
    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("added %s" % record["id"])
    return 0


def op_enrich(args, config, now):
    if not args.note:
        raise Refused("`enrich` requires --note: every change leaves a history line")

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    target = None
    for record in state.get("promises") or []:
        if record.get("id") == args.id:
            target = record
            break
    if target is None:
        raise Refused("no promise with id %r in state.json" % args.id)

    if target.get("status") == "promoted":
        raise Refused(
            "%r is `promoted` (collapsed into %r). Enrich the record it points at, "
            "never the collapsed one." % (args.id, target.get("promotedTo"))
        )

    history_before = list(target.get("history") or [])

    updated = dict(target)
    updated["lastVerified"] = now.isoformat(timespec="seconds")
    if args.expect_by:
        updated["expectBy"] = args.expect_by
    if args.verify_status:
        updated["verifyStatus"] = args.verify_status
    if args.verify_reason:
        updated["verifyReason"] = args.verify_reason
    if args.status:
        updated["status"] = args.status
    updated["history"] = history_before + [
        {"ts": now.isoformat(timespec="seconds"), "note": args.note}
    ]

    problems = validate_promise(updated, enforce_reality_gate=False)
    if problems:
        raise Refused("refusing to enrich %r:\n  %s" % (args.id, "\n  ".join(problems)))

    # append-only, checked rather than assumed
    if updated["history"][: len(history_before)] != history_before:
        raise Refused("internal error: history would not be append-only; refusing")

    if args.dry_run:
        print("DRY RUN: would enrich %s (+1 history line)" % args.id)
        return 0

    target.clear()
    target.update(updated)
    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("enriched %s" % args.id)
    return 0


def op_record_sweep(args, config, now):
    payload = args.sources_json if args.sources_json else sys.stdin.read()
    payload = payload.strip()
    sources = {}
    if payload:
        try:
            sources = json.loads(payload)
        except json.JSONDecodeError as error:
            raise Refused("the sources payload is not valid JSON: %s" % error)
    if not isinstance(sources, dict):
        raise Refused("the sources payload must be a JSON object of {source: result}")

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    stamp = now.isoformat(timespec="seconds")
    state["lastSwept"] = stamp
    log = state.setdefault("sweepLog", [])
    log.append({"ts": stamp, "sources": sources})
    # a log, not a store: keep the tail so it cannot grow without bound
    if len(log) > SWEEP_LOG_CAP:
        del log[: len(log) - SWEEP_LOG_CAP]

    if args.dry_run:
        print("DRY RUN: would set lastSwept=%s and append 1 sweepLog entry" % stamp)
        return 0

    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("recorded sweep at %s (%d sources)" % (stamp, len(sources)))
    return 0


def _route(state, promise_id):
    """Where does ADHDecoder-owned metadata for this id belong?

    A promise that lives in `state.json` keeps it on the record. Anything else -
    a note-backed record - keeps it in the `itemMeta` companion, keyed by id.
    This branch is the one that keeps a read-only backend read-only, so it is
    decided here rather than restated in prose at each call site.
    """
    for record in state.get("promises") or []:
        if record.get("id") == promise_id:
            return "record", record
    return "itemMeta", state.setdefault("itemMeta", {}).setdefault(promise_id, {})


def op_record_verify(args, config, now):
    if args.status not in VERIFY_STATUSES:
        raise Refused(
            "--status must be one of %s" % [s for s in VERIFY_STATUSES if s]
        )

    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    where, target = _route(state, args.id)

    if where == "itemMeta" and not any(
        p.get("id") == args.id for p in existing_union(config, now)
    ):
        raise Refused(
            "no promise or note with id %r - refusing to create an itemMeta entry "
            "for something the Query cannot see (that is how orphaned overlay "
            "records accumulate)" % args.id
        )

    target["verifyStatus"] = args.status
    if args.reason:
        target["verifyReason"] = args.reason
    target["lastVerified"] = now.isoformat(timespec="seconds")

    if args.source_url:
        # the link reconcile actually found, kept rather than discarded; on a
        # note-backed record this upgrades the overlay, never the note
        target["source"] = {
            "type": args.source_type or "unknown",
            "ref": args.source_ref,
            "url": args.source_url,
        }
        target["noteOnly"] = False

    if where == "record":
        problems = validate_promise(target, enforce_reality_gate=False)
        if problems:
            raise Refused("refusing to record verify on %r:\n  %s"
                          % (args.id, "\n  ".join(problems)))

    if args.dry_run:
        print("DRY RUN: would record %s on %s (%s)" % (args.status, args.id, where))
        return 0

    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("recorded %s for %s -> %s" % (args.status, args.id, where))
    return 0


def op_draft_mark_met(args, config, now):
    """Park a 'the source says this is done' decision the user has not seen yet.

    Only ever a draft: a record ADHDecoder cannot write (a read-only note) must
    not be closed on its behalf. The board renders these in Ready to close until
    the user acts, which is the only thing keeping the note store and reality
    from drifting apart.
    """
    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)

    if not any(p.get("id") == args.id for p in existing_union(config, now)):
        raise Refused("no promise or note with id %r" % args.id)

    where, target = _route(state, args.id)
    if where == "record":
        raise Refused(
            "%r lives in state.json, which ADHDecoder can write directly - use "
            "`enrich --status met` rather than parking a draft. Drafts exist for "
            "records this cannot write." % args.id
        )

    entry = state.setdefault("itemMeta", {}).setdefault(args.id, {})
    if entry.get("appliedMarkMet"):
        raise Refused(
            "%r already has an appliedMarkMet audit entry - it was closed. "
            "Refusing to park a new draft over a completed close." % args.id
        )
    entry["markMetDraft"] = {
        "status": "done",
        "completedDate": args.completed_date or now.date().isoformat(),
        "reason": args.reason,
    }

    if args.dry_run:
        print("DRY RUN: would park a markMetDraft on %s" % args.id)
        return 0

    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("parked markMetDraft for %s (renders in Ready to close until applied)" % args.id)
    return 0


def op_mark_seen(args, config, now):
    state = read_state(config.state_file)
    before = digest(config.state_file)
    problems_before = validate_state(state)
    seen = state.setdefault("dedup", {}).setdefault("seen", [])
    added = [i for i in args.id if i not in seen]
    if not added:
        print("nothing to add; all %d id(s) already in dedup.seen" % len(args.id))
        return 0
    if args.dry_run:
        print("DRY RUN: would add %d id(s) to dedup.seen" % len(added))
        return 0
    seen.extend(added)
    backup_path = backup(config.state_file, config.instance_path)
    commit(config.state_file, state, before, backup_path, problems_before)
    print("marked seen: %s" % ", ".join(added))
    return 0


OPS = {
    "add": op_add,
    "enrich": op_enrich,
    "record-verify": op_record_verify,
    "draft-mark-met": op_draft_mark_met,
    "record-sweep": op_record_sweep,
    "mark-seen": op_mark_seen,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, help="instance config.json")
    parser.add_argument("--now", default=None, help="ISO 8601 clock override (tests)")
    parser.add_argument("--dry-run", action="store_true", help="validate, write nothing")
    sub = parser.add_subparsers(dest="op", required=True)

    p_add = sub.add_parser("add", help="record a new promise (reality gate enforced)")
    p_add.add_argument("--promise-json", default=None, help="JSON object; stdin if omitted")

    p_enrich = sub.add_parser("enrich", help="update an existing promise, append-only")
    p_enrich.add_argument("--id", required=True)
    p_enrich.add_argument("--note", required=True, help="the history line for this change")
    p_enrich.add_argument("--expect-by", default=None)
    p_enrich.add_argument("--verify-status", default=None)
    p_enrich.add_argument("--verify-reason", default=None)
    p_enrich.add_argument("--status", default=None)

    p_verify = sub.add_parser(
        "record-verify",
        help="persist a reconcile verdict, routed to the record or itemMeta")
    p_verify.add_argument("--id", required=True)
    p_verify.add_argument("--status", required=True)
    p_verify.add_argument("--reason", default=None)
    p_verify.add_argument("--source-url", default=None, help="the link reconcile found")
    p_verify.add_argument("--source-type", default=None)
    p_verify.add_argument("--source-ref", default=None)

    p_draft = sub.add_parser(
        "draft-mark-met",
        help="park a 'looks done' decision for a record this cannot write")
    p_draft.add_argument("--id", required=True)
    p_draft.add_argument("--reason", required=True)
    p_draft.add_argument("--completed-date", default=None)

    p_sweep = sub.add_parser("record-sweep", help="stamp lastSwept + append a sweepLog entry")
    p_sweep.add_argument("--sources-json", default=None, help="JSON {source: result}; stdin if omitted")

    p_seen = sub.add_parser("mark-seen", help="add decoded ids to dedup.seen")
    p_seen.add_argument("--id", action="append", required=True)

    args = parser.parse_args(argv)

    try:
        config = lq.Config(args.config)
    except (OSError, json.JSONDecodeError) as error:
        print("cannot read config: %s" % error, file=sys.stderr)
        return 2

    now = datetime.fromisoformat(args.now) if args.now else datetime.now()

    try:
        return OPS[args.op](args, config, now)
    except Refused as error:
        print("REFUSED: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
