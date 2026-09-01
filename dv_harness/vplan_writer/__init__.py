"""dv_harness.vplan_writer -- engine-code vPlan .xlsx writer.

Mirrors dv_harness/uvm_generator/generator.py's placement as engine code
(CLAUDE.md's Methodology Consolidation Rule: a validated code-level
capability belongs under dv_harness/, not a one-off script). Public API
re-exported here; see writer.py for the full implementation and design
rationale.
"""

from .writer import (
    VPlanEvidenceContext,
    build_evidence_context,
    VPlanSchemaError,
    UnresolvedPatternFileError,
    UnknownTaskDeclarationError,
    PatternNotInDispatcherError,
    UnknownCheckerNameError,
    ConstraintNotInSVSourceError,
    EvidenceSourceEmptyError,
    validate_items,
    VPlanWriteResult,
    write_vplan_workbook,
    CREDITED_STATES,
    COVERED_BY_STATES,
    RANDOM_OR_DIRECTED_STATES,
    BLOCKED_ON_STATES,
)

__all__ = [
    "VPlanEvidenceContext",
    "build_evidence_context",
    "VPlanSchemaError",
    "UnresolvedPatternFileError",
    "UnknownTaskDeclarationError",
    "PatternNotInDispatcherError",
    "UnknownCheckerNameError",
    "ConstraintNotInSVSourceError",
    "EvidenceSourceEmptyError",
    "validate_items",
    "VPlanWriteResult",
    "write_vplan_workbook",
    "CREDITED_STATES",
    "COVERED_BY_STATES",
    "RANDOM_OR_DIRECTED_STATES",
    "BLOCKED_ON_STATES",
]
