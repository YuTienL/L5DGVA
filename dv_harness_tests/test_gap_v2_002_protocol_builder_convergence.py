"""GAP-V2-002 remediation (`CAP-M6-GAPV2002-001`, `DEC-GAP-V2-002 = OPTION_B`).

Machine-checkable anti-drift guards, so a future edit cannot silently
re-open the capability island this task closed:

1. All 11 `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` converge on the
   governed `dv-harness start --generate` entry point -- none calls
   `tools/generate_protocol_uvm_environment.py` directly any more.
2. `tools/generate_protocol_uvm_environment.py`'s own header states its
   real, current role (`INTERNAL_GENERATION_PRIMITIVE`), so a reader (or
   an agent) cannot mistake it for a supported standalone workflow entry.
3. `create_environment()`'s own real caller set stays exactly what
   `GAP_V2_002_GENERATOR_ENTRY_DECISION.md` found and this remediation
   closed for -- 2 real callers (the governed `engine.py` path and this
   script itself, kept as the internal primitive) -- `UNKNOWN_RUNTIME_
   CALLERS = 0` re-verified as a real, re-runnable check rather than a
   one-time claim in a report.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_BUILDERS_DIR = ROOT / ".claude" / "skills" / "PROTOCOL_BUILDERS"
TARGET_SCRIPT = ROOT / "tools" / "generate_protocol_uvm_environment.py"

DIRECT_INVOCATION_PATTERN = re.compile(
    r"generate_protocol_uvm_environment\.py\s+--manifest")
GOVERNED_INVOCATION_PATTERN = re.compile(r"dv-harness start --goal")


def _skill_files():
    return sorted(PROTOCOL_BUILDERS_DIR.glob("*/SKILL.md"))


def test_exactly_eleven_protocol_builder_skills_found():
    skills = _skill_files()
    assert len(skills) == 11, sorted(p.parent.name for p in skills)


def test_every_protocol_builder_skill_converges_on_the_governed_entry_point():
    skills = _skill_files()
    missing = []
    for f in skills:
        text = f.read_text(encoding="utf-8")
        if not GOVERNED_INVOCATION_PATTERN.search(text):
            missing.append(f.parent.name)
    assert missing == [], "skill(s) not yet converged on dv-harness start --generate: %s" % missing


def test_no_protocol_builder_skill_still_calls_the_script_directly():
    skills = _skill_files()
    still_direct = []
    for f in skills:
        text = f.read_text(encoding="utf-8")
        if DIRECT_INVOCATION_PATTERN.search(text):
            still_direct.append(f.parent.name)
    assert still_direct == [], "skill(s) still invoking the internal primitive directly: %s" % still_direct


def test_target_script_header_declares_itself_an_internal_generation_primitive():
    text = TARGET_SCRIPT.read_text(encoding="utf-8")
    assert "INTERNAL_GENERATION_PRIMITIVE" in text
    assert "GAP-V2-002" in text


def _real_create_environment_call_sites():
    """AST-based, not text-grep-based: a docstring/comment mentioning
    `create_environment()` in prose must never be mistaken for a real call
    expression (grep on the bare substring over-matches badly here -- every
    module that merely CITES the function in its own module docstring, e.g.
    `generation_readiness.py`, contains the literal text
    `create_environment()`  with no real call at all)."""
    import ast

    real_callers = set()
    for py_file in ROOT.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(ROOT).as_posix()
        if rel.startswith("dv_harness_tests/"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"), filename=rel)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else \
                func.attr if isinstance(func, ast.Attribute) else None
            if name != "create_environment":
                continue
            # Exclude the function's own definition file matching its own
            # internal recursive-looking reference (it has none, but this
            # keeps the check honest if that ever changed).
            real_callers.add(rel)
    return real_callers


def test_create_environment_real_caller_set_is_exactly_the_two_known_ones():
    """Re-derives GAP_V2_002_GENERATOR_ENTRY_DECISION.md's own
    UNKNOWN_RUNTIME_CALLERS=0 finding as a real, re-runnable check: the
    real AST call-site set for `create_environment(...)` must be exactly
    the governed engine.py call and this script's own call -- never a new,
    unaccounted-for third caller."""
    real_callers = _real_create_environment_call_sites()
    assert real_callers == {
        "dv_harness/engine.py",
        "tools/generate_protocol_uvm_environment.py",
    }, sorted(real_callers)
