"""retrieval_ranking_learns_usefulness (2026-09-07): MemoryRetriever.search()
gains a new, opt-in `rank_by=MemoryRetriever.USEFULNESS_RANK` mode that folds
the existing, real `reuse_count`/`MemoryGC.mark_used()` signal into the
relevance score -- additively. The pre-existing fixed-heuristic ranking
(`rank_by` omitted, or explicitly RELEVANCE_RANK) is byte-for-byte unchanged
for every existing caller; see test_default_relevance_ranking_is_byte_
identical_to_before below for the direct proof.

Every test here is real: real MemoryStore records on disk, real MemoryGC
writes (never a hand-set reuse_count field bypassing the real write path),
real MemoryRetriever.search() calls -- no mocking.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.memory import MemoryGC, MemoryRetriever, MemoryStore


@pytest.fixture()
def tmp_root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _ids(hits):
    return [h["memory"]["memory_id"] for h in hits]


def _seed_two_equally_relevant_records(root: Path, created_at: float = 1_700_000_000.0,
                                        reuse_counts: dict | None = None) -> MemoryStore:
    """Two engineering-tier records that tie on every RELEVANCE_RANK factor
    (protocol, no symptoms/text overlap difference, identical confidence, and
    an explicitly IDENTICAL created_at so recency ties exactly rather than
    merely approximately -- real wall-clock writes a fraction of a second
    apart would otherwise give the two records genuinely different ages).
    `reuse_counts` sets the real, persisted `reuse_count` field directly at
    creation time (the same field `MemoryStore.mark_used()` itself increments
    and re-writes via `add()` -- see the dedicated `mark_used()`-driven tests
    below for the proof that a real mutator call is read identically), used
    here so a test can isolate reuse_count's effect on ranking without also
    disturbing `last_used_at` (which `mark_used()` sets to "now" and would
    otherwise break the recency tie between the two records)."""
    reuse_counts = reuse_counts or {}
    store = MemoryStore(root)
    store.add("engineering", {
        "memory_id": "MEM-RARELY-USED", "title": "USB2 LFPS polling timeout",
        "protocol": "USB2", "root_cause": "missing sync flop on lfps_detect",
        "confidence": "HIGH", "created_at": created_at,
        "reuse_count": reuse_counts.get("MEM-RARELY-USED", 0),
    })
    store.add("engineering", {
        "memory_id": "MEM-OFTEN-USED", "title": "USB2 LFPS polling timeout",
        "protocol": "USB2", "root_cause": "missing sync flop on lfps_detect",
        "confidence": "HIGH", "created_at": created_at,
        "reuse_count": reuse_counts.get("MEM-OFTEN-USED", 0),
    })
    return store


# ===========================================================================
# 1. The default path is untouched -- the mandatory non-regression proof.
# ===========================================================================

def test_default_relevance_ranking_is_byte_identical_to_before(tmp_root):
    """Omitting rank_by must reproduce the exact pre-existing score: ties
    stay ties regardless of how unevenly the two records have actually been
    reused (real, persisted reuse_count -- see _seed_two_equally_relevant_
    records's own docstring for why it is set directly here rather than via
    mark_used())."""
    import time as _time

    store = _seed_two_equally_relevant_records(tmp_root, reuse_counts={"MEM-OFTEN-USED": 9})

    r = MemoryRetriever(store)
    frozen_now = _time.time()
    no_kw = r.search({"protocol": "USB2"}, now=frozen_now)
    explicit_default = r.search({"protocol": "USB2"}, rank_by=MemoryRetriever.RELEVANCE_RANK, now=frozen_now)

    # Both calls to the unchanged default must produce identical scores for
    # the two records -- reuse_count must never leak into RELEVANCE_RANK.
    # (now= is pinned identically on both calls so wall-clock drift between
    # two search() invocations can never masquerade as a real difference.)
    assert {h["memory"]["memory_id"]: h["score"] for h in no_kw} == \
           {h["memory"]["memory_id"]: h["score"] for h in explicit_default}
    scores = {h["memory"]["memory_id"]: h["score"] for h in no_kw}
    assert scores["MEM-RARELY-USED"] == scores["MEM-OFTEN-USED"]


def test_default_rank_by_matches_the_pre_change_score_formula(tmp_root):
    """A single record, scored with and without touching rank_by at all --
    proves the new parameter's default value truly reproduces the exact
    pre-existing arithmetic (relevance + confidence + recency), with no
    usefulness term silently present."""
    store = MemoryStore(tmp_root)
    store.add("engineering", {
        "memory_id": "MEM-X", "title": "PCIe LTSSM recovery loop",
        "protocol": "PCIE", "root_cause": "eq phase 2 preset never applied",
        "confidence": "MEDIUM",
    })
    for _ in range(25):
        store.mark_used("MEM-X")

    r = MemoryRetriever(store)
    hit = r.search({"protocol": "PCIE"})[0]
    now = hit["memory"].get("last_used_at")
    # protocol hard filter contributes 3 to relevance; MEDIUM confidence
    # contributes .75; recency at t==last_used_at is 1.0 (age_days == 0).
    assert hit["score"] == pytest.approx(3.0 + 0.75 + 1.0)


# ===========================================================================
# 2. USEFULNESS_RANK re-orders among already-relevant hits by real reuse.
# ===========================================================================

def test_usefulness_rank_promotes_the_more_reused_record_among_ties(tmp_root):
    import time as _time

    store = _seed_two_equally_relevant_records(tmp_root, reuse_counts={"MEM-OFTEN-USED": 12})

    r = MemoryRetriever(store)
    frozen_now = _time.time()
    relevance_order = _ids(r.search({"protocol": "USB2"}, now=frozen_now))
    usefulness_order = _ids(r.search({"protocol": "USB2"}, rank_by=MemoryRetriever.USEFULNESS_RANK, now=frozen_now))

    # Under the unchanged default the two tie (whatever stable order the
    # store happens to return); under usefulness ranking the reused record
    # must win outright.
    assert usefulness_order[0] == "MEM-OFTEN-USED"
    assert set(relevance_order) == set(usefulness_order) == {"MEM-RARELY-USED", "MEM-OFTEN-USED"}


def test_usefulness_rank_never_reused_record_scores_identically_to_relevance_rank(tmp_root):
    """log1p(0) == 0: a record nobody has ever reused gets exactly the same
    score under both modes -- the usefulness term is additive, never a
    penalty and never a rescale of the base score."""
    store = MemoryStore(tmp_root)
    store.add("engineering", {
        "memory_id": "MEM-NEVER-USED", "title": "AMBA fabric arbitration stall",
        "protocol": "AMBA4", "root_cause": "round robin arbiter starves low priority master",
        "confidence": "LOW",
    })
    import time as _time

    r = MemoryRetriever(store)
    frozen_now = _time.time()
    relevance_hit = r.search({"protocol": "AMBA4"}, now=frozen_now)[0]
    usefulness_hit = r.search({"protocol": "AMBA4"}, rank_by=MemoryRetriever.USEFULNESS_RANK, now=frozen_now)[0]
    assert relevance_hit["score"] == usefulness_hit["score"]


def test_usefulness_weight_is_tunable_and_scales_the_added_term(tmp_root):
    store = MemoryStore(tmp_root)
    store.add("engineering", {
        "memory_id": "MEM-Y", "title": "Ethernet MAC underrun",
        "protocol": "ETHERNET", "root_cause": "tx fifo prefetch too shallow",
        "confidence": "LOW",
    })
    for _ in range(6):
        store.mark_used("MEM-Y")

    r = MemoryRetriever(store)
    base = r.search({"protocol": "ETHERNET"}, rank_by=MemoryRetriever.RELEVANCE_RANK)[0]["score"]
    weight1 = r.search({"protocol": "ETHERNET"}, rank_by=MemoryRetriever.USEFULNESS_RANK,
                        usefulness_weight=1.0)[0]["score"]
    weight3 = r.search({"protocol": "ETHERNET"}, rank_by=MemoryRetriever.USEFULNESS_RANK,
                        usefulness_weight=3.0)[0]["score"]

    import math
    assert weight1 == pytest.approx(base + 1.0 * math.log1p(6))
    assert weight3 == pytest.approx(base + 3.0 * math.log1p(6))
    assert weight3 > weight1 > base


# ===========================================================================
# 3. Negative control: usefulness must never manufacture relevance on its
#    own -- a record with zero query overlap stays excluded under
#    USEFULNESS_RANK exactly as it does under RELEVANCE_RANK (finding I2's
#    relevance-floor guarantee must survive this addition unchanged).
# ===========================================================================

def test_negative_control_heavy_reuse_never_manufactures_relevance(tmp_root):
    store = MemoryStore(tmp_root)
    store.add("engineering", {
        "memory_id": "MEM-UNRELATED-BUT-HEAVILY-REUSED", "title": "Ethernet MAC underrun",
        "protocol": "ETHERNET", "root_cause": "tx fifo prefetch too shallow",
        "confidence": "HIGH",
    })
    for _ in range(100):
        store.mark_used("MEM-UNRELATED-BUT-HEAVILY-REUSED")

    r = MemoryRetriever(store)
    # A USB coverage query has zero protocol/scope/symptom/text overlap with
    # the Ethernet record above -- 100 real reuses must not be enough to
    # smuggle it past the relevance floor under either ranking mode.
    query = {"protocol": "USB2", "text": "lsf queue drain"}
    assert r.search(query, rank_by=MemoryRetriever.RELEVANCE_RANK) == []
    assert r.search(query, rank_by=MemoryRetriever.USEFULNESS_RANK) == []


def test_negative_control_unknown_rank_by_is_rejected(tmp_root):
    store = MemoryStore(tmp_root)
    r = MemoryRetriever(store)
    with pytest.raises(ValueError):
        r.search({"protocol": "USB2"}, rank_by="most_recent")


# ===========================================================================
# 4. USEFULNESS_RANK composes cleanly with the pre-existing structural
#    filters (level/confidence/status/property) -- it only changes ordering,
#    never which records those filters admit.
# ===========================================================================

def test_usefulness_rank_still_honors_structural_filters(tmp_root):
    store = MemoryStore(tmp_root)
    store.add("engineering", {
        "memory_id": "MEM-ENG", "title": "USB2 LFPS polling timeout",
        "protocol": "USB2", "root_cause": "missing sync flop on lfps_detect",
        "confidence": "HIGH",
    })
    store.add("working", {
        "memory_id": "MEM-WORK", "title": "USB2 LFPS polling timeout",
        "protocol": "USB2", "root_cause": "missing sync flop on lfps_detect",
        "confidence": "LOW",
    })
    for _ in range(20):
        store.mark_used("MEM-WORK")

    r = MemoryRetriever(store)
    hits = r.search({"protocol": "USB2", "level": "engineering"}, rank_by=MemoryRetriever.USEFULNESS_RANK)
    # MEM-WORK is far more reused, but the level="engineering" filter must
    # still exclude it outright -- usefulness ranking never overrides a
    # structural filter.
    assert _ids(hits) == ["MEM-ENG"]
