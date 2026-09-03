"""dv_harness/context_budget.py -- the 3-tier context budget, as enforced
code rather than an aspiration.

The rule this module implements (three tiers, in the user's own terms):

  Tier 1  NEVER into context   -- VIP source full text, raw PDF originals,
                                  whole-chip design/waveform/evidence
                                  databases, complete regression logs.
  Tier 2  ALWAYS resident      -- a small, bounded set of generated fact
                                  artifacts (CLAUDE.md index,
                                  env.manifest.json, run_profile.json,
                                  hierarchy.json, phy_boundary.json).
  Tier 3  LOAD ON DEMAND       -- distilled per-protocol VIP references,
                                  the verification-intent statement, and
                                  single-register regmap lookups.

Why this module exists (audit finding, 2026-09-03): the 3-tier text existed
NOWHERE in this repo except inside a workflow prompt, and nothing enforced
it. `.claude/settings.json`'s only PreToolUse hook (block-destructive.ps1)
matches `Bash|PowerShell` and inspects the command for destructive patterns
-- it never fires on `Read` and never looks at WHAT is being read. There was
no `.claudeignore`. Meanwhile `.claude/settings.local.json`'s own allow
history documented real, repeated tier-1 violations: `pdftotext -layout
".../usb_svt_uvm_user_guide.pdf"`, `sed -n "24320,24350p" $M` against a live
`sim.log`, `grep -h ss_vout_model .../sim.log`, plus blanket
`Read(//d/DV/Task/VIP/**)`. The MCP interface (dv_harness/mcp/verbs.py, 5
fixed verbs, no free-text fallback) was a real and well-built OPTION, but
never a GATE -- nothing stopped, warned on, or logged a Read/Bash/Grep that
bypassed it.

What actually closes that:

  * POLICY AS DATA -- context_budget.policy.json (validated against
    schemas/context_budget.schema.json) holds the tiers. A project extends
    its own DUT/VIP roots there, not by editing this file.
  * A REAL DENY -- evaluate_tool_call() consumes a Claude Code PreToolUse
    payload and returns a deny decision for a tier-1 read.
    .claude/hooks/context-budget-guard.ps1 pipes the hook's stdin straight
    into `python -m dv_harness.context_budget hook`, and settings.json
    registers it for `Read|Grep|Glob|Bash|PowerShell`. That is the gate the
    audit said did not exist.
  * A REAL RESIDENCY MECHANISM -- build_resident_pack()/render_resident_pack()
    emit the bounded tier-2 bundle, and
    .claude/hooks/context-resident-pack.ps1 injects it via SessionStart
    `hookSpecificOutput.additionalContext`. Before this, "always resident"
    was true of exactly one artifact (CLAUDE.md) and only because the agent
    harness auto-loads project CLAUDE.md -- an accident of the tool, not a
    property this project engineered.

Honest limits, stated rather than papered over:

  * Deny-by-path is only as good as the path being literal in the tool
    call. `sed -n "1,50p" $M` where `$M` was assigned earlier cannot be
    classified, because at PreToolUse time the shell has not expanded it.
    command_patterns in the policy catch the common literal-filename
    shapes; a variable-indirected read still gets through. This is a
    reduction in bypass surface, not a proof of impossibility, and the
    module says so rather than claiming a seal.
  * A denial is never a dead end: every tier-1 rule must carry an
    mcp_redirect verb and/or a distiller script, and the deny reason names
    them. A gate with no route forward would just get disabled.
  * MISSING tier-2 artifacts are reported as MISSING with the real command
    that would produce them. Two of the five (hierarchy.json,
    phy_boundary.json) have no non-agent extractor in this repo at all;
    the pack says exactly that instead of pretending the slot is filled.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA_VERSION = "1.0"
POLICY_PATH = Path(__file__).resolve().parent / "context_budget.policy.json"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "context_budget.schema.json"

TIER_NEVER = "never_load"
TIER_RESIDENT = "always_resident"
TIER_ON_DEMAND = "load_on_demand"
TIER_UNCLASSIFIED = "unclassified"

#: Tool names whose payload can pull file CONTENT into the context window.
#: Glob is deliberately absent: it returns file NAMES, which are cheap, and
#: denying a directory listing would be a false positive that gets the whole
#: gate switched off.
READ_LIKE_TOOLS = ("Read", "Grep", "NotebookRead")
#: Tool names whose payload is a shell command string.
COMMAND_TOOLS = ("Bash", "PowerShell", "BashOutput")

#: Hard cap on the whole rendered resident pack. Tier 2 is only meaningful
#: if it is bounded -- an unbounded "always resident" set is just tier 1
#: with extra steps.
MAX_PACK_BYTES = 24_000


class ContextBudgetPolicyError(ValueError):
    """The policy document is not schema-valid. Raised (never swallowed)
    so a malformed policy fails loudly at load time instead of silently
    degrading into a permit-everything gate -- the same fail-closed
    discipline as EnvManifestValidationError/RunProfileValidationError."""


# ---------------------------------------------------------------------------
# policy loading
# ---------------------------------------------------------------------------

def validate_policy(policy: dict) -> None:
    """Validate `policy` against context_budget.schema.json. Raises
    ContextBudgetPolicyError on any violation."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise ContextBudgetPolicyError(
            "jsonschema package is not installed; cannot validate "
            "context_budget.policy.json. Install it rather than skipping validation."
        ) from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(policy), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
                 for e in errors]
        raise ContextBudgetPolicyError(
            "context_budget.schema.json validation failed:\n" + "\n".join(lines))


def load_policy(path=None, *, validate: bool = True) -> dict:
    """Load the context-budget policy from `path` (default: the shipped
    context_budget.policy.json) and validate it."""
    p = Path(path) if path is not None else POLICY_PATH
    policy = json.loads(p.read_text(encoding="utf-8"))
    if validate:
        validate_policy(policy)
    return policy


# ---------------------------------------------------------------------------
# path normalisation + glob matching
# ---------------------------------------------------------------------------

def normalise_path(raw: str) -> str:
    """Fold a path into the single canonical form the policy globs are
    written against: forward slashes, collapsed separators, lower case.

    Both halves matter on this project. Windows tool calls arrive as
    `D:\\DV\\Task\\USB\\VIP\\...`, git-bash ones as `/d/DV/Task/USB/VIP/...`
    and settings.json permission entries as `//d/DV/Task/USB/VIP/**` -- all
    three must classify identically, or the gate is trivially bypassed by
    choosing a different spelling of the same file."""
    s = str(raw).strip().strip('"').strip("'")
    s = s.replace("\\", "/")
    while "//" in s:
        s = s.replace("//", "/")
    return s.lower()


def _glob_to_regex(glob: str) -> re.Pattern:
    """Translate a policy glob to a regex. `**` spans directory
    separators, `*` and `?` do not. Written out rather than delegated to
    fnmatch because fnmatch's `*` DOES span `/`, which would make
    `**/vip/**/*.sv` and `*/vip/*.sv` mean the same thing and silently
    over-match."""
    out = ["^"]
    i = 0
    n = len(glob)
    while i < n:
        c = glob[i]
        if c == "*":
            if i + 1 < n and glob[i + 1] == "*":
                out.append(".*")
                i += 2
                # '**/' should also match zero directories: a/**/b ~ a/b
                if i < n and glob[i] == "/":
                    out.append("/?")
                    i += 1
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    out.append("$")
    return re.compile("".join(out))


_REGEX_CACHE: dict = {}


def path_matches(path: str, globs: Iterable[str]) -> Optional[str]:
    """Return the first glob in `globs` that matches `path`, else None.
    `path` is normalised here, so callers may pass a raw tool-call path."""
    norm = normalise_path(path)
    for g in globs or ():
        rx = _REGEX_CACHE.get(g)
        if rx is None:
            rx = _REGEX_CACHE[g] = _glob_to_regex(normalise_path(g))
        if rx.match(norm):
            return g
    return None


# ---------------------------------------------------------------------------
# tier classification
# ---------------------------------------------------------------------------

def _exempted(policy: dict, rule_id: str, path: str) -> Optional[dict]:
    for ex in policy.get("exemptions") or ():
        if ex.get("rule_id") != rule_id:
            continue
        if path_matches(path, [ex["path_glob"]]):
            return ex
    return None


def _artifact_hit(entries, path) -> Optional[dict]:
    norm = normalise_path(path)
    for art in entries or ():
        candidates = [art["path"], *(art.get("alt_paths") or ())]
        for cand in candidates:
            c = normalise_path(cand)
            # exact, suffix (absolute tool path ending in the repo-relative
            # path), or a prefix for directory-shaped artifacts like
            # docs/vip_ref.
            if norm == c or norm.endswith("/" + c) or norm.startswith(c + "/") \
                    or ("/" + c + "/") in norm:
                return art
    return None


def classify_path(path: str, policy: Optional[dict] = None) -> dict:
    """Classify one path into a tier.

    Returns {"tier", "path", "rule_id"|"artifact_id", "reason",
    "mcp_redirect", "distiller", "exemption"}. tier is one of TIER_NEVER /
    TIER_RESIDENT / TIER_ON_DEMAND / TIER_UNCLASSIFIED.

    TIER_UNCLASSIFIED is deliberate and is the common case: ordinary source
    files, tests and reports are neither budget-blowing nor budget-managed,
    and this module must not turn into a whole-repo read gate."""
    policy = policy if policy is not None else load_policy()
    for rule in policy["never_load"]:
        if path_matches(path, rule.get("allow_globs")):
            continue
        hit = path_matches(path, rule.get("path_globs"))
        if not hit:
            continue
        ex = _exempted(policy, rule["rule_id"], path)
        return {
            "tier": TIER_NEVER,
            "path": path,
            "rule_id": rule["rule_id"],
            "matched_glob": hit,
            "label": rule["label"],
            "reason": rule["reason"],
            "mcp_redirect": rule.get("mcp_redirect"),
            "distiller": rule.get("distiller"),
            "distiller_note": rule.get("distiller_note"),
            "exemption": ex,
        }
    art = _artifact_hit(policy["always_resident"], path)
    if art:
        return {"tier": TIER_RESIDENT, "path": path, "artifact_id": art["artifact_id"],
                "reason": art["purpose"], "mcp_redirect": art.get("mcp_verb"),
                "distiller": None, "exemption": None}
    art = _artifact_hit(policy["load_on_demand"], path)
    if art:
        return {"tier": TIER_ON_DEMAND, "path": path, "artifact_id": art["artifact_id"],
                "reason": art["purpose"], "mcp_redirect": art.get("mcp_verb"),
                "distiller": None, "exemption": None}
    return {"tier": TIER_UNCLASSIFIED, "path": path, "reason": "no context-budget rule applies",
            "mcp_redirect": None, "distiller": None, "exemption": None}


_TOKEN_RX = re.compile(r"""(?:"([^"]+)"|'([^']+)'|(\S+))""")

#: Commands that NAME a file without pulling its content into context.
#: `ls docs/*.pdf`, `find . -name '*.fsdb'` and `stat sim.log` cost nothing
#: and must not be denied -- a gate that blocks listing a directory is a
#: gate that gets switched off. Only honoured for a simple, single command
#: with no pipe/redirect/chaining, since `ls x && cat sim.log` is not an
#: `ls`.
NON_CONTENT_COMMANDS = frozenset({
    "ls", "dir", "find", "stat", "file", "du", "df", "basename", "dirname",
    "mkdir", "touch", "which", "test", "wc", "md5sum", "sha1sum", "sha256sum",
    "cygpath", "realpath", "chmod", "get-childitem", "get-item",
})
_CHAINING_RX = re.compile(r"[|;&><`]|\$\(")


def _is_non_content_command(cmd: str) -> bool:
    if _CHAINING_RX.search(cmd or ""):
        return False
    head = (cmd or "").strip().split()
    if not head:
        return False
    verb = head[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    return verb in NON_CONTENT_COMMANDS


def extract_command_paths(command: str) -> list:
    """Best-effort extraction of literal path-shaped tokens from a shell
    command string.

    Deliberately conservative: a token counts only if it contains a `/` or
    `\\` or has a file extension. It CANNOT resolve shell variables --
    `sed -n "1,50p" $M` yields nothing here, which is exactly the residual
    bypass the module docstring admits to. The policy's own
    command_patterns exist to catch the common literal-filename shapes that
    slip past this."""
    out = []
    for m in _TOKEN_RX.finditer(command or ""):
        tok = m.group(1) or m.group(2) or m.group(3) or ""
        if tok.startswith("-") or "$" in tok or "%" in tok:
            continue
        if "/" in tok or "\\" in tok or re.search(r"\.[A-Za-z0-9]{1,8}$", tok):
            out.append(tok.rstrip(";|&,)"))
    return out


def classify_command(command: str, policy: Optional[dict] = None) -> dict:
    """Classify a shell command string: first any policy command_pattern
    regex hit, then the tier of every literal path-shaped token it names.
    Returns the same decision shape as classify_path(), with tier
    TIER_NEVER as soon as one component is tier 1."""
    policy = policy if policy is not None else load_policy()
    cmd = command or ""
    for rule in policy["never_load"]:
        for pat in rule.get("command_patterns") or ():
            if re.search(pat, cmd):
                return {
                    "tier": TIER_NEVER, "path": None, "rule_id": rule["rule_id"],
                    "matched_command_pattern": pat, "label": rule["label"],
                    "reason": rule["reason"], "mcp_redirect": rule.get("mcp_redirect"),
                    "distiller": rule.get("distiller"),
                    "distiller_note": rule.get("distiller_note"),
                    "exemption": None,
                }
    if not _is_non_content_command(cmd):
        for tok in extract_command_paths(cmd):
            d = classify_path(tok, policy)
            if d["tier"] == TIER_NEVER:
                return d
    return {"tier": TIER_UNCLASSIFIED, "path": None,
            "reason": "no context-budget rule applies to this command",
            "mcp_redirect": None, "distiller": None, "exemption": None}


# ---------------------------------------------------------------------------
# the PreToolUse decision
# ---------------------------------------------------------------------------

def _deny_reason(d: dict, policy: dict) -> str:
    parts = [
        f"CONTEXT BUDGET tier-1 (NEVER into context) violation: {d['rule_id']} "
        f"-- {d['label']}.",
        d["reason"],
    ]
    if d.get("path"):
        parts.append(f"Blocked target: {d['path']}")
    if d.get("mcp_redirect"):
        parts.append(
            f"Use the fixed MCP verb `{d['mcp_redirect']}` instead "
            f"({policy['mcp']['module']}; the 5 verbs are "
            f"{', '.join(policy['mcp']['verbs'])})."
        )
    if d.get("distiller"):
        parts.append(f"Or distil it first with {d['distiller']}, then read the distilled artifact.")
    elif d.get("distiller_note"):
        # Never send a denied agent hunting for a script nobody wrote.
        parts.append(d["distiller_note"])
    parts.append(
        "If this read is genuinely necessary, add a reasoned entry to "
        "`exemptions` in dv_harness/context_budget.policy.json -- do not "
        "re-try the same call.")
    return " ".join(parts)


def evaluate_tool_call(tool_name: str, tool_input: Optional[dict] = None,
                       policy: Optional[dict] = None) -> dict:
    """The gate. Given a PreToolUse tool name + input, return
    {"decision": "allow"|"deny", "tier", "reason", ...}.

    Only READ_LIKE_TOOLS and COMMAND_TOOLS are inspected -- an Edit/Write
    is a different concern (settings.json's deny rules and
    block-destructive.ps1 already cover the protected RTL roots) and a
    context budget has nothing to say about it.

    An exempted tier-1 match returns decision "allow" with tier still
    reported as TIER_NEVER and the exemption attached, so the audit trail
    records that the rule fired and was consciously waived."""
    policy = policy if policy is not None else load_policy()
    tool_input = tool_input or {}

    if tool_name in READ_LIKE_TOOLS:
        target = (tool_input.get("file_path") or tool_input.get("path")
                  or tool_input.get("notebook_path") or "")
        if not target:
            return {"decision": "allow", "tier": TIER_UNCLASSIFIED,
                    "reason": f"{tool_name} call names no path to classify"}
        d = classify_path(target, policy)
    elif tool_name in COMMAND_TOOLS:
        d = classify_command(tool_input.get("command") or "", policy)
    else:
        return {"decision": "allow", "tier": TIER_UNCLASSIFIED,
                "reason": f"{tool_name} cannot pull file content into context"}

    if d["tier"] == TIER_NEVER and not d.get("exemption"):
        return {"decision": "deny", "tier": TIER_NEVER,
                "rule_id": d["rule_id"], "reason": _deny_reason(d, policy),
                "mcp_redirect": d.get("mcp_redirect"), "distiller": d.get("distiller")}
    if d["tier"] == TIER_NEVER:
        return {"decision": "allow", "tier": TIER_NEVER, "rule_id": d["rule_id"],
                "exemption": d["exemption"],
                "reason": f"{d['rule_id']} matched but is exempted: {d['exemption']['reason']}"}
    return {"decision": "allow", "tier": d["tier"], "reason": d["reason"],
            "mcp_redirect": d.get("mcp_redirect")}


def hook_decision_payload(tool_name: str, tool_input: Optional[dict] = None,
                          policy: Optional[dict] = None) -> Optional[dict]:
    """Return the Claude Code PreToolUse hook JSON for a denial, or None
    when the call is allowed (a PreToolUse hook that wants to permit simply
    prints nothing and exits 0)."""
    decision = evaluate_tool_call(tool_name, tool_input, policy)
    if decision["decision"] != "deny":
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": decision["reason"],
    }}


# ---------------------------------------------------------------------------
# tier 2: the resident pack
# ---------------------------------------------------------------------------

def _summarise_json(doc: Any) -> str:
    """One line per top-level key: the shape of a fact file, not its
    content. Keeps a 2 MB manifest inside a 4 KB residency budget."""
    if isinstance(doc, dict):
        bits = []
        for k, v in doc.items():
            if isinstance(v, dict):
                bits.append(f"{k}{{{', '.join(list(v.keys())[:8])}}}")
            elif isinstance(v, list):
                bits.append(f"{k}[{len(v)}]")
            else:
                bits.append(f"{k}={v!r}" if len(repr(v)) < 40 else k)
        return "; ".join(bits)
    if isinstance(doc, list):
        return f"[{len(doc)} entries]"
    return str(doc)[:200]


def resolve_artifact(art: dict, root: Path) -> Optional[Path]:
    """First existing path among the artifact's canonical + alt paths."""
    for cand in [art["path"], *(art.get("alt_paths") or ())]:
        p = (root / cand)
        if p.exists():
            return p
    return None


def build_resident_pack(root=None, policy: Optional[dict] = None) -> dict:
    """Build the tier-2 always-resident bundle as structured data.

    Every declared tier-2 artifact appears in the result exactly once, with
    status PRESENT (plus a bounded summary) or MISSING (plus the real
    `produced_by` command). A MISSING artifact is reported, never omitted --
    the whole point is that "always resident" is checkable."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    policy = policy if policy is not None else load_policy()
    entries = []
    for art in policy["always_resident"]:
        found = resolve_artifact(art, root)
        entry = {
            "artifact_id": art["artifact_id"],
            "declared_path": art["path"],
            "purpose": art["purpose"],
            "residency": art.get("residency"),
            "mcp_verb": art.get("mcp_verb"),
        }
        if found is None:
            entry["status"] = "MISSING"
            entry["produced_by"] = art.get("produced_by", "")
        else:
            size = found.stat().st_size
            entry["status"] = "PRESENT"
            entry["resolved_path"] = str(found.relative_to(root)).replace("\\", "/")
            entry["bytes"] = size
            budget = art.get("max_resident_bytes", 4096)
            if found.suffix == ".json":
                try:
                    entry["summary"] = _summarise_json(
                        json.loads(found.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError) as exc:
                    entry["summary"] = f"<unreadable: {exc.__class__.__name__}>"
            elif size <= budget:
                entry["summary"] = f"{size} bytes, inlined by the reader on request"
            else:
                entry["summary"] = (f"{size} bytes -- exceeds this artifact's "
                                    f"{budget}-byte residency budget; read targeted sections")
        entries.append(entry)
    present = sum(1 for e in entries if e["status"] == "PRESENT")
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root).replace("\\", "/"),
        "artifacts": entries,
        "present_count": present,
        "declared_count": len(entries),
        "mcp": policy["mcp"],
        "never_load_rules": [
            {"rule_id": r["rule_id"], "label": r["label"],
             "mcp_redirect": r.get("mcp_redirect"), "distiller": r.get("distiller")}
            for r in policy["never_load"]
        ],
    }


def render_resident_pack(pack: dict, *, max_bytes: int = MAX_PACK_BYTES) -> str:
    """Render the pack as the markdown block injected into every session's
    context by the SessionStart hook. Truncated (with a visible marker) at
    `max_bytes` -- a residency mechanism that can grow without bound is
    itself a context-budget bug."""
    L = [
        "## Context Budget (3 tiers) -- resident pack",
        "",
        f"Policy: dv_harness/context_budget.policy.json | "
        f"tier-2 artifacts present {pack['present_count']}/{pack['declared_count']}",
        "",
        "### Tier 1 -- NEVER read these into context (enforced: PreToolUse deny)",
    ]
    for r in pack["never_load_rules"]:
        route = r.get("mcp_redirect") or r.get("distiller") or "distil first"
        L.append(f"- {r['rule_id']}: {r['label']} -> use `{route}`")
    L += ["", "### Tier 2 -- always resident"]
    for e in pack["artifacts"]:
        if e["status"] == "PRESENT":
            L.append(f"- {e['artifact_id']} PRESENT ({e['resolved_path']}, "
                     f"{e['bytes']} B): {e.get('summary', '')}")
        else:
            L.append(f"- {e['artifact_id']} MISSING (declared {e['declared_path']}) "
                     f"-- produce with: {e.get('produced_by', 'n/a')}")
    L += ["", "### Tier 3 -- load on demand, through the fixed MCP verbs",
          f"- {pack['mcp']['module']} verbs: {', '.join(pack['mcp']['verbs'])}",
          "- Anything not answered by those 5 verbs: read the distilled artifact, "
          "not the raw source.", ""]
    text = "\n".join(L)
    if len(text.encode("utf-8")) > max_bytes:
        cut = text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
        text = cut + "\n[... resident pack truncated at "
        text += f"{max_bytes} bytes by the context budget itself ...]\n"
    return text


def session_start_payload(root=None, policy: Optional[dict] = None) -> dict:
    """The Claude Code SessionStart hook JSON that makes tier 2 actually
    resident, via hookSpecificOutput.additionalContext."""
    pack = build_resident_pack(root, policy)
    return {"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": render_resident_pack(pack),
    }}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def read_hook_stdin() -> str:
    """Read the hook payload, tolerating a UTF-8 BOM.

    Windows PowerShell 5.1 prepends U+FEFF when it pipes a string into a
    native command, so `.claude/hooks/context-budget-guard.ps1` delivers
    '\\ufeff{"tool_name":...' -- which json.loads rejects, which fails the
    guard open on every single call. This was a real, silent
    never-fires bug found by running the hook end-to-end from PowerShell
    rather than only testing the Python entry point."""
    buf = getattr(sys.stdin, "buffer", None)
    if buf is not None:
        return buf.read().decode("utf-8-sig", "replace")
    return sys.stdin.read().lstrip("﻿")


def _cmd_hook(args) -> int:
    raw = read_hook_stdin()
    if not raw.strip():
        return 0
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return 0  # fail open on a payload shape we do not understand
    payload = hook_decision_payload(data.get("tool_name", ""),
                                    data.get("tool_input") or {})
    if payload is not None:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def _cmd_session_start(args) -> int:
    print(json.dumps(session_start_payload(args.root), ensure_ascii=False))
    return 0


def _cmd_classify(args) -> int:
    policy = load_policy()
    if args.command:
        d = classify_command(args.command, policy)
    else:
        d = classify_path(args.target, policy)
    print(json.dumps(d, indent=2, ensure_ascii=False))
    return 1 if d["tier"] == TIER_NEVER and not d.get("exemption") else 0


def _cmd_resident(args) -> int:
    pack = build_resident_pack(args.root)
    if args.json:
        print(json.dumps(pack, indent=2, ensure_ascii=False))
    else:
        print(render_resident_pack(pack))
    return 0 if pack["present_count"] == pack["declared_count"] else 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.context_budget",
        description="3-tier context budget: classify a path/command, emit the "
                    "PreToolUse deny for a tier-1 read, or build the tier-2 "
                    "resident pack.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("hook", help="Read a PreToolUse payload on stdin; print a "
                                    "deny JSON for a tier-1 read, nothing otherwise.")
    p.set_defaults(fn=_cmd_hook)

    p = sub.add_parser("session-start", help="Print the SessionStart hook JSON that "
                                             "injects the tier-2 resident pack.")
    p.add_argument("--root", default=None)
    p.set_defaults(fn=_cmd_session_start)

    p = sub.add_parser("classify", help="Classify one path (or --command) into a tier. "
                                        "Exit 1 when tier-1.")
    p.add_argument("target", nargs="?", default="")
    p.add_argument("--command", default=None, help="Classify a shell command string instead.")
    p.set_defaults(fn=_cmd_classify)

    p = sub.add_parser("resident", help="Report tier-2 artifact residency. Exit 2 when "
                                        "any declared artifact is MISSING.")
    p.add_argument("--root", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=_cmd_resident)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
