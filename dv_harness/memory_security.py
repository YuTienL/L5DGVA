"""Secret-pattern detection and redaction for the DV-Knowledge Vault (Phase 19
of the Obsidian+Git/Markdown Hybrid Engineering Memory spec, Workstream 2).

This project had a REAL credential-leak incident this same session: a VCPW
value was embedded directly in `.claude/settings.local.json` permission
rules (756 occurrences, remediated -- see CLAUDE.md's "Remote Linux
Execution" section for the surrounding policy this incident hardened).
That incident is the concrete, real shape this module's test suite is built
against, not a hypothetical: a `VCPW=<value>`-shaped assignment, SSH private
key headers, and common token/API-key shapes are all detected and redacted
here, alongside generic password/secret/license-key/personal-credential
patterns the spec also names.

Design, matching this codebase's existing conventions (memory_vault.py's own
"no embedding/vector DB, string/set-based only" scoping):
  - Pure regex/string matching. No third-party dependency, no ML classifier.
  - Every pattern is intentionally CONSERVATIVE-TO-CATCH (a few plausible
    false positives, e.g. a long grouped-hex license-key-shaped string that
    happens to be something else, are an acceptable cost for a detector
    whose job is "never let a real secret reach a committed vault note" --
    see `run_doctor()`'s "secret leakage" check, which is a hard BLOCKED
    condition specifically because of this incident).
  - Redaction always preserves the surrounding text/key name and only
    replaces the secret VALUE itself with a labeled `***REDACTED-<TYPE>***`
    marker, so a reader can still see *that* a credential was present and of
    what kind, without the credential itself ever landing in a note, in git
    history, or in a shared Knowledge Center push.

Wired at BOTH real write layers, so no record can reach disk unscanned:
  - `memory.MemoryStore.add()` / `memory.CornerCaseLibrary.add()` via
    `redact_record()` below -- the durable JSON store `memory_router.py`
    calls "the system of record", written for EVERY tier including
    WORKING_MEMORY (which is deliberately never mirrored into the vault at
    all, see memory_router._VAULT_WRITE_THROUGH_DESTINATIONS, and so has no
    other scanner).
  - `memory_vault.FileSystemMarkdownAdapter.create()`/`update()` via
    `redact_note_content()` (see that module's own comments at the call
    sites) for the Markdown mirror.
Both run BEFORE any content is written -- never as an after-the-fact scrub.
`route_memory()`'s hard `REJECT` of a record whose `kind` is
credential/password/token/secret is a separate, coarser gate: it stops a
record that IS a credential, and cannot see a secret-shaped string embedded
in a legitimate record's free-text field. That case is what `redact_record()`
covers.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Pattern registry: (type_name, compiled_regex, redact_group)
# redact_group == 0 means "redact the whole match"; any other int means
# "redact only that capture group's span, keep the rest of the match intact"
# (e.g. keep "VCPW=" visible, redact only the value after it).
# ---------------------------------------------------------------------------

_KEY_VALUE_TAIL = r"\s*[:=]\s*['\"]?(\S+?)['\"]?(?=\s|$|['\"])"

SECRET_PATTERNS: List[Tuple[str, "re.Pattern[str]", int]] = [
    # Real incident pattern (2026-09-03, this session): a VC password
    # assigned via VCPW=<value> (or the sibling VCPASS/VC_PASSWORD spellings
    # CLAUDE.md's own remote-execution docs use interchangeably).
    ("vc_password", re.compile(r"\b(VCPW|VCPASS|VC_PASSWORD)" + _KEY_VALUE_TAIL, re.IGNORECASE), 2),
    # SSH private key material -- redact the entire PEM block, never just a
    # fragment of it.
    ("ssh_private_key", re.compile(
        r"-----BEGIN (?:RSA |OPENSSH |DSA |EC |)PRIVATE KEY-----"
        r"[\s\S]+?"
        r"-----END (?:RSA |OPENSSH |DSA |EC |)PRIVATE KEY-----"
    ), 0),
    # Generic password/passphrase assignments.
    ("password", re.compile(r"\b(PASSWORD|PASSWD|SSHPASS|PASSPHRASE)" + _KEY_VALUE_TAIL, re.IGNORECASE), 2),
    # Generic secret/token/API-key assignments (KEY=value / KEY: "value" shapes).
    ("api_key_or_token", re.compile(
        r"\b(API_KEY|APIKEY|API_TOKEN|ACCESS_KEY|ACCESS_TOKEN|SECRET_KEY|"
        r"CLIENT_SECRET|AUTH_TOKEN|PRIVATE_TOKEN|SECRET)" + _KEY_VALUE_TAIL, re.IGNORECASE), 2),
    # AWS access key id -- a fixed, well-known shape, no key-name context needed.
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 0),
    # GitHub personal-access-token shapes (ghp_/gho_/ghu_/ghs_/ghr_).
    ("github_token", re.compile(r"\bgh[poursc]_[A-Za-z0-9]{36,}\b"), 0),
    # Slack bot/user/app tokens.
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"), 0),
    # A bare JWT (three base64url segments separated by dots).
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), 0),
    # "Bearer <token>" HTTP auth header shape.
    ("bearer_token", re.compile(r"\bBearer\s+([A-Za-z0-9\-_.]{20,})\b", re.IGNORECASE), 1),
    # Personal credentials embedded directly in a URL (scheme://user:pass@host).
    ("url_embedded_credential", re.compile(r"://[^\s:@/]+:([^\s@/]+)@"), 1),
    # License/product-key assignments (Synopsys/VCS-style LM_LICENSE_FILE,
    # generic LICENSE_KEY).
    ("license_key_assignment", re.compile(
        r"\b(LICENSE_KEY|LM_LICENSE_FILE|LICENSE)" + _KEY_VALUE_TAIL, re.IGNORECASE), 2),
    # License/product-key SHAPE (grouped hex blocks, e.g. "AB12-CD34-EF56-7890"),
    # independent of any surrounding key name -- the shape itself is what a
    # hand-pasted license or activation key typically looks like. Requires at
    # least 4 groups of 4+ hex characters to keep short git-SHA-like strings
    # (which are not dash-grouped) from matching.
    ("license_key_shape", re.compile(r"\b[0-9A-Fa-f]{4,}(?:-[0-9A-Fa-f]{4,}){3,}\b"), 0),
]

# Idempotency guard: a KEY=value-shaped pattern (vc_password, password,
# api_key_or_token, license_key_assignment) matches its OWN prior redaction
# output right back (`VCPW=***REDACTED-VC_PASSWORD***` still textually looks
# like `VCPW=<value>`) -- without this guard, memory_vault.py's update()
# (which re-redacts the FULL merged content on every call, not just the
# incoming patch) and memory_doctor.py's check_secrets() (which re-scans raw
# on-disk note text) would both perpetually re-"detect" an already-redacted
# marker as a fresh secret. A value that is already exactly one of this
# module's own `***REDACTED-<TYPE>***` markers is never a new finding and is
# never re-wrapped.
_ALREADY_REDACTED_VALUE_RE = re.compile(r"^\*\*\*REDACTED-[A-Z0-9_]+\*\*\*$")

# Frontmatter keys that are structural/identity metadata, never free-text
# content -- never scanned/redacted, both because they cannot plausibly
# contain a leaked secret in this schema and because mangling them (e.g.
# `id`) would break note identity.
_FRONTMATTER_SKIP_KEYS = {
    "id", "memory_level", "created", "updated", "confidence", "status",
    "schema_status", "confirmation_count", "last_confirmed_at",
}


def _mask(value: str) -> str:
    value = value.strip()
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + ("*" * (len(value) - 4)) + value[-2:]


def detect_secrets(text: str) -> List[Dict[str, Any]]:
    """Real pattern matching over `text` -- returns one finding dict per
    match: {"type", "line", "preview"} (never the secret's real value; only
    a first/last-2-char masked preview, for a human to sanity-check the
    finding without the detector itself becoming a leak vector)."""
    if not text:
        return []
    findings: List[Dict[str, Any]] = []
    for name, pattern, group in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(group) if group else m.group(0)
            if not value or _ALREADY_REDACTED_VALUE_RE.match(value.strip()):
                continue
            line_no = text.count("\n", 0, m.start(group if group else 0)) + 1
            preview = "<SSH PRIVATE KEY BLOCK>" if name == "ssh_private_key" else _mask(value)
            findings.append({"type": name, "line": line_no, "preview": preview})
    return findings


def redact_secrets(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Returns (redacted_text, findings). Findings are computed BEFORE
    redaction (so line numbers refer to the original text) via
    `detect_secrets()`; redaction then replaces only the secret VALUE for a
    group-based pattern (keeping the key name / surrounding text intact and
    legible) or the whole match for a whole-match pattern (SSH keys, and
    fixed-shape tokens that carry no meaningful surrounding context)."""
    if not text:
        return text, []
    findings = detect_secrets(text)
    redacted = text
    for name, pattern, group in SECRET_PATTERNS:
        def _sub(m: "re.Match[str]", name: str = name, group: int = group) -> str:
            value = m.group(group) if group else m.group(0)
            if not value or _ALREADY_REDACTED_VALUE_RE.match(value.strip()):
                return m.group(0)  # already redacted -- leave untouched (idempotent)
            if not group:
                return f"***REDACTED-{name.upper()}***"
            whole = m.group(0)
            start_in_whole = m.start(group) - m.start(0)
            end_in_whole = m.end(group) - m.start(0)
            return whole[:start_in_whole] + f"***REDACTED-{name.upper()}***" + whole[end_in_whole:]

        redacted = pattern.sub(_sub, redacted)
    return redacted, findings


def redact_frontmatter(frontmatter: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Scans every free-text frontmatter value (skipping `_FRONTMATTER_SKIP_KEYS`
    structural fields) and redacts in place. Returns (redacted_copy,
    findings) -- findings carry a `field` key naming which frontmatter field
    the secret was found in, on top of `detect_secrets()`'s type/line/preview."""
    out = dict(frontmatter)
    all_findings: List[Dict[str, Any]] = []
    for key, value in frontmatter.items():
        if key in _FRONTMATTER_SKIP_KEYS:
            continue
        if isinstance(value, str):
            redacted, findings = redact_secrets(value)
            if findings:
                out[key] = redacted
                for f in findings:
                    f["field"] = key
                all_findings.extend(findings)
        elif isinstance(value, list):
            new_list = []
            changed = False
            for item in value:
                if isinstance(item, str):
                    redacted_item, findings = redact_secrets(item)
                    if findings:
                        changed = True
                        for f in findings:
                            f["field"] = key
                        all_findings.extend(findings)
                    new_list.append(redacted_item)
                else:
                    new_list.append(item)
            if changed:
                out[key] = new_list
    return out, all_findings


def redact_sections(sections: Dict[str, str]) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Same contract as `redact_frontmatter()`, over a note body's section
    dict (see memory_vault.MEMORY_NOTE_BODY_SECTIONS) -- findings carry
    `field` as `"section:<Section Name>"`."""
    out = dict(sections)
    all_findings: List[Dict[str, Any]] = []
    for name, content in sections.items():
        if not isinstance(content, str):
            continue
        redacted, findings = redact_secrets(content)
        if findings:
            out[name] = redacted
            for f in findings:
                f["field"] = f"section:{name}"
            all_findings.extend(findings)
    return out, all_findings


# Structural/identity keys on a JSON MemoryStore / CornerCaseLibrary record,
# never scanned by `redact_record()` -- the same reasoning as
# `_FRONTMATTER_SKIP_KEYS` above, applied to the record shape
# `MemoryStore.add()` actually writes: none of them can hold free text a
# secret could hide in, and rewriting `memory_id`/`ccl_id` would break the
# identity every upsert, index row and vault-note id keys on. Matched at any
# nesting depth, because these names mean the same thing wherever they appear
# in this schema (e.g. a nested `provenance` block's own `created_at`).
_RECORD_SKIP_KEYS = {
    "memory_id", "ccl_id", "level", "created_at", "updated_at", "last_used_at",
    "reuse_count", "confidence", "status", "confirmation_count",
    "last_confirmed_at", "knowledge_commit_sha", "rtl_sha", "tb_sha",
    "revalidate_by", "secrets_redacted", "secrets_redacted_types",
}


def redact_record(record: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Recursively redact every free-text string in a JSON memory record --
    the counterpart of `redact_note_content()` for the durable JSON store
    rather than the Markdown mirror. Returns (redacted_copy, findings).

    Recursion is required, not decorative: the real records this repo writes
    nest genuinely free-form text several levels down -- a job-tier record's
    `prior_related_knowledge` is a LIST of related-case dicts each carrying
    note titles/frontmatter, an engineering record's `evidence` is an
    arbitrary caller-supplied dict or list, and a working-memory
    react-reasoning step carries hypothesis/evidence/next-action prose. A
    top-level-only scan would miss every one of them.

    Each finding carries a dotted `field` path (`prior_related_knowledge[0].
    frontmatter.title`) on top of `detect_secrets()`'s type/line/preview, so
    a reader can find exactly where the secret was without the finding itself
    ever quoting the secret.
    """
    findings: List[Dict[str, Any]] = []
    return _redact_mapping(record, "", findings), findings


def _redact_mapping(mapping: Dict[str, Any], prefix: str,
                     findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in mapping.items():
        if key in _RECORD_SKIP_KEYS:
            out[key] = value
            continue
        out[key] = _redact_any(value, f"{prefix}.{key}" if prefix else str(key), findings)
    return out


def _redact_any(value: Any, path: str, findings: List[Dict[str, Any]]) -> Any:
    if isinstance(value, str):
        redacted, found = redact_secrets(value)
        for f in found:
            f["field"] = path
        findings.extend(found)
        return redacted
    if isinstance(value, dict):
        return _redact_mapping(value, path, findings)
    if isinstance(value, (list, tuple)):
        return [_redact_any(v, f"{path}[{i}]", findings) for i, v in enumerate(value)]
    return value


def redact_note_content(frontmatter: Dict[str, Any],
                         sections: Dict[str, str] = None) -> Tuple[Dict[str, Any], Dict[str, str], List[Dict[str, Any]]]:
    """Convenience wrapper combining `redact_frontmatter()` +
    `redact_sections()` -- the single call memory_vault.py's create()/
    update() actually make before writing any content to disk."""
    fm_out, fm_findings = redact_frontmatter(frontmatter)
    if sections:
        sections_out, sec_findings = redact_sections(sections)
    else:
        sections_out, sec_findings = sections, []
    return fm_out, sections_out, fm_findings + sec_findings
