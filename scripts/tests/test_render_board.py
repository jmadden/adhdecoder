#!/usr/bin/env python3
"""Fixture test for scripts/render-board.py.

Run: python3 scripts/tests/test_render_board.py

Asserts the acceptance criteria from the render spec: Ready to close renders,
parse failures surface by filename, output is byte-identical across runs, and
dismissed / snoozed / promoted items stay off the active tabs. The fixture
ledger is invented data (Acme Corp / ISSUE-123 style), per the repo's no
personal or company data rule.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = REPO / "scripts" / "render-board.py"
QUERY = REPO / "scripts" / "ledger_query.py"
FIXTURES = HERE / "fixtures"
NOW = "2026-08-12T09:15:00"

FAILURES = []


def check(condition, label):
    print("%s %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def build_instance(tmp):
    """Copy the fixture vault + state into a temp dir and write a config for it."""
    vault = tmp / "vault"
    instance = tmp / "instance"
    shutil.copytree(FIXTURES / "vault", vault)
    # the fixture ledger is named `fixture-state.json` on purpose: the repo's
    # .gitignore blocks `state.json` and `instance/` so real instance data can
    # never be committed, and those guards stay intact
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
                "ledger": {
                    "backend": "obsidian",
                    "writeMode": "readwrite",
                    "cutover": {"singleWriterConfirmed": True},
                },
                "schedule": {"boardPath": str(tmp / "Board.html")},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return config_path, tmp / "Board.html", vault


def run(config_path, extra=()):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(config_path), "--now", NOW, *extra],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise SystemExit("render-board.py exited %d" % result.returncode)
    return result.stdout


def group_block(html, label):
    """Slice out one .today-group by its label, for group-scoped assertions."""
    marker = "</span> %s</div>" % label
    start = html.find(marker)
    if start < 0:
        return ""
    start = html.rfind('<div class="today-group">', 0, start)
    end = html.find('<div class="today-group">', start + 1)
    return html[start:end if end > 0 else len(html)]


def check_pronoun_matching():
    """Unit-check the people lookup directly: getting this wrong misgenders a real
    person, and the board-level assertions cannot cover the ambiguous cases."""
    # pronouns_for lives in the shared Query, not the renderer
    spec = importlib.util.spec_from_file_location("ledger_query", QUERY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    people = {
        "Robin": {"pronouns": "she/her"},
        "Robin Vega": {"pronouns": "he/him"},
        "Sam": {"pronouns": "he/him"},
        "Jo": {"pronouns": "they/them"},
        "No Pronouns Recorded": {"note": "deliberately has none"},
    }
    cases = [
        ("Robin Vega (Org)", "he/him", "the longest recorded name wins over a bare first name"),
        ("Robin (Org)", "she/her", "a bare first name still matches when it is the whole name"),
        ("Samantha Jones (Org)", None, "a recorded 'Sam' does not match inside 'Samantha'"),
        ("Sam Okafor", "he/him", "a whole-word first name matches"),
        ("Jonathan Reyes", None, "a recorded 'Jo' does not match inside 'Jonathan'"),
        ("Jo Reyes", "they/them", "a two-letter name still matches on a word boundary"),
        ("Nobody. The assignee is still null.", None, "prose in the owner field matches nobody"),
        ("No Pronouns Recorded", None, "a person recorded without pronouns gets none invented"),
        ("", None, "an empty owner matches nobody"),
        (None, None, "a missing owner matches nobody"),
    ]
    for owner, expected, label in cases:
        check(module.pronouns_for(owner, people) == expected, "pronouns: %s" % label)


def main():
    check_pronoun_matching()
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config_path, board_path, vault = build_instance(tmp)

        mtimes_before = {p: p.stat().st_mtime_ns for p in sorted(vault.rglob("*.md"))}
        stdout = run(config_path)
        first = board_path.read_bytes()

        # --- determinism ---------------------------------------------------
        board_path.unlink()
        run(config_path)
        check(board_path.read_bytes() == first, "byte-identical output across runs")

        html = first.decode("utf-8")

        # --- Ready to close renders, first, and is counted separately ------
        ready = group_block(html, "Ready to close (confirm)")
        check(bool(ready), "Ready to close group is present")
        check(
            bool(ready) and html.find(ready) == html.find('<div class="today-group">'),
            "Ready to close is the first group on the board",
        )
        check(
            "Spec the header passthrough for Gamma" in ready,
            "a dismissed item carrying markMetDraft renders in Ready to close",
        )
        # ready-to-close and done-today are different states (confirm vs finished),
        # so they must not render in the same colour - they did once, and finished
        # work was indistinguishable from work still owed a decision
        done_today = group_block(html, "Done today")
        check(
            'class="big ready"' in ready and 'class="big done"' not in ready,
            "Ready to close cards use the ready variant, not the done variant",
        )
        check(
            'class="big done"' in done_today and 'class="big ready"' not in done_today,
            "Done today cards keep the done variant",
        )
        check(
            ".big.ready{border-left-color:var(--ready);}" in html
            and "--ready:" in html
            and "var(--ready)" in ready,
            "the ready colour is defined and the group dot uses it",
        )
        check(
            "Answered on the thread on 07/21" in ready,
            "the mark-met draft reason is the card body",
        )
        check(
            "Review the Delta labeling recommendation" in ready,
            "an item carrying updateDraft renders in Ready to close",
        )
        check(
            '<span class="chip c-need">dismissed</span>' in ready,
            "a revived dismissed item is marked as dismissed on the card",
        )
        check(
            "1 item of those was dismissed from the board but still carries an unapplied draft"
            in html,
            "the board note counts the dismissed items a draft revived",
        )

        # --- projects: the tab always, the Board-tab block only when lagging --
        check(
            'id="pane-projects"' in html and "Upsilon rollout" in html,
            "the Projects tab renders each declared project",
        )
        check(
            "Projects worth a look" in html
            and "nothing has moved in" in html,
            "a lagging project surfaces on the Board tab itself",
        )
        check(
            "Omicron integration" in html
            and "Omicron integration" not in html.split("Projects worth a look")[1].split("</div>")[0],
            "a healthy project appears on the tab but NOT in the lagging block",
        )
        check(
            "projects lagging" in html or "project lagging" in html,
            "the headline count names lagging projects when there are any",
        )
        check(
            "Nothing tagged yet" in html,
            "a project with no members still renders (its emptiness is the point)",
        )
        check(
            'keyword &quot;SSO&quot; in title' in html or 'keyword "SSO" in title' in html,
            "every member states on the card WHY it is in the project - a project "
            "that cannot say why is a project that assumes",
        )
        check(
            "Excluded (1)" in html and "--unexclude" in html,
            "an excluded item gets its own block plus the undo command: it is "
            "absent from the member list by definition, so without this the field "
            "is write-only and a mistaken exclude is unfindable",
        )
        check(
            "check in every 14 days" in html and "check-in 2026-08-08" in html,
            "the check-in rhythm and its next date render",
        )
        check(
            "THE IDEA" in html.upper()
            and html.find("THE IDEA") < html.upper().find("MATCHES"),
            "the user's own sentence renders directly ABOVE the rules that claim "
            "to implement it, so a lossy translation is visible at a glance",
        )

        # A board with NOTHING lagging must render the block as empty and must
        # not crash. The injection point is unconditional and the renderer
        # returns "" - if a future edit deletes the marker instead, render()
        # raises SystemExit, and it would do so on exactly the calm board this
        # feature promises to leave alone.
        calm = tmp / "calm"
        shutil.copytree(tmp, calm, ignore=shutil.ignore_patterns("calm"))
        calm_config = calm / "config.json"
        raw = json.loads(calm_config.read_text())
        raw["storage"]["instancePath"] = str(calm / "instance")
        raw["storage"]["knowledgePath"] = str(calm / "vault")
        raw["schedule"]["boardPath"] = str(calm / "Board.html")
        calm_config.write_text(json.dumps(raw, indent=2))
        calm_state = calm / "instance" / "state.json"
        data = json.loads(calm_state.read_text())
        data["projects"] = []
        calm_state.write_text(json.dumps(data, indent=2))
        run(calm_config)
        calm_html = (calm / "Board.html").read_text()
        check(
            "Projects worth a look" not in calm_html,
            "with nothing lagging, the Board tab carries no projects section at all",
        )
        check(
            "lagging" not in calm_html.split('<div class="counts">')[1].split("</div>")[0],
            "and the headline count says nothing about projects",
        )
        check(
            'id="pane-projects"' in calm_html and "No projects declared" in calm_html,
            "the Projects tab still exists and explains how to populate it",
        )
        check(
            "<b>2</b> ready to close, <b>6</b> need your move, <b>2</b> waiting, <b>3</b> shipped"
            in html,
            "counts split ready-to-close out of need-your-move",
        )
        check(
            "6 items need your move" in html and "3 notes could not be parsed and are not" in html,
            "the board note agrees in number",
        )
        check(
            "Provide the Mu quarterly summary" in html
            and "Provide the Mu quarterly summary" not in group_block(html, "Your move"),
            "a future-dated item renders on Tomorrow, not on Today",
        )
        check('<span class="tbadge">1</span>' in html, "the Tomorrow tab badge is filled")
        check(
            "your move - soft date 2026-08-01" in html
            and "Soft date 2026-08-01, no hard deadline." in html
            and "overdue" not in group_block(html, "Your move").split("Maintain the Nu")[-1][:400],
            "a past soft date reads as a soft date, never as overdue",
        )
        move = group_block(html, "Your move")
        check(
            "Spec the header passthrough for Gamma" not in move,
            "a resolved item never lands in Your move",
        )

        # --- parse failures surface ---------------------------------------
        check(
            "Broken frontmatter for Theta.md" in html,
            "the unparseable note surfaces by filename in the board note",
        )
        check(
            "Untagged scratch note.md" in html,
            "a note missing the task tag surfaces rather than vanishing",
        )
        check(
            "parse failure: Broken frontmatter for Theta.md" in stdout,
            "the recap names the parse failure",
        )

        # --- suppression ---------------------------------------------------
        check(
            "Answer the Eta capacity question" not in html,
            "a future snoozedUntil item is excluded from the active tabs",
        )
        check(
            "Configure the Zeta test tenant" not in html,
            "a dismissed item with no pending draft is excluded",
        )
        check(
            "Lambda promoted record" not in html,
            "a promoted state.json promise is not resurrected",
        )
        check(
            "Duplicate of the Acme note" not in html,
            "the union dedups a state.json promise into the note that owns its source",
        )
        check(
            "collapsed into Tasks/Deliver the staging redirect fix to Acme.md" in stdout,
            "the recap names every collapse, so dedup is never invisible",
        )
        check(
            "1 ledger promise folded into the note that already owns its source" in html,
            "the collapse count is on the board too, not stdout-only "
            "(a scheduled run's stdout reaches nobody)",
        )
        check(
            "Answer the Omicron header question" in html
            and "Provide the Omicron domain list" in html,
            "two notes citing one ticket both survive (same-store records never collapse)",
        )

        # --- no write-only overlay fields (schemaVersion 2 invariant) -------
        check(
            "Nudge B. Person (they/them)." in html,
            "recorded pronouns from state.json `people` reach the action line",
        )
        check(
            "A. Contact (Acme Corp)." in html and "A. Contact (Acme Corp) (" not in html,
            "an owner with no recorded pronouns gets no guessed ones",
        )
        check(
            "Finance replied on the 9th asking which cost centre owns the split" in html,
            "the promise `note` renders in the card body",
        )
        check(
            "<b>Soft date:</b> The due date was the original kickoff" in html,
            "itemMeta.deadlineTypeReason renders on a soft-date card",
        )
        check(
            '<span class="since">also: ISSUE-790</span>' in html,
            "promise.relatedRefs renders beside the source link",
        )
        check(
            "1 record carries a frontmatter warning:" in html
            and "Draft the Xi migration summary.md" in html
            and "Follow up with Beta Co on the SSO answer.md" not in html,
            "a live lint (the duplicate key) reaches the board note, and the two "
            "fixture notes carrying only a STORED itemMeta warning do not - a "
            "stored lint is never re-checked, so it is not rendered at all",
        )
        check(
            "frontmatter warning: Draft the Xi migration summary" in stdout,
            "the recap names the frontmatter warning too",
        )

        # --- card contents -------------------------------------------------
        check(html.count('class="chip c-task"') >= 5, "every card carries a verifyStatus chip")
        check(
            "unverified - confirm" in html,
            "an unverifiable item renders as unverified, not as an asserted move",
        )
        check(
            "https://tracker.example.com/browse/ISSUE-123" in html,
            "the actionable source.url is on the card, not the note link",
        )
        check("obsidian://open?vault=" in html, "the noteRef record link is on the card")
        check("Zeta &amp; Sons" in html or "&amp;" in html, "ledger values are HTML-escaped")
        check("{{" not in html, "no unfilled template tokens remain")
        check("RENDER " not in html, "no injection-point comments remain")

        # --- a half-written ledger is refused, not rendered ----------------
        good_board = board_path.read_bytes()
        (tmp / "instance" / "state.json").write_text('{"promises": [')
        partial = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(config_path), "--now", NOW],
            capture_output=True, text=True,
        )
        check(
            partial.returncode != 0 and "did not parse" in (partial.stderr + partial.stdout),
            "a partially-written ledger is refused with a clear message",
        )
        check(
            board_path.read_bytes() == good_board,
            "the last good board is left untouched when the ledger will not parse",
        )

        # --- guardrail: never writes a note --------------------------------
        mtimes_after = {p: p.stat().st_mtime_ns for p in sorted(vault.rglob("*.md"))}
        check(mtimes_before == mtimes_after, "no note was written (mtimes unchanged)")

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
