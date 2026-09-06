"""Tests for dv_harness/requirement_risk_ir.py.

`change_frequency` is exercised against a REAL throwaway git repository with
real commits (built via subprocess in this file, mirroring
test_trend_analysis.py's `rtl_repo` fixture) -- never mocked. Every other
factor is exercised through real dataclass/return-value behavior: no
producer is invented for `bug_history`, and the four declared factors are
checked against real caller-supplied dicts, including invalid ones.
"""
import json
import subprocess

import pytest

from dv_harness import requirement_risk_ir as rri


def _git(repo, *args):
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


@pytest.fixture
def git_repo(tmp_path):
    """A REAL git repository with a real, known commit history touching one
    tracked file a known number of times."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "risk-ir test")

    def commit(rel_path, text, msg):
        p = repo / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", msg)

    # hot.sv: 4 real commits -> bucket 3 (3-5 commits)
    commit("rtl/hot.sv", "module hot; endmodule\n", "hot v1")
    commit("rtl/hot.sv", "module hot; wire a; endmodule\n", "hot v2")
    commit("rtl/hot.sv", "module hot; wire a,b; endmodule\n", "hot v3")
    commit("rtl/hot.sv", "module hot; wire a,b,c; endmodule\n", "hot v4")
    # cold.sv: 1 real commit -> bucket 2 (1-2 commits)
    commit("rtl/cold.sv", "module cold; endmodule\n", "cold v1")
    return repo


# --------------------------------------------------------------------------
# change_frequency -- the one MEASURED factor
# --------------------------------------------------------------------------

class TestChangeFrequencyMeasured:
    def test_real_commit_count_is_read_and_bucketed(self, git_repo):
        result = rri.measure_change_frequency("rtl/hot.sv", str(git_repo))
        assert result.status == "MEASURED"
        assert result.score == 3
        assert "4 commit" in result.evidence
        assert "hot.sv" in result.evidence

    def test_different_real_commit_count_gives_different_real_bucket(self, git_repo):
        result = rri.measure_change_frequency("rtl/cold.sv", str(git_repo))
        assert result.status == "MEASURED"
        assert result.score == 2
        assert "1 commit" in result.evidence

    def test_file_with_zero_real_commits_is_measured_not_not_available(self, git_repo):
        """No history for a specific (never-committed) path is itself real
        evidence (commit_count == 0), not a missing-evidence NOT_AVAILABLE."""
        result = rri.measure_change_frequency("rtl/never_committed.sv", str(git_repo))
        assert result.status == "MEASURED"
        assert result.score == 1
        assert "0 commit" in result.evidence


# --------------------------------------------------------------------------
# change_frequency -- honest NOT_AVAILABLE degradation (negative controls)
# --------------------------------------------------------------------------

class TestChangeFrequencyNotAvailable:
    def test_missing_inputs_are_not_available(self):
        result = rri.measure_change_frequency(None, None)
        assert result.status == "NOT_AVAILABLE"
        assert result.score is None

    def test_nonexistent_project_root_is_not_available(self, tmp_path):
        missing_root = tmp_path / "does_not_exist"
        result = rri.measure_change_frequency("rtl/hot.sv", str(missing_root))
        assert result.status == "NOT_AVAILABLE"
        assert "does not exist" in result.evidence

    def test_directory_that_is_not_a_git_repo_is_not_available(self, tmp_path):
        plain_dir = tmp_path / "not_a_repo"
        plain_dir.mkdir()
        (plain_dir / "rtl").mkdir()
        (plain_dir / "rtl" / "hot.sv").write_text("module hot; endmodule\n", encoding="utf-8")
        result = rri.measure_change_frequency("rtl/hot.sv", str(plain_dir))
        assert result.status == "NOT_AVAILABLE"
        assert result.score is None
        # never silently defaults to a fabricated score
        assert "git" in result.evidence.lower()


# --------------------------------------------------------------------------
# bug_history -- must ALWAYS be NOT_AVAILABLE, never invented
# --------------------------------------------------------------------------

class TestBugHistoryNeverInvented:
    def test_bug_history_is_always_not_available(self):
        result = rri.bug_history_factor()
        assert result.status == "NOT_AVAILABLE"
        assert result.score is None
        assert "no" in result.evidence.lower()

    def test_bug_history_ignores_any_caller_supplied_value(self, git_repo):
        """Even if a caller's requirement_facts happens to carry a
        'bug_history' key, this module must never treat it as a legitimate
        declaration -- there is no producer and no declaration path."""
        facts = {"bug_history": 5, "bug_history_rationale": "looks risky"}
        profile = rri.assess_requirement_risk(facts, source_file="rtl/hot.sv",
                                               project_root=str(git_repo))
        assert profile.factors["bug_history"].status == "NOT_AVAILABLE"
        assert profile.factors["bug_history"].score is None


# --------------------------------------------------------------------------
# declared factors -- caller-supplied only, never self-measured
# --------------------------------------------------------------------------

class TestDeclaredFactors:
    def test_valid_declared_value_is_reported_as_declared(self):
        result = rri.declared_factor({"complexity": 4}, "complexity")
        assert result.status == "DECLARED"
        assert result.score == 4
        assert "caller-declared" in result.evidence

    def test_declared_value_carries_optional_rationale(self):
        facts = {"customer_impact": 5, "customer_impact_rationale": "field escalation history"}
        result = rri.declared_factor(facts, "customer_impact")
        assert result.status == "DECLARED"
        assert "field escalation history" in result.evidence

    def test_missing_declared_value_is_not_available_not_defaulted(self):
        result = rri.declared_factor({}, "observability_difficulty")
        assert result.status == "NOT_AVAILABLE"
        assert result.score is None
        assert "not declared" in result.evidence

    def test_out_of_range_declared_value_is_not_available(self):
        result = rri.declared_factor({"protocol_criticality": 9}, "protocol_criticality")
        assert result.status == "NOT_AVAILABLE"
        assert result.score is None
        assert "outside the valid" in result.evidence

    def test_non_numeric_declared_value_is_not_available(self):
        result = rri.declared_factor({"complexity": "very high"}, "complexity")
        assert result.status == "NOT_AVAILABLE"
        assert result.score is None

    def test_boolean_declared_value_is_rejected_not_coerced(self):
        """bool is a Python int subclass; True/False must not silently pass
        through as a risk score of 1/0."""
        result = rri.declared_factor({"complexity": True}, "complexity")
        assert result.status == "NOT_AVAILABLE"
        assert result.score is None

    def test_duck_typed_object_attribute_access_also_works(self):
        class Facts:
            complexity = 3
        result = rri.declared_factor(Facts(), "complexity")
        assert result.status == "DECLARED"
        assert result.score == 3


# --------------------------------------------------------------------------
# full assess_requirement_risk() profile
# --------------------------------------------------------------------------

class TestAssessRequirementRisk:
    def test_full_profile_mixes_measured_declared_and_not_available_honestly(self, git_repo):
        facts = {
            "requirement_id": "REQ-042",
            "complexity": 4,
            "customer_impact": 5,
            "observability_difficulty": 2,
            "protocol_criticality": 3,
            # bug_history deliberately omitted -- must stay NOT_AVAILABLE regardless
        }
        profile = rri.assess_requirement_risk(facts, source_file="rtl/hot.sv",
                                               project_root=str(git_repo))
        assert profile.requirement_id == "REQ-042"
        assert profile.factors["complexity"].status == "DECLARED"
        assert profile.factors["change_frequency"].status == "MEASURED"
        assert profile.factors["change_frequency"].score == 3
        assert profile.factors["bug_history"].status == "NOT_AVAILABLE"
        assert profile.available_factor_count == 5
        assert profile.missing_factors == ["bug_history"]
        assert profile.coverage == "5/6"
        # composite is the mean of exactly the 5 available scores
        expected = round((4 + 3 + 5 + 2 + 3) / 5, 2)
        assert profile.composite_score == expected

    def test_profile_with_no_evidence_at_all_reports_zero_available_and_no_composite(self):
        profile = rri.assess_requirement_risk({})
        assert profile.available_factor_count == 0
        assert profile.composite_score is None
        assert set(profile.missing_factors) == set(rri.RISK_FACTORS)
        assert profile.coverage == "0/6"

    def test_requirement_id_falls_back_to_id_key_then_unknown(self):
        assert rri.assess_requirement_risk({"id": "R7"}).requirement_id == "R7"
        assert rri.assess_requirement_risk({}).requirement_id == "UNKNOWN"

    def test_profile_to_dict_round_trips_through_json(self, git_repo):
        facts = {"requirement_id": "REQ-1", "complexity": 2}
        profile = rri.assess_requirement_risk(facts, source_file="rtl/cold.sv",
                                               project_root=str(git_repo))
        blob = json.dumps(profile.to_dict())
        restored = json.loads(blob)
        assert restored["requirement_id"] == "REQ-1"
        assert restored["factors"]["change_frequency"]["status"] == "MEASURED"
        assert restored["factors"]["bug_history"]["status"] == "NOT_AVAILABLE"

    def test_format_risk_report_lists_all_six_factors_in_order(self, git_repo):
        profile = rri.assess_requirement_risk({"complexity": 3}, source_file="rtl/hot.sv",
                                               project_root=str(git_repo))
        text = rri.format_risk_report(profile)
        seen_order = [name for name in rri.RISK_FACTORS if name in text]
        assert seen_order == list(rri.RISK_FACTORS)
        assert "missing:" in text
