"""Tests for dv_harness/vip_api_card.py -- spec section 187's VIPApiCard
artifact and the coded "if the API cannot be proven -> UNKNOWN / BLOCKED"
enforcement.

Discipline, the same one test_power_intent.py / test_uvm_structural_lint.py
use:

  1. A CLEAN generated-sequence fixture (fixtures/vip_api/demo_env_seq.sv)
     validated against a REAL `vip_symbol_index` built by the REAL indexer over
     the REAL synthetic VIP source this repo already ships
     (examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv) reports status
     PROVEN with zero BLOCKED and zero UNPROVABLE cards, and every VIPApiCard
     carries the REAL file:line the indexer recorded. A validator that fires on
     correct, fully-provable generated code would be unusable no matter how
     many fabrications it catches.
  2. Every decision rule is then driven by MUTATING that same clean source one
     fabrication at a time, so each assertion proves the validator caught THAT
     specific injected defect. The clean baseline being all-PROVEN is what
     makes that inference valid.
  3. The false-positive directions are tested explicitly and separately,
     because a blocking check that cries wolf is worse than none: a class the
     validated sources declare themselves, a base-library method, an
     unresolvable receiver, a fabricated name that appears only inside a
     comment or a string, an inheritance chain that leaves the index, and a
     REAL environment this project's own generator produced.
  4. The integration is exercised through the REAL entry points: the REAL
     `create_environment()` CREATE ENVIRONMENT dispatch (both non-blocking and
     `strict_vip_api`), the REAL `dv-harness vip-api-check` CLI subprocess, and
     the REAL `python -m dv_harness.vip_api_card` module subprocess.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import vip_api_card as vac
from dv_harness import vip_symbol_index as vsi

REPO_ROOT = Path(__file__).resolve().parents[1]
VIP_SRC_ROOT = REPO_ROOT / "examples" / "asset_processing" / "inputs" / "vip_src"
VIP_SRC_BASE = REPO_ROOT / "examples" / "asset_processing" / "inputs"
FIXTURE = Path(__file__).parent / "fixtures" / "vip_api" / "demo_env_seq.sv"


# ---------------------------------------------------------------------------
# shared real inputs
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def demo_index():
    """A REAL vip_symbol_index over the REAL synthetic VIP source, built by the
    real indexer -- not a hand-written dict. `validate_vip_api_usage()`
    schema-validates whatever it is given, so a fabricated index could not be
    substituted here anyway."""
    return vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)


@pytest.fixture(scope="module")
def clean_source():
    return FIXTURE.read_text(encoding="utf-8")


def _validate(tmp_path, text, index, name="generated_seq.sv", **kw):
    """Write `text` as a generated source and validate it. Every mutation test
    goes through this, so each one differs from the clean baseline by exactly
    the mutation it names."""
    d = tmp_path / "env"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return vac.validate_vip_api_usage([d], index, relative_to=d, **kw)


def _card(report, citation):
    hits = [c for c in report.cards if c.citation == citation]
    assert hits, (f"no VIPApiCard for {citation!r}; got "
                  f"{sorted({c.citation for c in report.cards})}")
    return hits[0]


# ---------------------------------------------------------------------------
# 1. the clean baseline
# ---------------------------------------------------------------------------

def test_clean_generated_sequence_is_fully_proven(tmp_path, demo_index, clean_source):
    report = _validate(tmp_path, clean_source, demo_index)
    assert report.status == vac.PROVEN
    assert report.counts[vac.BLOCKED] == 0
    assert report.counts[vac.UNPROVABLE] == 0
    assert report.counts[vac.PROVEN] > 0


def test_every_proven_card_cites_the_real_indexed_file_and_line(tmp_path, demo_index,
                                                                clean_source):
    """The VIPApiCard artifact's whole point: a PROVEN citation carries the
    REAL location the indexer resolved it to, so section 187's "Manual /
    Source / Class Reference" leg is a citable location and not a claim."""
    report = _validate(tmp_path, clean_source, demo_index)
    vip_text = (VIP_SRC_ROOT / "svt_demo_pkg.sv").read_text(encoding="utf-8").splitlines()
    for card in report.cards:
        if card.status != vac.PROVEN:
            continue
        assert card.resolved_file == "vip_src/svt_demo_pkg.sv"
        assert card.resolved_line is not None
        source_line = vip_text[card.resolved_line - 1]
        target = card.member if card.kind == "METHOD" else card.vip_class
        assert target in source_line, (
            f"{card.citation} resolved to {card.location}, but that line does "
            f"not declare it: {source_line!r}")


def test_method_card_carries_the_real_signature_and_kind(tmp_path, demo_index, clean_source):
    report = _validate(tmp_path, clean_source, demo_index)
    preset = _card(report, "svt_demo_cfg.apply_preset")
    assert preset.status == vac.PROVEN
    assert preset.resolved_kind == "function"
    assert preset.resolved_signature == "(input int preset_id)"
    assert preset.location == "vip_src/svt_demo_pkg.sv:26"
    wait = _card(report, "svt_demo_cfg.wait_for_ready")
    assert wait.resolved_kind == "task"
    assert wait.resolved_signature == "(input int timeout_ns)"


def test_vip_naming_scope_is_derived_from_the_real_index(demo_index):
    assert vac.derive_vip_scope_prefixes(demo_index) == ["svt_"]


# ---------------------------------------------------------------------------
# 2. mutations: each proves one rule caught one injected fabrication
# ---------------------------------------------------------------------------

def test_fabricated_method_name_is_blocked(tmp_path, demo_index, clean_source):
    """The headline case: a call to a method that does not exist on an
    otherwise real, indexed VIP class."""
    mutated = clean_source.replace("cfg.apply_preset(2);", "cfg.apply_prezet(2);")
    assert mutated != clean_source
    report = _validate(tmp_path, mutated, demo_index)
    assert report.status == vac.BLOCKED
    card = _card(report, "svt_demo_cfg.apply_prezet")
    assert card.status == vac.BLOCKED
    assert card.reason == vac.R_METHOD_NOT_INDEXED
    assert card.location is None
    assert card.chain_closed is True
    assert card.inheritance_chain == ["svt_demo_cfg"]
    # and the real call on the same class is still proven, so the finding is
    # attributable to the fabrication rather than to the class being rejected.
    assert _card(report, "svt_demo_cfg.set_defaults").status == vac.PROVEN


def test_fabricated_vip_class_name_is_blocked(tmp_path, demo_index, clean_source):
    mutated = clean_source.replace("svt_demo_cfg cfg;", "svt_demo_turbo_cfg cfg;")
    assert mutated != clean_source
    report = _validate(tmp_path, mutated, demo_index)
    assert report.status == vac.BLOCKED
    card = _card(report, "svt_demo_turbo_cfg")
    assert card.status == vac.BLOCKED
    assert card.reason == vac.R_CLASS_NOT_INDEXED
    # every call made on the fabricated handle is blocked too, for the same
    # reason -- an unprovable class makes every call through it unprovable.
    assert _card(report, "svt_demo_turbo_cfg.apply_preset").reason == vac.R_CLASS_NOT_INDEXED


def test_method_of_the_wrong_vip_class_is_blocked(tmp_path, demo_index, clean_source):
    """`wait_for_ready` is really declared -- on svt_demo_cfg, not on
    svt_demo_transaction. Calling it on the wrong class must not resolve just
    because the name exists somewhere in the index: resolution walks THAT
    class's own inheritance chain, not the whole index."""
    mutated = clean_source.replace("txn.convert2string()", "txn.wait_for_ready(10)")
    assert mutated != clean_source
    report = _validate(tmp_path, mutated, demo_index)
    card = _card(report, "svt_demo_transaction.wait_for_ready")
    assert card.status == vac.BLOCKED
    assert card.reason == vac.R_METHOD_NOT_INDEXED
    # the same name on the class that really declares it still resolves
    assert _card(report, "svt_demo_cfg.wait_for_ready").status == vac.PROVEN


def test_fabricated_scope_resolution_class_is_blocked(tmp_path, demo_index, clean_source):
    mutated = clean_source.replace("svt_demo_transaction::type_id::create",
                                   "svt_demo_txn::type_id::create")
    assert mutated != clean_source
    report = _validate(tmp_path, mutated, demo_index)
    assert report.status == vac.BLOCKED
    card = _card(report, "svt_demo_txn::type_id")
    assert card.status == vac.BLOCKED
    assert card.reason == vac.R_CLASS_NOT_INDEXED


# ---------------------------------------------------------------------------
# 3. false-positive directions -- a blocking check that cries wolf is worse
#    than no check at all
# ---------------------------------------------------------------------------

def test_base_library_method_on_a_vip_handle_is_not_blocked(tmp_path, demo_index,
                                                            clean_source):
    """`cfg.get_full_name()` is uvm_object API. The index does not (and should
    not) contain it, and calling it is not a VIP API citation."""
    report = _validate(tmp_path, clean_source, demo_index)
    card = _card(report, "svt_demo_cfg.get_full_name")
    assert card.status == vac.OUT_OF_SCOPE
    assert card.reason == vac.R_BASE_LIBRARY


def test_class_declared_by_the_validated_sources_is_never_blocked(tmp_path, demo_index,
                                                                  clean_source):
    """A generated environment legitimately names its own classes with the same
    vendor token the VIP index's scope was derived from. Blocking those would
    be pure false positive, so a locally-declared class is out of scope --
    resolved by reusing the real indexer over the validated sources."""
    mutated = clean_source + textwrap.dedent("""
        class svt_demo_project_helper extends uvm_object;
          function void helper_hook();
          endfunction
        endclass

        class demo_env_user_vseq extends demo_env_base_vseq;
          virtual task body();
            svt_demo_project_helper helper;
            helper = new();
            helper.helper_hook();
          endtask
        endclass
        """)
    report = _validate(tmp_path, mutated, demo_index)
    assert "svt_demo_project_helper" in report.local_classes
    card = _card(report, "svt_demo_project_helper.helper_hook")
    assert card.status == vac.OUT_OF_SCOPE
    assert card.reason == vac.R_LOCAL_CLASS
    assert report.status == vac.PROVEN


def test_unresolvable_receiver_is_never_blocked(tmp_path, demo_index, clean_source):
    """`p_sequencer.some_seqr[0].do_thing()` -- the receiver's type is not
    resolvable from any declaration this scan saw. Unresolved is our ignorance,
    not the generator's error, so no card is minted at all."""
    mutated = clean_source.replace(
        "    cfg.set_defaults();",
        "    cfg.set_defaults();\n    p_sequencer.demo_seqr[0].do_something(cfg);")
    report = _validate(tmp_path, mutated, demo_index)
    assert report.status == vac.PROVEN
    assert not [c for c in report.cards if "do_something" in c.citation]


def test_citations_inside_comments_and_strings_are_not_citations(tmp_path, demo_index,
                                                                 clean_source):
    """Generated environments in this repo carry `// evidence: ...` provenance
    comments naming real and adapted VIP symbols. A validator that scanned them
    as code would block on its own provenance trail."""
    mutated = clean_source.replace(
        "  virtual task body();",
        "  /* svt_demo_ghost_cfg ghost; ghost.vanish(); */\n"
        "  // svt_demo_phantom_cfg phantom; phantom.evaporate();\n"
        "  string note = \"svt_demo_spectre_cfg::HAUNT\";\n"
        "  virtual task body();")
    report = _validate(tmp_path, mutated, demo_index)
    assert report.status == vac.PROVEN
    for ghost in ("ghost", "phantom", "spectre"):
        assert not [c for c in report.cards if ghost in c.citation.lower()], ghost


def test_open_inheritance_chain_is_unprovable_not_blocked(tmp_path):
    """An indexed class whose base is neither indexed nor a base-library class
    leaves the world OPEN: the missing part of the hierarchy could declare the
    method, so absence is not provable and must report UNKNOWN, never BLOCKED."""
    vip = tmp_path / "vip"
    vip.mkdir()
    (vip / "part.sv").write_text(textwrap.dedent("""
        class svt_part_ext extends svt_part_hidden_base;
          virtual function void known_call();
          endfunction
        endclass

        class svt_part_other extends uvm_object;
          virtual function void other_call();
          endfunction
        endclass
        """), encoding="utf-8")
    index = vsi.build_symbol_index([vip], "part", relative_to=tmp_path)

    report = _validate(tmp_path, textwrap.dedent("""
        class part_vseq extends uvm_sequence;
          virtual task body();
            svt_part_ext handle;
            handle.unknown_call();
          endtask
        endclass
        """), index)
    card = _card(report, "svt_part_ext.unknown_call")
    assert card.status == vac.UNPROVABLE
    assert card.reason == vac.R_CHAIN_OPEN
    assert card.chain_closed is False
    assert report.status == vac.UNPROVABLE

    # ...while the SAME index blocks the same fabrication on a class whose
    # chain terminates at the UVM base library. The difference is the chain,
    # not the method name.
    blocked = _validate(tmp_path, textwrap.dedent("""
        class part_vseq extends uvm_sequence;
          virtual task body();
            svt_part_other handle;
            handle.unknown_call();
          endtask
        endclass
        """), index, name="other_seq.sv")
    assert _card(blocked, "svt_part_other.unknown_call").status == vac.BLOCKED


def test_real_generated_environment_reports_no_blocked_against_an_unrelated_index(
        demo_index):
    """examples/generated_pcie_uvm_env/ is an environment this project's own
    generator really produced. Its classes are `pcie_*`, entirely outside the
    `svt_` scope this demo index defines, so nothing in it may be blocked --
    an index of one VIP must never manufacture findings against an environment
    that does not use that VIP."""
    env = REPO_ROOT / "examples" / "generated_pcie_uvm_env"
    report = vac.validate_vip_api_usage([env], demo_index, relative_to=REPO_ROOT)
    assert report.files_scanned > 0
    assert report.counts[vac.BLOCKED] == 0
    assert report.counts[vac.UNPROVABLE] == 0
    assert report.status == vac.NOT_AVAILABLE
    assert report.reason == "NO_VIP_API_CITATIONS_FOUND"


# ---------------------------------------------------------------------------
# 4. "we could not check" is never a pass
# ---------------------------------------------------------------------------

def test_missing_index_raises_rather_than_silently_passing(tmp_path):
    with pytest.raises(vac.VipApiValidationError):
        vac.load_index(tmp_path / "nope.json")


def test_empty_index_is_not_available_never_proven(tmp_path, clean_source):
    empty = tmp_path / "empty_vip"
    empty.mkdir()
    (empty / "nothing.sv").write_text("// no classes here\n", encoding="utf-8")
    index = vsi.build_symbol_index([empty], "empty", relative_to=tmp_path)
    report = _validate(tmp_path, clean_source, index)
    assert report.status == vac.NOT_AVAILABLE
    assert report.reason == "VIP_SYMBOL_INDEX_CONTAINS_NO_CLASSES"


def test_missing_source_root_raises(tmp_path, demo_index):
    with pytest.raises(vac.VipApiValidationError):
        vac.validate_vip_api_usage([tmp_path / "does_not_exist"], demo_index)


# ---------------------------------------------------------------------------
# 5. the artifact
# ---------------------------------------------------------------------------

def test_vip_api_cards_artifact_is_written_and_round_trips(tmp_path, demo_index,
                                                           clean_source):
    report = _validate(tmp_path, clean_source, demo_index)
    out = tmp_path / "artifact"
    out.mkdir()
    path = vac.write_vip_api_cards(report, out)
    assert path.name == vac.VIP_API_CARDS_REPORT_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == vac.PROVEN
    assert payload["schema_version"] == vac.SCHEMA_VERSION
    citations = {c["citation"]: c for c in payload["cards"]}
    assert citations["svt_demo_cfg.apply_preset"]["resolved_line"] == 26
    # deterministic: no timestamp, so an unchanged input regenerates identically
    again = vac.write_vip_api_cards(_validate(tmp_path, clean_source, demo_index), out)
    assert again.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 6. the REAL create_environment() wiring
# ---------------------------------------------------------------------------

def _write_seq_env(root: Path, text: str) -> Path:
    out = root / "generated_env"
    (out / "tb" / "seq").mkdir(parents=True, exist_ok=True)
    (out / "tb" / "seq" / "demo_vseq.sv").write_text(text, encoding="utf-8")
    return out


def test_create_environment_runs_the_check_and_writes_the_artifact(tmp_path, demo_index,
                                                                   clean_source):
    """Driven through the REAL CREATE ENVIRONMENT entry point's own helper, on
    a real generated-environment directory, with the real index on disk."""
    from dv_harness.uvm_generator import create_environment as ce

    index_path = tmp_path / "vip_symbol_index.json"
    vsi.save_symbol_index(demo_index, index_path)
    out = _write_seq_env(tmp_path, clean_source)

    payload = ce._run_vip_api_validation(out, {"vip_symbol_index": str(index_path)})
    assert payload["status"] == vac.PROVEN
    written = json.loads((out / vac.VIP_API_CARDS_REPORT_NAME).read_text(encoding="utf-8"))
    assert written["status"] == vac.PROVEN
    assert any(c["citation"] == "svt_demo_cfg.apply_preset" for c in written["cards"])


def test_create_environment_without_a_declared_index_is_not_available(tmp_path,
                                                                      clean_source):
    from dv_harness.uvm_generator import create_environment as ce
    out = _write_seq_env(tmp_path, clean_source)
    payload = ce._run_vip_api_validation(out, {})
    assert payload["status"] == "NOT_AVAILABLE"
    assert payload["reason"] == "NO_VIP_SYMBOL_INDEX_DECLARED_IN_REQUEST"
    assert not (out / vac.VIP_API_CARDS_REPORT_NAME).exists()


def test_create_environment_mistyped_index_does_not_silently_disable_the_check(
        tmp_path, clean_source):
    from dv_harness.uvm_generator import create_environment as ce
    out = _write_seq_env(tmp_path, clean_source)
    payload = ce._run_vip_api_validation(out, {"vip_symbol_index": str(tmp_path / "gone.json")})
    assert payload["status"] == "NOT_AVAILABLE"
    assert payload["reason"] == "VIP_SYMBOL_INDEX_UNREADABLE"


def test_create_environment_non_blocking_by_default_but_strict_raises(tmp_path, demo_index,
                                                                      clean_source):
    from dv_harness.uvm_generator import create_environment as ce

    index_path = tmp_path / "vip_symbol_index.json"
    vsi.save_symbol_index(demo_index, index_path)
    out = _write_seq_env(tmp_path, clean_source.replace("cfg.apply_preset(2);",
                                                        "cfg.apply_prezet(2);"))

    # default: recorded, returned, and NOT fatal -- a new check must not turn a
    # previously-working generation into a hard failure on its own.
    payload = ce._run_vip_api_validation(out, {"vip_symbol_index": str(index_path)})
    assert payload["status"] == vac.BLOCKED
    assert (out / vac.VIP_API_CARDS_REPORT_NAME).exists()

    # opted in: section 187's stop condition as a raised error.
    with pytest.raises(ce.VipApiUnprovableError) as excinfo:
        ce._run_vip_api_validation(out, {"vip_symbol_index": str(index_path),
                                         "strict_vip_api": True})
    assert excinfo.value.reason == "VIP_API_UNPROVABLE_BLOCKED"
    assert "svt_demo_cfg.apply_prezet" in excinfo.value.detail["summary"]


def test_create_environment_end_to_end_carries_vip_api_validation(tmp_path, demo_index):
    """The full REAL create_environment() dispatch, SUBSYSTEM_MODE, asserting
    the new field reaches the caller's result alongside structural_lint."""
    from dv_harness.uvm_generator.create_environment import create_environment

    index_path = tmp_path / "vip_symbol_index.json"
    vsi.save_symbol_index(demo_index, index_path)
    out = tmp_path / "env"
    result = create_environment(tmp_path, {"protocol": "demo",
                                           "vip_symbol_index": str(index_path)}, out)
    assert result["environment_mode"] == "SUBSYSTEM_MODE"
    assert "vip_api_validation" in result
    # The generated skeleton cites no svt_ symbols, so the honest answer is
    # "nothing to decide" -- never a fabricated PROVEN.
    assert result["vip_api_validation"]["status"] in (vac.PROVEN, "NOT_AVAILABLE")
    assert result["vip_api_validation"]["counts"].get(vac.BLOCKED, 0) == 0


# ---------------------------------------------------------------------------
# 7. the REAL CLI entry points
# ---------------------------------------------------------------------------

def _module_cli(*args):
    return subprocess.run([sys.executable, "-m", "dv_harness.vip_api_card", *args],
                          cwd=REPO_ROOT, capture_output=True, text=True)


def _harness_cli(*args):
    return subprocess.run([sys.executable, "-m", "dv_harness.cli", "vip-api-check", *args],
                          cwd=REPO_ROOT, capture_output=True, text=True)


def test_module_cli_exit_codes(tmp_path, demo_index, clean_source):
    index_path = tmp_path / "index.json"
    vsi.save_symbol_index(demo_index, index_path)
    clean = tmp_path / "clean.sv"
    clean.write_text(clean_source, encoding="utf-8")
    bad = tmp_path / "bad.sv"
    bad.write_text(clean_source.replace("cfg.apply_preset(2);", "cfg.apply_prezet(2);"),
                   encoding="utf-8")

    ok = _module_cli("--source", str(clean), "--index", str(index_path))
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "PROVEN" in ok.stdout

    blocked = _module_cli("--source", str(bad), "--index", str(index_path))
    assert blocked.returncode == 1, blocked.stdout + blocked.stderr
    assert "svt_demo_cfg.apply_prezet" in blocked.stdout
    assert vac.R_METHOD_NOT_INDEXED in blocked.stdout

    missing = _module_cli("--source", str(clean), "--index", str(tmp_path / "gone.json"))
    assert missing.returncode == 2


def test_harness_cli_blocks_and_writes_the_artifact(tmp_path, demo_index, clean_source):
    index_path = tmp_path / "index.json"
    vsi.save_symbol_index(demo_index, index_path)
    env = tmp_path / "env"
    env.mkdir()
    (env / "seq.sv").write_text(
        clean_source.replace("svt_demo_cfg cfg;", "svt_demo_turbo_cfg cfg;"),
        encoding="utf-8")

    res = _harness_cli("--source", str(env), "--index", str(index_path),
                       "--out-dir", str(env), "--relative-to", str(env))
    assert res.returncode == 1, res.stdout + res.stderr
    assert vac.R_CLASS_NOT_INDEXED in res.stdout
    payload = json.loads((env / vac.VIP_API_CARDS_REPORT_NAME).read_text(encoding="utf-8"))
    assert payload["status"] == vac.BLOCKED


def test_harness_cli_unprovable_is_reported_and_only_fatal_when_strict(tmp_path):
    vip = tmp_path / "vip"
    vip.mkdir()
    (vip / "part.sv").write_text(textwrap.dedent("""
        class svt_part_ext extends svt_part_hidden_base;
          virtual function void known_call();
          endfunction
        endclass

        class svt_part_two extends svt_part_hidden_base;
          virtual function void second_call();
          endfunction
        endclass
        """), encoding="utf-8")
    index = vsi.build_symbol_index([vip], "part", relative_to=tmp_path)
    index_path = tmp_path / "index.json"
    vsi.save_symbol_index(index, index_path)
    src = tmp_path / "seq.sv"
    src.write_text(textwrap.dedent("""
        class part_vseq extends uvm_sequence;
          virtual task body();
            svt_part_ext handle;
            handle.unknown_call();
          endtask
        endclass
        """), encoding="utf-8")

    lenient = _harness_cli("--source", str(src), "--index", str(index_path))
    assert lenient.returncode == 0, lenient.stdout + lenient.stderr
    assert "UNPROVABLE" in lenient.stdout
    assert vac.R_CHAIN_OPEN in lenient.stdout

    strict = _harness_cli("--source", str(src), "--index", str(index_path),
                          "--strict-unprovable")
    assert strict.returncode == 3, strict.stdout + strict.stderr
