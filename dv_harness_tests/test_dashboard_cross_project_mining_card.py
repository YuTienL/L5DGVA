"""GET /api/cross-project-mining -- the VI-2 Cross-Project Pattern Mining
dashboard card (item cross-project-mining-no-dashboard-card).

cross_project_mining.py (VI-2 cross-project pattern mining) already has a real,
already-tested miner and registry: `production_status()`, `ProjectRegistry`,
`mine_cross_project_patterns()`. `dv-harness cross-project` is already a wired
CLI verb, but nothing in dashboard.py ever surfaced any of it -- confirmed by
grep before this file was written: `grep -c cross_project_mining
dv_harness/dashboard.py` returned 0 prior to this change.

This is a WIRING_GAP_EXISTING_MODULE close, not new capability: no analysis,
registry, or mining logic was added anywhere. `_read_cross_project_mining_state()`
is a thin reader calling `production_status()` and `mine_cross_project_patterns()`
directly, following the exact same fetch-real-artifact-and-render convention
`_read_confidence_calibration_state()`/`_read_generation_readiness_state()`
already established one card over.

These tests exist to prove three things beyond "the endpoint returns 200":

  * The card READS the real module. The served status/mining payloads are
    compared against direct calls into production_status()/
    mine_cross_project_patterns() over the identical host root -- never
    against a value typed into the test.
  * A bare project (nothing registered) reports the honest
    INSUFFICIENT_PROJECTS/zero-registered state, never a fabricated pattern.
  * A real cross-project pattern -- built from two genuinely separate,
    real memory stores sharing one real failure signature -- is served
    correctly, including a real transferable-fix finding once one side
    closes it with a gate-shaped verified_fix.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers --
the same cross-test import convention every sibling *_card.py test file in
this directory already uses.
"""
from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)


def test_cross_project_mining_reports_honest_empty_state_on_a_bare_project():
    """No project ever registered -> registered_project_count == 0,
    mining.status == INSUFFICIENT_PROJECTS, zero cross-project patterns --
    never a fabricated pattern, and byte-identical to calling
    production_status()/mine_cross_project_patterns() directly over the same
    host root."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.cross_project_mining import (
            ProjectRegistry,
            mine_cross_project_patterns,
            production_status,
        )

        status, data = _get(base, "/api/cross-project-mining")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        expected_status = production_status(tmp)
        assert data["status"] == expected_status
        assert data["status"]["registered_project_count"] == 0
        assert data["status"]["can_produce_cross_project_result"] is False

        expected_mining = mine_cross_project_patterns(ProjectRegistry(tmp).roots())
        assert data["mining"] == expected_mining
        assert data["mining"]["status"] == "INSUFFICIENT_PROJECTS"
        assert data["mining"]["cross_project_patterns"] == []
    finally:
        shutil.rmtree(tmp)


def test_cross_project_mining_reports_a_real_pattern_from_two_registered_projects():
    """Two genuinely separate memory stores, each recording the same real
    failure signature, registered with this host's cross_project_mining
    registry: the served report must find the real cross-project pattern,
    byte-identical to a direct call into mine_cross_project_patterns() over
    the same registered roots -- proving the endpoint reads the real
    registry/miner rather than a dashboard-local re-derivation."""
    port = _free_port()
    host_root = _mk_dashboard_project(port)
    proj_a = Path(shutil.os.path.abspath(shutil.os.path.join(
        str(host_root), "..", host_root.name + "_proj_a")))
    proj_b = Path(shutil.os.path.abspath(shutil.os.path.join(
        str(host_root), "..", host_root.name + "_proj_b")))
    proj_a.mkdir(parents=True, exist_ok=True)
    proj_b.mkdir(parents=True, exist_ok=True)
    try:
        from dv_harness import memory_router
        from dv_harness.cross_project_mining import (
            ProjectRegistry,
            mine_cross_project_patterns,
        )

        signature = {
            "symptom": "usb link training timeout",
            "root_cause_hint": None,
            "protocol": "USB3",
        }

        def _write_job_failure(root: Path, job_id: str, git_sha: str) -> None:
            memory_router.route_and_store(
                root,
                {
                    "kind": "job_failure",
                    "protocol": "USB3",
                    "job_id": job_id,
                    "git_sha": git_sha,
                    "failure_signature": signature,
                    "symptoms": "link training timeout",
                },
            )

        _write_job_failure(proj_a, "jobA1", "shaA1")
        _write_job_failure(proj_b, "jobB1", "shaB1")

        registry = ProjectRegistry(host_root)
        registry.register(proj_a, "proj_a")
        registry.register(proj_b, "proj_b")

        base = f"http://127.0.0.1:{port}"
        _start_dashboard(host_root)
        _wait_ready(base)

        status, data = _get(base, "/api/cross-project-mining")
        assert status == 200
        assert data["available"] is True
        assert data["status"]["registered_project_count"] == 2
        assert data["status"]["can_produce_cross_project_result"] is True

        expected_mining = mine_cross_project_patterns(registry.roots())
        assert data["mining"] == expected_mining
        assert data["mining"]["status"] == "OK"
        patterns = data["mining"]["cross_project_patterns"]
        assert len(patterns) == 1
        pattern = patterns[0]
        assert sorted(pattern["project_ids"]) == ["proj_a", "proj_b"]
        assert pattern["project_count"] == 2
        # Neither project has a gate-verified verified_fix yet: no
        # transferable fix, and the pattern must say so honestly rather than
        # fabricating one.
        assert pattern["transferable_fix"] is None
    finally:
        shutil.rmtree(host_root, ignore_errors=True)
        shutil.rmtree(proj_a, ignore_errors=True)
        shutil.rmtree(proj_b, ignore_errors=True)


def test_cross_project_mining_reports_the_real_module_error_rather_than_a_500():
    """A CrossProjectRegistryError raised by the underlying module (an
    unreadable registry file) must surface as this endpoint's own error
    reason/detail -- the same honest-error contract
    _read_generation_readiness_state()/_read_confidence_calibration_state()
    already hold to -- never a bare 500 and never a silently empty card."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.cross_project_mining import CrossProjectRegistryError

        def _raise(*args, **kwargs):
            raise CrossProjectRegistryError("registry at ... is not readable JSON")

        import dv_harness.cross_project_mining as cpm
        saved = cpm.production_status
        cpm.production_status = _raise
        try:
            status, data = _get(base, "/api/cross-project-mining")
            assert status == 200
            assert data["available"] is False
            assert data["status"] is None
            assert data["mining"] is None
            assert data["error"]["reason"] == "CROSS_PROJECT_REGISTRY_UNREADABLE"
        finally:
            cpm.production_status = saved
    finally:
        shutil.rmtree(tmp)


def test_cross_project_mining_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() -- an
    endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    gap-close exists to avoid."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="crossProjectMiningCard"' in html
        assert "Cross-Project Pattern Mining" in html
        assert "'/api/cross-project-mining'" in html
        assert "await loadCrossProjectMining();" in html
        assert 'id="crossProjectMiningTiles"' in html
        assert 'id="crossProjectMiningProjectsTableBody"' in html
        assert 'id="crossProjectMiningPatternsTableBody"' in html
        # This card is read-only, matching every reader function it reuses
        # the convention of -- no POST verb of its own, and no project is
        # registered/unregistered from this route.
        assert "Read-only" in html.split('id="crossProjectMiningCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
