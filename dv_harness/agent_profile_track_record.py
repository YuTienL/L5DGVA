from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# agent_profile_track_record.py (2026-09-07, agent_profile_track_record gap-close)
#
# THE GAP THIS CLOSES. `memory.py` already records, per-record, an
# ACCUMULATION mechanism for whether a conclusion later held up
# (`MemoryGC.confirm()`/`retract()`/`supersede()`), and `confidence_
# calibration.py` already reuses that mechanism to ask whether a CONFIDENCE
# TIER's own track record matches the ordering this harness acts on. Neither
# module -- nor anything else in this repository, confirmed by a repo-wide
# grep for `producing_agent_profile`/`agent_profile_track_record` before
# this module was written -- ever asked the adjacent question this item
# names: which `.claude/agents/*.md` profile PRODUCED a given memory record
# in the first place, and does THAT profile's own track record (across
# confirm()/retract()/supersede() outcomes) look any different from another
# profile's.
#
# This module is deliberately two small, additive pieces, matching the
# item's own scope exactly:
#   (1) `memory.py`'s `MemoryStore.add()` gained one new OPTIONAL field,
#       `producing_agent_profile`, defaulting to `None` for a record whose
#       writer never supplied one -- which is every real record on disk
#       before this change, and still the overwhelming majority of real
#       writers today, since only `engine.py`'s PASS-verdict memory writers
#       were updated to actually supply it (their own real, already-resolved
#       `route_info["agent"]`/`_resolved_agent_name` value -- never a second,
#       independently-derived attribution).
#   (2) THIS module: a read-only report joining that new field against the
#       real, already-recorded confirm()/retract()/supersede() outcomes --
#       reusing `confidence_calibration.classify_record_outcome()` verbatim
#       rather than re-deriving a second definition of "what really happened
#       to this record" (REJECTED-checked-first, a confirmation after a
#       retraction still counts as REJECTED -- see that function's own
#       docstring for why that ordering is load-bearing).
#
# Deliberately NOT wired into engine.py's real dispatch logic. Per this
# item's own instruction and the Evidence Truth Rule this whole project
# enforces for a weight/threshold-shaped proposal, a finding here (e.g. "one
# profile's records get retracted far more often than another's") must never
# be applied directly to production routing/scoring -- doing so would need a
# separate, human-approved change routed through `capability_evolution.py`'s
# existing controlled-experiment machinery, exactly like every other
# production-behavior change in this project. This module only reports.
#
# `memory.py` cannot import this module's own reuse target,
# `confidence_calibration.py`, without a circular import:
# `confidence_calibration.py` already imports FROM `memory.py`
# (`from .memory import MEMORY_LEVELS, MemoryStore`). So the read/write halves
# live in different files by necessity, not by accident -- `memory.py` only
# ever stores the new field; this module is where it is read back and
# compared against real outcomes.

from .memory import MemoryStore
from .confidence_calibration import (
    classify_record_outcome,
    OUTCOME_VERIFIED,
    OUTCOME_REJECTED,
    OUTCOME_INDETERMINATE,
)
from .env_manifest import build_generation_agent

#: Bucket label for a real, scanned record whose `producing_agent_profile`
#: is absent/None/blank -- kept honestly distinct from a named profile bucket
#: rather than silently folded into one, the same "an unattributed record is
#: a different fact from an attributed-but-unknown one" discipline
#: `confidence_calibration.py`'s own `records_without_recognized_tier` bucket
#: already applies to its own domain.
UNATTRIBUTED_LABEL = "UNATTRIBUTED_NO_PRODUCING_AGENT_PROFILE_RECORDED"

#: Report-level status vocabulary. Checked disjoint from
#: `dv_harness.models.Status` at import time below, the same discipline
#: several sibling domain-vocabulary modules in this project already apply
#: to themselves.
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_NO_ATTRIBUTED_RECORDS = "NO_ATTRIBUTED_RECORDS"
STATUS_REPORTED = "REPORTED"

REPORT_STATUSES = (STATUS_NOT_AVAILABLE, STATUS_NO_ATTRIBUTED_RECORDS, STATUS_REPORTED)


class AgentProfileTrackRecordError(ValueError):
    def __init__(self, reason: str, detail: Dict[str, Any]):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own report/bucket vocabulary must never collide with a
    real stage-gate verdict -- the same guard `capability_evolution.py`,
    `benchmark_dataset.py` and several other domain-vocabulary modules in
    this project already run against `dv_harness.models.Status` for their
    own vocabularies, so a reader can never mistake "this profile's records
    keep getting retracted" for a real PASS/FAIL stage result."""
    from . import models
    verdict_values = {member.value for member in models.Status}
    own_values = {UNATTRIBUTED_LABEL, OUTCOME_VERIFIED, OUTCOME_REJECTED,
                  OUTCOME_INDETERMINATE, *REPORT_STATUSES}
    collision = verdict_values & own_values
    if collision:
        raise AgentProfileTrackRecordError(
            "VOCABULARY_COLLIDES_WITH_VERIFICATION_VERDICT",
            {"collision": sorted(collision)})


assert_no_verification_verdict_vocabulary()


def _memory_index_path(root: Path) -> Path:
    return Path(root) / ".dv-harness" / "memory" / "index.json"


def _profile_bucket() -> Dict[str, Any]:
    return {
        "records": 0,
        OUTCOME_VERIFIED: 0,
        OUTCOME_REJECTED: 0,
        OUTCOME_INDETERMINATE: 0,
        "outcome_reasons": {},
        "kinds": {},
        "levels": {},
    }


def _profile_report(profile: str, bucket: Dict[str, Any], *,
                     profile_root=None) -> Dict[str, Any]:
    verified = bucket[OUTCOME_VERIFIED]
    rejected = bucket[OUTCOME_REJECTED]
    determinate = verified + rejected
    resolution = (
        {"status": "UNATTRIBUTED", "identifier": None, "resolution": "UNATTRIBUTED", "reason": None}
        if profile == UNATTRIBUTED_LABEL
        else build_generation_agent(profile, profile_root=profile_root)
    )
    return {
        "producing_agent_profile": None if profile == UNATTRIBUTED_LABEL else profile,
        "profile_resolution": resolution,
        "records": bucket["records"],
        "verified": verified,
        "rejected": rejected,
        "indeterminate": bucket[OUTCOME_INDETERMINATE],
        "determinate": determinate,
        "observed_reliability": (verified / determinate) if determinate else None,
        "outcome_reasons": dict(sorted(bucket["outcome_reasons"].items())),
        "kinds": dict(sorted(bucket["kinds"].items())),
        "levels": dict(sorted(bucket["levels"].items())),
    }


def collect_agent_profile_track_record(root, *, store: Optional[MemoryStore] = None,
                                        profile_root=None) -> Dict[str, Any]:
    """The per-`producing_agent_profile` track record for one project, built
    ONLY from that project's REAL `MemoryStore` records -- read-only, and
    provably so: a project with no memory store on disk is reported
    NOT_AVAILABLE WITHOUT constructing a `MemoryStore` (that constructor
    `mkdir()`s the whole 5-tier tree and writes an empty `index.json`, the
    same real side effect `confidence_calibration.calibrate()`/
    `cross_project_mining.py` already guard against for the identical
    reason -- asking whether a project's agent profiles have a track record
    must never itself create the store being asked about).

    Every record's real outcome is `confidence_calibration.
    classify_record_outcome()`, called, never re-derived -- there is exactly
    one definition of VERIFIED/REJECTED/INDETERMINATE in this codebase, and
    this module does not add a second one.

    Three honest statuses:
      NOT_AVAILABLE          no memory store on disk at all.
      NO_ATTRIBUTED_RECORDS  the store exists and holds real records, but not
                             one of them carries a real `producing_agent_
                             profile` -- an honest, real answer for a
                             project whose engine.py memory writers have not
                             (yet, or ever) supplied one, never a fabricated
                             empty-but-clean report.
      REPORTED               at least one record carries the field; every
                             named profile's bucket is reported, plus the
                             UNATTRIBUTED bucket for every record that does
                             not.
    """
    root = Path(root)
    index_path = _memory_index_path(root)
    if store is None and not index_path.exists():
        return {
            "status": STATUS_NOT_AVAILABLE,
            "reason": "NO_MEMORY_STORE",
            "detail": (
                f"no {index_path} in this project. There is nothing to report a "
                "producing-agent-profile track record over until real memory "
                "records exist."
            ),
            "project_root": str(root),
            "source": str(index_path),
            "records_scanned": 0,
            "profiles": {},
        }

    store = store if store is not None else MemoryStore(root)
    buckets: Dict[str, Dict[str, Any]] = {}
    scanned = 0
    for record in store.find():
        scanned += 1
        raw_profile = record.get("producing_agent_profile")
        profile = str(raw_profile).strip() if raw_profile else ""
        key = profile if profile else UNATTRIBUTED_LABEL
        bucket = buckets.setdefault(key, _profile_bucket())
        bucket["records"] += 1
        verdict = classify_record_outcome(record)
        bucket[verdict["outcome"]] += 1
        bucket["outcome_reasons"][verdict["reason"]] = (
            bucket["outcome_reasons"].get(verdict["reason"], 0) + 1)
        kind = str(record.get("kind") or "unknown")
        bucket["kinds"][kind] = bucket["kinds"].get(kind, 0) + 1
        level = str(record.get("level") or "unknown")
        bucket["levels"][level] = bucket["levels"].get(level, 0) + 1

    attributed_profiles = sorted(k for k in buckets if k != UNATTRIBUTED_LABEL)
    integrity = store.index_integrity()

    base = {
        "project_root": str(root),
        "source": str(index_path),
        "records_scanned": scanned,
        "index_integrity_ok": integrity["ok"],
        "index_rows_without_file": len(integrity["index_rows_without_file"]),
        "record_files_missing_from_index": len(integrity["files_missing_from_index"]),
    }

    if not attributed_profiles:
        return dict(
            base,
            status=STATUS_NO_ATTRIBUTED_RECORDS,
            reason="NO_RECORD_CARRIES_A_PRODUCING_AGENT_PROFILE",
            detail=(
                f"{scanned} record(s) scanned; none carries a "
                "producing_agent_profile. MemoryStore.add() defaults an "
                "unsupplied value to None, which this report never treats "
                "as attribution to a real profile."
            ),
            profiles={},
        )

    profiles = {
        p: _profile_report(p, buckets[p], profile_root=profile_root)
        for p in attributed_profiles
    }
    if UNATTRIBUTED_LABEL in buckets:
        profiles[UNATTRIBUTED_LABEL] = _profile_report(
            UNATTRIBUTED_LABEL, buckets[UNATTRIBUTED_LABEL], profile_root=profile_root)

    return dict(
        base,
        status=STATUS_REPORTED,
        reason="PROFILES_REPORTED",
        detail=(
            f"{len(attributed_profiles)} named producing-agent-profile(s) found "
            f"over {scanned} scanned record(s)."
        ),
        profiles=profiles,
    )


def render_report_text(report: Dict[str, Any]) -> str:
    """Human-readable form of `collect_agent_profile_track_record()`'s
    payload. Every profile bucket this report found is always printed --
    "this profile has zero determinate outcomes yet" and "this profile was
    omitted" must not look alike once the report is on screen."""
    lines = [
        f"Agent-Profile Track Record -- {report['status']} ({report['reason']})",
        f"  {report.get('detail', '')}",
        f"  source: {report['source']}",
    ]
    if report["status"] == STATUS_NOT_AVAILABLE:
        return "\n".join(lines)
    lines.append(
        f"  records scanned: {report['records_scanned']}  "
        f"index_integrity_ok={report.get('index_integrity_ok')}"
    )
    profiles = report.get("profiles") or {}
    if profiles:
        lines.append("")
        lines.append(f"  {'PROFILE':<40} {'RESOLUTION':<24} {'RECORDS':>7} "
                     f"{'VERIF':>6} {'REJECT':>6} {'DETERM':>6}  RELIABILITY")
        for name in sorted(profiles):
            row = profiles[name]
            rel = ("--" if row["observed_reliability"] is None
                   else f"{row['observed_reliability']:.0%}")
            resolution = row["profile_resolution"].get("resolution")
            label = "(unattributed)" if row["producing_agent_profile"] is None else name
            lines.append(
                f"  {label:<40} {str(resolution):<24} {row['records']:>7} "
                f"{row['verified']:>6} {row['rejected']:>6} {row['determinate']:>6}  {rel}")
    return "\n".join(lines)


def execute_verb(root: Path, verb: str, *, as_json: bool = False) -> "tuple[int, Any]":
    """One implementation behind `python -m dv_harness.agent_profile_track_record`
    and any future CLI front door -- the same shared-`execute_verb()`
    convention `confidence_calibration`/`loop_contract`/`loop_budget` follow.

    Exit 2 means "nothing attributed to report" (NOT_AVAILABLE or
    NO_ATTRIBUTED_RECORDS). A reporting signal only -- nothing in this module
    can authorize anything, and nothing here changes engine.py's dispatch."""
    root = Path(root)
    if verb in ("report", "show"):
        report = collect_agent_profile_track_record(root)
        code = 0 if report["status"] == STATUS_REPORTED else 2
        if verb == "show" and not as_json:
            return code, render_report_text(report)
        return code, report
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["report", "show"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m dv_harness.agent_profile_track_record",
        description="Which .claude/agents/*.md profile produced each real memory "
                    "record in this project, joined against real confirm()/"
                    "retract() outcomes.",
    )
    p.add_argument("verb", choices=["report", "show"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb, as_json=args.json)
    print(payload if isinstance(payload, str)
          else json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover - CLI shim
    raise SystemExit(main())
