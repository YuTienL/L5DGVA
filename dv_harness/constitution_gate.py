"""L5DGVA Constitution — Article 0 anti-drift enforcement.

Real, mechanical safeguard against the constitution being silently
removed or weakened, per the Article 0 governance update's own explicit
requirement ("with focused tests preventing Article 0 from being
silently removed or weakened"). This module is the code half; the tests
are `dv_harness_tests/test_l5dgva_constitution.py`.

Two artifacts are checked together, never just one: the canonical full
text at `docs/architecture/L5DGVA_CONSTITUTION.md`, and CLAUDE.md's own
condensed pointer section (which must exist AND must appear before
"Core Operating Rules" -- Article 0 sits above ordinary rules by
position, not just by claim).

Deliberately narrow: this checks textual intactness (the constitution's
own words are present, unweakened, correctly positioned), never whether
the constitution's substantive promise (both continuous-learning loops
OPERATIONAL) is actually met -- that is `FINAL_COMPLIANCE_STATUS`'s job,
a final-product-only gate never claimed by an intermediate wave (see
`FINAL_COMPLIANCE_STATUS_INTERMEDIATE`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Union

CONSTITUTION_DOC_PATH = "docs/architecture/L5DGVA_CONSTITUTION.md"

CONSTITUTIONAL_DIMENSIONS = (
    "LOCATION_INDEPENDENT",
    "EVIDENCE_GROUNDED",
    "KNOWLEDGE_DRIVEN",
    "CONTINUOUS_EVOLUTION",
    "END_TO_END_DV_ALIGNMENT",
)

ANTI_DRIFT_MARKER = "ARCHITECTURE_CONFLICT"

# L5DGVA_CONSTITUTIONAL_COMPLIANCE is a final-product-only acceptance gate
# (per the constitution's own "Migration-Wave Scoping" section). No
# intermediate wave (M1, M3, ...) may ever report this as PASS -- the only
# legal intermediate value is this one, until the final qualification wave
# computes the real thing from both continuous-learning loops' own
# OPERATIONAL status.
FINAL_COMPLIANCE_STATUS_INTERMEDIATE = "NOT_YET_QUALIFIED"


@dataclass(frozen=True)
class ConstitutionCheckResult:
    status: str  # "PASS" or "FAIL"
    reasons: List[str] = field(default_factory=list)


def check_constitution_intact(root: Union[str, Path]) -> ConstitutionCheckResult:
    """Real, on-disk check. Never raises -- returns FAIL with reasons
    instead, so a caller (dv doctor, a future CI gate) always gets one
    clear verdict."""
    root = Path(root)
    reasons: List[str] = []

    doc_path = root / CONSTITUTION_DOC_PATH
    doc_text = None
    if not doc_path.is_file():
        reasons.append("constitution document missing at %s" % CONSTITUTION_DOC_PATH)
    else:
        doc_text = doc_path.read_text(encoding="utf-8")
        if "Article 0" not in doc_text:
            reasons.append("constitution document no longer names Article 0")
        for dim in CONSTITUTIONAL_DIMENSIONS:
            if dim not in doc_text:
                reasons.append("constitution document is missing dimension %s" % dim)
        if ANTI_DRIFT_MARKER not in doc_text:
            reasons.append("constitution document is missing the Anti-Drift Rule marker %s" % ANTI_DRIFT_MARKER)

    claude_md_path = root / "CLAUDE.md"
    if not claude_md_path.is_file():
        reasons.append("CLAUDE.md missing entirely")
    else:
        claude_text = claude_md_path.read_text(encoding="utf-8")
        if "Article 0" not in claude_text or CONSTITUTION_DOC_PATH not in claude_text:
            reasons.append("CLAUDE.md no longer carries the Article 0 pointer")
        else:
            article_pos = claude_text.find("Article 0")
            core_rules_pos = claude_text.find("Core Operating Rules")
            if core_rules_pos != -1 and article_pos > core_rules_pos:
                reasons.append("CLAUDE.md's Article 0 section no longer precedes Core Operating Rules")

    return ConstitutionCheckResult(status="FAIL" if reasons else "PASS", reasons=reasons)
