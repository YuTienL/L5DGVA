"""Tests for dv_harness/context_budget.py -- the 3-tier context budget.

These tests exist because the audit finding this module closes was
specifically "real, well-designed OPTION, but not a GATE". So the tests are
weighted towards the gate actually firing, and towards it NOT firing on
ordinary repo work -- a context budget that denies routine reads gets
switched off within a day, at which point it enforces nothing.

The tier-1 cases are not invented: they are the exact tool calls
.claude/settings.local.json's own allow history documents as having really
happened in this project (a `pdftotext -layout` of a VIP user guide, a
`grep -h ... sim.log`, a `sed -n` range out of a live sim.log, blanket VIP
source reads). Each one must now be denied.

test_guard_hook_denies_through_real_powershell_process is the end-to-end
test: it runs .claude/hooks/context-budget-guard.ps1 as a real subprocess
with the payload on real process stdin, which is how Claude Code invokes it.
That path found a real bug the Python-level tests could not -- PowerShell
prepends a UTF-8 BOM when it pipes a string into a native command, which
made json.loads fail and the guard fail open on every call.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import context_budget as cb

ROOT = Path(__file__).resolve().parents[1]
GUARD_HOOK = ROOT / ".claude" / "hooks" / "context-budget-guard.ps1"
RESIDENT_HOOK = ROOT / ".claude" / "hooks" / "context-resident-pack.ps1"
SETTINGS = ROOT / ".claude" / "settings.json"


@pytest.fixture(scope="module")
def policy():
    return cb.load_policy()


# ---------------------------------------------------------------------------
# policy document
# ---------------------------------------------------------------------------

def test_shipped_policy_is_schema_valid(policy):
    cb.validate_policy(policy)  # raises on any violation
    assert policy["schema_version"] == cb.SCHEMA_VERSION


def test_policy_covers_all_four_tier1_content_classes(policy):
    ids = {r["rule_id"] for r in policy["never_load"]}
    assert ids == {
        "NEVER-VIP-SOURCE",       # VIP source full text
        "NEVER-RAW-PDF",          # raw PDF originals
        "NEVER-WHOLE-CHIP-DB",    # whole-chip / waveform / evidence database
        "NEVER-REGRESSION-LOGS",  # complete regression logs
    }


def test_every_tier1_rule_offers_a_real_route_forward(policy):
    """A deny with nowhere to go gets the gate disabled. Every rule must
    name an MCP verb or a distiller script, and a named distiller must be a
    file that really exists in this repo."""
    for rule in policy["never_load"]:
        assert rule.get("mcp_redirect") or rule.get("distiller"), rule["rule_id"]
        if rule.get("distiller"):
            assert (ROOT / rule["distiller"]).is_file(), rule["distiller"]
        else:
            assert rule.get("distiller_note", "").strip(), rule["rule_id"]


#: A token each cited distiller must really mention, keyed by rule. Existence
#: alone is not enough: the policy originally cited dv_harness/vip_distill.py
#: as the VIP-source distiller purely because the name looked right -- that
#: module is an evidence-envelope normaliser for sim logs, job records and
#: fsdb reports and never reads VIP source. This check would have caught it.
DISTILLER_MUST_MENTION = {
    "NEVER-RAW-PDF": ".pdf",
    "NEVER-WHOLE-CHIP-DB": ".fsdb",
    "NEVER-REGRESSION-LOGS": "sim.log",
}


def test_a_cited_distiller_really_handles_that_content_class(policy):
    for rule in policy["never_load"]:
        token = DISTILLER_MUST_MENTION.get(rule["rule_id"])
        if token is None or not rule.get("distiller"):
            continue
        text = (ROOT / rule["distiller"]).read_text(encoding="utf-8", errors="replace")
        assert token.lower() in text.lower(), (rule["rule_id"], rule["distiller"], token)


def test_vip_source_rule_cites_a_real_vip_source_distiller(policy):
    """Updated 2026-09-04: this rule used to assert `distiller is None`,
    because no VIP-source distiller existed. One now does --
    dv_harness/vip_symbol_index.py -- so the rule cites it.

    The test's ORIGINAL intent is preserved and is the important half: the
    miscitation of `vip_distill.py` (an evidence-envelope normaliser for sim
    logs/job records/fsdb reports, which never reads VIP source) must not
    quietly come back. So this asserts the cited distiller is the real one,
    that it genuinely reads VIP source, and that the note still disclaims
    vip_distill.py by name."""
    rule = next(r for r in policy["never_load"] if r["rule_id"] == "NEVER-VIP-SOURCE")
    assert rule["distiller"] == "dv_harness/vip_symbol_index.py"
    assert rule["mcp_redirect"] == "get_vip_config"
    # The miscitation guard, unchanged in spirit.
    assert "vip_distill.py" in rule["distiller_note"]
    assert "does not read VIP source" in rule["distiller_note"]
    # The cited distiller must really be a VIP-source reader, not another
    # suggestively-named module.
    src = (ROOT / rule["distiller"]).read_text(encoding="utf-8", errors="replace")
    assert "build_symbol_index" in src and "vip_ref" in src


def test_vip_distiller_retains_no_bodies(policy):
    """The property that makes indexing a tier-1-denied tree legitimate at
    all: the distiller keeps declarations and locations, never bodies. If
    this invariant were dropped, this rule would be routing agents to a
    module that smuggles VIP source into context."""
    from dv_harness import vip_symbol_index

    index = vip_symbol_index.build_symbol_index(
        [ROOT / "examples" / "asset_processing" / "inputs" / "vip_src"], "demo")
    vip_symbol_index.assert_no_bodies_retained(index)
    assert index["stats"]["classes_indexed"] > 0


def test_mcp_redirects_name_only_the_five_real_fixed_verbs(policy):
    from dv_harness.mcp import verbs as mcp_verbs
    assert set(policy["mcp"]["verbs"]) == set(mcp_verbs.VERBS)
    for entry in policy["never_load"] + policy["always_resident"] + policy["load_on_demand"]:
        verb = entry.get("mcp_redirect") or entry.get("mcp_verb")
        if verb:
            assert verb in mcp_verbs.VERBS, verb


def test_malformed_policy_raises_rather_than_degrading_to_permit_all(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")
    with pytest.raises(cb.ContextBudgetPolicyError):
        cb.load_policy(bad)


# ---------------------------------------------------------------------------
# path normalisation / glob semantics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spelling", [
    r"D:\DV\Task\USB\VIP\src\svt_usb_driver.sv",
    "D:/DV/Task/USB/VIP/src/svt_usb_driver.sv",
    "/d/DV/Task/USB/VIP/src/svt_usb_driver.sv",
    "//d/DV/Task/USB/VIP/src/svt_usb_driver.sv",
])
def test_every_spelling_of_the_same_file_classifies_identically(spelling, policy):
    """If a Windows path, a git-bash path and a settings.json-style
    double-slash path classified differently, the gate would be bypassed by
    simply re-spelling the target."""
    assert cb.classify_path(spelling, policy)["tier"] == cb.TIER_NEVER


def test_single_star_does_not_span_directory_separators():
    rx = cb._glob_to_regex("**/vip/*.sv")
    assert rx.match("d:/x/vip/a.sv")
    assert not rx.match("d:/x/vip/sub/a.sv")


def test_double_star_matches_zero_directories():
    rx = cb._glob_to_regex("a/**/b")
    assert rx.match("a/b")
    assert rx.match("a/x/y/b")


# ---------------------------------------------------------------------------
# tier 1: the gate fires on real, previously-committed violations
# ---------------------------------------------------------------------------

REAL_PRIOR_VIOLATIONS = [
    # .claude/settings.local.json lines 8-9: raw VIP PDF originals really
    # were converted and read.
    ("Bash", {"command": 'pdftotext -layout "D:/DV/Task/USB/VIP/doc/usb_svt_uvm_user_guide.pdf" ug.txt'},
     "NEVER-RAW-PDF"),
    ("Read", {"file_path": "D:/DV/Task/USB/VIP/doc/usb_svt_uvm_user_guide.pdf"},
     "NEVER-RAW-PDF"),
    # settings.local.json line 295/339: raw regression-log content really
    # was read directly rather than through query_regression.
    ("Bash", {"command": 'grep -hi mem_view /d/DV/Task/USB/sim/sim.log'},
     "NEVER-REGRESSION-LOGS"),
    ("Bash", {"command": 'sed -n "24320,24350p" /d/DV/Task/USB/sim/sim.log'},
     "NEVER-REGRESSION-LOGS"),
    ("Read", {"file_path": "/d/DV/Task/USB/sim/regress_nightly/run.log"},
     "NEVER-REGRESSION-LOGS"),
    # settings.local.json lines 19-20: blanket VIP source read allows.
    ("Read", {"file_path": "D:/DV/Task/VIP/src/svt_usb_agent.svh"},
     "NEVER-VIP-SOURCE"),
    ("Grep", {"pattern": "class svt_", "path": "D:/DV/Task/USB/VIP"},
     "NEVER-VIP-SOURCE"),
    # whole-chip / waveform / evidence databases
    ("Read", {"file_path": "D:/DV/Task/USB/sim/waves.fsdb"}, "NEVER-WHOLE-CHIP-DB"),
    ("Read", {"file_path": "D:/DV/Task/USB/sim/wave.txt"}, "NEVER-WHOLE-CHIP-DB"),
    ("Bash", {"command": "cat .dv-harness/evidence.db"}, "NEVER-WHOLE-CHIP-DB"),
]


@pytest.mark.parametrize("tool,payload,rule_id", REAL_PRIOR_VIOLATIONS,
                         ids=[c[2] + "-" + str(i) for i, c in enumerate(REAL_PRIOR_VIOLATIONS)])
def test_tier1_violation_is_denied(tool, payload, rule_id, policy):
    d = cb.evaluate_tool_call(tool, payload, policy)
    assert d["decision"] == "deny", d
    assert d["rule_id"] == rule_id
    assert d["tier"] == cb.TIER_NEVER


def test_deny_reason_always_names_a_route_forward(policy):
    for tool, payload, _rule in REAL_PRIOR_VIOLATIONS:
        reason = cb.evaluate_tool_call(tool, payload, policy)["reason"]
        assert "CONTEXT BUDGET tier-1" in reason
        assert ("MCP verb" in reason) or ("distil it first" in reason), reason


# ---------------------------------------------------------------------------
# tier 1: the gate must NOT fire on ordinary repo work
# ---------------------------------------------------------------------------

ORDINARY_WORK = [
    ("Read", {"file_path": str(ROOT / "dv_harness" / "connectivity.py")}),
    ("Read", {"file_path": "CLAUDE.md"}),
    ("Read", {"file_path": ".claude/skills/USB/usb-profile/PROFILE.yaml"}),
    ("Read", {"file_path": ".dv-harness/vault/03_Verification/VIP/note.md"}),
    ("Grep", {"pattern": "bind", "path": "dv_harness"}),
    ("Bash", {"command": "python -m pytest dv_harness_tests/ -q"}),
    ("Bash", {"command": "git diff --stat"}),
    ("Bash", {"command": "ls -la .dv-harness/"}),
    # VIP Examples and .f filelists are deliberate carve-outs: they are the
    # sanctioned reference material and are already covered by a real Read
    # allow entry. Denying them would be the false positive that gets the
    # whole gate switched off.
    ("Read", {"file_path": "D:/DV/Task/USB/VIP/Examples/usb_basic_sys/tb.sv"}),
    ("Read", {"file_path": "D:/DV/Task/USB/VIP/build/vip.f"}),
    # Edit/Write are a different concern (settings.json deny rules +
    # block-destructive.ps1); a context budget has nothing to say about them.
    ("Write", {"file_path": "D:/DV/Task/USB/VIP/src/x.sv"}),
]


@pytest.mark.parametrize("tool,payload", ORDINARY_WORK,
                         ids=[f"{t}-{i}" for i, (t, _p) in enumerate(ORDINARY_WORK)])
def test_ordinary_work_is_allowed(tool, payload, policy):
    assert cb.evaluate_tool_call(tool, payload, policy)["decision"] == "allow"


NON_CONTENT_COMMANDS_ON_TIER1_PATHS = [
    "ls -la D:/DV/Task/USB/sim/waves.fsdb",
    "find D:/DV/Task/USB/VIP -name '*.sv'",
    "stat /d/DV/Task/USB/sim/sim.log",
    "wc -l /d/DV/Task/USB/sim/sim.log",
    "file D:/DV/Task/USB/VIP/doc/ug.pdf",
]


@pytest.mark.parametrize("cmd", NON_CONTENT_COMMANDS_ON_TIER1_PATHS)
def test_naming_a_tier1_file_without_reading_it_is_allowed(cmd, policy):
    """`ls`/`find`/`stat`/`wc`/`file` name a tier-1 file without pulling its
    content into context. Denying those would block ordinary navigation and
    get the whole gate switched off."""
    assert cb.evaluate_tool_call("Bash", {"command": cmd}, policy)["decision"] == "allow"


@pytest.mark.parametrize("cmd", [
    "ls -la /d/DV/Task/USB/sim && cat /d/DV/Task/USB/sim/sim.log",
    "stat x.txt; grep UVM_ERROR /d/DV/Task/USB/sim/sim.log",
    "ls /d/DV/Task/USB/VIP && head -200 /d/DV/Task/USB/VIP/src/svt_drv.sv",
])
def test_a_chained_command_is_not_treated_as_a_bare_listing(cmd, policy):
    """`ls x && cat sim.log` is not an `ls` -- the non-content carve-out
    must not become a one-token bypass prefix. Any pipe/redirect/chaining
    metacharacter disables the carve-out and the tier-1 target in the rest
    of the command is classified normally."""
    assert cb.evaluate_tool_call("Bash", {"command": cmd}, policy)["decision"] == "deny"


def test_directory_indirection_is_a_known_residual_gap(policy):
    """`ls <dir> | xargs cat` names no tier-1 FILE, only the directory that
    contains them, so the path scan has nothing to classify. Recorded here
    deliberately: the alternative -- marking every `sim/` directory tier-1 --
    would deny grepping a build directory for its Makefile, which is a worse
    trade. Same family as the shell-variable gap below."""
    d = cb.evaluate_tool_call(
        "Bash", {"command": "ls /d/DV/Task/USB/sim | xargs cat"}, policy)
    assert d["decision"] == "allow"


def test_variable_indirected_read_is_a_known_residual_gap(policy):
    """Documented honestly rather than claimed as sealed: at PreToolUse time
    the shell has not expanded $M, so a variable-indirected path cannot be
    classified. The policy's command_patterns catch the literal-filename
    shapes; this one gets through, and the module docstring says so."""
    d = cb.evaluate_tool_call("Bash", {"command": 'sed -n "1,50p" $M'}, policy)
    assert d["decision"] == "allow"


# ---------------------------------------------------------------------------
# exemptions
# ---------------------------------------------------------------------------

def test_exemption_allows_but_still_reports_the_rule_that_fired(policy):
    exempted = json.loads(json.dumps(policy))
    exempted["exemptions"] = [{
        "rule_id": "NEVER-RAW-PDF",
        "path_glob": "**/tiny_errata.pdf",
        "reason": "2-page errata sheet, no distilled artifact exists yet",
        "owner": "dv-lead",
        "valid_until": "2026-12-31",
    }]
    cb.validate_policy(exempted)
    d = cb.evaluate_tool_call("Read", {"file_path": "docs/tiny_errata.pdf"}, exempted)
    assert d["decision"] == "allow"
    assert d["tier"] == cb.TIER_NEVER           # the rule DID fire ...
    assert d["rule_id"] == "NEVER-RAW-PDF"      # ... and is named in the trail
    assert "errata" in d["exemption"]["reason"]


def test_shipped_policy_ships_with_no_exemptions(policy):
    assert policy["exemptions"] == []


# ---------------------------------------------------------------------------
# tier 2: residency
# ---------------------------------------------------------------------------

def test_resident_pack_reports_every_declared_artifact_exactly_once(policy):
    pack = cb.build_resident_pack(ROOT, policy)
    ids = [e["artifact_id"] for e in pack["artifacts"]]
    assert ids == [a["artifact_id"] for a in policy["always_resident"]]
    assert len(ids) == len(set(ids))
    assert pack["declared_count"] == len(policy["always_resident"])


def test_claude_md_is_present_and_resident_in_this_repo(policy):
    pack = cb.build_resident_pack(ROOT, policy)
    entry = next(e for e in pack["artifacts"] if e["artifact_id"] == "claude_md_index")
    assert entry["status"] == "PRESENT"
    assert entry["residency"] == "harness_auto_load"
    assert entry["bytes"] > 0


def test_missing_artifact_is_reported_with_the_command_that_produces_it(policy):
    """A MISSING tier-2 artifact must never be silently omitted -- the whole
    point of tier 2 is that residency is checkable."""
    pack = cb.build_resident_pack(ROOT, policy)
    for entry in pack["artifacts"]:
        if entry["status"] == "MISSING":
            assert entry["produced_by"].strip(), entry["artifact_id"]


def test_present_artifact_is_summarised_not_inlined(tmp_path, policy):
    """A 2 MB manifest must not blow the residency budget it belongs to."""
    (tmp_path / ".dv-harness").mkdir()
    big = {"vip_config": {"status": "CAPTURED", "vip_instances": [{}] * 500},
           "dut_facts": {"registers": {"blocks": []}, "rtl": {"files": []}},
           "env_topology": {"component_hierarchy": {"components": [{}] * 5000}}}
    (tmp_path / ".dv-harness" / "env.manifest.json").write_text(
        json.dumps(big), encoding="utf-8")
    pack = cb.build_resident_pack(tmp_path, policy)
    entry = next(e for e in pack["artifacts"] if e["artifact_id"] == "env_manifest")
    assert entry["status"] == "PRESENT"
    assert entry["bytes"] > 20_000
    assert len(entry["summary"]) < 500
    assert "vip_config" in entry["summary"]


def test_alt_path_is_searched_when_canonical_path_is_absent(tmp_path, policy):
    (tmp_path / "run_profile.json").write_text('{"schema_version":"1.0"}', encoding="utf-8")
    pack = cb.build_resident_pack(tmp_path, policy)
    entry = next(e for e in pack["artifacts"] if e["artifact_id"] == "run_profile")
    assert entry["status"] == "PRESENT"
    assert entry["resolved_path"] == "run_profile.json"


def test_rendered_pack_is_bounded(policy):
    pack = cb.build_resident_pack(ROOT, policy)
    text = cb.render_resident_pack(pack)
    assert len(text.encode("utf-8")) <= cb.MAX_PACK_BYTES
    tiny = cb.render_resident_pack(pack, max_bytes=300)
    assert len(tiny.encode("utf-8")) < 500
    assert "truncated" in tiny


def test_rendered_pack_states_all_three_tiers(policy):
    text = cb.render_resident_pack(cb.build_resident_pack(ROOT, policy))
    assert "Tier 1 -- NEVER" in text
    assert "Tier 2 -- always resident" in text
    assert "Tier 3 -- load on demand" in text
    for rule in policy["never_load"]:
        assert rule["rule_id"] in text


def test_session_start_payload_is_a_valid_claude_code_hook_shape(policy):
    payload = cb.session_start_payload(ROOT, policy)
    hso = payload["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    assert "Context Budget" in hso["additionalContext"]


# ---------------------------------------------------------------------------
# tier 3
# ---------------------------------------------------------------------------

def test_regmap_lookup_is_tier3_and_routes_to_get_register(policy):
    d = cb.classify_path(".dv-harness/register_map.json", policy)
    assert d["tier"] == cb.TIER_ON_DEMAND
    assert d["mcp_redirect"] == "get_register"


def test_vip_ref_directory_is_tier3_not_tier1(policy):
    """docs/vip_ref/<protocol>.md is the DISTILLED replacement for VIP source
    -- it must never be caught by the VIP-source never-load rule."""
    d = cb.classify_path("docs/vip_ref/usb.md", policy)
    assert d["tier"] == cb.TIER_ON_DEMAND
    assert d["artifact_id"] == "vip_ref"


# ---------------------------------------------------------------------------
# hook payload + the real PowerShell wrappers
# ---------------------------------------------------------------------------

def test_hook_payload_is_none_on_allow_and_a_deny_block_on_deny(policy):
    assert cb.hook_decision_payload("Read", {"file_path": "CLAUDE.md"}, policy) is None
    payload = cb.hook_decision_payload(
        "Read", {"file_path": "D:/DV/Task/USB/VIP/doc/ug.pdf"}, policy)
    hso = payload["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert "NEVER-RAW-PDF" in hso["permissionDecisionReason"]


def test_hook_cli_fails_open_on_unparseable_stdin(monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
    assert cb.main(["hook"]) == 0
    assert capsys.readouterr().out == ""


def test_hook_cli_tolerates_a_utf8_bom(monkeypatch, capsys):
    """PowerShell 5.1 prepends U+FEFF when piping a string into a native
    command. Without utf-8-sig decoding the guard failed open on every
    single call -- a real, silent never-fires bug."""
    import io
    payload = '{"tool_name":"Read","tool_input":{"file_path":"x/VIP/doc/ug.pdf"}}'
    monkeypatch.setattr(sys, "stdin", io.StringIO("\ufeff" + payload))
    assert cb.main(["hook"]) == 0
    assert "NEVER-RAW-PDF" in capsys.readouterr().out


def test_classify_cli_exits_nonzero_on_tier1(capsys):
    assert cb.main(["classify", "D:/DV/Task/USB/VIP/doc/ug.pdf"]) == 1
    assert cb.main(["classify", "dv_harness/context_budget.py"]) == 0
    capsys.readouterr()


def test_resident_cli_exits_2_while_any_declared_artifact_is_missing(capsys):
    rc = cb.main(["resident", "--root", str(ROOT)])
    pack = cb.build_resident_pack(ROOT)
    capsys.readouterr()
    assert rc == (0 if pack["present_count"] == pack["declared_count"] else 2)


# --- the wrappers themselves -----------------------------------------------

def test_hook_files_exist():
    assert GUARD_HOOK.is_file()
    assert RESIDENT_HOOK.is_file()


def test_settings_json_registers_both_hooks():
    """The audit's core finding was that the MCP interface was an option and
    not a gate. It is only a gate while it is wired here."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    pre = settings["hooks"]["PreToolUse"]
    guard = [e for e in pre
             if any("context-budget-guard.ps1" in h["command"] for h in e["hooks"])]
    assert len(guard) == 1
    for tool in ("Read", "Grep", "Bash", "PowerShell"):
        assert tool in guard[0]["matcher"]
    # the pre-existing destructive-operation guard must still be registered
    assert any(any("block-destructive.ps1" in h["command"] for h in e["hooks"]) for e in pre)
    start = settings["hooks"]["SessionStart"]
    assert any(any("context-resident-pack.ps1" in h["command"] for h in e["hooks"])
               for e in start)


_POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
_needs_ps = pytest.mark.skipif(_POWERSHELL is None, reason="no powershell on PATH")


def _run_guard(payload: str):
    return subprocess.run(
        [_POWERSHELL, "-NoProfile", "-File", str(GUARD_HOOK)],
        input=payload.encode("utf-8"), capture_output=True,
        env={**__import__("os").environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
        timeout=120,
    )


@_needs_ps
def test_guard_hook_denies_through_real_powershell_process():
    """End-to-end through the real wrapper, with the payload on real process
    stdin -- exactly how Claude Code invokes a PreToolUse hook."""
    proc = _run_guard(json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "grep -h ss_vout_model /d/DV/Task/USB/sim/sim.log"},
    }))
    assert proc.returncode == 0
    out = json.loads(proc.stdout.decode("utf-8-sig"))
    hso = out["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    assert "NEVER-REGRESSION-LOGS" in hso["permissionDecisionReason"]
    assert "query_regression" in hso["permissionDecisionReason"]


@_needs_ps
def test_guard_hook_is_silent_on_an_allowed_call():
    proc = _run_guard(json.dumps({
        "tool_name": "Read", "tool_input": {"file_path": "CLAUDE.md"}}))
    assert proc.returncode == 0
    assert proc.stdout.decode("utf-8-sig").strip() == ""


@_needs_ps
def test_guard_hook_fails_open_on_empty_stdin():
    proc = _run_guard("")
    assert proc.returncode == 0
    assert proc.stdout.decode("utf-8-sig").strip() == ""


@_needs_ps
def test_resident_pack_hook_emits_session_start_context():
    proc = subprocess.run(
        [_POWERSHELL, "-NoProfile", "-File", str(RESIDENT_HOOK)],
        input=b"", capture_output=True,
        env={**__import__("os").environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
        timeout=120,
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout.decode("utf-8-sig"))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Tier 1 -- NEVER" in ctx
    assert len(ctx.encode("utf-8")) <= cb.MAX_PACK_BYTES


# ---------------------------------------------------------------------------
# documentation: the rule must exist somewhere a human/agent actually reads
# ---------------------------------------------------------------------------

def test_context_budget_is_documented_in_claude_md():
    """The original audit finding was that the 3-tier text existed nowhere
    in this repo except a workflow prompt. This test is the drift guard."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Context Budget" in text
    for token in ("NEVER into context", "ALWAYS resident", "LOAD ON DEMAND",
                  "context_budget.policy.json", "context-budget-guard.ps1"):
        assert token in text, token


# ---------------------------------------------------------------------------
# produced_by drift: the resident pack must not misinform the session
# ---------------------------------------------------------------------------
#
# Why this block exists (2026-09-04). `never_load[].distiller` was already
# guarded three ways above: the cited file must exist, must really mention
# its content class, and the specific vip_distill.py miscitation is named and
# refused. `artifact[].produced_by` -- the OTHER half of exactly the same
# "cite a real producer" contract -- was guarded only for non-emptiness by
# test_missing_artifact_is_reported_with_the_command_that_produces_it.
#
# That asymmetry was not theoretical. Three produced_by fields had gone stale
# and were caught by hand, not by this suite:
#   * phy_boundary said "NOT IMPLEMENTED -- no extractor exists" while
#     dv_harness/phy_boundary.py existed.
#   * intent said "NOT IMPLEMENTED -- no generator exists" while
#     dv_harness/design_intent.py existed.
#   * vip_ref cited dv_harness/vip_distill.py -- the very miscitation the
#     never_load rule's distiller_note already disclaims by name. Only the
#     never_load half of that 2026-09-04 correction had been applied.
#
# build_resident_pack() prints produced_by VERBATIM into every session for a
# MISSING artifact, so a stale field is not cosmetic: it is the context
# budget's own resident pack telling every agent that a real generator does
# not exist. These tests make that class of drift fail the suite instead.

import re as _re

_MODULE_CITATION_RX = _re.compile(r"\b((?:dv_harness|tools)/[A-Za-z0-9_./]+\.py)\b")
_EXAMPLE_CITATION_RX = _re.compile(
    r"\b(examples/[A-Za-z0-9_./-]+\.(?:json|md|ya?ml|sv))\b")

#: Phrases that assert an artifact has no producer. Legitimate when true --
#: the policy is deliberately allowed to say a slot is unfilled rather than
#: fake one. A lie the moment the cited module lands.
_NO_PRODUCER_PHRASES = ("NOT IMPLEMENTED", "no extractor exists", "no generator exists")


def _all_artifacts(policy):
    return policy["always_resident"] + policy["load_on_demand"]


def test_every_produced_by_module_citation_is_a_real_file(policy):
    """A produced_by that names `dv_harness/<x>.py` must name one that
    exists. Same contract the cited-distiller test already enforces for
    never_load; artifacts were exempt from it until now."""
    seen = 0
    for art in _all_artifacts(policy):
        for cited in _MODULE_CITATION_RX.findall(art.get("produced_by", "")):
            seen += 1
            assert (ROOT / cited).is_file(), (art["artifact_id"], cited)
    assert seen >= 4, "expected several artifacts to cite a real producer module"


#: artifact_id -> extra module basenames that could be its producer, for the
#: cases where the module is not simply named after the artifact. Kept small
#: on purpose: the PRIMARY candidate is derived from artifact_id itself
#: (dv_harness/<artifact_id>.py), so an artifact added later is checked
#: automatically instead of silently escaping this guard until someone
#: remembers to extend a list.
_PRODUCER_ALIASES = {
    "intent": ["design_intent"],
    "constraints": ["design_intent"],
    "vip_ref": ["vip_symbol_index"],
    "regmap_single_lookup": ["sys_regmap"],
    "claude_md_index": [],
    "hierarchy": [],  # genuinely has no non-agent extractor; see its produced_by
}


def _existing_producer_modules(artifact_id):
    """Every real dv_harness module that could plausibly produce this
    artifact, found on disk right now."""
    names = [artifact_id, *_PRODUCER_ALIASES.get(artifact_id, [])]
    return [f"dv_harness/{n}.py" for n in names
            if (ROOT / "dv_harness" / (n + ".py")).is_file()]


def test_no_artifact_claims_unimplemented_while_its_producer_exists(policy):
    """The exact drift that really happened: phy_boundary and intent kept
    saying 'NOT IMPLEMENTED -- no extractor exists' for a day after their
    extractors landed, and build_resident_pack() printed that verbatim into
    every session.

    The check deliberately does NOT read which module the text cites -- the
    stale text cited none at all, which is precisely why an earlier version
    of this test passed on the very state it was written to catch. It asks
    the filesystem instead: does a producer for this artifact exist? If so,
    the text may not claim one doesn't."""
    checked = []
    for art in _all_artifacts(policy):
        produced_by = art.get("produced_by", "")
        claims_absent = [p for p in _NO_PRODUCER_PHRASES if p in produced_by]
        if not claims_absent:
            continue
        # A dated correction is allowed to quote the old wording it replaced.
        if "CORRECTED" in produced_by:
            continue
        found = _existing_producer_modules(art["artifact_id"])
        checked.append(art["artifact_id"])
        assert not found, (
            art["artifact_id"],
            "produced_by claims %r but these real producers exist: %s"
            % (claims_absent, ", ".join(found)))
    assert checked == [], checked


def test_the_unimplemented_guard_really_fires_on_the_real_pre_fix_text(policy):
    """Guard the guard, against the REAL string that was in the policy on
    2026-09-04 rather than an invented one.

    Without this, test_no_artifact_claims_unimplemented_while_its_producer_exists
    passes forever the moment the policy is clean, and nothing proves it
    would ever fail -- which is exactly how its first version shipped
    broken (it keyed off a cited module, and the stale text cited none)."""
    import copy

    stale = copy.deepcopy(policy)
    art = next(a for a in stale["always_resident"] if a["artifact_id"] == "phy_boundary")
    art["produced_by"] = (
        "NOT IMPLEMENTED -- no extractor exists in this repo as of 2026-09-03; "
        "the only real reference is the critical_fields entry at "
        ".claude/skills/USB/usb-profile/PROFILE.yaml:8. Owned by the "
        "asset-processing-table workstream.")
    with pytest.raises(AssertionError, match="phy_boundary.py"):
        test_no_artifact_claims_unimplemented_while_its_producer_exists(stale)


def test_hierarchy_may_still_honestly_report_no_extractor(policy):
    """The guard must not force a false claim in the other direction.
    hierarchy.json really has no non-agent extractor -- only a skill that
    declares the output path -- and saying so is correct, not drift."""
    art = next(a for a in policy["always_resident"] if a["artifact_id"] == "hierarchy")
    assert _existing_producer_modules("hierarchy") == []
    assert "hierarchy-discovery" in art["produced_by"]
    assert "no non-agent extractor exists" in art["produced_by"]


def test_vip_ref_produced_by_is_not_the_vip_distill_miscitation(policy):
    """Mirror of test_vip_source_rule_cites_a_real_vip_source_distiller, for
    the produced_by half that the original correction missed."""
    art = next(a for a in policy["load_on_demand"] if a["artifact_id"] == "vip_ref")
    produced_by = art["produced_by"]
    assert "dv_harness/vip_symbol_index.py" in produced_by
    # vip_distill.py may only appear as the disclaimed miscitation.
    if "vip_distill.py" in produced_by:
        assert "never reads VIP source" in produced_by
    src = (ROOT / "dv_harness" / "vip_symbol_index.py").read_text(
        encoding="utf-8", errors="replace")
    assert "def write_vip_ref" in src and "def build_symbol_index" in src


def test_cited_worked_examples_really_exist(policy):
    """produced_by cites `examples/asset_processing/...` files as the proof
    that each generator really runs. A citation to a file nobody generated
    is the same defect in a different field."""
    seen = 0
    for art in _all_artifacts(policy):
        for cited in _EXAMPLE_CITATION_RX.findall(art.get("produced_by", "")):
            seen += 1
            assert (ROOT / cited).is_file(), (art["artifact_id"], cited)
    assert seen >= 3, "expected the corrected artifacts to cite worked examples"


# ---------------------------------------------------------------------------
# tier 3 completeness against the asset-processing table
# ---------------------------------------------------------------------------

def test_tier3_covers_the_real_on_demand_artifact_types(policy):
    """sys_regmap.json, init_seq.yaml and constraints.md gained real modules
    and schemas but were in NO tier, so classify_path() called them
    'unclassified' -- the budget had nothing to say about artifacts it
    exists to route. Added 2026-09-04."""
    ids = {a["artifact_id"] for a in policy["load_on_demand"]}
    assert {"regmap_single_lookup", "vip_ref", "intent",
            "constraints", "sys_regmap", "init_seq"} <= ids


@pytest.mark.parametrize("relpath,artifact_id", [
    ("examples/asset_processing/inputs/sys_regmap.json", "sys_regmap"),
    ("examples/asset_processing/inputs/init_seq.yaml", "init_seq"),
    ("examples/asset_processing/generated/docs/constraints.md", "constraints"),
    ("examples/asset_processing/generated/docs/intent.md", "intent"),
])
def test_real_tier3_files_classify_as_load_on_demand(relpath, artifact_id, policy):
    """Classified against files that really exist on disk, not invented
    paths -- so this also asserts the worked examples stay put."""
    assert (ROOT / relpath).is_file(), relpath
    d = cb.classify_path(relpath, policy)
    assert d["tier"] == cb.TIER_ON_DEMAND, d
    assert d["artifact_id"] == artifact_id


def test_tier3_additions_are_not_denied_by_any_tier1_rule(policy):
    """A tier-3 artifact the budget tells you to read must not be one the
    guard then denies."""
    for art in policy["load_on_demand"]:
        d = cb.classify_path(art["path"], policy)
        assert d["tier"] != cb.TIER_NEVER, (art["artifact_id"], art["path"])


def test_every_tier3_module_citation_names_a_module_that_handles_it(policy):
    """Existence is not enough -- the vip_distill miscitation existed too.
    Each new tier-3 artifact's cited producer must really mention it."""
    must_mention = {
        "sys_regmap": ("dv_harness/sys_regmap.py", "control_kind"),
        "init_seq": ("dv_harness/init_seq.py", "init_seq"),
        "constraints": ("dv_harness/design_intent.py", "write_constraints"),
        "intent": ("dv_harness/design_intent.py", "write_intent"),
    }
    for art in policy["load_on_demand"]:
        expect = must_mention.get(art["artifact_id"])
        if expect is None:
            continue
        module, token = expect
        assert module in art["produced_by"], (art["artifact_id"], module)
        src = (ROOT / module).read_text(encoding="utf-8", errors="replace")
        assert token in src, (module, token)
