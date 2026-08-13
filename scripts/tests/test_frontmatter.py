#!/usr/bin/env python3
"""Tests for scripts/frontmatter.py, the stdlib replacement for PyYAML.

Run: python3 scripts/tests/test_frontmatter.py

Two halves:

1. **Unit cases** for every construct in the measured subset, every known trap,
   and every construct the parser must REFUSE. The refusals are the point: a
   subset parser is only safe if it cannot silently misread, so each unsupported
   construct must raise rather than guess.
2. **A differential** against PyYAML over a corpus, asserting equivalence. It
   skips cleanly when PyYAML is absent, so it never becomes a dependency again -
   it exists to prove the port, not to gate the plugin.
"""

import datetime
import glob
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FIXTURE_VAULT = HERE / "fixtures" / "vault" / "Tasks"

spec = importlib.util.spec_from_file_location("frontmatter", REPO / "scripts" / "frontmatter.py")
fm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fm)

FAILURES = []


def check(condition, label):
    print("%s %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def parses_to(text, expected, label):
    try:
        got = fm.parse_frontmatter(text)
    except fm.FrontmatterError as error:
        check(False, "%s (raised: %s)" % (label, error))
        return
    check(got == expected, "%s%s" % (label, "" if got == expected else " -> got %r" % (got,)))


def refuses(text, label):
    try:
        fm.parse_frontmatter(text)
    except fm.FrontmatterError:
        check(True, "refuses: %s" % label)
        return
    check(False, "refuses: %s (parsed instead of raising)" % label)


def unit_cases():
    print("--- the measured subset ---")
    parses_to("status: done", {"status": "done"}, "plain scalar")
    parses_to("due: 2026-08-01", {"due": "2026-08-01"},
              "a date stays a STRING (as_date parses it; a datetime is not JSON-serialisable)")
    parses_to("dateModified: 2026-08-01T09:00:00.862-07:00",
              {"dateModified": "2026-08-01T09:00:00.862-07:00"},
              "a timestamp keeps its exact text, no microsecond padding")
    parses_to("projects: []", {"projects": []}, "empty inline collection")
    parses_to('projects: ["[[A]]", "B"]', {"projects": ["[[A]]", "B"]}, "inline list")
    parses_to("tags:\n  - task\n  - work", {"tags": ["task", "work"]}, "block list")
    parses_to('projects:\n  - "[[Acme]]"', {"projects": ["[[Acme]]"]}, "quoted block list item")
    parses_to("", {}, "empty frontmatter")
    parses_to("# just a comment\nstatus: todo", {"status": "todo"}, "comment line skipped")
    parses_to("a: 1\n\nb: 2", {"a": "1", "b": "2"}, "blank line between keys")
    parses_to("tasknotes_manual_order: 3", {"tasknotes_manual_order": "3"},
              "underscored key")

    print("\n--- the traps ---")
    parses_to("due:\ncustomer: Acme", {"due": None, "customer": "Acme"},
              "THE BLANK-DUE TRAP: an empty key is absent, not the next line's value")
    parses_to("requester:\n  - Jose\ncustomer: Acme",
              {"requester": ["Jose"], "customer": "Acme"},
              "an empty key followed by list items IS the list")
    parses_to("dateModified: 2026-08-04\ndateModified: 2026-08-07",
              {"dateModified": "2026-08-07"},
              "duplicate key keeps last-wins, matching the library it replaces")
    parses_to('Updates: "2026-08-05 - said \\"yes\\" to the ask: it is done"',
              {"Updates": '2026-08-05 - said "yes" to the ask: it is done'},
              "quoted scalar with an embedded colon AND escaped quotes")
    parses_to("url: https://example.com/a#frag",
              {"url": "https://example.com/a#frag"},
              "a # inside a value is not a comment")
    parses_to("note: text  # trailing comment",
              {"note": "text"},
              "a clearly separated trailing comment is stripped")
    parses_to('title: "a, b"', {"title": "a, b"}, "comma inside a quoted scalar")
    parses_to('list: ["a, still one", "b"]', {"list": ["a, still one", "b"]},
              "comma inside a quoted inline-list item does not split it")

    print("\n--- refusals: anything outside the subset must raise, never guess ---")
    refuses("summary: |\n  a block scalar", "block scalar (|)")
    refuses("summary: >\n  a folded scalar", "folded scalar (>)")
    refuses("base: &anchor value", "anchor (&)")
    refuses("ref: *anchor", "alias (*)")
    refuses("meta: {a: 1}", "flow mapping")
    refuses("nested:\n  inner: value", "nested mapping")
    refuses("  - orphan", "list item with no parent key")
    refuses('bad: "unterminated', "unterminated quote")
    refuses("bad: [a, b", "unterminated inline list")
    refuses("this line has no colon", "unparsable line")


def differential():
    """Prove equivalence with PyYAML where it happens to be installed."""
    print("\n--- differential against PyYAML ---")
    try:
        import yaml
    except ModuleNotFoundError:
        print("SKIP PyYAML is not installed, so there is nothing to compare against")
        print("     (that is the point of this change; the plugin no longer needs it)")
        return

    def canon(value):
        """One canonical form for both sides: PyYAML builds date objects, we
        return strings, and its round-trip pads microseconds."""
        if isinstance(value, datetime.datetime):
            return "DT:" + value.isoformat().replace(".000000", "")
        if isinstance(value, datetime.date):
            return "D:" + value.isoformat()
        if value is None:
            return None
        if isinstance(value, list):
            return [canon(v) for v in value]
        if isinstance(value, bool):
            return "true" if value else "false"
        text = str(value)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return "D:" + text
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ].*", text):
            try:
                return "DT:" + datetime.datetime.fromisoformat(text).isoformat().replace(".000000", "")
            except ValueError:
                return text
        return text

    compared = equivalent = 0
    for path in sorted(glob.glob(str(FIXTURE_VAULT / "*.md"))):
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            continue
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
        if end is None:
            continue
        block = "\n".join(lines[1:end])
        try:
            expected = yaml.safe_load(block) or {}
        except Exception:
            continue
        if not isinstance(expected, dict):
            continue
        try:
            got = fm.parse_frontmatter(block)
        except fm.FrontmatterError:
            # a note this parser deliberately refuses; the caller reports it
            continue
        compared += 1
        if {k: canon(v) for k, v in expected.items()} == {k: canon(v) for k, v in got.items()}:
            equivalent += 1
        else:
            keys = [
                k for k in set(expected) | set(got)
                if canon(expected.get(k)) != canon(got.get(k))
            ]
            print("     mismatch in %s: %s" % (Path(path).name, keys))
    check(
        compared > 0 and equivalent == compared,
        "differential: %d of %d fixture notes parse equivalently to PyYAML"
        % (equivalent, compared),
    )


def main():
    unit_cases()
    differential()
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
