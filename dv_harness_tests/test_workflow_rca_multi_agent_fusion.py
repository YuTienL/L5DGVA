"""Structural validation for .claude/workflows/rca-multi-agent-fusion.js.

This is a Workflow-tool script (plain JS run by the Workflow tool's own
runtime), not a Python module -- it cannot have ordinary pytest unit tests
that import and execute it (no filesystem/Node API access inside the script,
and the agent()/parallel()/phase() hooks only exist inside a live Workflow
run). What CAN be verified here, statically, from the repo's own Python test
suite:

  1. The file is syntactically valid JS (via `node --check`, skipped if node
     is not installed in this environment).
  2. `export const meta = {...}` exists with the required `name`/`description`
     fields, and every `meta.phases[].title` has a matching `phase('...')`
     call in the script body (and vice versa) -- a mismatch there is exactly
     the kind of drift the workflow-authoring skill warns about.
  3. Every `agentType: '<name>'` string the script references names a real,
     existing `.claude/agents/<name>.md` file -- this script must not
     silently depend on an agent persona that was never actually created.
  4. The Blackboard topic name and the `dv-harness ... blackboard write/read`
     CLI invocation the script's prompts instruct agents to run are real:
     the topic is 'rca_evidence_fusion' consistently, and the `blackboard`
     CLI subcommand this script depends on actually exists in
     dv_harness/cli.py (see test_cli_blackboard.py for that subcommand's own
     functional tests).

End-to-end execution (an actual live Workflow run against a real failure,
fanning the agents out for real and confirming a real
`.dv-harness/blackboard/rca_evidence_fusion.json` appears) was NOT performed
by this task -- that requires a live multi-agent Workflow run, which this
offline implementation pass cannot itself invoke. A future session should
try it end-to-end on a real REAL_ISSUE-classified failure.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".claude" / "workflows" / "rca-multi-agent-fusion.js"
AGENTS_DIR = ROOT / ".claude" / "agents"


def _source() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_workflow_file_exists():
    assert WORKFLOW_PATH.is_file()


def test_workflow_is_syntactically_valid_js():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not installed in this environment")
    r = subprocess.run([node, "--check", str(WORKFLOW_PATH)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node --check failed:\n{r.stdout}\n{r.stderr}"


def test_meta_has_required_shape():
    src = _source()
    assert "export const meta = {" in src
    meta_match = re.search(r"export const meta = \{.*?\n\}\n", src, re.DOTALL)
    assert meta_match, "could not isolate the meta object literal"
    meta_src = meta_match.group(0)
    assert re.search(r"name\s*:\s*'rca-multi-agent-fusion'", meta_src)
    assert re.search(r"description\s*:\s*'", meta_src)
    assert re.search(r"whenToUse\s*:\s*'", meta_src)
    assert "phases:" in meta_src


def _meta_phase_titles(src: str):
    meta_match = re.search(r"export const meta = \{.*?\n\}\n", src, re.DOTALL)
    phases_match = re.search(r"phases\s*:\s*\[(.*?)\]\s*,?\s*\n\}", meta_match.group(0), re.DOTALL)
    assert phases_match, "meta.phases block not found"
    return re.findall(r"title\s*:\s*'([^']+)'", phases_match.group(1))


def _body_phase_calls(src: str):
    # Body starts after the meta object literal closes.
    body = src.split("export const meta = {", 1)[1]
    body = body.split("\n}\n", 1)[1] if "\n}\n" in body else body
    return re.findall(r"^phase\('([^']+)'\)", body, re.MULTILINE)


def test_meta_phase_titles_match_body_phase_calls_exactly():
    src = _source()
    meta_titles = _meta_phase_titles(src)
    body_titles = _body_phase_calls(src)
    assert meta_titles == ["Parallel Evidence Gathering", "Evidence Fusion", "RCA Review"]
    assert body_titles == meta_titles, (
        f"meta.phases titles {meta_titles} must exactly match, in order, the phase() calls "
        f"in the script body {body_titles} -- workflow-authoring: 'titles are matched exactly'."
    )


def test_every_referenced_agent_type_is_a_real_agent_file():
    src = _source()
    referenced = sorted(set(re.findall(r"agentType\s*:\s*'([^']+)'", src)))
    assert referenced, "expected at least one agentType reference in the fan-out"
    missing = [name for name in referenced if not (AGENTS_DIR / f"{name}.md").is_file()]
    assert not missing, f"rca-multi-agent-fusion.js references non-existent agent file(s): {missing}"
    # The specific specialists this task was scoped to create/reuse.
    assert "rtl-evidence-agent" in referenced
    assert "log-evidence-agent" in referenced
    assert "vip-spec-evidence-agent" in referenced
    assert "waveform-root-cause-agent" in referenced, "must reuse the EXISTING FSDB/waveform agent, not duplicate it"
    assert "review-agent" in referenced, "Evidence Fusion stage should reuse the existing independent reviewer role"
    assert "analysis_debug" in referenced, "RCA Review stage should reuse the existing deep-RCA arbiter role"


def test_no_fictional_new_evidence_agent_files_were_invented():
    """Guard against scope creep: this task's ruling was exactly 3 new narrow
    agents (rtl/log/vip-spec) plus reuse of the existing waveform agent --
    not a new fsdb-evidence-agent (would duplicate waveform-root-cause-agent)
    and not a generic org-chart-style agent name."""
    assert not (AGENTS_DIR / "fsdb-evidence-agent.md").exists()
    for forbidden in ("pm-agent", "architect-agent", "knowledge-agent", "rca-arbiter-agent"):
        assert not (AGENTS_DIR / f"{forbidden}.md").exists()


def test_uses_the_real_blackboard_topic_and_cli_subcommand_consistently():
    src = _source()
    assert src.count("rca_evidence_fusion") >= 3
    assert "blackboard write rca_evidence_fusion" in src
    assert "blackboard read rca_evidence_fusion" in src

    cli_src = (ROOT / "dv_harness" / "cli.py").read_text(encoding="utf-8")
    assert 'sub.add_parser("blackboard"' in cli_src, (
        "workflow instructs agents to run `dv-harness blackboard write/read`, but no such "
        "CLI subcommand exists in dv_harness/cli.py"
    )
    commands_src = (ROOT / "dv_harness" / "commands.py").read_text(encoding="utf-8")
    assert "def cmd_blackboard_write(" in commands_src
    assert "def cmd_blackboard_read(" in commands_src


def test_console_script_name_matches_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dv-harness = "dv_harness.cli:main"' in pyproject
    assert "dv-harness --project-root" in _source() or "dv-harness\" --project-root" in _source()
