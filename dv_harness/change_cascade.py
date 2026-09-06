"""dv_harness/change_cascade.py -- change-cascade impact table (2026-09-06).

GAP THIS CLOSES. This project produces a great many derived artifacts off a
small set of upstream facts -- a VIP release, a chunk of DUT RTL, a register
map, an address map, a bind topology, a UPF power-intent file, a requirement
record, a waiver, a configuration-variant space, a subsystem registry entry,
a testplan/vPlan correspondence. Each of those facts already has a REAL
producer somewhere in this codebase (`env_manifest.py`, `vip_api_card.py`,
`connectivity.py`, `phy_boundary.py`, `power_intent.py`,
`requirement_contract.py`, `waiver_store.py`, `config_variant_coverage.py`,
`golden_scenario.py`, `signoff_export.py`, ...), and several of those
producers already compute a NARROW re-derive-one-thing staleness check of
their own (`golden_scenario.evaluate_freshness()` for a capsule,
`waiver_store.derive_status()` for one waiver,
`signoff_export.evaluate_freeze_invalidation()` for one frozen baseline).
None of them, and nothing anywhere in this repo, answers the WIDER question
a human or an agent actually has the instant one of those upstream facts
changes: "which OTHER already-computed artifacts across this whole harness
does that change make suspect, and why, specifically enough to know what to
re-run?" A repo-wide grep for `change_cascade`/`ChangeCascade`/
`downstream_artifact`/`cascade_impact` before this change returned nothing
executable. An agent who bumped a VIP version had no single place to be
told that the VIP API cards, the connectivity gate verdicts and any golden
scenario capsule watching that tool version were all now suspect -- each of
those three facts individually IS discoverable (by reading three different
modules' own narrow staleness logic), but nothing joined them into one
lookup keyed on "what changed".

THIS MODULE IS THAT LOOKUP, and only that. It is a small, hand-curated
{changed_field -> downstream artifacts} table plus a function that answers
"what does this changed field make suspect, and why" -- it does not itself
RE-DERIVE any staleness verdict (that stays each artifact's own real
producer's job, cited here by `producing_module` so the citation is
checkable rather than trusted prose -- see `assert_producing_modules_resolve()`,
the same "does the cited module really import" discipline
`protocol_capability.py`'s registry and `golden_flow_readiness.py`'s row
table already hold themselves to). It also never widens the table by
guessing: an undeclared `changed_field` reports `UNKNOWN_FIELD` naming the
real declared fields, never a silently empty "nothing downstream" -- an
unmapped change is unknown impact, not zero impact.

REUSE, NOT REINVENTION OF question_queue.py's REVOCATION MECHANISM. When a
changed field invalidates the very fact an earlier Tier-2 auto-assumption or
human answer was keyed on, the sanctioned undo is already real:
`question_queue.QuestionQueueStore.revoke_decision()`. This module's
`revoke_stale_decisions()` is a thin, explicit caller of that existing
function -- it invents no second decisions store and no second revocation
mechanic. It is deliberately NOT automatic: this module has no way to know,
for an arbitrary project, which `question_key` strings that project's own
question-queue callers used for a decision that a given field change now
invalidates (question_key naming is each caller's own convention -- see
`question_queue.make_question_key()`), so guessing one would be exactly the
fabrication the Evidence Truth Rule forbids. A caller (human or agent) who
already knows which decision(s) a change invalidated supplies those
`question_key` strings explicitly, and this module performs the real
revocation call, one key at a time, treating "nothing was on file for that
key" (`revoke_decision()`'s own `KeyError`) as an honest `NO_LIVE_DECISION`
outcome rather than an error.

DECOUPLED FROM EVERY OTHER MODULE IN THIS BATCH, ON PURPOSE. Several other
gap-closure items in flight alongside this one would be natural upstream
producers of "what changed" (a real diff-detection module, a subsystem
change-request tracker, ...). None of them is imported here. `assess_changes()`
takes a plain, duck-typed iterable -- each entry either a bare field-name
string or any dict/object carrying a `field` attribute/key -- so a future
detector's real output can be handed to this function unmodified, once that
detector exists, as long as each of its records names the field it changed.
Until then, a caller (human, agent, or a hand-rolled diff check) supplies the
list of changed fields directly.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import question_queue as _question_queue

SCHEMA_VERSION = "1.0"

STATUS_MAPPED = "MAPPED"
STATUS_UNKNOWN_FIELD = "UNKNOWN_FIELD"
STATUS_NO_FIELD_NAMED = "NO_FIELD_NAMED"

REVOKE_STATUS_REVOKED = "REVOKED"
REVOKE_STATUS_NO_LIVE_DECISION = "NO_LIVE_DECISION"


class ChangeCascadeError(Exception):
    """Raised only by assert_producing_modules_resolve() -- a table citation
    that no longer imports. Never raised by cascade_for_changed_field() or
    assess_changes(), which report an unknown field as data, not an error."""


@dataclass(frozen=True)
class DownstreamArtifact:
    """One artifact this harness already produces that a given changed_field
    makes suspect. `artifact` names the real on-disk path/artifact this repo
    already writes (per the modules cited in CLAUDE.md); `producing_module`
    is the dotted module that really owns it (checked, not trusted, by
    assert_producing_modules_resolve()); `revalidation_action` is the real
    command that would re-derive or re-check it -- never a made-up verb."""

    artifact: str
    reason: str
    producing_module: str
    revalidation_action: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "artifact": self.artifact,
            "reason": self.reason,
            "producing_module": self.producing_module,
            "revalidation_action": self.revalidation_action,
        }


# ---------------------------------------------------------------------------
# The dependency table. Deliberately small and hand-curated (per the task:
# "a small {changed_field -> downstream_artifacts} dependency table"), not an
# attempt at exhaustive coverage of every fact this harness ever derives --
# an undeclared field reports UNKNOWN_FIELD rather than a guessed answer, so
# the table can grow without ever having silently claimed completeness.
# ---------------------------------------------------------------------------

CHANGE_CASCADE_TABLE: Dict[str, Tuple[DownstreamArtifact, ...]] = {
    "vip_version": (
        DownstreamArtifact(
            artifact="<generated env out_dir>/vip_api_cards.json",
            reason="a VIP API card's PROVEN/BLOCKED verdict is resolved against one specific "
                   "installed VIP release's real symbol index (vip_symbol_index.py); a different "
                   "release can rename, remove or add methods a prior verdict never saw.",
            producing_module="dv_harness.vip_api_card",
            revalidation_action="dv-harness vip-api-check --source <dir> --index <new vip index>",
        ),
        DownstreamArtifact(
            artifact=".dv-harness/env.manifest.json (vip_config.vip_release layer)",
            reason="vip_config.vip_release is a real $DESIGNWARE_HOME filesystem scan "
                   "(env_manifest.scan_designware_home()); a version bump changes which "
                   "release/feature-matrix files that scan finds.",
            producing_module="dv_harness.env_manifest",
            revalidation_action="dv-harness env-manifest generate",
        ),
        DownstreamArtifact(
            artifact="bind validations (connectivity.py Gate 1-3 verdicts, connectivity matrix)",
            reason="the 3 machine gates and the bind-confidence tiers were computed against a "
                   "specific VIP instance's real zero-time config-db dump; a VIP release change "
                   "can move default config values those gates already trusted.",
            producing_module="dv_harness.connectivity",
            revalidation_action="just connectivity-check",
        ),
        DownstreamArtifact(
            artifact="recorded golden scenario capsule freshness",
            reason="golden_scenario.evaluate_freshness() explicitly treats a recorded VIP/tool "
                   "version that no longer matches a caller-supplied current one as STALE, with "
                   "no git change required at all.",
            producing_module="dv_harness.golden_scenario",
            revalidation_action="dv-harness golden-scenario status --vip-version <tool>=<version>",
        ),
    ),
    "rtl_source": (
        DownstreamArtifact(
            artifact=".dv-harness/env.manifest.json (dut_facts.rtl layer)",
            reason="dut_facts.rtl is a real verible --export_json parse of the DUT RTL tree; "
                   "changed RTL text changes what that parse reports (ports, module names).",
            producing_module="dv_harness.env_manifest",
            revalidation_action="dv-harness env-manifest generate",
        ),
        DownstreamArtifact(
            artifact=".dv-harness/connectivity_check_state.json (Gate 1-3 verdicts)",
            reason="connectivity_check.py's own staleness trigger is a content fingerprint of "
                   "the declared rtl_sources; a real RTL edit moves that fingerprint and the "
                   "recorded gate verdicts are, by that module's own rule, no longer citable.",
            producing_module="dv_harness.connectivity_check",
            revalidation_action="just connectivity-check",
        ),
        DownstreamArtifact(
            artifact="recorded golden scenario capsule freshness",
            reason="evaluate_freshness() runs a real git diff against the capsule's recorded "
                   "verified_sha through change_impact's HIGH/MEDIUM/LOW risk model; RTL under a "
                   "capsule's watched_paths at HIGH risk makes it STALE.",
            producing_module="dv_harness.golden_scenario",
            revalidation_action="dv-harness golden-scenario status",
        ),
        DownstreamArtifact(
            artifact=".dv-workflow/phy_boundary.json (PHY mount-layer decision)",
            reason="phy_boundary.py derives the serial/parallel boundary from the same "
                   "verible-parsed port table env_manifest.py produces; a port list change can "
                   "move a boundary from bindable to serial-only or back.",
            producing_module="dv_harness.phy_boundary",
            revalidation_action="python -m dv_harness.phy_boundary",
        ),
    ),
    "register_map": (
        DownstreamArtifact(
            artifact=".dv-harness/env.manifest.json (dut_facts.address_map register_map_agreement)",
            reason="every address_map entry carries a real cross-check against dut_facts.registers, "
                   "compared as integers; a changed register file can flip that agreement or "
                   "produce a new DISAGREES the manifest must surface.",
            producing_module="dv_harness.env_manifest",
            revalidation_action="dv-harness env-manifest generate",
        ),
        DownstreamArtifact(
            artifact="verified `` `define `` entries emitted by address_map_verifier",
            reason="address_map_verifier.verify_address_map() resolves a register document's base "
                   "address against the real decoder; a changed register map is one half of that "
                   "comparison and can move which side is stale.",
            producing_module="dv_harness.uvm_generator.address_map_verifier",
            revalidation_action="re-run the project's address-map verification pass",
        ),
    ),
    "address_map": (
        DownstreamArtifact(
            artifact="SYS-9..SYS-14 cross-subsystem resource findings",
            reason="system_resource_inventory.real_cross_subsystem_findings() reasons about shared/"
                   "conflicting address regions across subsystems; an address-map edit is exactly "
                   "the input that analysis consumes.",
            producing_module="dv_harness.system_resource_inventory",
            revalidation_action="re-run the project's system resource inventory analysis",
        ),
        DownstreamArtifact(
            artifact="system topology analysis document",
            reason="system_topology_analysis.analyze_system_topology() reports address-region "
                   "overlap/containment; a moved region changes that report's own findings.",
            producing_module="dv_harness.system_topology_analysis",
            revalidation_action="re-run the project's system topology analysis",
        ),
        DownstreamArtifact(
            artifact="soc_composition_manifest.json (cross_subsystem_analysis)",
            reason="compose_soc_environment() consults the same cross-subsystem analysis before "
                   "composing and records what it found; a moved address map can flip a clean "
                   "composition into CrossSubsystemIntegrationBlockedError or vice versa.",
            producing_module="dv_harness.uvm_generator.soc_environment_composer",
            revalidation_action="re-run SYSTEM_LEVEL composition",
        ),
    ),
    "bind_topology": (
        DownstreamArtifact(
            artifact="tb/*_bind.sv (bind_mechanism_generator emission)",
            reason="emit_bind_sv() writes bind statements from exactly the entries it was handed; "
                   "a changed instance path, tier, or human_confirmation invalidates the emitted "
                   "file until it is regenerated from the new topology.",
            producing_module="dv_harness.uvm_generator.bind_mechanism_generator",
            revalidation_action="re-run tools/generate_bind_mechanism.py over the new topology",
        ),
        DownstreamArtifact(
            artifact="connectivity matrix bind_target column + Gate 1-3 verdicts",
            reason="a changed bind target/tier can move a previously-clean bind into a different "
                   "confidence tier or a different Gate-3 mount-layer outcome.",
            producing_module="dv_harness.connectivity",
            revalidation_action="just connectivity-check",
        ),
    ),
    "phy_boundary": (
        DownstreamArtifact(
            artifact="bind emission's Rule-5 layer decision (assert_phy_boundary_decided_first)",
            reason="validate_bind_entries()/emit_bind_sv() run the boundary check BEFORE the tier "
                   "check; a changed PHY boundary document can flip a previously-bindable mount "
                   "layer to serial-only, which must block emission until re-decided.",
            producing_module="dv_harness.uvm_generator.bind_mechanism_generator",
            revalidation_action="re-run tools/generate_bind_mechanism.py --phy-boundary <doc>",
        ),
        DownstreamArtifact(
            artifact="Gate 3 transaction-activity verdict for any monitor mounted on that boundary",
            reason="a protocol monitor bound at a boundary that has since become serial-only "
                   "decodes nothing -- it would keep passing Gates 1-2 and silently fail Gate 3.",
            producing_module="dv_harness.connectivity",
            revalidation_action="just connectivity-check",
        ),
    ),
    "protocol_model_topology": (
        DownstreamArtifact(
            artifact="tb/env/<protocol>_assertions.sv (compiled state-machine SVA)",
            reason="protocol_model_layer compiles the model's state graph against the manifest's "
                   "declared DUT signal into real transition-legality SVA; a changed lane_width/"
                   "gen_speed/role or state-signal name changes what that compile produces.",
            producing_module="dv_harness.uvm_generator.protocol_model_layer",
            revalidation_action="re-run create_environment() over the updated manifest",
        ),
        DownstreamArtifact(
            artifact="environment_manifest.json protocol_model record",
            reason="a topology change can move a manifest from a resolved protocol_model record "
                   "to PROTOCOL_MODEL_TOPOLOGY_NOT_SUPPLIED or vice versa.",
            producing_module="dv_harness.uvm_generator.protocol_model_layer",
            revalidation_action="re-run create_environment() over the updated manifest",
        ),
    ),
    "upf_power_intent": (
        DownstreamArtifact(
            artifact="architecture_model.json power_domains field",
            reason="power_domains_for_architecture_model() reads the UPF file directly; any edit "
                   "to it changes the modelled domains/strategies build_architecture_model.py "
                   "records.",
            producing_module="dv_harness.power_intent",
            revalidation_action="dv-harness power-intent --upf <file>",
        ),
    ),
    "requirement_contract": (
        DownstreamArtifact(
            artifact="downstream_consumable() gate on any generator fed by this requirement",
            reason="a requirement record's own content decides its derived status (COMPLETE/"
                   "PARTIAL/AMBIGUOUS/CONTRADICTORY/UNKNOWN); an edited field can flip whether "
                   "downstream_consumable() still allows it to feed a generator.",
            producing_module="dv_harness.requirement_contract",
            revalidation_action="dv-harness requirement-contract --requirements <file>",
        ),
        DownstreamArtifact(
            artifact="REQUIREMENTS_TRACEABILITY stage gate verdicts citing this requirement",
            reason="spec_to_vplan_requirement_quality_gate.py (and, for a contract-shaped record, "
                   "requirement_contract.py's own gate layer) judges the requirement's current "
                   "content on every run.",
            producing_module="dv_harness.requirement_contract",
            revalidation_action="re-run the REQUIREMENTS_TRACEABILITY stage gates",
        ),
    ),
    "waiver_ledger": (
        DownstreamArtifact(
            artifact="waiver_scope_consistency_gate / waiver_revision_freshness_gate / "
                     "waiver_revalidation_gate verdicts",
            reason="all three gates read a ledger waiver's DERIVED status on every run; a "
                   "recorded, revoked, or expired waiver is re-evaluated live, not cached.",
            producing_module="dv_harness.waiver_store",
            revalidation_action="python -m dv_harness.waiver_store statuses",
        ),
        DownstreamArtifact(
            artifact="signoff freeze baseline invalidation (waivers field)",
            reason="signoff_export.evaluate_freeze_invalidation() re-derives every frozen waiver's "
                   "status through waiver_store.status_report(); a waiver expiring or being "
                   "revoked after a freeze invalidates that baseline with no git change at all.",
            producing_module="dv_harness.signoff_export",
            revalidation_action="python -m dv_harness.signoff_export status --freeze-id <id>",
        ),
    ),
    "config_variant_space": (
        DownstreamArtifact(
            artifact="config-variant covering-array plan (pairwise/t-way coverage claim)",
            reason="generate_covering_array()/verify_coverage() are computed against one declared "
                   "dimension/legal-value/constraint space; a changed dimension or constraint "
                   "changes both the legal cross-product and the plan's covered-pairs claim.",
            producing_module="dv_harness.config_variant_coverage",
            revalidation_action="dv-harness config-variants plan --space <file>",
        ),
    ),
    "subsystem_registry": (
        DownstreamArtifact(
            artifact="soc_tb_top.sv / soc_composition_manifest.json (SYSTEM_LEVEL composition)",
            reason="compose_soc_environment() reads registered subsystem entries "
                   "(read_registered_subsystem_entries()) directly; a re-qualified or changed "
                   "entry changes what a subsequent composition instantiates.",
            producing_module="dv_harness.uvm_generator.soc_environment_composer",
            revalidation_action="re-run SYSTEM_LEVEL composition",
        ),
        DownstreamArtifact(
            artifact="generation_readiness.py Flow-B rows (Single-Test Proof and later)",
            reason="the Single-Test Proof row is judged from the registry's own qualification_state "
                   "through qualification.map_to_system_level_state(); a demoted or changed entry "
                   "moves that row's status.",
            producing_module="dv_harness.generation_readiness",
            revalidation_action="dv-harness generation-readiness",
        ),
        DownstreamArtifact(
            artifact="system_build_proof.py merge/smoke-proof analysis",
            reason="subsystem_source_sets() reads the same registry to assemble the merged source "
                   "set the smoke-proof ladder runs the 5 merge checks and rungs against.",
            producing_module="dv_harness.system_build_proof",
            revalidation_action="dv-harness system-smoke-proof",
        ),
    ),
    "testplan_correspondence": (
        DownstreamArtifact(
            artifact=".dv-harness/env.manifest.json (env_topology.testplan_correspondence)",
            reason="this is the computed three-way join of the real testlist, vPlan items and "
                   "coverage model; an edit to any one of the three changes what the join reports "
                   "(NOT_CHECKED/LINKED/conflicting claims).",
            producing_module="dv_harness.env_manifest",
            revalidation_action="dv-harness env-manifest generate",
        ),
        DownstreamArtifact(
            artifact="golden_flow_readiness.py Verification-IR / Testplan-Trace rows",
            reason="those rows read env.manifest.json's testplan_correspondence directly, so a "
                   "join that moved changes the golden-flow readiness table too.",
            producing_module="dv_harness.golden_flow_readiness",
            revalidation_action="dv-harness golden-flow-readiness",
        ),
    ),
}


def known_changed_fields() -> Tuple[str, ...]:
    """The declared changed_field keys this table maps, sorted for a stable
    report. Not every fact this harness derives is here -- see the table's
    own header comment -- but every key returned here really has at least
    one downstream artifact entry."""
    return tuple(sorted(CHANGE_CASCADE_TABLE.keys()))


@dataclass(frozen=True)
class CascadeResult:
    changed_field: str
    status: str
    artifacts: Tuple[DownstreamArtifact, ...]
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "changed_field": self.changed_field,
            "status": self.status,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "reason": self.reason,
        }


def cascade_for_changed_field(changed_field: str) -> CascadeResult:
    """The downstream artifacts one changed field makes suspect, and why.
    An undeclared field is `UNKNOWN_FIELD` naming the real declared fields --
    never a silent empty MAPPED result, which would read as "nothing is
    downstream of this" rather than "this table does not know"."""
    entries = CHANGE_CASCADE_TABLE.get(changed_field)
    if entries is None:
        known = ", ".join(known_changed_fields())
        return CascadeResult(
            changed_field=changed_field, status=STATUS_UNKNOWN_FIELD, artifacts=(),
            reason=(f"{changed_field!r} is not a declared changed_field in CHANGE_CASCADE_TABLE "
                    f"-- known fields: {known}. An undeclared field's downstream impact is "
                    "genuinely unknown to this module, never assumed clean."),
        )
    return CascadeResult(changed_field=changed_field, status=STATUS_MAPPED, artifacts=entries)


def _field_of(change: Any) -> Tuple[Optional[str], Dict[str, Any]]:
    """Duck-type one entry of assess_changes()'s input into (field_name,
    an echo of the record to carry back in the report). Accepts a bare
    string, a dict carrying a 'field' key, or any object carrying a
    `.field` attribute -- and nothing else, so a genuinely unrecognisable
    record reports NO_FIELD_NAMED rather than being silently skipped."""
    if isinstance(change, str):
        return change, {"field": change}
    if isinstance(change, dict):
        return change.get("field"), dict(change)
    field_name = getattr(change, "field", None)
    return field_name, {"field": field_name}


def assess_changes(changes: Sequence[Any]) -> Dict[str, Any]:
    """Look up the cascade for each of several changed fields and aggregate
    the result into one report: a per-change breakdown plus a deduplicated
    `suspect_artifacts` list naming, for each artifact, every changed field
    that made it suspect and every reason given.

    `changes` is deliberately duck-typed (see the module docstring's
    "DECOUPLED" section): each entry is a bare field-name string, or a dict/
    object naming its field via a `field` key/attribute. This module imports
    no change-detection module of its own; a future one's real output can be
    passed here unmodified once it exists, provided each of its records
    names the field it changed."""
    per_change: List[Dict[str, Any]] = []
    unknown_fields: List[str] = []
    suspect: Dict[str, Dict[str, Any]] = {}
    for change in changes:
        field_name, echo = _field_of(change)
        if not field_name:
            per_change.append({
                "change": echo, "status": STATUS_NO_FIELD_NAMED,
                "artifacts": [],
                "reason": "this change record names no 'field' -- cannot look up its cascade",
            })
            continue
        cascade = cascade_for_changed_field(field_name)
        per_change.append({
            "change": echo, "status": cascade.status,
            "artifacts": [a.to_dict() for a in cascade.artifacts],
            "reason": cascade.reason,
        })
        if cascade.status == STATUS_UNKNOWN_FIELD:
            unknown_fields.append(field_name)
            continue
        for artifact in cascade.artifacts:
            entry = suspect.setdefault(artifact.artifact, {
                "artifact": artifact.artifact,
                "producing_module": artifact.producing_module,
                "revalidation_action": artifact.revalidation_action,
                "triggered_by": [],
                "reasons": [],
            })
            entry["triggered_by"].append(field_name)
            entry["reasons"].append(artifact.reason)
    return {
        "schema_version": SCHEMA_VERSION,
        "changes": per_change,
        "suspect_artifacts": sorted(suspect.values(), key=lambda d: d["artifact"]),
        "unknown_fields": unknown_fields,
    }


def revoke_stale_decisions(root: Any, changed_field: str, question_keys: Sequence[str], *,
                             revoked_by: Optional[str] = None,
                             extra_reason: Optional[str] = None,
                             store: Optional["_question_queue.QuestionQueueStore"] = None
                             ) -> Dict[str, Dict[str, Any]]:
    """Actually REVOKE the named, caller-supplied stale question-queue
    decisions -- a real call into question_queue.QuestionQueueStore.
    revoke_decision(), never a re-implementation of it.

    `question_keys` must be supplied by the caller (see the module
    docstring: this module has no way to know another caller's question_key
    naming convention). For each key, `revoke_decision()`'s own KeyError
    ("no live decision for this key") is treated as the honest
    NO_LIVE_DECISION outcome -- there was nothing stale on file, which is not
    an error condition for a cascade sweep that does not know in advance
    which of several candidate keys actually had a live decision."""
    qq_store = store if store is not None else _question_queue.QuestionQueueStore(Path(root))
    reason = f"change_cascade: changed_field={changed_field!r} invalidates this decision"
    if extra_reason:
        reason = f"{reason} ({extra_reason})"
    outcomes: Dict[str, Dict[str, Any]] = {}
    for key in question_keys:
        try:
            revocation = qq_store.revoke_decision(key, reason=reason, revoked_by=revoked_by)
        except KeyError:
            outcomes[key] = {
                "status": REVOKE_STATUS_NO_LIVE_DECISION,
                "reason": "no persisted decision on file for this question_key",
            }
        else:
            outcomes[key] = {"status": REVOKE_STATUS_REVOKED, "revocation": revocation}
    return outcomes


def assert_producing_modules_resolve() -> None:
    """Every producing_module cited in CHANGE_CASCADE_TABLE must really
    import -- the same citation-checking discipline
    protocol_capability.py's registry and golden_flow_readiness.py's row
    table already hold their own module citations to, so a renamed or
    removed module leaves a stale citation caught by a test rather than
    silently trusted as prose."""
    cited = sorted({a.producing_module for entries in CHANGE_CASCADE_TABLE.values() for a in entries})
    unresolved = []
    for dotted in cited:
        try:
            importlib.import_module(dotted)
        except Exception as exc:  # pragma: no cover - exercised via test with a bad citation
            unresolved.append((dotted, str(exc)))
    if unresolved:
        detail = "; ".join(f"{m}: {e}" for m, e in unresolved)
        raise ChangeCascadeError(f"producing_module citation(s) do not resolve: {detail}")


# ---------------------------------------------------------------------------
# Rendering + a shared CLI-verb implementation, same convention
# power-intent/golden-scenario/config-variants already use.
# ---------------------------------------------------------------------------

def format_cascade_report(report: Dict[str, Any]) -> str:
    lines = [f"change-cascade report ({len(report['changes'])} change(s) assessed)"]
    for change in report["changes"]:
        field_name = change["change"].get("field")
        if change["status"] == STATUS_MAPPED:
            lines.append(f"  {field_name}: {len(change['artifacts'])} suspect artifact(s)")
            for artifact in change["artifacts"]:
                lines.append(f"    - {artifact['artifact']}")
                lines.append(f"        reason: {artifact['reason']}")
                lines.append(f"        revalidate: {artifact['revalidation_action']}")
        else:
            lines.append(f"  {field_name}: {change['status']} -- {change['reason']}")
    if report["unknown_fields"]:
        lines.append(f"unknown fields: {', '.join(report['unknown_fields'])}")
    return "\n".join(lines)


def format_revoke_outcomes(outcomes: Dict[str, Dict[str, Any]]) -> str:
    lines = [f"revoked {sum(1 for v in outcomes.values() if v['status'] == REVOKE_STATUS_REVOKED)}"
             f" of {len(outcomes)} named question_key(s)"]
    for key, outcome in outcomes.items():
        lines.append(f"  {key}: {outcome['status']}")
    return "\n".join(lines)


def execute_verb(verb: str, *, root: Any = ".", changed_field: Optional[str] = None,
                   changes_json_file: Optional[str] = None,
                   question_keys: Optional[Sequence[str]] = None,
                   revoked_by: Optional[str] = None,
                   as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `dv-harness change-cascade <verb>` and
    `python -m dv_harness.change_cascade <verb>`. Returns (text, exit_code).
    Reading (`fields`, `assess`) is never a mutating act; `revoke` is the
    one verb that writes, and only through the real
    question_queue.revoke_decision() call."""
    root = Path(root)
    if verb == "fields":
        fields = known_changed_fields()
        text = json.dumps(fields, indent=2) if as_json else "\n".join(fields)
        return text, 0
    if verb == "assess":
        if changes_json_file:
            changes = json.loads(Path(changes_json_file).read_text(encoding="utf-8"))
            if isinstance(changes, (str, dict)):
                changes = [changes]
        elif changed_field:
            changes = [changed_field]
        else:
            return ("change-cascade assess requires --changed-field <field> or "
                     "--changes-file <json>", 2)
        report = assess_changes(changes)
        text = json.dumps(report, indent=2) if as_json else format_cascade_report(report)
        code = 1 if report["unknown_fields"] else 0
        return text, code
    if verb == "revoke":
        if not changed_field:
            return ("change-cascade revoke requires --changed-field <field>", 2)
        if not question_keys:
            return ("change-cascade revoke requires at least one --question-key <key>", 2)
        outcomes = revoke_stale_decisions(root, changed_field, question_keys, revoked_by=revoked_by)
        text = json.dumps(outcomes, indent=2) if as_json else format_revoke_outcomes(outcomes)
        code = 0 if any(v["status"] == REVOKE_STATUS_REVOKED for v in outcomes.values()) else 1
        return text, code
    return f"unknown change-cascade verb {verb!r}", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.change_cascade",
        description="Given a changed field name, report which of this harness's own already-"
                    "computed downstream artifacts are now suspect and why, and (on request) "
                    "revoke a named stale question-queue decision through the real "
                    "question_queue.revoke_decision(). Runs, builds, submits and approves "
                    "nothing.")
    ap.add_argument("verb", choices=("fields", "assess", "revoke"))
    ap.add_argument("--root", default=".", help="Project root (for `revoke`'s question-queue store).")
    ap.add_argument("--changed-field", default=None,
                     help="assess/revoke: one changed field name (see `fields` for the list).")
    ap.add_argument("--changes-file", default=None,
                     help="assess: a JSON file holding a field name, a list of field names, or a "
                          "list of {'field': ...} records to assess together.")
    ap.add_argument("--question-key", action="append", default=None, dest="question_keys",
                     help="revoke: a question_key to revoke (repeatable).")
    ap.add_argument("--revoked-by", default=None, help="revoke: who is revoking this decision.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(
        a.verb, root=a.root, changed_field=a.changed_field, changes_json_file=a.changes_file,
        question_keys=a.question_keys, revoked_by=a.revoked_by, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
