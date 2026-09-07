"""Context-Scoped Validity (dv_harness/memory.py), item context_scoped_validity
(2026-09-07).

`MemoryGC.confirm()`/`retract()` were unconditionally GLOBAL before this
change: any record's `memory_id` resolved, the confirmation/retraction
applied, full stop, with no notion that a finding might genuinely apply only
under one VIP release/protocol version and not another. This is a PURE,
ADDITIVE extension of that existing 5-value status vocabulary's semantics
(ACTIVE/DEPRECATED/SUPERSEDED/RETRACTED/NEEDS_REVALIDATION are completely
unchanged -- no sixth status value is introduced anywhere):

  * A new, optional `applicability_context` field on a record (defaulted to
    `None` by `MemoryStore.add()`, exactly like `provenance`) lets whoever
    creates a record declare what it is scoped to, e.g.
    `{"vip_release": "R-2020.12"}`.
  * A new, optional, keyword-only `context` parameter on `MemoryGC.confirm()`/
    `retract()` lets a caller OPT IN to context-aware scoping. Omitting it --
    every pre-existing call site in this codebase, none of which was
    edited -- preserves the exact old unconditional-global behavior, proven
    directly below.

Every test drives the REAL `MemoryStore`/`MemoryGC` on a real temp directory
-- never a hand-shaped record standing in for what `MemoryStore.add()` itself
produces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dv_harness.memory import MemoryGC, MemoryStore, _context_compatible


# ---------------------------------------------------------------------------
# _context_compatible(): the pure matching rule, tested directly
# ---------------------------------------------------------------------------

def test_context_compatible_no_record_context_is_always_compatible():
    assert _context_compatible(None, {"vip_release": "R-2020.12"}) is True
    assert _context_compatible({}, {"vip_release": "R-2020.12"}) is True


def test_context_compatible_no_query_context_is_always_compatible():
    assert _context_compatible({"vip_release": "R-2020.12"}, None) is True
    assert _context_compatible({"vip_release": "R-2020.12"}, {}) is True


def test_context_compatible_both_none_is_compatible():
    assert _context_compatible(None, None) is True


def test_context_compatible_matching_shared_key_is_compatible():
    assert _context_compatible(
        {"vip_release": "R-2020.12"}, {"vip_release": "R-2020.12"}
    ) is True


def test_context_compatible_disagreeing_shared_key_is_incompatible():
    assert _context_compatible(
        {"vip_release": "R-2020.12"}, {"vip_release": "R-2019.06"}
    ) is False


def test_context_compatible_unshared_keys_never_count_as_a_mismatch():
    # The record only claims something about protocol_version; the caller's
    # context additionally names vip_release, which the record never made
    # any claim about either way -- that must not manufacture a mismatch.
    assert _context_compatible(
        {"protocol_version": "3.0"},
        {"protocol_version": "3.0", "vip_release": "R-2020.12"},
    ) is True


def test_context_compatible_multi_key_partial_disagreement_is_incompatible():
    assert _context_compatible(
        {"protocol_version": "3.0", "vip_release": "R-2020.12"},
        {"protocol_version": "3.0", "vip_release": "R-2019.06"},
    ) is False


# ---------------------------------------------------------------------------
# MemoryStore.add(): the new field defaults honestly and is preserved
# ---------------------------------------------------------------------------

def test_add_defaults_applicability_context_to_none(tmp_path: Path):
    store = MemoryStore(tmp_path)
    mem = store.add("engineering", {"title": "no context declared", "protocol": "USB3"})
    assert mem["applicability_context"] is None
    # And it round-trips through get() unchanged.
    assert store.get(mem["memory_id"])["applicability_context"] is None


def test_add_preserves_a_caller_declared_applicability_context(tmp_path: Path):
    store = MemoryStore(tmp_path)
    ctx = {"vip_release": "R-2020.12"}
    mem = store.add(
        "engineering",
        {"title": "scoped finding", "protocol": "USB3", "applicability_context": ctx},
    )
    assert mem["applicability_context"] == ctx
    assert store.get(mem["memory_id"])["applicability_context"] == ctx


# ---------------------------------------------------------------------------
# Backward compatibility: omitting `context` is byte-for-byte the old
# behavior, for BOTH an unscoped record and a scoped one.
# ---------------------------------------------------------------------------

def test_confirm_without_context_param_is_unconditionally_global_unscoped_record(tmp_path: Path):
    store = MemoryStore(tmp_path)
    mem = store.add("engineering", {"title": "t", "protocol": "USB3"})
    gc = MemoryGC(store)
    assert gc.confirm(mem["memory_id"], evidence={"job": "JOB-1"}) is True
    got = store.get(mem["memory_id"])
    assert got["confirmation_count"] == 1
    assert got["last_confirmation_evidence"] == {"job": "JOB-1"}


def test_confirm_without_context_param_ignores_a_declared_scope_entirely(tmp_path: Path):
    # The REQUIRED negative control for backward compatibility: a record
    # DOES declare an applicability_context, but the caller never opted into
    # scoping (never passed `context=`) -- this must behave exactly as it
    # did before this field existed: unconditionally global.
    store = MemoryStore(tmp_path)
    mem = store.add(
        "engineering",
        {
            "title": "scoped finding", "protocol": "USB3",
            "applicability_context": {"vip_release": "R-2020.12"},
        },
    )
    gc = MemoryGC(store)
    assert gc.confirm(mem["memory_id"]) is True
    assert store.get(mem["memory_id"])["confirmation_count"] == 1


def test_retract_without_context_param_ignores_a_declared_scope_entirely(tmp_path: Path):
    store = MemoryStore(tmp_path)
    mem = store.add(
        "engineering",
        {
            "title": "scoped finding", "protocol": "USB3",
            "applicability_context": {"vip_release": "R-2020.12"},
        },
    )
    gc = MemoryGC(store)
    assert gc.retract(mem["memory_id"], reason="found wrong") is True
    got = store.get(mem["memory_id"])
    assert got["status"] == "RETRACTED"
    assert got["retraction_reason"] == "found wrong"


# ---------------------------------------------------------------------------
# New behavior: an explicit `context=` opts into scoping.
# ---------------------------------------------------------------------------

def test_confirm_with_context_applies_to_a_record_with_no_declared_scope(tmp_path: Path):
    # A record with no declared applicability_context stays global even when
    # the CALLER opts into a scoped call -- "no scope claim" always matches.
    store = MemoryStore(tmp_path)
    mem = store.add("engineering", {"title": "t", "protocol": "USB3"})
    gc = MemoryGC(store)
    assert gc.confirm(mem["memory_id"], context={"vip_release": "R-2020.12"}) is True
    assert store.get(mem["memory_id"])["confirmation_count"] == 1


def test_confirm_with_matching_context_succeeds(tmp_path: Path):
    store = MemoryStore(tmp_path)
    mem = store.add(
        "engineering",
        {
            "title": "scoped finding", "protocol": "USB3",
            "applicability_context": {"vip_release": "R-2020.12"},
        },
    )
    gc = MemoryGC(store)
    assert gc.confirm(mem["memory_id"], context={"vip_release": "R-2020.12"}) is True
    assert store.get(mem["memory_id"])["confirmation_count"] == 1


def test_confirm_with_mismatched_context_is_a_real_no_op(tmp_path: Path):
    store = MemoryStore(tmp_path)
    mem = store.add(
        "engineering",
        {
            "title": "scoped finding", "protocol": "USB3",
            "applicability_context": {"vip_release": "R-2020.12"},
        },
    )
    gc = MemoryGC(store)
    assert gc.confirm(mem["memory_id"], context={"vip_release": "R-2019.06"}) is False
    # Nothing was mutated -- a real no-op, not merely a false return value.
    got = store.get(mem["memory_id"])
    assert got["confirmation_count"] == 0
    assert "last_confirmed_at" not in got or got["last_confirmed_at"] is None
    assert "last_confirmation_evidence" not in got


def test_retract_with_matching_context_succeeds(tmp_path: Path):
    store = MemoryStore(tmp_path)
    mem = store.add(
        "engineering",
        {
            "title": "scoped finding", "protocol": "USB3",
            "applicability_context": {"vip_release": "R-2020.12"},
        },
    )
    gc = MemoryGC(store)
    assert gc.retract(
        mem["memory_id"], reason="wrong under this release",
        context={"vip_release": "R-2020.12"},
    ) is True
    assert store.get(mem["memory_id"])["status"] == "RETRACTED"


def test_retract_with_mismatched_context_is_a_real_no_op(tmp_path: Path):
    store = MemoryStore(tmp_path)
    mem = store.add(
        "engineering",
        {
            "title": "scoped finding", "protocol": "USB3",
            "applicability_context": {"vip_release": "R-2020.12"},
        },
    )
    gc = MemoryGC(store)
    assert gc.retract(
        mem["memory_id"], reason="wrong under a DIFFERENT release",
        context={"vip_release": "R-2019.06"},
    ) is False
    got = store.get(mem["memory_id"])
    assert got["status"] == "ACTIVE"
    assert "retraction_reason" not in got


def test_confirm_with_mismatched_context_never_restores_needs_revalidation(tmp_path: Path):
    # confirm()'s existing NEEDS_REVALIDATION -> ACTIVE restoration must not
    # fire on a scope-mismatched call either -- it is a real no-op, full stop.
    store = MemoryStore(tmp_path)
    mem = store.add(
        "engineering",
        {
            "title": "scoped finding", "protocol": "USB3",
            "applicability_context": {"vip_release": "R-2020.12"},
        },
    )
    gc = MemoryGC(store)
    assert gc.flag_stale(mem["memory_id"], reason="aged out") is True
    assert store.get(mem["memory_id"])["status"] == "NEEDS_REVALIDATION"

    assert gc.confirm(mem["memory_id"], context={"vip_release": "R-2019.06"}) is False
    got = store.get(mem["memory_id"])
    assert got["status"] == "NEEDS_REVALIDATION"
    assert got["confirmation_count"] == 0


def test_confirm_with_matching_context_still_restores_needs_revalidation(tmp_path: Path):
    store = MemoryStore(tmp_path)
    mem = store.add(
        "engineering",
        {
            "title": "scoped finding", "protocol": "USB3",
            "applicability_context": {"vip_release": "R-2020.12"},
        },
    )
    gc = MemoryGC(store)
    assert gc.flag_stale(mem["memory_id"], reason="aged out") is True
    assert gc.confirm(mem["memory_id"], context={"vip_release": "R-2020.12"}) is True
    got = store.get(mem["memory_id"])
    assert got["status"] == "ACTIVE"
    assert got["confirmation_count"] == 1


def test_confirm_context_scoping_unaffected_by_unrelated_query_keys(tmp_path: Path):
    # The record only scopes on vip_release; a caller's context additionally
    # naming an unrelated key (protocol_version) the record never claimed
    # anything about must not block the confirmation.
    store = MemoryStore(tmp_path)
    mem = store.add(
        "engineering",
        {
            "title": "scoped finding", "protocol": "USB3",
            "applicability_context": {"vip_release": "R-2020.12"},
        },
    )
    gc = MemoryGC(store)
    assert gc.confirm(
        mem["memory_id"],
        context={"vip_release": "R-2020.12", "protocol_version": "3.0"},
    ) is True


def test_unresolved_memory_id_still_returns_false_with_or_without_context(tmp_path: Path):
    store = MemoryStore(tmp_path)
    gc = MemoryGC(store)
    assert gc.confirm("MEM-DOES-NOT-EXIST") is False
    assert gc.confirm("MEM-DOES-NOT-EXIST", context={"vip_release": "X"}) is False
    assert gc.retract("MEM-DOES-NOT-EXIST", reason="n/a") is False
    assert gc.retract("MEM-DOES-NOT-EXIST", reason="n/a", context={"vip_release": "X"}) is False
