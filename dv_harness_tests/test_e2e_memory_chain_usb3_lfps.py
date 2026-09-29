"""Phase 23 as a REGRESSION net, not a one-off script (2026-09-04).

The synthetic USB3 Polling.LFPS end-to-end chain (failure -> memory search ->
hypothesis -> evidence -> confidence -> root cause -> verified fix -> Job
Memory -> Engineering Memory -> promotion evaluation -> wiki links -> git
traceability -> session save/restore) was real and reproducible, but lived
only as `.work/e2e_usb3_lfps_demo.py`: nothing under `dv_harness_tests/` or
`.claude/` referenced it, so a regression anywhere along the chain would have
been caught only if a human remembered to re-run that script by hand. CLAUDE.md's
Methodology Consolidation Rule says a process proven once in a session becomes a
permanent, automatically-run Harness asset. This is that asset.

Every test below runs the REAL chain (`dv_harness_tests.e2e_memory_chain_usb3_
lfps.run_memory_chain()`, the same driver the demo narrates) against a real
isolated project dir with real git integration -- no mocked router, vault,
scorer or provider. What is synthetic is the input failure data only.

Deliberately NOT asserted: a real PASS/FAIL verdict for the fix. That needs a
real LSF job and a real VCS run on the Linux server, which this LOCAL_ANALYSIS
test does not perform; `test_step_7_real_execution_half_stays_honestly_partial`
pins that boundary so it cannot quietly be presented as a real regression result.

The chain is expensive relative to a unit test (real git commits, real vault
writes, a session save/restore), so it runs ONCE per module through a
module-scoped fixture and each test asserts one link of the result.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dv_harness.inference import score_confidence
from dv_harness.memory import MemoryStore
from dv_harness.memory_router import ORGANIZATIONAL_MIN_CONFIRMATIONS
from dv_harness_tests.e2e_memory_chain_usb3_lfps import (
    CONFIDENCE_INPUTS_POST_FIX, EVIDENCE, EXECUTION_MODE, FIX, ROOT_CAUSE,
    SESSION_NAME, STEP_7_REAL_EXECUTION_STATUS, default_cfg, run_memory_chain,
)


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    project_root = tmp_path_factory.mktemp("e2e_usb3_lfps")
    result = run_memory_chain(project_root, cfg=default_cfg())
    result["project_root"] = project_root
    return result


def test_chain_declares_local_analysis_execution_mode(chain):
    assert chain["execution_mode"] == EXECUTION_MODE == "LOCAL_ANALYSIS"


def test_memory_search_on_a_fresh_vault_reports_zero_not_everything(chain):
    # A search that "finds" prior knowledge on an empty vault would make every
    # later hypothesis look pre-confirmed. Honest zero is the assertion.
    assert chain["search_result"]["ok"] is True
    assert chain["search_result"]["count"] == 0
    assert chain["search_result"].get("results", []) == []


def test_failure_signature_carries_the_real_terminal_signature(chain):
    sig = chain["failure_signature"]
    assert sig["protocol"] == "USB"
    assert sig["terminal_signature"] == "POLLING_LFPS_TIMEOUT"
    assert sig["uvm_error_count"] == 1 and sig["uvm_fatal_count"] == 0
    # Derived by build_failure_signature(), never asked of the caller: a real
    # terminal_signature marker is one of the terminal conditions
    # evaluate_auto_kill() already treats as abnormal, UVM_FATAL or not.
    assert sig["abnormal_termination"] is True


def test_confidence_is_the_real_scorer_not_a_typed_in_level(chain):
    # Recompute independently from the same inputs: the chain must not be able
    # to report a level the scorer would not produce.
    recomputed = score_confidence(**CONFIDENCE_INPUTS_POST_FIX)
    assert chain["confidence_post_fix"] == recomputed
    assert chain["confidence_post_fix"]["level"] == "HIGH"
    assert chain["confidence_pre_fix"]["level"] in {"HIGH", "MEDIUM", "LOW"}


def test_gap_and_next_best_action_are_derived_not_hardcoded(chain):
    assert chain["gaps"] == ["USB3 LTSSM/LFPS/TS patterns"]
    nba = chain["next_best_action"]
    assert isinstance(nba, list) and nba, "next_best_action() returned nothing usable"
    # One action per identified gap, each citing the real source it came from
    # rather than a generic "investigate further" string.
    assert [a["gap"] for a in nba] == chain["gaps"]
    assert all(a["source"] and a["suggested_action"] for a in nba)


def test_job_result_and_failed_attempt_both_land_in_job_memory_only(chain):
    assert chain["job_result"]["destination"] == "JOB_MEMORY"
    # The FAIL attempt is the case that must never promote: a debug attempt
    # that did not pass is not knowledge, by construction.
    assert chain["failed_attempt_result"]["destination"] == "JOB_MEMORY"


def test_verified_root_cause_clears_the_engineering_admission_gate(chain):
    assert chain["engineering_result"]["destination"] == "ENGINEERING_MEMORY"
    assert "engineering_admission_rejected" not in chain["engineering_result"]
    rec = MemoryStore(chain["project_root"]).get(chain["engineering_memory_id"])
    assert rec["root_cause"] == ROOT_CAUSE
    assert rec["fix"] == FIX
    assert rec["evidence"] == EVIDENCE
    assert rec["confidence"] == "HIGH"


def test_organizational_promotion_is_refused_for_a_single_confirmation(chain):
    promotion = chain["promotion"]
    assert promotion["promoted"] is False
    assert promotion["reason"] == "INSUFFICIENT_CONFIRMATION"
    assert promotion["confirmation_count"] == 0
    assert promotion["required"] == ORGANIZATIONAL_MIN_CONFIRMATIONS == 2


def test_wiki_links_resolve_forward_and_back_between_the_two_notes(chain):
    assert chain["job_vault_note_id"] in chain["forward_links"]
    assert chain["engineering_vault_note_id"] in chain["backlinks"]
    assert any(f"[[{chain['job_vault_note_id']}]]" in line
               for line in chain["engineering_note_wiki_lines"])


def test_vault_note_confidence_matches_the_measured_confidence(chain):
    # A vault note reading UNKNOWN over a HIGH-confidence verified fix is a
    # traceability break between the JSON system of record and its
    # human-browsable mirror.
    assert chain["engineering_note_confidence"] == chain["confidence_post_fix"]["level"]


def test_knowledge_commit_sha_resolves_to_a_real_commit_in_the_vault(chain):
    sha = chain["knowledge_commit_sha"]
    assert sha, "no knowledge_commit_sha written back onto the Engineering record"
    # `git log --oneline` abbreviates; confirm the full SHA is a real object in
    # this vault rather than trusting the string on the record.
    resolved = subprocess.run(["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
                              cwd=chain["vault_path"], capture_output=True, text=True)
    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout.strip() == sha
    assert chain["vault_git_log"].strip().splitlines()[0].startswith(sha[:7])
    assert "memory(USB):" in chain["vault_git_log"]


def test_session_restore_resumes_this_run_not_a_generic_summary(chain):
    summary = chain["resume_summary"]
    assert "RE_AUDIT" in summary
    assert chain["confidence_post_fix"]["level"] in summary
    assert (Path(chain["project_root"]) / ".dv-harness" / "sessions" / SESSION_NAME).exists()


def test_step_7_real_execution_half_stays_honestly_partial(chain):
    # The disclosed boundary: no LSF job, no VCS run. If this ever starts
    # claiming a real verdict without a real run behind it, that is the
    # regression this test exists to catch.
    assert chain["real_execution_status"] == STEP_7_REAL_EXECUTION_STATUS
    assert STEP_7_REAL_EXECUTION_STATUS == "PARTIAL_NOT_PERFORMED"


def test_no_raw_log_or_waveform_payload_reaches_the_vault_note(chain):
    # CLAUDE.md "Never": cite a path/offset/signature, never embed a giant log
    # or raw FSDB content. Every evidence entry must stay a citation.
    notes = [p for p in Path(chain["vault_path"]).rglob("*.md")
             if chain["engineering_vault_note_id"] in p.name]
    assert notes, "no engineering vault note was written"
    for path in notes:
        body = path.read_text(encoding="utf-8")
        assert ".fsdb" not in body
        assert "UVM_ERROR @" not in body.replace(chain["sim_log_excerpt"], "")
        assert len(body) < 20000, "vault note grew to log-dump size"


def test_the_demo_script_and_this_test_drive_the_same_chain():
    # The consolidation itself: `.work/e2e_usb3_lfps_demo.py` must narrate this
    # module's driver rather than keep a second, drift-prone copy of the chain.
    demo = (Path(__file__).resolve().parents[1] / ".work" / "e2e_usb3_lfps_demo.py")
    assert demo.exists()
    text = demo.read_text(encoding="utf-8")
    assert "e2e_memory_chain_usb3_lfps" in text
    assert "run_memory_chain" in text
