"""dv_harness/mcp/claude_md_index.py -- the CLAUDE.md MCP index, and the
doc/code non-drift check that keeps it honest.

WHY THIS MODULE EXISTS. CLAUDE.md's contract is "index + rules only, details
on demand": an agent reading it must learn WHICH questions this environment
can answer and WHERE to ask them, not the answers themselves. Before
2026-09-04 the file named the 5 verbs in one sentence inside the Context
Budget section (`## Context Budget: 3 Tiers + MCP-First Routing`) and
nothing else -- no per-verb "ask it when" routing, no statement of which
on-disk paths this server reads, and no statement of where the protocol
list actually comes from. An agent could learn that 5 verbs exist without
learning which one answers the question it currently has, which is the
whole point of an index.

The obvious fix -- write a nice paragraph -- creates the failure mode this
repo already names elsewhere (`source_authority.assert_doc_matches_code`):
prose that was true when written and silently rots the first time a verb,
a required argument or a query shape changes. So the index is PARSED and
compared against the real code on every test run:

  * the verb rows must be EXACTLY `verbs.VERBS` -- a 6th verb added to the
    code with no index row, or an index row for a verb that no longer
    exists, both fail;
  * each row's required arguments must equal that verb's real
    `schema.PARAM_SCHEMAS[verb]["required"]`;
  * the query shapes the `query_regression` row names must equal
    `regression_queries.QUERY_SHAPES`;
  * the read-only fact-source paths the section lists must equal the real
    code-owned paths (`context_budget.policy.json`'s declared manifest
    artifact, and `evidence_db.DB_PATH_PARTS`);
  * the `python -m ...` invocation the section prints must name a module
    that really exists and really accepts the flags shown.

WHAT THIS MODULE DOES NOT DO. It does not check that the section's PROSE is
good, and it deliberately does not require the section to be byte-identical
to a rendered template -- the wording stays hand-editable (several other
workstreams edit CLAUDE.md concurrently). Only the FACTS are pinned. It
also does not enumerate protocols: which protocols a given environment
actually contains is a manifest question, answered by calling
`get_vip_config` with no arguments, and inlining a protocol list into
CLAUDE.md would be exactly the "details, not index" bloat the file's own
contract forbids. `assert_index_matches_code()` enforces that too --
the section must ROUTE the protocol question to a verb, not answer it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import regression_queries, schema, verbs
from .errors import McpError

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The real markdown file this index lives in. `assert_index_matches_code()`
#: parses it, so the section can never silently drift from the code below.
DOC_PATH = REPO_ROOT / "CLAUDE.md"

#: Exact heading text the section is found by. Changing the heading without
#: changing this constant fails the check loudly rather than silently
#: skipping it -- a "the section vanished" bug is the one this catches.
INDEX_HEADING = "## MCP Query Interface: the 5 Verbs (index)"

#: The `python -m` module the section tells an agent to run, and the flags
#: it shows. Verified against server.py's real argparse.
SERVER_MODULE = "dv_harness.mcp.server"
SERVER_FLAGS = ("--manifest", "--evidence-db")

#: The verb that answers "which protocols/VIPs does this environment
#: actually contain". The section must route that question here rather than
#: inlining a protocol list (see this module's docstring).
PROTOCOL_ROUTING_VERB = "get_vip_config"


class ClaudeMdIndexError(McpError):
    """The CLAUDE.md MCP index section is missing, unparseable, or has
    drifted from the code it indexes. Carries the concrete mismatch in
    `detail` -- never a bare "docs are stale"."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ---- real, code-owned fact-source paths -------------------------------------

def evidence_db_rel_path() -> str:
    """`.dv-harness/evidence/evidence.duckdb`, read from
    `evidence_db.DB_PATH_PARTS` rather than retyped, so renaming the store
    breaks this check instead of quietly making CLAUDE.md wrong. Imported
    lazily: evidence_db pulls in duckdb-adjacent module state and this
    package's own import contract (see __init__.py) is that importing
    `dv_harness.mcp` never requires duckdb."""
    from dv_harness.evidence_db import DB_PATH_PARTS

    return "/".join(DB_PATH_PARTS)


def manifest_rel_path() -> str:
    """`.dv-harness/env.manifest.json`, read from the real context-budget
    policy's tier-2 always-resident declaration -- the one place in this
    repo that actually owns that path (env_manifest.py's CLI takes `--out`
    and hardcodes nothing)."""
    policy_path = REPO_ROOT / "dv_harness" / "context_budget.policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    for entry in policy.get("always_resident", []):
        path = entry.get("path", "")
        if path.endswith("env.manifest.json"):
            return path
    raise ClaudeMdIndexError(
        "NO_MANIFEST_ARTIFACT_IN_POLICY",
        {"policy_path": str(policy_path),
         "detail": "context_budget.policy.json declares no always-resident "
                   "env.manifest.json artifact, so this module has no "
                   "code-owned path to check CLAUDE.md against."})


def fact_source_paths() -> List[str]:
    """The two, and only two, on-disk sources this server ever reads."""
    return [manifest_rel_path(), evidence_db_rel_path()]


# ---- parsing ----------------------------------------------------------------

_TABLE_ROW = re.compile(r"^\|\s*`(?P<verb>[a-z_]+)`\s*\|(?P<when>[^|]*)\|(?P<args>[^|]*)\|\s*$")
_BACKTICKED = re.compile(r"`([^`]+)`")


def extract_section(text: str) -> str:
    """Returns the index section's own text (heading line through the line
    before the next `## ` heading). Raises rather than returning "" when the
    heading is absent -- a silently-empty section would make every
    downstream comparison vacuously pass."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(INDEX_HEADING):
            start = i
            break
    if start is None:
        raise ClaudeMdIndexError(
            "INDEX_SECTION_MISSING",
            {"heading": INDEX_HEADING, "doc": str(DOC_PATH)})
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def parse_index(text: str) -> dict:
    """Parses the facts out of the index section. Returns
    `{"verbs": {verb: [required args]}, "query_shapes": [...],
      "fact_source_paths": [...], "server_module": str|None,
      "server_flags": [...], "protocol_routing_verb": str|None}`.

    Prose is ignored on purpose -- only the pinned facts are extracted."""
    section = extract_section(text)
    parsed_verbs: Dict[str, List[str]] = {}
    query_shapes: List[str] = []
    for line in section.splitlines():
        m = _TABLE_ROW.match(line.strip())
        if not m:
            continue
        verb = m.group("verb")
        args_cell = m.group("args")
        required = [a for a in _BACKTICKED.findall(args_cell)]
        if verb == "query_regression":
            # This row names both the required arg and the fixed shapes; the
            # shapes are the trailing backticked tokens after the arg name.
            query_shapes = [a for a in required if a != "query_shape"]
            required = [a for a in required if a == "query_shape"]
        parsed_verbs[verb] = required

    fact_paths: List[str] = []
    server_module: Optional[str] = None
    server_flags: List[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- `"):
            first = _BACKTICKED.findall(stripped)
            if first and ("/" in first[0]) and not first[0].startswith("python "):
                fact_paths.append(first[0])
        # FIRST `python -m` line only. The section legitimately mentions a
        # second one further down (this module's own checker command), and
        # last-wins would silently check the wrong invocation.
        if server_module is None and "python -m " in stripped:
            mm = re.search(r"python -m ([A-Za-z0-9_.]+)", stripped)
            if mm:
                server_module = mm.group(1)
                server_flags = sorted(set(re.findall(r"--[a-z-]+", stripped)))

    # Routing is matched per PARAGRAPH, not per line: the sentence that
    # routes "which protocols exist" to a verb is hard-wrapped, so the word
    # and the verb it routes to routinely land on different lines.
    protocol_routing_verb: Optional[str] = None
    for para in re.split(r"\n\s*\n", section):
        if "protocol" not in para.lower():
            continue
        for token in _BACKTICKED.findall(para):
            if token in verbs.VERBS:
                protocol_routing_verb = token
                break
        if protocol_routing_verb is not None:
            break

    return {
        "verbs": parsed_verbs,
        "query_shapes": query_shapes,
        "fact_source_paths": fact_paths,
        "server_module": server_module,
        "server_flags": server_flags,
        "protocol_routing_verb": protocol_routing_verb,
    }


# ---- the check --------------------------------------------------------------

#: File suffixes a backticked token must end in to be treated as a
#: "details on demand" pointer that has to really exist. Deliberately narrow:
#: the fact-source paths (.json/.duckdb) are checked separately and may
#: legitimately not exist yet in a checkout with no generated environment,
#: whereas a .py/.md pointer that does not exist is always a dead citation.
_CITED_SUFFIXES = (".py", ".md")

_INLINE_CODE = re.compile(r"`([^`\n]+)`")


def cited_detail_paths(text: str) -> List[str]:
    """Repo-relative `.py`/`.md` paths the index points at for detail. The
    whole "index + rules only, details on demand" contract rests on those
    pointers resolving; a dead one turns the index into a dead end."""
    section = extract_section(text)
    found: List[str] = []
    for line in section.splitlines():
        for token in _INLINE_CODE.findall(line):
            token = token.strip()
            if "/" in token and token.endswith(_CITED_SUFFIXES) and " " not in token:
                found.append(token)
    return sorted(set(found))


def _required_params(verb: str) -> List[str]:
    return list(schema.PARAM_SCHEMAS[verb].get("required", []))


def _real_server_flags() -> List[str]:
    """The flags server.py's own argparse really defines, read out of its
    source rather than by importing it (importing server.py hard-requires
    the `mcp` transport SDK; this check must still run in an environment
    that has the core package but not the SDK)."""
    src = (REPO_ROOT / "dv_harness" / "mcp" / "server.py").read_text(encoding="utf-8")
    return sorted(set(re.findall(r'add_argument\("(--[a-z-]+)"', src)))


def check_index(text: Optional[str] = None) -> List[str]:
    """Returns a list of concrete, human-readable drift problems. Empty list
    means the CLAUDE.md index and the code agree."""
    if text is None:
        text = DOC_PATH.read_text(encoding="utf-8")
    parsed = parse_index(text)
    problems: List[str] = []

    documented = set(parsed["verbs"])
    real = set(verbs.VERBS)
    for missing in sorted(real - documented):
        problems.append(
            f"verb {missing!r} exists in verbs.VERBS but has no row in the "
            f"CLAUDE.md index -- an agent reading the index would never know to call it")
    for extra in sorted(documented - real):
        problems.append(
            f"CLAUDE.md indexes verb {extra!r}, which is not in verbs.VERBS "
            f"(valid: {sorted(real)})")

    for verb in sorted(documented & real):
        want = _required_params(verb)
        got = parsed["verbs"][verb]
        if sorted(got) != sorted(want):
            problems.append(
                f"verb {verb!r}: CLAUDE.md index shows required args {sorted(got)}, "
                f"schema.PARAM_SCHEMAS says {sorted(want)}")

    if "query_regression" in documented:
        want_shapes = sorted(regression_queries.QUERY_SHAPES)
        got_shapes = sorted(parsed["query_shapes"])
        if got_shapes != want_shapes:
            problems.append(
                f"query_regression: CLAUDE.md index names shapes {got_shapes}, "
                f"regression_queries.QUERY_SHAPES is {want_shapes}")

    want_paths = sorted(fact_source_paths())
    got_paths = sorted(set(parsed["fact_source_paths"]))
    if got_paths != want_paths:
        problems.append(
            f"read-only fact sources: CLAUDE.md index lists {got_paths}, "
            f"the code-owned paths are {want_paths}")

    if parsed["server_module"] != SERVER_MODULE:
        problems.append(
            f"server invocation: CLAUDE.md index names module "
            f"{parsed['server_module']!r}, expected {SERVER_MODULE!r}")
    else:
        # Built with split/join rather than `str.replace(".", "/")` on
        # purpose: test_mcp_read_only_boundary.py's AST scan forbids the
        # NAME `replace` anywhere under dv_harness/mcp/, because it cannot
        # tell a harmless `str.replace` from `Path.replace` -- a real
        # filesystem rename. Conforming to the conservative rule is correct
        # here; weakening the scanner to admit a string method would open a
        # hole for the real one.
        module_file = Path(REPO_ROOT, *SERVER_MODULE.split(".")).with_suffix(".py")
        if not module_file.is_file():
            problems.append(
                f"server invocation: CLAUDE.md index names `python -m {SERVER_MODULE}` "
                f"but {module_file} does not exist")

    real_flags = _real_server_flags()
    for flag in SERVER_FLAGS:
        if flag not in parsed["server_flags"]:
            problems.append(
                f"server invocation: CLAUDE.md index does not show the {flag} flag")
        if flag not in real_flags:
            problems.append(
                f"server invocation: {flag} is documented but server.py's argparse "
                f"defines only {real_flags}")
    for flag in parsed["server_flags"]:
        if flag not in real_flags:
            problems.append(
                f"server invocation: CLAUDE.md index shows flag {flag}, which "
                f"server.py's argparse does not define (defines {real_flags})")

    cited = cited_detail_paths(text)
    if not cited:
        problems.append(
            "the index cites no `.py`/`.md` detail document at all -- an index "
            "whose 'details on demand' point nowhere is a dead end")
    for rel in cited:
        if not (REPO_ROOT / rel).exists():
            problems.append(
                f"dead citation: the index points at {rel!r} for detail, but "
                f"{REPO_ROOT / rel} does not exist")

    if parsed["protocol_routing_verb"] != PROTOCOL_ROUTING_VERB:
        problems.append(
            "the index must ROUTE 'which protocols exist' to "
            f"`{PROTOCOL_ROUTING_VERB}` rather than inlining a protocol list "
            f"(found routing verb: {parsed['protocol_routing_verb']!r})")

    return problems


def assert_index_matches_code(text: Optional[str] = None) -> None:
    """Raises `ClaudeMdIndexError` listing every drift problem, or returns
    None when the CLAUDE.md index and the code agree."""
    problems = check_index(text)
    if problems:
        raise ClaudeMdIndexError(
            "CLAUDE_MD_MCP_INDEX_DRIFT",
            {"doc": str(DOC_PATH), "heading": INDEX_HEADING, "problems": problems})


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m dv_harness.mcp.claude_md_index` -- prints OK or every
    concrete drift problem, exit 0 / 1."""
    try:
        problems = check_index()
    except ClaudeMdIndexError as exc:
        print(f"CLAUDE.md MCP index: {exc.reason} {exc.detail}")
        return 1
    if not problems:
        print(f"CLAUDE.md MCP index OK -- {len(verbs.VERBS)} verbs, "
              f"{len(regression_queries.QUERY_SHAPES)} query shapes, "
              f"{len(fact_source_paths())} read-only fact sources, all match the code.")
        return 0
    print(f"CLAUDE.md MCP index DRIFT ({len(problems)} problem(s)):")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
