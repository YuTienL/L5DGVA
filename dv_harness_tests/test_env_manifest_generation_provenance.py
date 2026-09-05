"""Tests for spec section 210's per-artifact GENERATION PROVENANCE TUPLE, as
carried by dv_harness/env_manifest.py's existing `generator` block (schema
1.2).

THE GAP THESE CLOSE. Before 2026-09-06 `generator` was
`{"tool", "version"}` and `version` was env_manifest.py's own SCHEMA_VERSION,
so a generated env.manifest.json could not say which harness build produced
it, which agent/skill produced it, what input drove the generation, or which
commit it was generated at -- and no git SHA appeared anywhere in the schema.

What gives these tests detection power is that nothing here asserts against
this module's own bookkeeping:
  * the harness git SHA is compared against an INDEPENDENT real
    `git rev-parse HEAD` subprocess run by the test itself;
  * the project git SHA is compared against a REAL throwaway git repository
    with a REAL commit that the test creates and reads back the same way;
  * `tool_version` is compared against the real `dv_harness.__version__`;
  * the agent identifier is resolved against the REAL `.claude/agents/*.md`
    and `.claude/skills/**/SKILL.md` profiles in this checkout, with a
    fabricated identifier as the negative control;
  * the input-IR sha256 is compared against an independently-computed
    hashlib digest of the real requirements file;
  * the requirement-contract cross-check is driven through the REAL
    `dv_harness.requirement_contract` validator and `downstream_consumable()`.

Nothing here runs a build, a regression or an LSF submission, and no
human-approval gate is touched.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import dv_harness
from dv_harness import change_impact, env_manifest
from dv_harness.env_manifest import (
    GenerationProvenanceIncompleteError,
    InputIrDeclarationError,
    assert_generation_provenance_complete,
    build_generation_agent,
    build_input_ir,
    build_repository_sha,
    generate_and_write,
    generate_env_manifest,
    generation_provenance,
    known_generation_identifiers,
    load_env_manifest,
    provenance_gaps,
)

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# helpers -- every one reads a REAL source, none reads this module's own state
# ---------------------------------------------------------------------------

def real_head_sha(root: Path):
    """An INDEPENDENT `git rev-parse HEAD`, run by the test itself rather
    than through the code under test, so a broken resolve_sha() cannot make
    this assertion agree with it."""
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def clean_requirement_record(**over):
    """A fully-populated, internally coherent COMPLETE section 184 requirement
    contract. Synthetic -- it describes no real DUT."""
    record = {
        "contract_schema_version": "1.0",
        "requirement_id": "REQ-USB-LPM-001",
        "source": {"document": "usb2_spec.pdf", "locator": "section 7.2.3",
                   "quote": "The device shall enter L1 within tL1Entry."},
        "feature": "LPM L1 entry",
        "protocol": "USB2",
        "configuration": "HS, LPM enabled",
        "precondition": "device configured, link in U0",
        "stimulus": "host issues an LPM EXT token with HIRD=3",
        "expected_result": "device ACKs and enters L1 within tL1Entry",
        "observability": "utmi_suspend_o asserted; VIP LPM callback",
        "checker": "scoreboard compares observed L1 entry latency against tL1Entry",
        "coverage_intent": "cover HIRD 0..15 crossed with BESL",
        "priority": "P0",
        "criticality": "BLOCKER",
        "confidence": "HIGH",
        "status": "COMPLETE",
    }
    record.update(over)
    return record


@pytest.fixture()
def requirements_file(tmp_path):
    p = tmp_path / "requirements.json"
    p.write_text(json.dumps({"schema_version": "1.0",
                             "requirements": [clean_requirement_record()]}),
                 encoding="utf-8")
    return p


@pytest.fixture()
def throwaway_git_project(tmp_path):
    """A REAL git repository with a REAL commit, so a recorded project SHA can
    be checked against a commit that genuinely exists."""
    root = tmp_path / "project_repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"],
                   cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True)
    (root / "rtl.sv").write_text("module dut(); endmodule\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(root), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(root), check=True)
    return root


# ---------------------------------------------------------------------------
# THE HEADLINE TEST: a generated manifest carries the whole tuple, and its git
# SHA really is this repository's HEAD at generation time.
# ---------------------------------------------------------------------------

def test_generated_manifest_carries_the_whole_section_210_provenance_tuple(
        tmp_path, requirements_file, throwaway_git_project):
    out = tmp_path / "env.manifest.json"
    manifest = generate_and_write(
        out,
        generated_by="debug-agent",
        project_root=throwaway_git_project,
        input_requirements_path=requirements_file,
        input_requirement_id="REQ-USB-LPM-001",
    )

    # 1. schema_version -- the manifest's own contract version.
    assert manifest["schema_version"] == env_manifest.SCHEMA_VERSION == "1.2"

    generator = manifest["generator"]
    assert generator["tool"] == "dv_harness.env_manifest"
    assert generator["version"] == "1.2"

    # 2. tool_version -- the real harness build, NOT the schema version it
    #    used to be conflated with.
    assert generator["tool_version"] == dv_harness.__version__
    assert generator["tool_version"] != generator["version"]

    # 3. agent identifier -- and it resolves to a REAL profile on disk.
    agent = generator["agent"]
    assert agent["status"] == "DECLARED"
    assert agent["identifier"] == "debug-agent"
    assert agent["resolution"] == "AGENT_PROFILE"
    assert (ROOT / ".claude" / "agents" / "debug-agent.md").is_file()

    # 4. a real git SHA, equal to this repository's real HEAD, compared
    #    against an independent `git rev-parse HEAD` this test ran itself.
    harness = generator["repository_sha"]["harness"]
    expected = real_head_sha(ROOT)
    assert expected is not None, "this checkout is not a git repository"
    assert harness["status"] == "RESOLVED"
    assert harness["sha"] == expected
    assert len(harness["sha"]) == 40

    # ... and the declared project's real HEAD, from a genuinely different repo.
    project = generator["repository_sha"]["project"]
    assert project["status"] == "RESOLVED"
    assert project["sha"] == real_head_sha(throwaway_git_project)
    assert project["sha"] != harness["sha"]

    # 5. the input that drove generation -- a real, validated, consumable
    #    section 184 requirement contract, cited with the real file digest.
    input_ir = generator["input_ir"]
    assert input_ir["status"] == "RESOLVED"
    assert input_ir["kind"] == "requirement_contract"
    assert input_ir["reference"] == "REQ-USB-LPM-001"
    assert input_ir["contract_schema_version"] == "1.0"
    assert input_ir["requirement_status"] == "COMPLETE"
    assert input_ir["downstream_consumable"] is True
    assert input_ir["source"]["sha256"] == hashlib.sha256(
        requirements_file.read_bytes()).hexdigest()

    # The whole tuple is answered, and the strict contract agrees.
    assert provenance_gaps(manifest) == []
    assert_generation_provenance_complete(manifest)

    # It survives the real write/validate/read round trip on disk.
    assert load_env_manifest(out) == manifest


# ---------------------------------------------------------------------------
# the git SHA comes from the EXISTING reader, not a reimplementation
# ---------------------------------------------------------------------------

def test_repository_sha_is_read_through_the_existing_change_impact_resolver(monkeypatch):
    """Reuse, held as a property rather than as a docstring claim: patching
    change_impact.resolve_sha() must change what the manifest records. A second
    hand-rolled `git rev-parse` in env_manifest.py would not respond to this."""
    calls = []

    def fake_resolve(root, rev):
        calls.append((Path(root), rev))
        return "0" * 40

    monkeypatch.setattr(change_impact, "resolve_sha", fake_resolve)
    block = build_repository_sha()
    assert block["harness"]["sha"] == "0" * 40
    assert calls and calls[0][1] == "HEAD"
    assert calls[0][0] == env_manifest.HARNESS_REPOSITORY_ROOT


def test_harness_sha_is_read_from_this_files_own_checkout_not_from_the_caller(
        throwaway_git_project):
    """The GENERATOR's identity must not be reroutable by a caller: declaring a
    project root records that root as `project` and never overwrites `harness`."""
    block = build_repository_sha(project_root=throwaway_git_project)
    assert block["harness"]["sha"] == real_head_sha(ROOT)
    assert block["project"]["sha"] == real_head_sha(throwaway_git_project)


def test_unresolvable_git_head_is_not_available_with_a_real_reason_never_a_sha(tmp_path):
    not_a_repo = tmp_path / "plain_dir"
    not_a_repo.mkdir()
    block = build_repository_sha(project_root=not_a_repo)
    assert block["project"]["status"] == "NOT_AVAILABLE"
    assert block["project"]["sha"] is None
    assert "does not resolve" in block["project"]["reason"]


def test_no_declared_project_root_is_not_declared_not_not_available(tmp_path):
    """Two different facts: nobody asked us to check, vs. we checked and could
    not. Collapsing them would report an operator omission as a git failure."""
    block = build_repository_sha()
    assert block["project"]["status"] == "NOT_DECLARED"
    assert block["project"]["reason"]


# ---------------------------------------------------------------------------
# agent identity -- checked against the REAL profiles, never accepted blind
# ---------------------------------------------------------------------------

def test_known_identifiers_are_read_from_the_real_profile_tree():
    known = known_generation_identifiers()
    assert known is not None
    # Real profiles that really exist in this checkout, each self-identifying
    # through its own YAML front-matter `name:`.
    assert "debug-agent" in known["agents"]
    assert "research-architect" in known["agents"]
    assert "git-push-gate" in known["skills"]
    assert "debug-agent" not in known["skills"]


def test_a_fabricated_agent_identifier_is_recorded_but_never_verified():
    agent = build_generation_agent("totally-invented-agent")
    assert agent["status"] == "DECLARED"
    assert agent["identifier"] == "totally-invented-agent"
    assert agent["resolution"] == "NOT_FOUND"
    assert "never accepted as verified" in agent["reason"]


def test_a_real_skill_identifier_resolves_as_a_skill():
    agent = build_generation_agent("git-push-gate")
    assert agent["resolution"] == "SKILL"
    assert agent["reason"] is None


def test_an_undeclared_agent_is_not_declared_and_names_the_flag_that_fixes_it():
    agent = build_generation_agent(None)
    assert agent["status"] == "NOT_DECLARED"
    assert agent["identifier"] is None
    assert agent["resolution"] == "NOT_DECLARED"
    assert "--generated-by" in agent["reason"]
    assert build_generation_agent("   ")["status"] == "NOT_DECLARED"


def test_no_profile_tree_is_distinct_from_a_fabricated_identifier(tmp_path):
    """A deployed harness copy carrying no .claude tree must not report every
    real agent as fabricated."""
    bare = tmp_path / "deployed"
    bare.mkdir()
    agent = build_generation_agent("debug-agent", profile_root=bare)
    assert agent["status"] == "DECLARED"
    assert agent["resolution"] == "PROFILE_TREE_NOT_AVAILABLE"
    assert known_generation_identifiers(bare) is None


def test_front_matter_name_is_read_only_from_the_front_matter_block(tmp_path):
    profile_root = tmp_path / "fake_root"
    (profile_root / ".claude" / "agents").mkdir(parents=True)
    (profile_root / ".claude" / "agents" / "real.md").write_text(
        "---\nname: real-agent\ndescription: x\n---\n# body\nname: body-agent\n",
        encoding="utf-8")
    (profile_root / ".claude" / "agents" / "no_front_matter.md").write_text(
        "# just a document\nname: not-an-agent\n", encoding="utf-8")
    known = known_generation_identifiers(profile_root)
    assert known == {"agents": ["real-agent"], "skills": []}


# ---------------------------------------------------------------------------
# input IR -- the requirement-contract form is really cross-checked
# ---------------------------------------------------------------------------

def test_input_ir_records_a_requirement_that_is_not_consumable_as_not_consumable(tmp_path):
    """The point of citing a requirement is not that it exists but that a
    generator was entitled to build from it. A PARTIAL requirement is
    RESOLVED (it really is the input) and downstream_consumable False."""
    p = tmp_path / "requirements.json"
    record = clean_requirement_record(checker="TBD", status="PARTIAL")
    p.write_text(json.dumps({"requirements": [record]}), encoding="utf-8")
    ir = build_input_ir(requirements_path=p, requirement_id="REQ-USB-LPM-001")
    assert ir["status"] == "RESOLVED"
    assert ir["requirement_status"] == "PARTIAL"
    assert ir["downstream_consumable"] is False
    assert "only COMPLETE may feed a generator" in ir["reason"]


def test_input_ir_not_found_when_the_cited_requirement_is_absent(requirements_file):
    ir = build_input_ir(requirements_path=requirements_file, requirement_id="REQ-NOPE")
    assert ir["status"] == "NOT_FOUND"
    assert ir["kind"] == "requirement_contract"
    assert ir["reference"] == "REQ-NOPE"
    assert "no contract-shaped record" in ir["reason"]


def test_input_ir_ignores_a_record_that_does_not_declare_the_contract_shape(tmp_path):
    p = tmp_path / "requirements.json"
    p.write_text(json.dumps({"requirements": [
        {"req_id": "REQ-USB-LPM-001", "spec_ref": "s", "feature": "f",
         "expected_behavior": "b", "verification_method": "directed",
         "coverage_goal": "cg"}]}), encoding="utf-8")
    ir = build_input_ir(requirements_path=p, requirement_id="REQ-USB-LPM-001")
    assert ir["status"] == "NOT_FOUND"


def test_input_ir_invalid_when_the_cited_record_is_not_schema_valid(tmp_path):
    p = tmp_path / "requirements.json"
    bad = clean_requirement_record()
    del bad["checker"]
    p.write_text(json.dumps({"requirements": [bad]}), encoding="utf-8")
    ir = build_input_ir(requirements_path=p, requirement_id="REQ-USB-LPM-001")
    assert ir["status"] == "INVALID"
    assert ir["downstream_consumable"] is None
    assert "not a schema-valid requirement contract" in ir["reason"]


def test_input_ir_not_found_when_the_requirements_document_cannot_be_read(tmp_path):
    ir = build_input_ir(requirements_path=tmp_path / "absent.json",
                        requirement_id="REQ-1")
    assert ir["status"] == "NOT_FOUND"
    assert "could not be read" in ir["reason"]
    assert ir["source"]["sha256"] is None


def test_input_ir_file_form_records_a_real_digest_and_size(tmp_path):
    p = tmp_path / "spec_extract.md"
    p.write_bytes(b"# driving input\n")
    ir = build_input_ir(input_file_path=p)
    assert ir["status"] == "RESOLVED"
    assert ir["kind"] == "file"
    assert ir["source"]["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert ir["source"]["bytes"] == p.stat().st_size
    assert ir["contract_schema_version"] is None
    assert ir["downstream_consumable"] is None


def test_input_ir_file_form_not_found_still_records_the_declared_path(tmp_path):
    ir = build_input_ir(input_file_path=tmp_path / "gone.md")
    assert ir["status"] == "NOT_FOUND"
    assert ir["source"]["path"].endswith("gone.md")
    assert ir["source"]["sha256"] is None


def test_input_ir_undeclared_is_not_declared_and_names_both_forms():
    ir = build_input_ir()
    assert ir["status"] == "NOT_DECLARED"
    assert ir["kind"] is None
    assert "--input-requirements" in ir["reason"] and "--input-file" in ir["reason"]


def test_declaring_both_input_forms_is_a_loud_caller_error(tmp_path, requirements_file):
    with pytest.raises(InputIrDeclarationError):
        build_input_ir(requirements_path=requirements_file,
                       requirement_id="REQ-USB-LPM-001",
                       input_file_path=tmp_path / "x.md")


def test_half_declaring_the_contract_form_is_a_loud_caller_error(requirements_file):
    with pytest.raises(InputIrDeclarationError):
        build_input_ir(requirements_path=requirements_file)
    with pytest.raises(InputIrDeclarationError):
        build_input_ir(requirement_id="REQ-USB-LPM-001")


# ---------------------------------------------------------------------------
# honest absence by default; strict contract only on request
# ---------------------------------------------------------------------------

def test_generation_without_any_declaration_still_succeeds_and_declares_nothing():
    """A project that has not adopted provenance is never retroactively
    failed -- every unanswered part is recorded, not fabricated."""
    manifest = generate_env_manifest()
    generator = manifest["generator"]
    assert generator["agent"]["status"] == "NOT_DECLARED"
    assert generator["input_ir"]["status"] == "NOT_DECLARED"
    assert generator["repository_sha"]["project"]["status"] == "NOT_DECLARED"
    # ... but the two facts that need nobody's cooperation are still real.
    assert generator["tool_version"] == dv_harness.__version__
    assert generator["repository_sha"]["harness"]["sha"] == real_head_sha(ROOT)


def test_require_provenance_names_every_gap_at_once():
    with pytest.raises(GenerationProvenanceIncompleteError) as exc:
        generate_env_manifest(require_provenance=True)
    message = str(exc.value)
    assert "generator.agent" in message
    assert "generator.input_ir" in message


def test_require_provenance_passes_on_a_fully_declared_run(requirements_file):
    manifest = generate_env_manifest(
        generated_by="debug-agent",
        input_requirements_path=requirements_file,
        input_requirement_id="REQ-USB-LPM-001",
        require_provenance=True,
    )
    assert provenance_gaps(manifest) == []


def test_a_declared_but_unresolved_agent_is_still_a_provenance_gap(requirements_file):
    manifest = generate_env_manifest(
        generated_by="totally-invented-agent",
        input_requirements_path=requirements_file,
        input_requirement_id="REQ-USB-LPM-001",
    )
    gaps = provenance_gaps(manifest)
    assert len(gaps) == 1 and "totally-invented-agent" in gaps[0]
    with pytest.raises(GenerationProvenanceIncompleteError):
        assert_generation_provenance_complete(manifest)


def test_an_unresolved_input_ir_is_a_provenance_gap(tmp_path):
    manifest = generate_env_manifest(generated_by="debug-agent",
                                     input_file_path=tmp_path / "absent.md")
    gaps = provenance_gaps(manifest)
    assert len(gaps) == 1 and "generator.input_ir" in gaps[0]


# ---------------------------------------------------------------------------
# schema: the tuple is REQUIRED, so a pre-1.2 manifest fails loudly
# ---------------------------------------------------------------------------

def test_a_schema_1_1_shaped_manifest_is_refused_rather_than_silently_accepted(tmp_path):
    """The 1.1 -> 1.2 bump is breaking on purpose, exactly as 1.0 -> 1.1 was:
    env_manifest.py is the sole writer, so the fix is to regenerate. A manifest
    that silently loaded without provenance would present an untraceable
    artifact as a traceable one."""
    manifest = generate_env_manifest()
    stale = json.loads(json.dumps(manifest))
    stale["schema_version"] = "1.1"
    stale["generator"] = {"tool": "dv_harness.env_manifest", "version": "1.1"}
    p = tmp_path / "stale.json"
    p.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(env_manifest.EnvManifestValidationError):
        load_env_manifest(p)


@pytest.mark.parametrize("dropped", ["tool_version", "agent", "input_ir", "repository_sha"])
def test_every_provenance_key_is_required_by_the_schema(dropped):
    manifest = generate_env_manifest()
    del manifest["generator"][dropped]
    with pytest.raises(env_manifest.EnvManifestValidationError):
        env_manifest.validate_env_manifest(manifest)


def test_the_schema_refuses_an_invented_agent_resolution_value():
    manifest = generate_env_manifest(generated_by="debug-agent")
    manifest["generator"]["agent"]["resolution"] = "TRUSTED"
    with pytest.raises(env_manifest.EnvManifestValidationError):
        env_manifest.validate_env_manifest(manifest)


# ---------------------------------------------------------------------------
# diffability, narrowed honestly
# ---------------------------------------------------------------------------

def test_regeneration_at_the_same_commit_from_unchanged_inputs_is_still_byte_identical(
        tmp_path, requirements_file):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    kwargs = dict(generated_by="debug-agent",
                  input_requirements_path=requirements_file,
                  input_requirement_id="REQ-USB-LPM-001")
    generate_and_write(a, **kwargs)
    generate_and_write(b, **kwargs)
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")
    assert "generated_at" not in a.read_text(encoding="utf-8")


def test_a_moved_harness_commit_is_the_only_new_source_of_diff(monkeypatch, tmp_path):
    """The narrowing this change makes to the diffability contract, stated as a
    test: a different harness commit produces a different manifest, and it
    differs in exactly the field that says so."""
    before = generate_env_manifest(generated_by="debug-agent")
    monkeypatch.setattr(change_impact, "resolve_sha", lambda root, rev: "f" * 40)
    after = generate_env_manifest(generated_by="debug-agent")
    assert before != after
    before["generator"]["repository_sha"]["harness"]["sha"] = "f" * 40
    assert before == after


# ---------------------------------------------------------------------------
# the provenance reaches the Blackboard topic a stage actually reads
# ---------------------------------------------------------------------------

def test_blackboard_summary_carries_the_provenance_tuple(requirements_file):
    manifest = generate_env_manifest(
        generated_by="debug-agent",
        input_requirements_path=requirements_file,
        input_requirement_id="REQ-USB-LPM-001")
    summary = env_manifest.summarize_for_blackboard(manifest, manifest_path="x/env.manifest.json")
    prov = summary["generation_provenance"]
    assert prov == generation_provenance(manifest)
    assert prov["agent_identifier"] == "debug-agent"
    assert prov["agent_resolution"] == "AGENT_PROFILE"
    assert prov["input_ir_reference"] == "REQ-USB-LPM-001"
    assert prov["harness_sha"] == real_head_sha(ROOT)
    assert prov["tool_version"] == dv_harness.__version__


# ---------------------------------------------------------------------------
# the real CLI front door
# ---------------------------------------------------------------------------

def _cli(tmp_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness", "--project-root", str(tmp_path),
         "env-manifest", "generate", "--out", str(tmp_path / "env.manifest.json"), *extra],
        capture_output=True, text=True, cwd=str(ROOT))


def test_cli_generate_records_real_provenance(tmp_path, requirements_file):
    r = _cli(tmp_path, "--generated-by", "debug-agent",
             "--input-requirements", str(requirements_file),
             "--input-requirement-id", "REQ-USB-LPM-001",
             "--require-provenance")
    assert r.returncode == 0, r.stdout + r.stderr
    written = json.loads((tmp_path / "env.manifest.json").read_text(encoding="utf-8"))
    generator = written["generator"]
    assert generator["agent"]["identifier"] == "debug-agent"
    assert generator["agent"]["resolution"] == "AGENT_PROFILE"
    assert generator["input_ir"]["reference"] == "REQ-USB-LPM-001"
    assert generator["input_ir"]["downstream_consumable"] is True
    assert generator["repository_sha"]["harness"]["sha"] == real_head_sha(ROOT)
    assert generator["tool_version"] == dv_harness.__version__


def test_cli_require_provenance_refuses_an_undeclared_run(tmp_path):
    r = _cli(tmp_path, "--require-provenance")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "generation provenance is incomplete" in (r.stdout + r.stderr)
    assert not (tmp_path / "env.manifest.json").exists()


def test_cli_without_require_provenance_still_generates_and_records_absences(tmp_path):
    r = _cli(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    written = json.loads((tmp_path / "env.manifest.json").read_text(encoding="utf-8"))
    assert written["generator"]["agent"]["status"] == "NOT_DECLARED"
    assert written["generator"]["repository_sha"]["harness"]["status"] == "RESOLVED"
