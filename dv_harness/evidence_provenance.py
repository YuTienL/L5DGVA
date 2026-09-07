"""dv_harness/evidence_provenance.py -- who actually produced a gate's
evidence, enforced on the shared gate-evidence block and carried through to
every surface that renders the resulting claim.

THE GAP THIS CLOSES (confirmed by direct search before anything was written:
`grep -rn "evidence_provenance|AGENT_SELF_ATTESTED|TOOL_DERIVED|
SIMULATION_DERIVED" --include=*.py --include=*.json .` matched exactly one
unrelated string in a reference-base manifest, and no gate anywhere asked who
produced its input).

`gates.run_gate()` assembles every stage gate's payload from the ONE fenced
```dv-harness-evidence:<gate_id>``` block the AGENT typed
(`gates.extract_evidence_blocks()`). For most gates that is fine: the script
re-derives something, or cross-checks the claim against a harness-owned
artifact (`ContextFlag`, `DV_HARNESS_PROJECT_ROOT`, the waiver ledger, the
subsystem registry, a real remote transcript).

Six gates are not like that. Each one's PASS is a statement about DYNAMIC
SYSTEM BEHAVIOUR -- deadlock freedom, livelock freedom, per-port forward
progress, fairness/QoS, interrupt acknowledgement latency, scoreboard
transaction liveness -- a property nothing can establish without RUNNING
something (a simulation, a formal tool, a trace analyser). Their scripts are
pure shape checks over numbers the agent typed. So before this module,
"the system is deadlock-free" could be produced by an agent writing
`{"deadlock_detected": false, ...}`, and the resulting PASS was rendered
identically to a PASS backed by a real tool run. That indistinguishability --
not the absence of a formal checker -- is the defect.

WHAT THIS DOES AND DOES NOT DO. It does NOT verify deadlock freedom; building
a real deadlock checker needs a formal tool this project does not have, and
pretending otherwise is exactly the fabrication CLAUDE.md's Evidence Truth
Rule forbids. What it does is make the SELF-ATTESTED nature of that evidence
impossible to mistake for independently-derived evidence:

  * `evidence_provenance` is a REQUIRED field on those six gates' evidence
    blocks. Absent -> the gate FAILs `EVIDENCE_PROVENANCE_MISSING` before its
    script is even invoked. An unrecognised value -> `EVIDENCE_PROVENANCE_
    INVALID`. There is no default, because defaulting would decide the very
    question the field exists to record.
  * Declaring the honest value (`AGENT_SELF_ATTESTED`) is FREE and always
    permitted -- an agent must never be pushed toward a stronger claim to get
    a stage moving. Claiming an INDEPENDENTLY-DERIVED value costs a real
    `evidence_derivation` naming a producing tool AND an artifact path that
    must EXIST on disk under the project root. That asymmetry is the whole
    design: the cheap answer is the true one.
  * Every consumer that renders the resulting claim renders the caveat with
    it -- `control_plane.describe_stage()` (the one shared read path the
    dashboard's "Why (current stage)" card and the CLI's explain/evidence/
    checklist verbs all already go through) and
    `signoff_export.read_signoff_stage_status()` (what a human reads when
    deciding to sign off, and what `collect_signoff_bundle()` stamps into the
    exported bundle).

DELIBERATELY BOUNDED, and stated rather than implied closed.
 1. The artifact check proves a FILE EXISTS at a path the agent named. It does
    NOT parse that file, and it cannot prove the file contains the claim. It
    is a real cost, not a proof: it stops a free upgrade from
    AGENT_SELF_ATTESTED to TOOL_DERIVED, it does not make TOOL_DERIVED mean
    "verified". A caller wanting content verification has to point the claim
    at a gate that re-derives it (`remote_execution_provenance_gate` is the
    model).
 2. Only the six gates in `PROVENANCE_REQUIRED_GATES` are enforced. That set
    is not "gates we got to"; it is the gates whose PASS asserts a measured
    DYNAMIC BEHAVIOUR property and whose script is a pure shape check over
    agent-typed numbers. Every other gate is untouched and every un-migrated
    project keeps its exact previous behaviour on them.
 3. It ARBITRATES nothing and AUTHORIZES nothing. It runs no stage, starts no
    build/regression/LSF submission, mints no approval, and there is
    deliberately no stage gate of its own. An AGENT_SELF_ATTESTED PASS is
    still a PASS -- it is a PASS a human is now told the provenance of.
 4. It cannot detect a FALSE provenance declaration. An agent that types
    `TOOL_DERIVED` and points at a real unrelated file passes the check. What
    is closed is the SILENT case: evidence that carried no provenance at all
    and was therefore rendered exactly like tool-derived evidence.

FLAG_SUSPICIOUS (2026-09-07), a DIFFERENT axis, additive to everything above.
Provenance answers "who produced this evidence"; it says nothing about
whether a reviewer, having read a PASS, doubts it. There was no verb for
that anywhere in this codebase, distinct from the two nearest-looking
mechanisms: CORRECT (`control_plane.py`'s `set_correction()`) resets a
whole STAGE, and COSIGN (`add_cosign()`) is opt-in AGREEMENT scoped only to
`gates.JUDGMENT_FIELDS`. `control_plane.py`'s `flag_suspicious()` is the
missing third verb -- a durable doubt record against one named `target` (a specific
gate result or evidence citation), resetting nothing and requiring no
agreement. `suspicion_target_for_gate()` above is the one convention this
module recognises for flagging a whole gate result (`"gate:<gate_id>"`);
`summarize_evidence_blocks()`/`summarize_project_provenance()` fold an OPEN
flag against one of `PROVENANCE_REQUIRED_GATES`' own results into the same
summary this module already produces, so a flagged claim is caveated on the
same surfaces a self-attested one already is, never a third, separately-read
place. A flag against any other target string (a non-provenance-required
gate, a bare evidence-citation path) is still real and on file --
`control_plane.describe_stage()`'s own top-level `suspicious_flags` key
carries every flag for a stage regardless of whether this module's narrower
convention recognises its `target`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: The field name on the gate-evidence block. One name, used by the enforcer,
#: every consumer and the prompt text -- never spelled a second way.
PROVENANCE_FIELD = "evidence_provenance"

#: The companion object an independently-derived claim must carry.
DERIVATION_FIELD = "evidence_derivation"

#: The agent wrote these numbers itself. Honest, always permitted, free.
AGENT_SELF_ATTESTED = "AGENT_SELF_ATTESTED"
#: A real tool (formal engine, trace analyser, fsdbreport, a checker script)
#: produced the numbers, and a real artifact of that run is on disk.
TOOL_DERIVED = "TOOL_DERIVED"
#: A real simulation produced the numbers, and its log/report is on disk.
SIMULATION_DERIVED = "SIMULATION_DERIVED"

PROVENANCE_VALUES: Tuple[str, ...] = (
    AGENT_SELF_ATTESTED,
    TOOL_DERIVED,
    SIMULATION_DERIVED,
)

#: The two values that CLAIM an independent producer, and therefore have to
#: pay for the claim with a real artifact. Deliberately a derived set rather
#: than a second hand-maintained list.
INDEPENDENTLY_DERIVED: frozenset = frozenset({TOOL_DERIVED, SIMULATION_DERIVED})

#: Failure reasons. Each is a distinct operator problem with a distinct fix,
#: so none of them is collapsed into a generic "bad provenance".
REASON_MISSING = "EVIDENCE_PROVENANCE_MISSING"
REASON_INVALID = "EVIDENCE_PROVENANCE_INVALID"
REASON_DERIVATION_MISSING = "EVIDENCE_PROVENANCE_DERIVATION_MISSING"
REASON_ARTIFACT_NOT_FOUND = "EVIDENCE_PROVENANCE_ARTIFACT_NOT_FOUND"
REASON_PAYLOAD_NOT_OBJECT = "EVIDENCE_PROVENANCE_PAYLOAD_NOT_OBJECT"

#: The gates whose PASS asserts a measured DYNAMIC BEHAVIOUR property that
#: nothing can establish without running something, and whose own script is a
#: pure shape check over agent-typed numbers. The value is the headline claim
#: that gate's PASS produces -- kept here so the table documents WHY each
#: entry is in it, and so a reader can check the rule was applied rather than
#: trusting that it was.
PROVENANCE_REQUIRED_GATES: Dict[str, str] = {
    "system_level_deadlock_livelock_gate":
        "the composed system is free of deadlock and livelock",
    "system_level_resource_contention_gate":
        "every shared-resource contention scenario is arbitrated and tested",
    "per_port_queue_starvation_gate":
        "no port starves; every port makes forward progress within its bound",
    "multi_port_fairness_qos_gate":
        "each port receives its minimum service share and QoS policy holds",
    "interrupt_storm_latency_gate":
        "interrupt acknowledgement latency is bounded and no interrupt is lost",
    "scoreboard_transaction_liveness_gate":
        "no transaction is missing or duplicated and latency stays in bound",
}

#: Rendered wherever an AGENT_SELF_ATTESTED result is shown. One string, so
#: the dashboard, the CLI and the signoff bundle cannot word the warning
#: differently and read as different strengths of warning.
SELF_ATTESTED_CAVEAT = (
    "SELF-ATTESTED: this claim was typed by the agent and was NOT "
    "independently derived by any tool or simulation. It is not evidence "
    "that the property holds."
)

#: Rendered for an independently-derived result, so the weaker guarantee that
#: check really makes is visible too rather than being read as verification.
DERIVED_CAVEAT = (
    "Declared as independently derived, and a real producing artifact was "
    "found on disk. The harness checked that the artifact EXISTS; it did not "
    "parse it, so this is provenance, not verification of the claim."
)

#: The `target` key convention `control_plane.py`'s `flag_suspicious()`
#: uses to flag one of PROVENANCE_REQUIRED_GATES' own results as suspicious
#: (2026-09-07). A suspicion flag is a DIFFERENT axis from provenance -- who
#: produced the evidence vs. whether a reviewer now doubts the result -- and
#: is neither CORRECT (a whole-stage reset) nor COSIGN (agreement, opt-in and
#: scoped only to gates.JUDGMENT_FIELDS); see that function's own docstring
#: for the full distinction. "gate:<gate_id>" is deliberately a
#: different shape from add_cosign()'s own "<gate_id>/<loc>" convention: a
#: suspicion flag here names the whole gate RESULT this module enforces
#: provenance on, never one judgment field inside it.
SUSPICION_TARGET_PREFIX = "gate:"

#: Rendered wherever an OPEN suspicion flag is shown against one of these six
#: gates' own results, alongside (never instead of) that gate's own provenance
#: caveat -- a flagged TOOL_DERIVED result is still exactly as independently
#: produced as it was; a human has separately said they doubt it.
SUSPICION_FLAG_CAVEAT = (
    "FLAGGED SUSPICIOUS: a reviewer has marked this gate's result as needing "
    "re-verification. See the flag's own 'reason' for why."
)


def suspicion_target_for_gate(gate_id: str) -> str:
    """The `target` string a caller passes to
    `control_plane.py`'s `flag_suspicious()` / `commands.cmd_flag_suspicious()`
    to flag one of PROVENANCE_REQUIRED_GATES' own results as suspicious. Not
    restricted to PROVENANCE_REQUIRED_GATES itself -- any gate id may be
    flagged this way -- but this is the one convention this module's own
    consumers (summarize_evidence_blocks() below) recognise and surface."""
    return f"{SUSPICION_TARGET_PREFIX}{gate_id}"


class ProvenanceCheckError(Exception):
    """Raised only by the module's own strict helpers. `check_payload()`
    itself returns a finding rather than raising, because it runs inside
    `gates.run_gate()`, whose contract is to return a GateResult for every
    outcome and never to propagate an exception out of a gate evaluation."""


def gate_requires_provenance(gate_id: str) -> bool:
    return gate_id in PROVENANCE_REQUIRED_GATES


def declared_provenance(payload: Any) -> Optional[str]:
    """The provenance an evidence block declares, or None. Never defaults --
    the absence IS the answer this module exists to surface."""
    if not isinstance(payload, dict):
        return None
    value = payload.get(PROVENANCE_FIELD)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def is_independently_derived(provenance: Optional[str]) -> bool:
    return provenance in INDEPENDENTLY_DERIVED


def caveat_for(provenance: Optional[str]) -> Optional[str]:
    """The caveat text for a declared provenance, or None when there is
    nothing to warn about beyond what the value itself says. An UNDECLARED
    provenance gets the self-attested caveat, not silence: on a gate this
    module does not enforce, "nobody said" is at best as strong as
    "the agent said so"."""
    if provenance is None:
        return SELF_ATTESTED_CAVEAT
    if provenance == AGENT_SELF_ATTESTED:
        return SELF_ATTESTED_CAVEAT
    if provenance in INDEPENDENTLY_DERIVED:
        return DERIVED_CAVEAT
    return SELF_ATTESTED_CAVEAT


def _resolve_artifact(root: Path, raw_path: str) -> Optional[Path]:
    """Resolve raw_path under root. Returns None (never a path outside root)
    when an absolute raw_path escapes the project root -- the artifact-
    existence check below treats that identically to a missing file, since a
    resolvable-but-uncontained path is not evidence about this project."""
    p = Path(str(raw_path))
    root = Path(root).resolve()
    candidate = p if p.is_absolute() else root / p
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def check_payload(root: Path, gate_id: str, payload: Any) -> Optional[Dict[str, Any]]:
    """The enforcement. Returns None when the payload satisfies this gate's
    provenance requirement, or a gate-detail dict (the same
    {"status": "FAIL", "reason": ...} shape every gate script prints) when it
    does not. A gate outside PROVENANCE_REQUIRED_GATES always returns None --
    this never touches a gate it does not enforce.

    Raises nothing: `gates.run_gate()` must return a GateResult for every
    outcome."""
    if not gate_requires_provenance(gate_id):
        return None
    claim = PROVENANCE_REQUIRED_GATES[gate_id]
    if not isinstance(payload, dict):
        return {
            "status": "FAIL",
            "reason": REASON_PAYLOAD_NOT_OBJECT,
            "gate_claim": claim,
            "detail": (
                "this gate's evidence block must be a JSON object carrying "
                f"'{PROVENANCE_FIELD}'"
            ),
        }
    raw = payload.get(PROVENANCE_FIELD)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {
            "status": "FAIL",
            "reason": REASON_MISSING,
            "gate_claim": claim,
            "required_field": PROVENANCE_FIELD,
            "accepted_values": list(PROVENANCE_VALUES),
            "detail": (
                f"'{claim}' is a claim about dynamic system behaviour. State who "
                f"produced this evidence: '{PROVENANCE_FIELD}' must be one of "
                f"{list(PROVENANCE_VALUES)}. '{AGENT_SELF_ATTESTED}' is always "
                "accepted and needs nothing else."
            ),
        }
    provenance = raw.strip() if isinstance(raw, str) else raw
    if provenance not in PROVENANCE_VALUES:
        return {
            "status": "FAIL",
            "reason": REASON_INVALID,
            "gate_claim": claim,
            "declared": provenance,
            "accepted_values": list(PROVENANCE_VALUES),
        }
    if provenance not in INDEPENDENTLY_DERIVED:
        return None

    derivation = payload.get(DERIVATION_FIELD)
    tool = (derivation or {}).get("tool") if isinstance(derivation, dict) else None
    artifact = (derivation or {}).get("artifact_path") if isinstance(derivation, dict) else None
    if not isinstance(derivation, dict) or not str(tool or "").strip() \
            or not str(artifact or "").strip():
        return {
            "status": "FAIL",
            "reason": REASON_DERIVATION_MISSING,
            "gate_claim": claim,
            "declared": provenance,
            "required_field": DERIVATION_FIELD,
            "detail": (
                f"declaring '{provenance}' claims a real producer, so "
                f"'{DERIVATION_FIELD}' must name both the producing 'tool' and an "
                "'artifact_path' that exists on disk. Declare "
                f"'{AGENT_SELF_ATTESTED}' instead if no such run happened."
            ),
        }
    resolved = _resolve_artifact(Path(root), str(artifact))
    if resolved is None or not resolved.exists():
        return {
            "status": "FAIL",
            "reason": REASON_ARTIFACT_NOT_FOUND,
            "gate_claim": claim,
            "declared": provenance,
            "tool": str(tool),
            "artifact_path": str(artifact),
            "resolved_path": str(resolved) if resolved is not None else None,
            "detail": (
                "the artifact this independently-derived claim cites does not "
                "exist under the project root. A provenance claim nothing on "
                "disk backs is not stronger than "
                f"'{AGENT_SELF_ATTESTED}'."
            ),
        }
    return None


def annotate_gate_detail(gate_id: str, payload: Any, detail: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp the declared provenance and its caveat onto a gate result so
    every downstream reader of that result sees them without having to
    re-open the evidence block. Returns a NEW dict; the caller's is untouched.

    Only stamps enforced gates: writing a provenance annotation onto a gate
    this module does not enforce would present a field nobody supplied and
    nobody checked as if it had been decided."""
    if not gate_requires_provenance(gate_id):
        return detail
    provenance = declared_provenance(payload)
    out = dict(detail or {})
    out[PROVENANCE_FIELD] = provenance
    out["evidence_provenance_independently_derived"] = is_independently_derived(provenance)
    out["evidence_provenance_caveat"] = caveat_for(provenance)
    out["evidence_provenance_claim"] = PROVENANCE_REQUIRED_GATES[gate_id]
    return out


def summarize_evidence_blocks(blocks: Dict[str, Any],
                               suspicious_flags: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The per-consumer summary: for the enforced gates present in one stage's
    evidence blocks, what each declared and whether any headline claim rests
    on self-attestation.

    `blocks` is exactly `gates.extract_evidence_blocks()`'s output, so a
    consumer that already has the blocks does not re-parse the agent text.

    `suspicious_flags` (2026-09-07) is optional and additive -- a stage's own
    `control.json["suspicious_flags"][stage]` map (as
    `control_plane.describe_stage()` now passes), keyed by the same `target`
    strings `control_plane.py`'s `flag_suspicious()` stores. Omitting it (the default)
    leaves every entry's `flagged_suspicious`/`suspicion_flag` at their honest
    False/None -- existing callers see no behaviour change. A flag is only
    ever recognised here when its `target` equals
    `suspicion_target_for_gate(gate_id)`; any other `target` string a caller
    used is a real flag `control_plane.describe_stage()`'s own top-level
    `suspicious_flags` key still carries, just not folded into this
    provenance-specific view."""
    entries: List[Dict[str, Any]] = []
    for gate_id in sorted(PROVENANCE_REQUIRED_GATES):
        if gate_id not in (blocks or {}):
            continue
        payload = (blocks or {})[gate_id]
        provenance = declared_provenance(payload)
        flag = (suspicious_flags or {}).get(suspicion_target_for_gate(gate_id))
        flagged = bool(flag and flag.get("status") == "OPEN")
        entries.append({
            "gate_id": gate_id,
            "claim": PROVENANCE_REQUIRED_GATES[gate_id],
            PROVENANCE_FIELD: provenance,
            "independently_derived": is_independently_derived(provenance),
            "caveat": caveat_for(provenance),
            "flagged_suspicious": flagged,
            "suspicion_flag": flag,
        })
    self_attested = [e["gate_id"] for e in entries if not e["independently_derived"]]
    flagged_gate_ids = [e["gate_id"] for e in entries if e["flagged_suspicious"]]
    return {
        "entries": entries,
        "self_attested_gate_ids": self_attested,
        "has_self_attested_claims": bool(self_attested),
        "caveat": SELF_ATTESTED_CAVEAT if self_attested else None,
        "flagged_gate_ids": flagged_gate_ids,
        "has_flagged_suspicious": bool(flagged_gate_ids),
        "suspicion_caveat": SUSPICION_FLAG_CAVEAT if flagged_gate_ids else None,
    }


def summarize_project_provenance(root: Path) -> Dict[str, Any]:
    """Project-wide summary across every stage that recorded a response,
    for a consumer that has no single stage in hand (signoff_export).

    Reads `.dv-harness/state.json` with a plain read_text/json.loads, NOT
    through `storage.StateStore`: StateStore.load() CREATES a state.json and
    the whole .dv-harness tree when none exists, and asking a project who
    attested its evidence must never bring that project's governance state
    into existence -- the same reason
    `signoff_export.read_signoff_stage_status()` reads it the same way.
    `.dv-harness/control.json` (the suspicion-flag store) is read the same
    plain way, for the same reason -- `control_plane.py`'s own read/write
    class constructor mkdirs `.dv-harness`, so it is never used here either."""
    from .gates import extract_evidence_blocks

    root = Path(root)
    state_path = root / ".dv-harness" / "state.json"
    if not state_path.is_file():
        return {
            "available": False,
            "reason": "NO_STATE_FILE",
            "state_path": str(state_path),
            "stages": {},
            "self_attested_claims": [],
            "has_self_attested_claims": False,
            "caveat": None,
        }
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "available": False,
            "reason": "STATE_FILE_UNREADABLE",
            "state_path": str(state_path),
            "error": str(exc),
            "stages": {},
            "self_attested_claims": [],
            "has_self_attested_claims": False,
            "caveat": None,
        }
    control_path = root / ".dv-harness" / "control.json"
    all_flags: Dict[str, Any] = {}
    if control_path.is_file():
        try:
            control = json.loads(control_path.read_text(encoding="utf-8"))
            if isinstance(control, dict):
                all_flags = control.get("suspicious_flags") or {}
        except (OSError, ValueError):
            all_flags = {}
    stages = state.get("stages") if isinstance(state, dict) else None
    per_stage: Dict[str, Any] = {}
    self_attested: List[Dict[str, Any]] = []
    flagged_suspicious: List[Dict[str, Any]] = []
    for stage, ss in sorted((stages or {}).items()):
        if not isinstance(ss, dict):
            continue
        blocks = extract_evidence_blocks(ss.get("last_message", "") or "")
        summary = summarize_evidence_blocks(blocks, suspicious_flags=all_flags.get(stage, {}))
        if not summary["entries"]:
            continue
        per_stage[stage] = summary
        for entry in summary["entries"]:
            if not entry["independently_derived"]:
                self_attested.append({
                    "stage": stage,
                    "gate_id": entry["gate_id"],
                    "claim": entry["claim"],
                    PROVENANCE_FIELD: entry[PROVENANCE_FIELD],
                })
            if entry["flagged_suspicious"]:
                flagged_suspicious.append({
                    "stage": stage,
                    "gate_id": entry["gate_id"],
                    "claim": entry["claim"],
                    "suspicion_flag": entry["suspicion_flag"],
                })
    return {
        "available": True,
        "reason": None,
        "flagged_suspicious_claims": flagged_suspicious,
        "has_flagged_suspicious_claims": bool(flagged_suspicious),
        "suspicion_caveat": SUSPICION_FLAG_CAVEAT if flagged_suspicious else None,
        "state_path": str(state_path),
        "stages": per_stage,
        "self_attested_claims": self_attested,
        "has_self_attested_claims": bool(self_attested),
        "caveat": SELF_ATTESTED_CAVEAT if self_attested else None,
    }


def render_caveat_lines(summary: Dict[str, Any]) -> List[str]:
    """Plain-text rendering shared by any text surface (CLI, report, bundle
    note). Returns [] when there is nothing to warn about, so a caller can
    append unconditionally without emitting an empty warning block."""
    if not summary or not summary.get("has_self_attested_claims"):
        return []
    lines = [SELF_ATTESTED_CAVEAT]
    claims = summary.get("self_attested_claims")
    if claims is None:
        claims = [
            {"stage": None, "gate_id": e["gate_id"], "claim": e["claim"]}
            for e in summary.get("entries", [])
            if not e.get("independently_derived")
        ]
    for c in claims:
        where = f"{c['stage']}/" if c.get("stage") else ""
        declared = c.get(PROVENANCE_FIELD) or "UNDECLARED"
        lines.append(f"  - {where}{c['gate_id']} [{declared}]: {c['claim']}")
    return lines


def assert_required_gates_are_registered() -> None:
    """Every gate this module enforces must be a gate that really runs.

    A provenance requirement on a gate id no stage registers would be a rule
    nothing ever applies -- it would read as coverage while enforcing nothing.
    Held as a real check rather than as a comment, so renaming or unwiring one
    of these gates fails a test instead of silently emptying the enforcement
    set. Imported lazily: gates.py imports this module."""
    from .gates import STAGE_GATES

    registered = {gid for entries in STAGE_GATES.values() for gid, _s, _f in entries}
    missing = sorted(set(PROVENANCE_REQUIRED_GATES) - registered)
    if missing:
        raise ProvenanceCheckError(
            "PROVENANCE_REQUIRED_GATES names gate ids that no stage registers "
            f"in gates.STAGE_GATES: {missing}"
        )
