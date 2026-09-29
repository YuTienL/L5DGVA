"""L5DGVA V14 (`L5DGVA/L5_DGVA_Generic_MultiLevel_Verification_Contract_v14_STRICT_AI_Architecture.md`,
section 374, "Runtime Telemetry / Audit") -- a per-engine CONTINUOUS telemetry
rollup, read only, over evidence that already exists.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim -- this
module is CAP-POOL-011's target capability. It re-imports `ENGINE_RULES` from
`eight_engine_runtime_proof_matrix.py` (migrated WITH ADAPTATION earlier in this
same batch: the `five_level_memory_engine` rule's `signals` tuple was reduced
from 8 to 5 real canonical event names) rather than hardcoding any event name
of its own, so the adapted 5-signal rule automatically propagates here with no
separate edit needed -- confirmed by the ported test suite passing unchanged.

PRIMARY SOURCE, quoted verbatim (section 374, lines 5326-5331 of that file):

    ## 374. Runtime Telemetry / Audit

    Each engine emits sufficient runtime telemetry/artifacts to prove
    invocation and outcome without storing prohibited secrets.

    Required: `EightEngineRuntimeAuditTrail_PASS = true`

WHY THIS MODULE EXISTS, DISTINCT FROM `eight_engine_runtime_proof_matrix.py`.
The 2026-09-16 L5DGVA audit (`.dv-harness/l5dgva_audit_result_A.md`, cluster
C23) found this requirement NOT_PROVEN: `loop_telemetry.py` is real and
dashboard-integrated, but nothing rolls its events up **per named engine**.
`eight_engine_runtime_proof_matrix.py` (built earlier the same session, for
section 342's distinct `EightEngineRuntimeProofMatrix` requirement) closed
part of that gap, but it deliberately answers only a binary question per
engine -- PROVEN / NOT_PROVEN / NO_RUNTIME_SIGNAL_SOURCE over one scanned
window. Section 374 asks for "sufficient runtime telemetry" -- a claim a
single yes/no bit cannot carry: it says nothing about HOW OFTEN an engine
fired, WHEN, or across HOW MANY distinct runs. This module answers that
narrower, still-real, still-honestly-bounded question: a per-engine
invocation-COUNT/frequency rollup, computed from the exact same events.jsonl
window and the exact same section-339 engine-to-signal mapping
`eight_engine_runtime_proof_matrix.ENGINE_RULES` already defines (imported,
never re-derived, so the two modules can never silently disagree about what
counts as evidence for a given engine).

WHAT THIS MODULE ACTUALLY DOES. For each of the 8 engines, over one scanned
window of `.dv-harness/events.jsonl` (via `loop_telemetry.read_events()`, the
same reader `eight_engine_runtime_proof_matrix.py`, `dashboard._tail_events()`
and `platform_health.py` already reuse):

  * `invocation_count` -- how many matched events fired in the window.
  * `per_signal_counts` -- the same count broken down per real event NAME
    (an engine can have more than one named signal; section 374's own
    "sufficient" reads differently for an engine whose only signal fired
    once versus one with five matches spread across three signal types).
  * `distinct_run_ids` -- how many distinct `run_id` values produced a match,
    a coarse but real frequency signal ("this engine fired in 1 of 10 scanned
    runs" is a materially different claim than "in 10 of 10").
  * `first_seen_ts` / `last_seen_ts` -- the matched events' own `ts` field,
    verbatim, never recomputed or estimated.

WHAT THIS MODULE DELIBERATELY DOES NOT DO -- read this before citing it as
section-374 closure.

  * It does not add a single new event producer to `engine.py`, and it does
    not touch `eight_engine_runtime_proof_matrix.py` or `loop_telemetry.py`.
    Pure additional read-only aggregation over data both already produce.
  * It does not compute or claim `EightEngineRuntimeAuditTrail_PASS`. Section
    374 requires proving both INVOCATION *and* OUTCOME; this module (like
    `eight_engine_runtime_proof_matrix.py` before it) has no per-engine
    outcome-verification signal to read -- a matched event proves the engine
    fired, never that its result was later consumed/verified. Claiming the
    literal section-374 flag here would be exactly the kind of "artifact
    exists -> PASS" fabrication section 380 prohibits. `rollup_pass()` below
    computes a narrower, honestly-named `EightEngineRuntimeTelemetryRollup_PASS`
    instead (see its own docstring for exactly what it does and does not
    assert).
  * It does not implement section 375 ("Per-Phase Eight-Engine Checkpoint" --
    persisting applicability/invocation/outcome state at each material phase
    closure so context rollover cannot erase proof). That requires a new call
    site inside `engine.py`'s own phase-closure path, which is out of this
    module's scope (a read-only rollup over an already-written log cannot
    itself become a write hook triggered at phase closure) -- a real,
    still-open, separately-scoped gap, not silently folded into this one.
  * For the 3 engines with NO events.jsonl producer at all today (Multi-Agent
    Orchestrator, Route & Skill Resolver, Plan-and-Execute/ReAct -- see
    `eight_engine_runtime_proof_matrix.py`'s own docstring for why), every
    count field here is honestly `NOT_AVAILABLE`, never `0` -- `0` would
    silently conflate "no producer exists" with "a producer exists but never
    fired", the exact distinction `NO_RUNTIME_SIGNAL_SOURCE` exists to keep
    separate.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import loop_telemetry
from .eight_engine_runtime_proof_matrix import ENGINE_RULES, EngineRule, EngineSignal

#: Reuse the exact same sentinel `eight_engine_runtime_proof_matrix.py` uses,
#: so a caller reading both artifacts sees one consistent vocabulary for "this
#: value cannot be honestly computed" rather than two different spellings of
#: the same disclosure.
NOT_AVAILABLE = "NOT_AVAILABLE"

EventRecord = Dict[str, Any]


def _signal_matches(signal: EngineSignal, rec: EventRecord) -> bool:
    """Identical match rule to `eight_engine_runtime_proof_matrix._matches()`
    -- re-implemented rather than importing that underscore-private name, but
    over the SAME `EngineSignal` objects from the SAME `ENGINE_RULES`, so the
    two modules' notion of "what counts as evidence for engine X" cannot
    silently drift apart even though the function bodies are separate."""
    if rec.get("event") != signal.event_name:
        return False
    if signal.predicate is None:
        return True
    try:
        return bool(signal.predicate(rec))
    except Exception:
        return False


@dataclass
class EngineTelemetryRollup:
    """A per-engine CONTINUOUS telemetry rollup -- distinct from, and never a
    replacement for, `eight_engine_runtime_proof_matrix.EngineProofRow`'s
    binary verdict. `has_signal_source is False` means every count/timestamp
    field below is `NOT_AVAILABLE` (see module docstring)."""
    engine_id: str
    engine_name: str
    has_signal_source: bool
    invocation_count: Any
    per_signal_counts: Any
    distinct_run_ids: Any
    first_seen_ts: Any
    last_seen_ts: Any
    gap_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "EngineId": self.engine_id,
            "EngineName": self.engine_name,
            "HasSignalSource": self.has_signal_source,
            "InvocationCount": self.invocation_count,
            "PerSignalCounts": self.per_signal_counts,
            "DistinctRunIds": self.distinct_run_ids,
            "FirstSeenTs": self.first_seen_ts,
            "LastSeenTs": self.last_seen_ts,
            "GapNote": self.gap_note,
        }


def build_rollup(root: Path, *, run_id: Optional[str] = None,
                  scan_lines: int = loop_telemetry.DEFAULT_EVENT_SCAN_LINES,
                  ) -> Dict[str, EngineTelemetryRollup]:
    """The real per-engine telemetry rollup for one project, over the real
    trailing window of `.dv-harness/events.jsonl` (via
    `loop_telemetry.read_events` -- no new parser). `run_id` narrows to one
    loop session, matching `eight_engine_runtime_proof_matrix.build_matrix`'s
    own `run_id` semantics."""
    root = Path(root)
    entries, _scanned, _truncated = loop_telemetry.read_events(root, scan_lines=scan_lines)
    if run_id:
        entries = [e for e in entries if e.get("run_id") == run_id]

    rows: Dict[str, EngineTelemetryRollup] = {}
    for rule in ENGINE_RULES:
        if not rule.signals:
            rows[rule.engine_id] = EngineTelemetryRollup(
                engine_id=rule.engine_id, engine_name=rule.engine_name,
                has_signal_source=False,
                invocation_count=NOT_AVAILABLE, per_signal_counts=NOT_AVAILABLE,
                distinct_run_ids=NOT_AVAILABLE, first_seen_ts=NOT_AVAILABLE,
                last_seen_ts=NOT_AVAILABLE, gap_note=rule.gap_note,
            )
            continue

        matched: List[EventRecord] = [
            e for e in entries if any(_signal_matches(sig, e) for sig in rule.signals)
        ]
        per_signal: Dict[str, int] = {sig.event_name: 0 for sig in rule.signals}
        for e in matched:
            for sig in rule.signals:
                if _signal_matches(sig, e):
                    per_signal[sig.event_name] += 1
        run_ids = sorted({e["run_id"] for e in matched if e.get("run_id")})
        timestamps = [e["ts"] for e in matched if e.get("ts")]

        rows[rule.engine_id] = EngineTelemetryRollup(
            engine_id=rule.engine_id, engine_name=rule.engine_name,
            has_signal_source=True,
            invocation_count=len(matched),
            per_signal_counts=per_signal,
            distinct_run_ids=run_ids,
            first_seen_ts=timestamps[0] if timestamps else None,
            last_seen_ts=timestamps[-1] if timestamps else None,
            gap_note=rule.gap_note,
        )
    return rows


def rollup_pass(rows: Dict[str, EngineTelemetryRollup]) -> bool:
    """`EightEngineRuntimeTelemetryRollup_PASS` -- deliberately NOT the literal
    section-374 `EightEngineRuntimeAuditTrail_PASS` flag (see module
    docstring for why this module cannot honestly claim that name). True only
    if every engine both HAS a signal source and fired at least once in the
    scanned window -- still always False today against real evidence, because
    3 of 8 engines have no producer at all yet. That is the honest current
    answer, not a bug to work around."""
    return bool(rows) and all(
        r.has_signal_source and isinstance(r.invocation_count, int) and r.invocation_count > 0
        for r in rows.values()
    )


def render_rollup_text(rows: Dict[str, EngineTelemetryRollup]) -> str:
    header = f"{'Engine':<32} | {'Count':<8} | {'Runs':<6} | {'Last Seen'}"
    lines = [header, "-" * len(header)]
    for row in rows.values():
        count = row.invocation_count if row.has_signal_source else "N/A"
        runs = len(row.distinct_run_ids) if row.has_signal_source else "N/A"
        last = row.last_seen_ts if row.has_signal_source and row.last_seen_ts else "-"
        lines.append(f"{row.engine_name:<32} | {str(count):<8} | {str(runs):<6} | {last}")
    lines.append("")
    lines.append(f"EightEngineRuntimeTelemetryRollup_PASS = {rollup_pass(rows)}")
    return "\n".join(lines)


def execute_verb(root: Path, verb: str, *, run_id: Optional[str] = None
                  ) -> Tuple[int, Any]:
    """Same shared-`execute_verb()` convention `loop_telemetry`/`loop_contract`/
    `loop_budget`/`eight_engine_runtime_proof_matrix` already follow."""
    root = Path(root)
    if verb in ("rollup", "show"):
        rows = build_rollup(root, run_id=run_id)
        if verb == "show":
            return (0 if rollup_pass(rows) else 2), render_rollup_text(rows)
        return (0 if rollup_pass(rows) else 2), {
            "rows": {k: v.to_dict() for k, v in rows.items()},
            "EightEngineRuntimeTelemetryRollup_PASS": rollup_pass(rows),
        }
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["rollup", "show"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    import json
    p = argparse.ArgumentParser(
        prog="python -m dv_harness.eight_engine_telemetry_rollup",
        description="L5DGVA V14 section 374's per-engine telemetry rollup over "
                    "real .dv-harness/events.jsonl evidence only.")
    p.add_argument("verb", choices=["rollup", "show"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--run-id", default=None)
    args = p.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb, run_id=args.run_id)
    print(payload if isinstance(payload, str)
          else json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
