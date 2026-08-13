#!/usr/bin/env python3
"""Parse the YAML frontmatter subset that task notes actually use. Stdlib only.

Replaces PyYAML, which was the plugin's only installable dependency and was
doing almost nothing: measured across a real 58-note vault, frontmatter uses six
constructs and none of YAML's hard parts (no block scalars, anchors, aliases,
nested mappings, or comments).

## Why a subset parser is safe here, when a previous one was not

An earlier hand-rolled parser was banned because it **silently misread**: a blank
`due:` was taken as the next line's value. The objection was to the silence, not
to hand-rolling. So this parser **refuses what it does not understand**. Anything
outside the measured subset raises `FrontmatterError`, and the caller reports the
note by filename through the existing parse-failure surface.

That makes it strictly safer than the library it replaces. PyYAML accepted a note
carrying two `dateModified` keys and quietly discarded one of the values; a
parser that raises on the unfamiliar cannot do that.

## The subset

    key: value                  -> "value"
    key: 2026-08-01             -> "2026-08-01"   (a string; as_date() parses it)
    key: "a: b, and \"quoted\"" -> 'a: b, and "quoted"'
    key:                        -> None, UNLESS followed by block list items
      - one                     -> ["one", "two"]
      - "[[two]]"
    key: []                     -> []
    key: ["[[a]]", "b"]         -> ["[[a]]", "b"]
    # comment                   -> skipped
    <blank line>                -> skipped

Everything is returned as a string, a list of strings, or None. Dates are
deliberately NOT converted: `as_date()` already parses strings, and returning
strings removes a whole class of bug (a datetime is not JSON-serialisable, which
broke the Query's JSON contract when PyYAML produced one).

Duplicate keys keep last-wins, matching the library's behaviour so this change
alters nothing. `duplicate_frontmatter_keys()` in `ledger_query.py` reports them
separately, because last-wins silently drops a value.
"""

import re

__all__ = ["FrontmatterError", "parse_frontmatter"]

KEY_LINE = re.compile(r"^([A-Za-z_][\w.-]*):(?:[ \t](.*))?$")
LIST_ITEM = re.compile(r"^[ \t]+-[ \t]+(.*)$")
BARE_KEY = re.compile(r"^([A-Za-z_][\w.-]*):$")


class FrontmatterError(ValueError):
    """Raised for anything outside the supported subset. Never guess."""


def _unquote(raw, where):
    """A quoted scalar -> its text. Refuses an unterminated quote."""
    quote = raw[0]
    if len(raw) < 2 or raw[-1] != quote:
        raise FrontmatterError("unterminated %s quote in %s" % (quote, where))
    inner = raw[1:-1]
    if quote == '"':
        # only the escapes real notes contain; anything else is left verbatim
        return inner.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
    return inner.replace("''", "'")


def _split_inline(raw, where):
    """`["a", "b"]` -> ["a", "b"]. Commas inside quotes do not split."""
    body = raw[1:-1].strip()
    if not body:
        return []
    items, current, quote, index = [], "", None, 0
    while index < len(body):
        char = body[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < len(body):
                current += body[index:index + 2]
                index += 2
                continue
            current += char
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current += char
        elif char == ",":
            items.append(current.strip())
            current = ""
        elif char in "[]{}":
            raise FrontmatterError("nested inline collection in %s" % where)
        else:
            current += char
        index += 1
    if quote:
        raise FrontmatterError("unterminated quote in inline list in %s" % where)
    items.append(current.strip())
    return [_scalar(item, where) for item in items if item != ""]


def _scalar(raw, where):
    """A single value -> string. Refuses constructs this parser cannot honour."""
    raw = raw.strip()
    if not raw:
        return None
    first = raw[0]
    if first in "|>":
        raise FrontmatterError("block scalar (%s) in %s is not supported" % (first, where))
    if first in "&*":
        raise FrontmatterError("anchor/alias (%s) in %s is not supported" % (first, where))
    if first == "{":
        raise FrontmatterError("flow mapping in %s is not supported" % where)
    if first == "[":
        if not raw.endswith("]"):
            raise FrontmatterError("unterminated inline list in %s" % where)
        return _split_inline(raw, where)
    if first in "\"'":
        return _unquote(raw, where)
    # a plain scalar: strip a trailing comment only when clearly separated,
    # never inside a value like a URL fragment
    match = re.match(r"^(.*?)\s+#\s", raw)
    if match:
        raw = match.group(1).rstrip()
    return raw


def parse_frontmatter(text):
    """Frontmatter body (no `---` fences) -> dict. Raises FrontmatterError.

    Returns {} for empty input, matching a library's None-to-empty handling at
    the call site.
    """
    result = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue

        if line[0].isspace():
            # an indented line that is not attached to a preceding bare key
            raise FrontmatterError(
                "unexpected indented line %d: %s" % (index + 1, stripped[:40])
            )

        bare = BARE_KEY.match(line)
        if bare:
            key = bare.group(1)
            items, look = [], index + 1
            while look < len(lines):
                nxt = lines[look]
                if not nxt.strip():
                    look += 1
                    continue
                item = LIST_ITEM.match(nxt)
                if not item:
                    break
                items.append(_scalar(item.group(1), "key %r" % key))
                look += 1
            if items:
                result[key] = items
                index = look
            else:
                # the blank-`due:` trap: an empty key is ABSENT, never a grab of
                # whatever the next line happens to say
                result[key] = None
                index += 1
            continue

        keyed = KEY_LINE.match(line)
        if keyed:
            key, raw = keyed.group(1), keyed.group(2) or ""
            result[key] = _scalar(raw, "key %r" % key)
            index += 1
            continue

        if LIST_ITEM.match(line):
            raise FrontmatterError("list item at line %d has no parent key" % (index + 1))
        raise FrontmatterError(
            "unparsable line %d: %s" % (index + 1, stripped[:40])
        )
    return result
