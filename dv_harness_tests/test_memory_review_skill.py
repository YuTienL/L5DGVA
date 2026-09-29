"""Tests for `.claude/skills/CORE/memory-review/SKILL.md` -- the skill that
covers `dv_harness/memory_doctor.py` and the `dv-harness memory validate` /
`dv-harness memory doctor` subcommands (Phase 16 of the Obsidian+Git/Markdown
Hybrid Engineering Memory spec).

These are NOT parse tests. Every claim the skill makes about the code is
re-derived from the real code on every run: the two check lists are compared
against the keys `run_validate()`/`run_doctor()` really return for a real
vault on disk, the documented statuses against the statuses those checks
really emit, and the two CLI subcommands are driven as real subprocesses
against a real temp project root (asserting the documented JSON shape and the
documented exit-code rule). A skill that drifts from the code it teaches is
worse than no skill, so the drift is a test failure rather than something a
reader has to notice.

Same doc-held-to-code discipline as `dv_harness/mcp/claude_md_index.py` and
`source_authority.assert_doc_matches_code()`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import memory_doctor as doctor
from dv_harness import memory_vault as mv

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "CORE" / "memory-review" / "SKILL.md"
AGENT_PATH = REPO_ROOT / ".claude" / "agents" / "memory-agent.md"

# The nine sections every memory skill in this tree carries; taken from the
# siblings this one was written to match, not from a style guide.
SIBLING_SKILLS = [
    REPO_ROOT / ".claude" / "skills" / "CORE" / "memory-link" / "SKILL.md",
    REPO_ROOT / ".claude" / "skills" / "CORE" / "memory-gc" / "SKILL.md",
    REPO_ROOT / ".claude" / "skills" / "CORE" / "memory-retrieval" / "SKILL.md",
]
_SECTION_RE = re.compile(r"^\*\*([A-Za-z /]+)\*\*:", re.MULTILINE)


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _anchored_check_names(text: str, anchor: str) -> list:
    """Every ``- `name` --`` list item between <!-- anchor --> markers."""
    block = re.search(rf"<!-- {anchor} -->(.*?)<!-- /{anchor} -->", text, re.DOTALL)
    assert block is not None, f"SKILL.md lost its <!-- {anchor} --> block"
    return re.findall(r"^- `([a-z_]+)`", block.group(1), re.MULTILINE)


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _rmtree(path: Path) -> None:
    def _on_rm_error(func, p, exc_info):
        import os as _os, stat as _stat
        _os.chmod(p, _stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=_on_rm_error, ignore_errors=True)


def _vault_path(tmp: Path) -> Path:
    return tmp / ".dv-harness" / "vault"


def _complete_note_fm(note_id: str) -> dict:
    return {"id": note_id, "memory_level": "engineering", "protocol": "USB",
            "status": "ACTIVE", "confidence": "HIGH"}


def _write_note(tmp: Path, frontmatter: dict) -> dict:
    adapter = mv.FileSystemMarkdownAdapter(_vault_path(tmp), git_enabled=False)
    return adapter.create(frontmatter, sections={s: "-" for s in mv.MEMORY_NOTE_BODY_SECTIONS})


def _run_cli(project_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dv_harness", "--project-root", str(project_root), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)


def _cli_json(proc: subprocess.CompletedProcess) -> dict:
    """The CLI prints a banner line or two before the JSON payload."""
    start = proc.stdout.index("{")
    return json.loads(proc.stdout[start:])


# --- the skill exists and is bound ------------------------------------------

def test_skill_file_exists_and_declares_its_own_name():
    text = _skill_text()
    assert text.startswith("---\n")
    assert re.search(r"^name: memory-review$", text, re.MULTILINE)


def test_skill_is_bound_to_the_memory_agent():
    agent = AGENT_PATH.read_text(encoding="utf-8")
    skills_block = agent.split("---")[1]
    assert "CORE/memory-review" in skills_block, "memory-agent.md's `skills:` list does not bind memory-review"
    # And the agent's prose actually routes a responsibility to it, rather
    # than binding a skill nothing tells the agent when to use.
    assert "memory-review" in agent.split("## Responsibilities", 1)[1]


def test_skill_carries_the_same_nine_sections_as_its_sibling_memory_skills():
    mine = set(_SECTION_RE.findall(_skill_text()))
    for sibling in SIBLING_SKILLS:
        expected = set(_SECTION_RE.findall(sibling.read_text(encoding="utf-8")))
        assert expected <= mine, f"missing section(s) {sorted(expected - mine)} that {sibling.name} carries"


# --- the documented check lists are the REAL check lists --------------------

def test_documented_validate_checks_equal_real_run_validate_keys():
    tmp = _tmp()
    try:
        mv.bootstrap_vault(_vault_path(tmp))
        real = list(doctor.run_validate(tmp, cfg={})["checks"].keys())
        assert _anchored_check_names(_skill_text(), "validate-checks") == real
    finally:
        _rmtree(tmp)


def test_documented_doctor_checks_equal_real_run_doctor_keys():
    tmp = _tmp()
    try:
        mv.bootstrap_vault(_vault_path(tmp))
        real = list(doctor.run_doctor(tmp, cfg={})["checks"].keys())
        documented = _anchored_check_names(_skill_text(), "doctor-checks")
        assert documented == real
        assert len(documented) == 11, "the skill's own '11 in total' claim"
    finally:
        _rmtree(tmp)


def test_validate_is_really_the_documented_subset_of_doctor():
    tmp = _tmp()
    try:
        mv.bootstrap_vault(_vault_path(tmp))
        v = set(doctor.run_validate(tmp, cfg={})["checks"])
        d = set(doctor.run_doctor(tmp, cfg={})["checks"])
        assert v < d and len(d - v) == 6, "the skill claims 5 correctness checks + 6 environment/store checks"
    finally:
        _rmtree(tmp)


# --- the documented Fallback states are real, not aspirational --------------

def test_git_disabled_and_obsidian_partial_do_not_block_a_healthy_vault():
    """The skill's Fallback section claims both are non-defects and that an
    honest empty vault is therefore PARTIAL, never BLOCKED."""
    tmp = _tmp()
    try:
        mv.bootstrap_vault(_vault_path(tmp))
        result = doctor.run_doctor(tmp, cfg={})
        assert result["checks"]["git"]["status"] == "DISABLED"
        assert "git" not in result["blocked_reasons"] and "git" not in result["partial_reasons"]
        assert result["overall"] != "BLOCKED"
    finally:
        _rmtree(tmp)


def test_every_status_a_real_check_emits_is_one_the_skill_documents():
    """A vault carrying a schema-PARTIAL note, a broken wiki-link and a
    duplicate id -- so PARTIAL and BLOCKED are both really produced, not just
    the happy path."""
    tmp = _tmp()
    try:
        mv.bootstrap_vault(_vault_path(tmp))
        fm = _complete_note_fm("MEM-AAAAAAAAAA")
        del fm["confidence"]
        _write_note(tmp, fm)
        adapter = mv.FileSystemMarkdownAdapter(_vault_path(tmp), git_enabled=False)
        adapter.create(_complete_note_fm("MEM-BBBBBBBBBB"),
                       sections={"Related Knowledge": "- [[MEM-DOESNOTEXIST]]"})
        # A duplicate id create() refuses, so the second copy is placed as a
        # real file in another tier's folder -- exactly the hand-dropped case
        # check_duplicate_ids() exists to catch.
        src = next(_vault_path(tmp).rglob("MEM-BBBBBBBBBB.md"))
        dup = _vault_path(tmp) / "06_Agent_Memory" / "dup_MEM-BBBBBBBBBB.md"
        dup.parent.mkdir(parents=True, exist_ok=True)
        dup.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        result = doctor.run_doctor(tmp, cfg={})
        emitted = {c["status"] for c in result["checks"].values()} | {result["overall"]}
        documented = set(re.findall(r"`(READY|PARTIAL|BLOCKED|DISABLED)`", _skill_text()))
        assert emitted <= documented, f"undocumented status(es): {sorted(emitted - documented)}"
        assert {"PARTIAL", "BLOCKED"} <= emitted, "the crafted defects did not actually reproduce"
        assert result["overall"] == "BLOCKED", "the skill's BLOCKED-trumps-PARTIAL aggregation claim"
        assert result["checks"]["schema"]["partial"][0]["missing_required"] == ["confidence"]
        assert result["checks"]["broken_links"]["notes_with_broken_links"][0]["broken_links"] == \
            ["MEM-DOESNOTEXIST"]
    finally:
        _rmtree(tmp)


# --- the two CLI subcommands the skill names really run ---------------------

@pytest.mark.parametrize("subcommand,anchor", [("validate", "validate-checks"), ("doctor", "doctor-checks")])
def test_cli_subcommand_runs_and_returns_the_documented_checks(subcommand, anchor):
    tmp = _tmp()
    try:
        mv.bootstrap_vault(_vault_path(tmp))
        proc = _run_cli(tmp, "memory", subcommand)
        assert proc.returncode == 0, proc.stderr
        payload = _cli_json(proc)
        assert list(payload["checks"].keys()) == _anchored_check_names(_skill_text(), anchor)
        assert payload["overall"] in ("READY", "PARTIAL", "BLOCKED")
    finally:
        _rmtree(tmp)


def test_cli_exits_nonzero_only_on_blocked_as_the_skill_documents():
    tmp = _tmp()
    try:
        mv.bootstrap_vault(_vault_path(tmp))
        assert _run_cli(tmp, "memory", "doctor").returncode == 0

        adapter = mv.FileSystemMarkdownAdapter(_vault_path(tmp), git_enabled=False)
        adapter.create(_complete_note_fm("MEM-CCCCCCCCCC"),
                       sections={s: "-" for s in mv.MEMORY_NOTE_BODY_SECTIONS})
        src = next(_vault_path(tmp).rglob("MEM-CCCCCCCCCC.md"))
        dup = _vault_path(tmp) / "06_Agent_Memory" / "dup_MEM-CCCCCCCCCC.md"
        dup.parent.mkdir(parents=True, exist_ok=True)
        dup.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        proc = _run_cli(tmp, "memory", "doctor")
        assert _cli_json(proc)["overall"] == "BLOCKED"
        assert proc.returncode == 1
    finally:
        _rmtree(tmp)


# --- the code entry points / constants the skill cites by name are real -----

def test_every_code_symbol_the_skill_cites_actually_exists():
    text = _skill_text()
    for name in ("run_validate", "run_doctor", "check_git", "_aggregate"):
        assert f"`{name}(" in text or f"`{name}()`" in text
        assert hasattr(doctor, name), f"memory_doctor.{name} does not exist"
    for name in ("validate_note", "validate_note_frontmatter", "validate_note_body_sections",
                 "resolve_vault_path", "detect_obsidian_cli"):
        assert name in text
        assert hasattr(mv, name), f"memory_vault.{name} does not exist"
    documented_required = re.findall(r"`(id|memory_level|protocol|status|confidence|created|updated)`",
                                     text.split("MEMORY_NOTE_REQUIRED_FIELDS", 1)[1].split("\n\n", 1)[0])
    assert set(documented_required) == set(mv.MEMORY_NOTE_REQUIRED_FIELDS)
