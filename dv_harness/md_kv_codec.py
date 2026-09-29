"""dv_harness/md_kv_codec.py -- the ONE strict Markdown key/value codec
shared by `model_handoff.py` (HANDOFF_V1) and `model_result.py`
(RESULT_V1).

Why shared: GAP-V2-012 was closed twice on independently duplicated
serializers/parsers and Codex's re-review (M7-V1-CODEX-REVIEW-002, R1/R6)
still reproduced a real defect in both, because each copy only hardened
the serializer side. A returned RESULT_V1 is authored by an external
model and carried by a human -- the PARSER is the trust boundary, so its
strictness cannot depend on the local serializer having escaped anything.

Two encodings, distinguished by an explicit marker line:

  * RAW (no marker): what an external model writes by hand. Values are
    taken VERBATIM -- no unescaping is ever applied, so text such as
    `a\\rb` or `C:\\new` in an external document is never silently
    transformed. Leading/trailing whitespace of a value is normalized
    away (a documented property of the raw format).
  * ESCAPED (`ENCODING_MARKER` present, emitted by every `to_markdown()`):
    an exact, lossless inverse for ANY Python string, including CR, LF,
    other Unicode line boundaries, leading/trailing whitespace, a leading
    '#', empty list items and the literal text "(none)".

Structure is fail-closed in BOTH encodings: a duplicate section, an
unknown section, or stray content before the first section raises a real
`MdKvError` -- a document is never silently "last header wins".
"""
from __future__ import annotations

import re as _re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ENCODING_MARKER = "<!-- L5DGVA_VALUE_ENCODING=escaped-v1 -->"

#: str.splitlines() boundaries other than LF/CR (which have named escapes).
_OTHER_LINE_BREAKS = "\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"

NONE_TOKEN = "(none)"
EMPTY_TOKEN = "(empty)"  # ESCAPED encoding only: an empty string, distinct from None


class MdKvError(ValueError):
    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# --- escaping ---------------------------------------------------------------

def _u(c: str) -> str:
    return "\\u%04x" % ord(c)


def escape_value(s: str) -> str:
    """Lossless single-physical-line encoding. Every character that could
    end a line, be stripped, or start a structural token is made explicit."""
    out: List[str] = []
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c in _OTHER_LINE_BREAKS:
            out.append(_u(c))
        else:
            out.append(c)
    text = "".join(out)
    # Edge whitespace would be lost to strip() -- make it explicit.
    lead = len(text) - len(text.lstrip())
    trail = len(text) - len(text.rstrip())
    if lead or trail:
        chars = list(text)
        for i in range(lead):
            chars[i] = _u(chars[i])
        for i in range(len(chars) - trail, len(chars)):
            if i >= lead:
                chars[i] = _u(chars[i])
        text = "".join(chars)
    if text.startswith("#"):
        text = _u("#") + text[1:]
    if text in (NONE_TOKEN, EMPTY_TOKEN):
        text = _u("(") + text[1:]
    return text


_HEX4 = _re.compile(r"[0-9a-fA-F]{4}")


def unescape_value(s: str) -> str:
    """Strict exact inverse of `escape_value()`. A backslash that does not
    begin one of the defined escapes is malformed input, never guessed."""
    out: List[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= n:
            raise MdKvError("MALFORMED_ESCAPE", {"value": s})
        nxt = s[i + 1]
        if nxt == "\\":
            out.append("\\")
            i += 2
        elif nxt == "n":
            out.append("\n")
            i += 2
        elif nxt == "r":
            out.append("\r")
            i += 2
        elif nxt == "u" and _HEX4.fullmatch(s[i + 2:i + 6] or ""):
            out.append(chr(int(s[i + 2:i + 6], 16)))
            i += 6
        else:
            raise MdKvError("MALFORMED_ESCAPE", {"value": s, "at": i})
    return "".join(out)


# --- rendering --------------------------------------------------------------

def render_scalar(value: Any) -> str:
    """None -> `(none)`; the empty string -> `(empty)`: the two are distinct
    values and stay distinct on round trip (REVIEW-003 N3)."""
    if value is None:
        return NONE_TOKEN
    if value == "":
        return EMPTY_TOKEN
    return escape_value(str(value))


def render_list(items: Iterable[Any]) -> str:
    items = list(items or [])
    if not items:
        return NONE_TOKEN
    lines = []
    for v in items:
        e = escape_value(str(v))
        lines.append("-" if e == "" else f"- {e}")
    return "\n".join(lines)


def render_document(title: str, field_order: Sequence[str], values: Dict[str, Any],
                    list_fields: Iterable[str]) -> str:
    list_fields = frozenset(list_fields)
    lines = [f"# {title}", "", ENCODING_MARKER, ""]
    for name in field_order:
        lines.append(f"## {name}")
        lines.append(render_list(values[name]) if name in list_fields else render_scalar(values[name]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --- parsing ----------------------------------------------------------------

def split_sections(text: str, allowed_fields: Sequence[str], title: str) -> Tuple[Dict[str, str], bool]:
    """Returns (sections, escaped). Fail-closed: the document must open with
    exactly ONE canonical `# {title}` line (a schema token appearing in some
    other title or in content does not make a document of that schema); the
    encoding marker, if any, must be the single line right after it; duplicate
    or unknown sections, and any other content before the first section,
    raise. Line boundaries follow `str.splitlines()` (every Unicode boundary)
    so a viewer and this parser never disagree about where a `## ` header
    starts."""
    allowed = frozenset(allowed_fields)
    canonical_title = f"# {title}"
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    escaped = False
    seen_title = False
    marker_slot_open = False  # only the first non-blank line after the title may be the marker
    lines = text.splitlines()
    if not any(l.strip() == canonical_title for l in lines):
        raise MdKvError("NOT_THIS_DOCUMENT", {"expected_title": canonical_title})
    for line in lines:
        if line.startswith("## "):
            name = line[3:].strip()
            if not seen_title:
                raise MdKvError("UNEXPECTED_PREAMBLE", {"line": line[:120]})
            if name in sections:
                raise MdKvError("DUPLICATE_SECTION", {"section": name})
            if name not in allowed:
                raise MdKvError("UNKNOWN_SECTION", {"section": name})
            current = name
            sections[name] = []
        elif current is None:
            stripped = line.strip()
            if not stripped:
                continue
            if not seen_title:
                if stripped != canonical_title:
                    raise MdKvError("UNEXPECTED_PREAMBLE", {"line": stripped[:120]})
                seen_title = True
                marker_slot_open = True
            elif stripped == ENCODING_MARKER:
                if not marker_slot_open:
                    raise MdKvError("DUPLICATE_ENCODING_MARKER" if escaped else "MISPLACED_ENCODING_MARKER", {})
                escaped = True
                marker_slot_open = False
            elif stripped == canonical_title or stripped.startswith("# "):
                raise MdKvError("DUPLICATE_TITLE", {"line": stripped[:120]})
            else:
                raise MdKvError("UNEXPECTED_PREAMBLE", {"line": stripped[:120]})
            if stripped != ENCODING_MARKER:
                marker_slot_open = seen_title and stripped == canonical_title
        else:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}, escaped


def parse_scalar(raw: str, escaped: bool) -> Optional[str]:
    if raw == NONE_TOKEN or raw == "":
        return None
    if escaped and raw == EMPTY_TOKEN:
        return ""
    if escaped:
        if "\n" in raw:
            raise MdKvError("MALFORMED_SCALAR", {"value": raw[:120]})
        return unescape_value(raw)
    return raw


def parse_list(raw: str, escaped: bool) -> List[str]:
    if raw == NONE_TOKEN or raw == "":
        return []
    items: List[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if line == "-":
            items.append("")
        elif line.startswith("- "):
            body = line[2:].strip()
            items.append(unescape_value(body) if escaped else body)
        elif line:
            # A wrapped/continuation line is ambiguous (separate item? part
            # of the previous one?) -- never guessed, never silently split.
            raise MdKvError("MALFORMED_LIST_ITEM", {"line": line[:120]})
    return items
