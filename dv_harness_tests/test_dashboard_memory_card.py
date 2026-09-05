"""GET /api/memory -- the Memory + Obsidian Knowledge Center dashboard card
(GUI-11, 2026-09-05 GUI completeness audit).

Before this, dashboard.py had no surface at all for the 5-tier Memory
Hierarchy (memory.MEMORY_LEVELS) or for the DV-Knowledge Vault that
memory_vault.py mirrors promoted records into -- the existing "Shared
Knowledge Center" card reports the cross-project broker's config/connectivity,
which is a different question from "what does THIS project's memory actually
hold, at which tier".

Every fixture below is written through the REAL writers -- MemoryStore.add()
for records, memory_vault.get_active_provider().create() with
build_frontmatter_from_memory_record() for notes -- so a fixture that drifted
from the real record/note schema fails at write time rather than quietly
proving the endpoint against a shape the real pipeline never produces. The
same convention test_dashboard_amba_card.py uses for its registry fixture.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers.
"""
from __future__ import annotations

import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)


def _add_records(tmp: Path):
    """Real records at four different tiers, through the real MemoryStore.

    Deliberately uneven per tier: a card that reported one number for the
    whole store would look correct against a uniform fixture and wrong the
    moment a real project's tiers diverge, which they always do."""
    from dv_harness.memory import MemoryStore

    store = MemoryStore(tmp)
    store.add("working", {"title": "hypothesis: LFPS handshake timing",
                          "protocol": "USB", "scope": "phy"})
    store.add("job", {"title": "job_failure: UVM_ERROR in u_usb_dev",
                      "protocol": "USB", "scope": "sim"})
    store.add("project", {"title": "project convention: branch_fw per port",
                          "protocol": "USB", "scope": "architecture"})
    store.add("project", {"title": "project convention: bind file location",
                          "protocol": "USB", "scope": "architecture"})
    store.add("engineering", {"title": "root cause: unwritten clock-enable",
                              "protocol": "USB", "scope": "rtl",
                              "root_cause": "clock enable never programmed",
                              "confidence": "HIGH", "verified": True})
    return store


def _add_vault_note(tmp: Path, memory_id: str, level: str, protocol: str,
                    root_cause: str):
    """One real vault note, built by the REAL frontmatter builder and written
    by the REAL provider -- never hand-authored markdown."""
    from dv_harness.memory_vault import (
        build_frontmatter_from_memory_record,
        get_active_provider,
    )

    destination = {"working": "JOB_MEMORY", "job": "JOB_MEMORY",
                   "project": "PROJECT_MEMORY", "engineering": "ENGINEERING_MEMORY",
                   "organizational": "ORGANIZATIONAL_MEMORY"}[level]
    fm = build_frontmatter_from_memory_record(destination, {
        "memory_id": memory_id, "protocol": protocol, "scope": "rtl",
        "root_cause": root_cause, "confidence": "HIGH", "status": "ACTIVE",
    })
    res = get_active_provider(tmp).create(fm, sections={"Root Cause": root_cause})
    assert res.get("ok"), res
    return res


def test_memory_reports_honest_empty_state_when_nothing_exists():
    """A project that has never written a memory record and has no vault must
    say so and name BOTH paths it looked at -- never a fabricated count. The
    same honest-empty-state contract GET /api/coverage and GET /api/amba hold
    to."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/memory")
        assert status == 200
        assert data["available"] is False
        assert data["notes"] == []
        assert data["note_detail"] is None
        assert data["error"] is None
        assert data["store"]["available"] is False
        assert data["vault"]["available"] is False
        assert data["store"]["store_dir"].endswith("memory")
        assert data["vault"]["vault_path"].endswith("vault")
        # Reading the endpoint must not CREATE either store -- a read-only
        # panel that materializes a memory tree just by being polled would
        # make "this project has no memory yet" unobservable ever after.
        assert not Path(data["store"]["store_dir"]).exists()
        assert not Path(data["vault"]["vault_path"]).exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_memory_returns_real_per_tier_counts_from_the_real_store():
    """Per-tier counts must equal what MemoryStore.index_integrity() itself
    reports -- not a dashboard-local re-count that could disagree with
    `dv-harness memory doctor`."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        store = _add_records(tmp)

        from dv_harness.memory import MEMORY_LEVELS

        status, data = _get(base, "/api/memory")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["levels"] == list(MEMORY_LEVELS)
        assert [t["level"] for t in data["tiers"]] == list(MEMORY_LEVELS)

        expected = store.index_integrity()
        assert data["store"]["index_integrity"] == expected
        by_level = {t["level"]: t for t in data["tiers"]}
        assert by_level["working"]["record_files"] == 1
        assert by_level["job"]["record_files"] == 1
        assert by_level["project"]["record_files"] == 2
        assert by_level["engineering"]["record_files"] == 1
        for lv in ("working", "job", "project", "engineering"):
            assert by_level[lv]["record_files"] == expected["per_level"][lv]["files"]
            assert by_level[lv]["index_rows"] == expected["per_level"][lv]["index_rows"]
            assert by_level[lv]["has_local_store"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_organizational_tier_is_reported_as_shared_not_as_a_local_zero():
    """memory_router.route_and_store() sends ORGANIZATIONAL_MEMORY to the
    shared Knowledge Center, never to `.dv-harness/memory/organizational/`.
    The card must carry that as a real fact off the router's own dispatch
    tables, so a local count of 0 can never be read as "no organizational
    knowledge exists"."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _add_records(tmp)

        from dv_harness.dashboard import _locally_stored_memory_levels

        # Derived from memory_router's own tables, not asserted here.
        assert "organizational" not in _locally_stored_memory_levels()

        status, data = _get(base, "/api/memory")
        org = {t["level"]: t for t in data["tiers"]}["organizational"]
        assert org["has_local_store"] is False
        assert "Knowledge Center" in org["backing_store"]
        # A temp project has no knowledge_center configured -- reported
        # honestly rather than as a count.
        assert org["knowledge_center_configured"] is False
        for t in data["tiers"]:
            if t["level"] != "organizational":
                assert "knowledge_center_configured" not in t
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_memory_surfaces_real_index_vs_file_drift():
    """`record_files` and `index_rows` are two separate numbers on purpose:
    this project's own store once had 18 of 31 engineering records on disk
    with no index row, invisible to MemoryRetriever.search() while still
    present as files. A card showing one number could not have shown that."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _add_records(tmp)

        # A record FILE with no index row -- exactly the lost-update signature
        # MemoryStore._index_lock() exists to prevent.
        orphan = tmp / ".dv-harness" / "memory" / "engineering" / "MEM-ORPHAN01.json"
        orphan.write_text('{"memory_id": "MEM-ORPHAN01", "level": "engineering"}',
                          encoding="utf-8")

        status, data = _get(base, "/api/memory")
        eng = {t["level"]: t for t in data["tiers"]}["engineering"]
        assert eng["record_files"] == 2
        assert eng["index_rows"] == 1
        ii = data["store"]["index_integrity"]
        assert ii["ok"] is False
        assert [f["memory_id"] for f in ii["files_missing_from_index"]] == ["MEM-ORPHAN01"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_memory_lists_and_searches_real_vault_notes():
    """Real notes reach the endpoint through the real provider's own
    search(), and both the free-text and the tier filter are that provider's
    filters -- dashboard.py parses no markdown and no frontmatter itself."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _add_vault_note(tmp, "MEM-ENG00001", "engineering", "USB",
                        "clock enable never programmed on port1")
        _add_vault_note(tmp, "MEM-PRJ00001", "project", "PCIe",
                        "ltssm recovery loop on lane reversal")

        status, data = _get(base, "/api/memory")
        assert status == 200
        assert data["available"] is True
        assert data["vault"]["available"] is True
        assert data["vault"]["note_count"] == 2
        assert data["vault"]["scan_truncated"] is False
        assert data["vault"]["status"] == "READY"
        ids = sorted(n["note_id"] for n in data["notes"])
        assert ids == ["MEM-ENG00001", "MEM-PRJ00001"]
        # The per-tier vault counts are bucketed off the real notes' own
        # frontmatter memory_level, never off the folder name.
        by_level = {t["level"]: t for t in data["tiers"]}
        assert by_level["engineering"]["vault_notes"] == 1
        assert by_level["project"]["vault_notes"] == 1
        assert by_level["working"]["vault_notes"] == 0

        # Free-text search, through FileSystemMarkdownAdapter.search().
        status, data = _get(base, "/api/memory?q=" + urllib.parse.quote("ltssm"))
        assert status == 200
        assert [n["note_id"] for n in data["notes"]] == ["MEM-PRJ00001"]

        # Tier filter, through that same adapter's memory_level property filter.
        status, data = _get(base, "/api/memory?level=engineering")
        assert [n["note_id"] for n in data["notes"]] == ["MEM-ENG00001"]

        # A search matching nothing is an empty result, never a fabricated hit.
        status, data = _get(base, "/api/memory?q=" + urllib.parse.quote("nosuchtoken"))
        assert data["notes"] == []
        assert data["vault"]["note_count"] == 2  # the vault itself is unchanged
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_memory_reads_one_real_note_body():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _add_vault_note(tmp, "MEM-ENG00002", "engineering", "USB",
                        "reset released before clock was stable")

        status, data = _get(base, "/api/memory?note=MEM-ENG00002")
        assert status == 200
        d = data["note_detail"]
        assert d["ok"] is True
        assert d["note_id"] == "MEM-ENG00002"
        assert "reset released before clock was stable" in d["body"]
        assert d["frontmatter"]["memory_level"] == "engineering"
        assert d["frontmatter"]["protocol"] == "USB"

        # A note that does not exist is an honest NOT_FOUND, not a 500.
        status, data = _get(base, "/api/memory?note=MEM-NOPE")
        assert status == 200
        assert data["note_detail"]["ok"] is False
        assert data["note_detail"]["error"] == "NOT_FOUND"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_memory_rejects_an_unknown_tier_with_a_real_reason():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _add_records(tmp)

        from dv_harness.memory import MEMORY_LEVELS

        status, data = _get(base, "/api/memory?level=not_a_tier")
        assert status == 200
        assert data["available"] is False
        assert data["error"]["reason"] == "UNKNOWN_MEMORY_LEVEL"
        assert data["error"]["detail"]["known_levels"] == list(MEMORY_LEVELS)
        assert data["notes"] == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_memory_card_is_served_and_wired_into_the_page():
    """The card must exist in the served HTML and really be fetched -- an
    endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    gap-close exists to avoid. It is deliberately fetched once on load (and on
    Search) rather than joined to load()'s 3s poll, so this asserts the
    fetch-once wiring specifically."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="memoryCenterCard"' in html
        assert "Memory + Obsidian Knowledge Center" in html
        assert "'/api/memory'" in html
        assert "loadMemoryCenter();" in html
        assert "showMemoryNote" in html
        # The organizational-tier honesty statement is part of the card, not
        # only of the payload.
        assert "Organizational is deliberately not a local file store" in html
        # Read-only surface: no write path to any memory tier from this page.
        assert "authoring a record or a note stays CLI-only" in html
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
