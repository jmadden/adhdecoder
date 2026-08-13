#!/usr/bin/env python3
"""The mechanical half of `doctor`. Stdlib only, read-only.

Runs the setup checks that are pure arithmetic over config and the filesystem,
so a health check gives the same answer every time instead of being re-derived
from prose on each invocation. Covers:

    1. config parses + required fields
    2. backend resolves + its paths exist and are writable
    3. write mode is coherent with the cutover confirmation
    5. record-store integrity (parse failures + frontmatter warnings)

Check 4 (connector presence) is deliberately NOT here and is reported as
`unchecked`: whether a session has a chat or issue-tracker connector attached is
a fact about the running session, invisible to a subprocess. Claiming it passed
would be worse than saying nothing, so this names it as the skill's job.

Checks 0 (runtime) and 6 (schema) live elsewhere - 0 is proven by this script
running at all, 6 is `validate-state.py`.

Usage:
    doctor_check.py --config CFG [--json]

Exit 0 when there are no gaps (notes do not fail), 1 when a gap was found,
2 when the config could not be read at all.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger_query as lq  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

OK, GAP, NOTE, UNCHECKED = "OK", "GAP", "note", "unchecked"


def result(check, status, message, fix=None):
    return {"check": check, "status": status, "message": message, "fix": fix}


# --------------------------------------------------------------------------
# 1. config parses + required fields
# --------------------------------------------------------------------------

def check_config(raw, config_path):
    out = []
    storage = raw.get("storage") or {}
    identity = raw.get("identity") or {}
    ledger = raw.get("ledger") or {}
    enabled = [s for s in (raw.get("sources") or []) if s.get("enabled")]

    if not storage.get("instancePath"):
        out.append(result(
            "config", GAP, "`storage.instancePath` is missing",
            "run `setup` - without it nothing knows where the ledger lives",
        ))
    if not identity:
        out.append(result("config", GAP, "`identity` is missing", "run `setup`"))
    elif not identity.get("name") and not identity.get("email"):
        out.append(result(
            "config", GAP, "`identity` has neither a name nor an email",
            "run `setup` - sweeps need to know who 'me' is",
        ))

    # the documented rule: at least one enabled source OR a backend + identity
    if not enabled and not (ledger.get("backend") and identity):
        out.append(result(
            "config", GAP, "no enabled sources and no backend + identity",
            "run `setup`, or enable at least one source",
        ))
    elif not enabled:
        out.append(result(
            "config", NOTE,
            "no sources are enabled - the ledger works, but nothing will sweep into it",
            "enable a source in config.json when you want automatic capture",
        ))

    if not out:
        out.append(result(
            "config", OK,
            "parses; identity + instancePath present, %d source(s) enabled" % len(enabled),
        ))
    return out


# --------------------------------------------------------------------------
# 2. backend resolves + paths
# --------------------------------------------------------------------------

def adapter_skill_names():
    """Every skill this plugin ships, by declared name.

    Deliberately NOT parsed with `frontmatter.py`: that parser is for note
    frontmatter and refuses constructs it cannot honour, and skill frontmatter
    legitimately uses a folded scalar (`description: >`) which it rejects. Only
    the `name:` line matters here, so read exactly that.
    """
    names = set()
    for skill_md in list(PLUGIN_ROOT.glob("adapters/*/SKILL.md")) + list(
        PLUGIN_ROOT.glob("skills/*/SKILL.md")
    ):
        try:
            lines = skill_md.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if not lines or lines[0].strip() != "---":
            continue
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.startswith("name:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    names.add(value)
                break
    return names


def writable_dir(path):
    path = Path(path)
    return path.is_dir() and os.access(path, os.W_OK)


def check_backend(raw, config):
    out = []
    ledger = raw.get("ledger") or {}
    declared = str(ledger.get("backend") or "builtin")

    # the builtin store is always required: even a note-backed backend keeps its
    # itemMeta companion, drafts and verify metadata there
    state_dir = config.state_file.parent
    if not state_dir.is_dir():
        out.append(result(
            "backend", GAP, "the instance directory does not exist: %s" % state_dir,
            "create it or fix `storage.instancePath`",
        ))
    elif not writable_dir(state_dir):
        out.append(result(
            "backend", GAP, "the instance directory is not writable: %s" % state_dir,
            "fix the path or its permissions - every write lands here",
        ))
    elif not config.state_file.is_file():
        out.append(result(
            "backend", NOTE, "no ledger yet at %s" % config.state_file,
            "`setup` creates it, or the first write will",
        ))

    if declared in ("builtin",):
        if not any(r["status"] == GAP for r in out):
            out.append(result("backend", OK, "builtin (state.json), directory writable"))
        return out

    # any other backend resolves by convention to a `ledger-<X>` skill
    wanted = "ledger-%s" % ("obsidian" if declared == "tasknotes" else declared)
    available = adapter_skill_names()
    if wanted not in available:
        out.append(result(
            "backend", GAP,
            "backend %r resolves to skill %r, which this plugin does not ship "
            "(available: %s)" % (declared, wanted, ", ".join(sorted(available)) or "none"),
            "install that adapter or set `ledger.backend` to `builtin`",
        ))
        return out

    if declared == "tasknotes":
        out.append(result(
            "backend", NOTE,
            "`tasknotes` is a deprecated alias for `obsidian`; it works unchanged",
            "rename it in config.json when convenient",
        ))

    # a note-backed backend needs its notes to actually be there
    if not config.knowledge_path or not Path(config.knowledge_path).is_dir():
        out.append(result(
            "backend", GAP,
            "`storage.knowledgePath` does not exist: %s" % config.knowledge_path,
            "fix the path in config.json",
        ))
    elif not config.tasks_dir.is_dir():
        out.append(result(
            "backend", GAP,
            "the notes directory does not exist: %s" % config.tasks_dir,
            "fix `storage.overrides.tasksDir`",
        ))
    else:
        count = len(list(config.tasks_dir.glob("*.md")))
        out.append(result(
            "backend", OK,
            "%s via %s; %d note(s) in %s" % (declared, wanted, count, config.tasks_dir),
        ))
    return out


# --------------------------------------------------------------------------
# 3. write mode coherent
# --------------------------------------------------------------------------

def check_write_mode(raw, config):
    ledger = raw.get("ledger") or {}
    mode = str(ledger.get("writeMode") or "readonly")
    confirmed = bool((ledger.get("cutover") or {}).get("singleWriterConfirmed"))
    backend = str(ledger.get("backend") or "builtin")

    if backend == "builtin":
        if mode == "readwrite":
            return [result(
                "writeMode", NOTE,
                "`readwrite` is ignored on the builtin backend, which is always writable",
            )]
        return [result("writeMode", OK, "readonly (default); builtin is always writable")]

    if mode == "readonly":
        return [result(
            "writeMode", OK,
            "readonly - mark-met and updates become drafts, notes are never written",
        )]
    if mode == "readwrite" and confirmed:
        return [result(
            "writeMode", OK,
            "readwrite, cutover confirmed - the backend is writable for deliberate "
            "user actions only; scheduled runs still never write a note",
            "confirm no other automation still writes these files",
        )]
    if mode == "readwrite":
        return [result(
            "writeMode", GAP,
            "`writeMode: readwrite` without `cutover.singleWriterConfirmed` - the "
            "backend stays read-only",
            "follow reference/cutover.md, or set writeMode back to readonly",
        )]
    return [result(
        "writeMode", GAP, "unknown writeMode %r" % mode,
        "use `readonly` or `readwrite`",
    )]


# --------------------------------------------------------------------------
# 5. record-store integrity
# --------------------------------------------------------------------------

def check_record_store(config, now):
    """Reuses the Query's own note read, so doctor and the board agree exactly.

    An unparseable record is silently invisible - not a promise, not on the
    board, not in any count - so a single malformed file can hide real work
    indefinitely. This is the check that makes it say something.
    """
    if config.backend != "obsidian":
        return [result("recordStore", OK, "builtin store; nothing to enumerate")]

    promises, meta = lq.query(config, now)
    out = []
    for failure in meta["failures"]:
        out.append(result(
            "recordStore", GAP,
            "%s: %s" % (failure["file"], failure["symptom"]),
            "fix the frontmatter by hand; this record is invisible to everything "
            "until you do",
        ))
    for warning in meta["warnings"]:
        out.append(result(
            "recordStore", NOTE,
            "%s: %s" % (warning["file"], warning["warning"]),
            "ambiguous but readable; fix when convenient",
        ))
    if not out:
        out.append(result(
            "recordStore", OK,
            "%d record(s) enumerated, all parse, none ambiguous" % len(promises),
        ))
    return out


# --------------------------------------------------------------------------

def run_checks(config_path):
    try:
        with open(Path(config_path).expanduser(), encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        return [result(
            "config", GAP, "config not found or unparseable: %s" % error, "run `setup`",
        )], True

    config = lq.Config(config_path)
    from datetime import datetime
    now = datetime.now()

    findings = []
    findings.extend(check_config(raw, config_path))
    findings.extend(check_backend(raw, config))
    findings.extend(check_write_mode(raw, config))
    try:
        findings.extend(check_record_store(config, now))
    except SystemExit as error:
        findings.append(result("recordStore", GAP, str(error), "resolve and re-run"))

    enabled = [s for s in (raw.get("sources") or []) if s.get("enabled")]
    findings.append(result(
        "connectors", UNCHECKED,
        "%d enabled source(s): %s" % (
            len(enabled),
            ", ".join(str(s.get("type")) for s in enabled) or "none",
        ),
        "a subprocess cannot see the session's connectors - confirm each one is "
        "attached, per CONNECTORS.md",
    ))
    return findings, False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, help="instance config.json")
    parser.add_argument("--json", action="store_true", help="machine-readable findings")
    args = parser.parse_args(argv)

    findings, fatal = run_checks(args.config)
    gaps = [f for f in findings if f["status"] == GAP]

    if args.json:
        json.dump({"findings": findings, "gaps": len(gaps)}, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        for finding in findings:
            line = "%-9s %-12s %s" % (finding["status"], finding["check"], finding["message"])
            print(line)
            if finding["fix"] and finding["status"] in (GAP, UNCHECKED):
                print("%-9s %-12s -> %s" % ("", "", finding["fix"]))
        print()
        print("%d gap(s), %d note(s)" % (
            len(gaps), len([f for f in findings if f["status"] == NOTE]),
        ))

    if fatal:
        return 2
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
