"""dv_harness/change_impact.py -- RTL-diff-driven regression test selection
(2026-09-04).

GAP THIS CLOSES (audited this session, Section 3 item 3a): nothing in this
repo computed an impact scope from a real git diff. The whole
CHANGE -> DESIGN IMPACT -> REQUIREMENT IMPACT -> PATTERN IMPACT -> REGRESSION
SELECTION chain that `.claude/skills/CORE/verification-change-impact/SKILL.md`
specifies existed only as (a) prose for the agent to follow by hand and
(b) `tools/verification_flow/regression_selection_completeness_gate.py`,
which checks that the agent's hand-written JSON has non-empty categories and
never looks at a diff. The two CSV outputs that skill names
(`change_impact.csv` / `regression_selection.csv`) existed on disk as
HEADER-ONLY files -- a schema with no producer.

This module is that producer. It computes, from real data only:

  1. CHANGED FILES  -- a real `git diff --name-only <base>..<head>`.
  2. DESIGN IMPACT  -- changed file -> RTL module name, resolved against the
     REAL `rtl_modules` table in the evidence DB (populated by
     `evidence_db.insert_rtl_parse()` from real `verible --export_json`
     output). No parse data for a file => that file resolves to its own path
     stem as the impacted area, and is COUNTED AS UNRESOLVED, never
     silently dropped.
  3. REQUIREMENT / VPLAN / PATTERN / COVERAGE IMPACT -- resolved against the
     REAL `.dv-harness/requirements.csv` traceability registry, whose header
     (`REQ_ID,SOURCE,SCOPE,VPLAN_ID,SCENARIO_ID,COMMAND_ID,PATTERN_ID,
     CHECKER_ID,COVERAGE_ID,RESULT,STATUS,EVIDENCE`) already exists in this
     repo and is the project's own declared traceability shape. This module
     reads that file; it never invents a linkage the registry does not
     assert.
  4. REGRESSION SELECTION -- TARGETED / DEPENDENCY / SAFETY /
     MANDATORY_SIGNOFF, computed, not attested.

HONESTY RULES, taken verbatim from the skill and enforced in code, not
documentation:
  - "任何 impact gap / unknown dependency: CONFIDENCE 降低。必要時擴大
    regression, 不得冒險縮小." A changed file that resolves to zero
    requirement rows lowers `confidence` and, when that file is HIGH risk,
    sets `expand_to_full_regression` -- which pushes the ENTIRE known pattern
    universe into the DEPENDENCY class. The failure mode of this module is
    therefore "runs too much", never "quietly skipped the test that would
    have caught it".
  - "不得因 impact analysis 而移除 project mandatory signoff regression."
    MANDATORY_SIGNOFF is never derived from the diff at all -- it comes
    only from the project's own declared list, so no impact computation can
    subtract from it.
  - An empty category is emitted with an explicit `<category>_empty_reason`
    (the same field `regression_selection_completeness_gate.py` already
    requires of an agent) naming the real reason -- an unconfigured safety
    set says so, it never masquerades as "nothing was impacted".

RELATIONSHIP TO THE AGENT'S OWN SELECTION. This module does not replace
Stage.REGRESSION_SELECT's evidence block; it grounds it. `engine.py` computes
this selection BEFORE the stage runs, writes it to
`.dv-harness/regression/computed_selection.json` plus the two CSVs, and shows
it to the agent. The gate then enforces one asymmetric rule: the agent may
ADD tests (its judgment can see things a traceability registry cannot), and
may never DROP a computed one. Expansion up, never down -- the same
direction as every other rule above.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .regression_tiers import (
    CLASS_DEPENDENCY, CLASS_MANDATORY, CLASS_SAFETY, CLASS_TARGETED,
)

# --- on-disk artifacts (all pre-existing paths/headers in this repo) ------

CHANGE_IMPACT_CSV_PARTS = (".dv-harness", "change_impact.csv")
REGRESSION_SELECTION_CSV_PARTS = (".dv-harness", "regression_selection.csv")
REQUIREMENTS_CSV_PARTS = (".dv-harness", "requirements.csv")
COMPUTED_SELECTION_PARTS = (".dv-harness", "regression", "computed_selection.json")

CHANGE_IMPACT_HEADER = ["BASE_SHA", "HEAD_SHA", "CHANGED_FILE", "IMPACTED_AREA", "REQ_ID",
                        "VPLAN_ID", "PATTERN_ID", "COVERAGE_ID", "RISK", "CONFIDENCE"]
REGRESSION_SELECTION_HEADER = ["SELECTION_CLASS", "PATTERN_OR_GROUP", "REASON", "REQ_ID",
                               "VPLAN_ID", "RISK", "MANDATORY", "RESULT", "EVIDENCE"]

CONFIG_KEY = "regression"

# --- risk classification (verification-change-impact/SKILL.md's own 3 tiers)

RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_LOW = "LOW"

_RTL_SUFFIXES = (".v", ".sv", ".svh", ".vh", ".vhd", ".vhdl")
# A .sv/.svh under one of these path segments is testbench/sequence/test
# source, which the skill puts in MEDIUM ("local config/sequence/test
# changes"), not the HIGH "RTL control/data path" bucket. Matched on whole
# path SEGMENTS, never substrings, so a design module named `testmode_ctrl`
# is not demoted by the letters "test" appearing in its name.
_TESTBENCH_SEGMENTS = frozenset({
    "tb", "testbench", "test", "tests", "verif", "verification", "uvm",
    "sequences", "seq", "sim", "sim_scripts", "patterns",
})
# Documentation-only: the ONLY things allowed to be LOW. Everything
# unrecognised is MEDIUM, never LOW -- an unknown file type must not be able
# to talk its way down to the cheapest bucket.
_DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc", ".html", ".pdf")
# Harness/workflow METADATA roots. A change under one of these is a change to
# the harness's own bookkeeping (state.json, events.jsonl, the traceability
# CSVs, skill/agent prose) -- never to DUT or testbench executable behavior --
# so it cannot impact a regression result and must not drag the whole run into
# "unknown dependency, expand to full regression". Found by a real test: a
# commit that merely updated `.dv-harness/requirements.csv` was being scored
# MEDIUM-risk-and-untraceable and forced a full regression, which would have
# made every harness bookkeeping commit cost a full run.
_METADATA_ROOTS = frozenset({".dv-harness", ".dv-workflow", ".claude", ".git", ".work",
                              ".github", "docs"})


def classify_risk(path: str) -> str:
    """SKILL.md's HIGH/MEDIUM/LOW, as a deterministic function of the path.

    `command.txt` is deliberately NOT treated as documentation despite its
    .txt suffix: in this project a command.txt IS an executable BFM pattern
    (see `.claude/skills/CORE` and the ip-uvm-dv-gen agent), so it is a real
    behavioral change -> MEDIUM."""
    p = str(path).replace("\\", "/").strip()
    name = p.rsplit("/", 1)[-1].lower()
    segments = {s.lower() for s in p.split("/")[:-1]}
    suffix = ("." + name.rsplit(".", 1)[-1]) if "." in name else ""

    first = p.split("/", 1)[0].lower() if "/" in p else ""
    if first in _METADATA_ROOTS:
        return RISK_LOW
    if name == "command.txt" or "patterns" in segments:
        return RISK_MEDIUM
    if suffix in _RTL_SUFFIXES:
        return RISK_MEDIUM if (segments & _TESTBENCH_SEGMENTS) else RISK_HIGH
    if suffix in _DOC_SUFFIXES:
        return RISK_LOW
    return RISK_MEDIUM


# --- git ------------------------------------------------------------------


def _git(root: Path, args: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    """Read-only git invocation, mirroring trend_analysis._git()'s exact
    degrade-never-raise contract (missing binary -> rc 127, timeout -> 124)
    so a machine without git produces an honest NO_GIT verdict instead of
    killing the stage that asked for a selection."""
    try:
        proc = subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        return 127, "", f"git not found on PATH: {e}"
    except subprocess.TimeoutExpired as e:
        return 124, "", f"git timed out: {e}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def resolve_sha(root: Path, rev: str) -> Optional[str]:
    rc, out, _ = _git(root, ["rev-parse", "--verify", f"{rev}^{{commit}}"])
    return out.strip() if rc == 0 and out.strip() else None


def changed_files(root: Path, base_sha: str, head_sha: str = "HEAD") -> Dict[str, Any]:
    """Real `git diff --name-only <base>..<head>`, plus the resolved SHAs.

    Returns {"status", "base_sha", "head_sha", "files", "detail"}. `status`
    is REAL_DIFF / NO_GIT / UNKNOWN_BASE / UNKNOWN_HEAD / DIFF_FAILED --
    every non-REAL_DIFF status carries an empty file list AND is propagated
    all the way into the selection's confidence, so a caller can never
    mistake "we could not compute a diff" for "nothing changed"."""
    rc, _, err = _git(root, ["rev-parse", "--git-dir"])
    if rc == 127:
        return {"status": "NO_GIT", "base_sha": base_sha, "head_sha": head_sha,
                "files": [], "detail": err}
    if rc != 0:
        return {"status": "NO_GIT", "base_sha": base_sha, "head_sha": head_sha,
                "files": [], "detail": err or "not a git repository"}

    base = resolve_sha(root, base_sha)
    if base is None:
        return {"status": "UNKNOWN_BASE", "base_sha": base_sha, "head_sha": head_sha,
                "files": [], "detail": f"base revision {base_sha!r} does not resolve to a commit"}
    head = resolve_sha(root, head_sha)
    if head is None:
        return {"status": "UNKNOWN_HEAD", "base_sha": base, "head_sha": head_sha,
                "files": [], "detail": f"head revision {head_sha!r} does not resolve to a commit"}

    rc, out, err = _git(root, ["diff", "--name-only", f"{base}..{head}"])
    if rc != 0:
        return {"status": "DIFF_FAILED", "base_sha": base, "head_sha": head,
                "files": [], "detail": err}
    files = [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]
    return {"status": "REAL_DIFF", "base_sha": base, "head_sha": head,
            "files": sorted(set(files)), "detail": None}


# --- design impact: changed file -> RTL module (real verible parse rows) ---


def file_to_module_map(root: Path, *, db_path: Optional[Path] = None) -> Dict[str, List[str]]:
    """`{normalized file path or basename: [module_name, ...]}` from the REAL
    `rtl_modules` rows in the evidence DB.

    Both the full normalized path AND the bare basename are keyed, because
    `insert_rtl_parse()` records whatever path the verible run was given
    (often absolute, on the Linux server) while a `git diff` emits
    repo-relative paths -- matching on basename is the only join that
    actually works across that boundary, and a basename collision can only
    ever ADD candidate modules (widening the impact scope), never remove one.

    Degrades to `{}` -- never raises -- when duckdb is not installed or the
    DB does not exist yet, which is the honest "no design-impact data
    available" state, propagated to the caller as unresolved files."""
    try:
        from .evidence_db import EvidenceStore, default_db_path
    except Exception:
        return {}
    path = Path(db_path) if db_path else default_db_path(root)
    if not Path(path).exists():
        return {}
    try:
        with EvidenceStore(path, read_only=True) as store:
            rows = store.query("SELECT DISTINCT file_path, module_name FROM rtl_modules")
    except Exception:
        return {}
    out: Dict[str, List[str]] = {}
    for file_path, module_name in rows:
        if not file_path or not module_name:
            continue
        norm = str(file_path).replace("\\", "/")
        base = norm.rsplit("/", 1)[-1]
        for key in {norm, base}:
            out.setdefault(key, [])
            if module_name not in out[key]:
                out[key].append(str(module_name))
    return out


def impacted_areas_for_file(changed_file: str, module_map: Dict[str, List[str]]) -> Tuple[List[str], bool]:
    """(areas, resolved_from_rtl_parse). `areas` is the real module name(s)
    when the evidence DB knows this file, else the file's own path stem --
    a deliberately weaker signal, which is why the boolean is returned
    separately and drives the confidence downgrade."""
    norm = str(changed_file).replace("\\", "/")
    base = norm.rsplit("/", 1)[-1]
    for key in (norm, base):
        mods = module_map.get(key)
        if mods:
            return sorted(mods), True
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return ([stem] if stem else []), False


# --- requirement impact: the real .dv-harness/requirements.csv registry ---

_MIN_AREA_TOKEN_LEN = 3


def load_trace_registry(root: Path) -> List[Dict[str, str]]:
    """Rows of the project's REAL traceability registry. Missing file or a
    header-only file (this repo's current state) both give `[]` -- an
    empty registry is a real, correct state that this module reports as
    zero targeted tests with an explicit reason, never as a crash."""
    p = Path(root).joinpath(*REQUIREMENTS_CSV_PARTS)
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8-sig")
    except Exception:
        return []
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        rows.append({(k or "").strip().upper(): (v or "").strip()
                     for k, v in row.items() if k})
    return [r for r in rows if any(r.values())]


def _row_scope_terms(row: Dict[str, str]) -> List[str]:
    """The registry fields that name a DESIGN location -- SCOPE is the
    hierarchy/subsystem column, VPLAN_ID the feature grouping. Only these
    two are matched against a changed file's area; PATTERN_ID/COVERAGE_ID
    are OUTPUTS of the match, never inputs to it (matching a pattern name
    against a file stem would let an unrelated file whose stem happens to
    appear in a pattern name select that pattern)."""
    terms = []
    for key in ("SCOPE", "VPLAN_ID"):
        v = (row.get(key) or "").strip().lower()
        if v:
            terms.append(v)
    return terms


def _area_matches_row(area: str, row: Dict[str, str]) -> bool:
    """Deterministic, documented match rule: an area token matches a registry
    row when it is equal to, contained in, or contains one of that row's
    scope terms. Tokens shorter than `_MIN_AREA_TOKEN_LEN` never match by
    containment (a 1-2 character stem would otherwise match nearly every
    scope string and silently select the whole registry)."""
    a = (area or "").strip().lower()
    if not a:
        return False
    for term in _row_scope_terms(row):
        if a == term:
            return True
        if len(a) >= _MIN_AREA_TOKEN_LEN and (a in term or term in a):
            return True
    return False


# --- impact rows ----------------------------------------------------------


@dataclass
class ChangeImpactRow:
    """One row of `.dv-harness/change_impact.csv`, field-for-field."""
    base_sha: str
    head_sha: str
    changed_file: str
    impacted_area: str
    req_id: str
    vplan_id: str
    pattern_id: str
    coverage_id: str
    risk: str
    confidence: str

    def to_csv_row(self) -> List[str]:
        return [self.base_sha, self.head_sha, self.changed_file, self.impacted_area,
                self.req_id, self.vplan_id, self.pattern_id, self.coverage_id,
                self.risk, self.confidence]

    def to_dict(self) -> dict:
        return asdict(self)


CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"


def compute_change_impact(root: Path, *, base_sha: str, head_sha: str = "HEAD",
                           db_path: Optional[Path] = None,
                           registry: Optional[List[Dict[str, str]]] = None,
                           diff: Optional[dict] = None) -> dict:
    """The CHANGE -> DESIGN -> REQUIREMENT/VPLAN/PATTERN/COVERAGE half of the
    chain. `diff`/`registry`/`db_path` are injectable so a caller (and a
    test) can drive this from real data it already has without a second git
    or DuckDB round trip -- the same injected-seam convention
    preflight.Runner / escalation_notify.NotifyTransport already use here."""
    diff = diff if diff is not None else changed_files(root, base_sha, head_sha)
    registry = registry if registry is not None else load_trace_registry(root)
    module_map = file_to_module_map(root, db_path=db_path)

    base = diff.get("base_sha") or base_sha
    head = diff.get("head_sha") or head_sha

    rows: List[ChangeImpactRow] = []
    unresolved: List[str] = []
    matched_rows: List[Dict[str, str]] = []
    behavioral_files = 0

    for f in diff.get("files") or []:
        risk = classify_risk(f)
        areas, from_parse = impacted_areas_for_file(f, module_map)
        area_text = "|".join(areas)
        hits = [r for r in registry if any(_area_matches_row(a, r) for a in areas)]
        if risk != RISK_LOW:
            behavioral_files += 1
        if hits:
            for r in hits:
                if r not in matched_rows:
                    matched_rows.append(r)
                rows.append(ChangeImpactRow(
                    base_sha=base, head_sha=head, changed_file=f, impacted_area=area_text,
                    req_id=r.get("REQ_ID", ""), vplan_id=r.get("VPLAN_ID", ""),
                    pattern_id=r.get("PATTERN_ID", ""), coverage_id=r.get("COVERAGE_ID", ""),
                    risk=risk,
                    confidence=CONFIDENCE_HIGH if from_parse else CONFIDENCE_MEDIUM,
                ))
        else:
            if risk != RISK_LOW:
                unresolved.append(f)
            rows.append(ChangeImpactRow(
                base_sha=base, head_sha=head, changed_file=f, impacted_area=area_text,
                req_id="", vplan_id="", pattern_id="", coverage_id="", risk=risk,
                confidence=CONFIDENCE_LOW if risk != RISK_LOW else CONFIDENCE_HIGH,
            ))

    diff_ok = diff.get("status") == "REAL_DIFF"
    if not diff_ok:
        confidence = CONFIDENCE_LOW
    elif behavioral_files == 0:
        # Nothing behavioral changed -- a genuinely HIGH-confidence "no
        # design impact" answer, not a gap.
        confidence = CONFIDENCE_HIGH
    elif not unresolved and matched_rows:
        confidence = CONFIDENCE_HIGH
    elif matched_rows:
        confidence = CONFIDENCE_MEDIUM
    else:
        confidence = CONFIDENCE_LOW

    # "必要時擴大 regression, 不得冒險縮小": a HIGH-risk file we could not
    # trace to ANY requirement is an unknown dependency -- so is a diff we
    # could not compute at all. Both force the full universe in.
    expand = (not diff_ok) or any(classify_risk(f) == RISK_HIGH for f in unresolved)

    return {
        "base_sha": base,
        "head_sha": head,
        "diff_status": diff.get("status"),
        "diff_detail": diff.get("detail"),
        "changed_files": list(diff.get("files") or []),
        "behavioral_file_count": behavioral_files,
        "rows": rows,
        "matched_rows": matched_rows,
        "unresolved_files": unresolved,
        "registry_size": len(registry),
        "rtl_parse_available": bool(module_map),
        "confidence": confidence,
        "expand_to_full_regression": expand,
    }


# --- selection ------------------------------------------------------------


def full_pattern_universe(root: Path, *,
                           registry: Optional[List[Dict[str, str]]] = None) -> List[str]:
    """Every pattern the project's own traceability registry knows about --
    the WEEKLY tier's "nothing may be skipped" universe and the expansion
    target when the impact model has a gap. Derived from real registry rows
    only; a project with an empty registry honestly has an empty universe,
    which callers report rather than paper over."""
    registry = registry if registry is not None else load_trace_registry(root)
    seen: List[str] = []
    for r in registry:
        pid = (r.get("PATTERN_ID") or "").strip()
        if pid and pid not in seen:
            seen.append(pid)
    return sorted(seen)


def _config_list(cfg: Optional[dict], key: str) -> List[str]:
    if not isinstance(cfg, dict):
        return []
    block = cfg.get(CONFIG_KEY, cfg)
    if not isinstance(block, dict):
        return []
    v = block.get(key)
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else []


def select_regression(impact: dict, *, registry: Optional[List[Dict[str, str]]] = None,
                       cfg: Optional[dict] = None,
                       universe: Optional[Sequence[str]] = None) -> dict:
    """REGRESSION SELECTION: the four classes, computed.

      TARGETED   -- PATTERN_ID of every registry row a changed file's
                    impacted area actually matched.
      DEPENDENCY -- PATTERN_ID of every OTHER registry row sharing a SCOPE
                    with a matched row (the skill's "共享 hierarchy/
                    resource/protocol/requirement 的相關 regression"),
                    plus, when `expand_to_full_regression` is set, the whole
                    known universe.
      SAFETY     -- the project's declared fixed smoke/sanity/critical-path
                    set (`config.json: regression.safety_patterns`). Never
                    derived from the diff: its entire purpose is to catch
                    what the impact model missed.
      MANDATORY_SIGNOFF -- `config.json: regression.mandatory_signoff_patterns`.
                    Never derived, never subtracted.
    """
    registry = registry if registry is not None else []
    matched = impact.get("matched_rows") or []

    targeted: List[str] = []
    for r in matched:
        pid = (r.get("PATTERN_ID") or "").strip()
        if pid and pid not in targeted:
            targeted.append(pid)

    matched_scopes = {t for r in matched for t in _row_scope_terms(r)}
    dependency: List[str] = []
    for r in registry:
        pid = (r.get("PATTERN_ID") or "").strip()
        if not pid or pid in targeted or pid in dependency:
            continue
        if matched_scopes & set(_row_scope_terms(r)):
            dependency.append(pid)

    expanded = bool(impact.get("expand_to_full_regression"))
    expansion_added: List[str] = []
    if expanded:
        for pid in (universe if universe is not None else []):
            pid = str(pid).strip()
            if pid and pid not in targeted and pid not in dependency:
                dependency.append(pid)
                expansion_added.append(pid)

    safety = _config_list(cfg, "safety_patterns")
    mandatory = _config_list(cfg, "mandatory_signoff_patterns")

    result: Dict[str, Any] = {
        "targeted_tests": sorted(targeted),
        "dependency_tests": sorted(dependency),
        "safety_tests": sorted(set(safety)),
        "mandatory_signoff_tests": sorted(set(mandatory)),
        "confidence": impact.get("confidence"),
        "expand_to_full_regression": expanded,
        "expansion_added": sorted(expansion_added),
        "diff_status": impact.get("diff_status"),
        "unresolved_files": list(impact.get("unresolved_files") or []),
    }

    # Explicit, real empty reasons -- the same contract
    # regression_selection_completeness_gate.py already demands of an agent.
    if not result["targeted_tests"]:
        if not (impact.get("changed_files") or []):
            reason = f"NO_CHANGED_FILES_IN_DIFF ({impact.get('diff_status')})"
        elif not registry:
            reason = "TRACEABILITY_REGISTRY_EMPTY (.dv-harness/requirements.csv has no rows)"
        else:
            reason = "NO_REGISTRY_ROW_MATCHED_ANY_IMPACTED_AREA"
        result["targeted_tests_empty_reason"] = reason
    if not result["dependency_tests"]:
        result["dependency_tests_empty_reason"] = (
            "NO_SHARED_SCOPE_ROWS_BEYOND_TARGETED" if targeted
            else "NO_TARGETED_ROWS_TO_DERIVE_DEPENDENCIES_FROM")
    if not result["safety_tests"]:
        result["safety_tests_empty_reason"] = (
            "NO_SAFETY_SET_CONFIGURED (config.json: regression.safety_patterns)")
    if not result["mandatory_signoff_tests"]:
        result["mandatory_signoff_tests_empty_reason"] = (
            "NO_MANDATORY_SIGNOFF_SET_CONFIGURED "
            "(config.json: regression.mandatory_signoff_patterns)")
    return result


def selection_rows(selection: dict, impact: dict) -> List[List[str]]:
    """`.dv-harness/regression_selection.csv` rows, one per selected pattern.
    RESULT is deliberately left as PENDING -- this module selects; only a
    real run may fill in a verdict."""
    by_pattern_row: Dict[str, Dict[str, str]] = {}
    for r in impact.get("matched_rows") or []:
        pid = (r.get("PATTERN_ID") or "").strip()
        if pid and pid not in by_pattern_row:
            by_pattern_row[pid] = r

    evidence_id = impact.get("change_impact_evidence_id") or ""
    expansion = set(selection.get("expansion_added") or [])
    out: List[List[str]] = []
    specs = (
        (CLASS_TARGETED, selection.get("targeted_tests") or [], "DIRECTLY_IMPACTED_BY_CHANGED_FILE", "NO"),
        (CLASS_DEPENDENCY, selection.get("dependency_tests") or [], "SHARED_SCOPE_WITH_IMPACTED_REQUIREMENT", "NO"),
        (CLASS_SAFETY, selection.get("safety_tests") or [], "FIXED_SMOKE_SANITY_CRITICAL_PATH_SET", "NO"),
        (CLASS_MANDATORY, selection.get("mandatory_signoff_tests") or [], "PROJECT_MANDATORY_SIGNOFF_SET", "YES"),
    )
    for cls, patterns, reason, mandatory in specs:
        for pid in patterns:
            row = by_pattern_row.get(pid, {})
            real_reason = ("IMPACT_GAP_EXPANDED_TO_FULL_REGRESSION"
                           if cls == CLASS_DEPENDENCY and pid in expansion else reason)
            out.append([cls, pid, real_reason, row.get("REQ_ID", ""), row.get("VPLAN_ID", ""),
                        selection.get("confidence") or "", mandatory, "PENDING", evidence_id])
    return out


# --- evidence id ----------------------------------------------------------


def change_impact_evidence_id(base_sha: str, head_sha: str, changed: Sequence[str]) -> str:
    """Stable id for one computed impact analysis: same base/head/file-set =>
    same id. Deterministic (no timestamp) precisely so the agent's declared
    `selection_source.change_impact_evidence_id` can be CHECKED against it
    instead of being an unverifiable free-text string, which is what it was
    before this module existed."""
    h = hashlib.sha256(
        json.dumps({"base": base_sha, "head": head_sha, "files": sorted(changed)},
                   sort_keys=True).encode("utf-8")).hexdigest()
    return f"CI-{h[:16]}"


# --- writers --------------------------------------------------------------


def _write_csv(path: Path, header: List[str], rows: Iterable[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(list(r))
    path.write_text(buf.getvalue(), encoding="utf-8")


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def computed_selection_path(root: Path) -> Path:
    return Path(root).joinpath(*COMPUTED_SELECTION_PARTS)


def read_computed_selection(root: Path) -> Optional[dict]:
    """The last computed selection, or None. Never raises -- the gate that
    reads this must degrade to its pre-existing attestation-only behavior
    when no computation has run, not fail the stage."""
    p = computed_selection_path(root)
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def compute_and_write(root: Path, *, base_sha: str, head_sha: str = "HEAD",
                       cfg: Optional[dict] = None, db_path: Optional[Path] = None,
                       diff: Optional[dict] = None,
                       registry: Optional[List[Dict[str, str]]] = None) -> dict:
    """The one call `engine.py` makes at REGRESSION_SELECT: compute the whole
    chain and write all three real artifacts (both CSVs the skill names, plus
    the machine-readable selection the gate enforces against). Returns the
    payload it wrote."""
    root = Path(root)
    registry = registry if registry is not None else load_trace_registry(root)
    impact = compute_change_impact(root, base_sha=base_sha, head_sha=head_sha,
                                    db_path=db_path, registry=registry, diff=diff)
    evidence_id = change_impact_evidence_id(impact["base_sha"], impact["head_sha"],
                                            impact["changed_files"])
    impact["change_impact_evidence_id"] = evidence_id
    universe = full_pattern_universe(root, registry=registry)
    selection = select_regression(impact, registry=registry, cfg=cfg, universe=universe)

    _write_csv(root.joinpath(*CHANGE_IMPACT_CSV_PARTS), CHANGE_IMPACT_HEADER,
               [r.to_csv_row() for r in impact["rows"]])
    _write_csv(root.joinpath(*REGRESSION_SELECTION_CSV_PARTS), REGRESSION_SELECTION_HEADER,
               selection_rows(selection, impact))

    payload = {
        "schema_version": "1.0",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "change_impact_evidence_id": evidence_id,
        "base_sha": impact["base_sha"],
        "head_sha": impact["head_sha"],
        "diff_status": impact["diff_status"],
        "diff_detail": impact["diff_detail"],
        "changed_files": impact["changed_files"],
        "unresolved_files": impact["unresolved_files"],
        "registry_size": impact["registry_size"],
        "rtl_parse_available": impact["rtl_parse_available"],
        "universe_size": len(universe),
        "impact_rows": [r.to_dict() for r in impact["rows"]],
        "selection": selection,
    }
    _atomic_write_json(computed_selection_path(root), payload)
    return payload


# --- prompt rendering (engine.py) -----------------------------------------


def render_selection_section(payload: dict) -> str:
    """The block engine.py appends to the REGRESSION_SELECT prompt. States
    the computed sets, the confidence and WHY, and the one asymmetric rule
    the gate enforces (add, never drop)."""
    sel = payload.get("selection") or {}
    lines = [
        "",
        "## 已計算的 Change-Impact Regression Selection（harness 端真實計算，非你的自述）",
        f"change_impact_evidence_id: {payload.get('change_impact_evidence_id')}",
        f"base_sha: {payload.get('base_sha')}  head_sha: {payload.get('head_sha')}  "
        f"diff_status: {payload.get('diff_status')}",
        f"changed_files: {len(payload.get('changed_files') or [])} 個; "
        f"traceability registry rows: {payload.get('registry_size')}; "
        f"RTL parse data available: {payload.get('rtl_parse_available')}",
        f"confidence: {sel.get('confidence')}; "
        f"expand_to_full_regression: {sel.get('expand_to_full_regression')}",
    ]
    unresolved = payload.get("unresolved_files") or []
    if unresolved:
        lines.append(f"無法追溯到任何 requirement 的變更檔（impact gap，已據此擴大選測）: {unresolved}")
    for key in ("targeted_tests", "dependency_tests", "safety_tests", "mandatory_signoff_tests"):
        value = sel.get(key) or []
        reason = sel.get(key + "_empty_reason")
        lines.append(f"- {key}: {value}" + (f"  (empty_reason: {reason})" if reason else ""))
    lines += [
        "",
        "規則（gate 會實際檢查，不是建議）：你回覆的 selection 必須包含上面每一個已計算的",
        "test；你可以**加**（你看得到 traceability registry 看不到的東西），但不得**刪**任何",
        "一個已計算的 test，且 selection_source.change_impact_evidence_id 必須等於上面那個 id。",
        "",
    ]
    return "\n".join(lines)


# ============================================================================
# --- semantic RTL diff: WHAT a diff means, not just which files/tests it --
# touches ("Semantic Change Impact Engine (verify-first)", 2026-09-06) -----
# ============================================================================
#
# GAP AUDITED FIRST (REUSE OVER REINVENT, before writing a line below):
# `change_impact.py`'s existing half of this module -- classify_risk(),
# compute_change_impact() -- computes impact purely from a real
# `git diff --name-only` FILE LIST resolved against changed FILE PATHS
# (suffix, path segment, RTL-parse module-name lookup). It never opens the
# diff's own CONTENT. A commit that adds one comment to a `.sv` file and a
# commit that deletes that same file's only DUT output port are scored
# byte-for-byte identically today -- same HIGH risk (RTL suffix), same
# confidence, same regression selection -- because nothing downstream of
# `classify_risk()` ever reads a line of the diff. A repo-wide search before
# writing this confirmed no other module closes this: `change_blast_radius.py`
# widens the same file-path reasoning to an import-closure ("how far does a
# changed FILE reach"), never a content diff; `command_txt_change_impact.py`
# and `spec_vplan_delta.py` semantic-diff a DE command REGISTRY and a
# requirement-contract SET respectively -- real semantic diffs, but over a
# different domain (structured records, not RTL/SV source text) and neither
# imports or is imported by this module. This section is the first place in
# the repo that reasons about WHAT a code-level diff actually changed.
#
# SCOPE, stated rather than implied wider: declaration-level only, the exact
# "module/port/signal hierarchy, not a full elaboration/semantic model"
# bound `verible_parser.py` already states for itself. A module added or
# removed, a port added/removed/re-directioned/re-typed(width), a parameter
# added/removed/re-typed/re-defaulted, a module-level signal added/removed/
# re-typed -- each a real, cited before/after value, never a guessed one.
# Anything living INSIDE a procedural block (an always_ff's own logic, an
# assertion body, a case statement) is invisible to this parser exactly as
# it is invisible to `verible_parser.py` itself, and is reported as the
# honest `BODY_ONLY_CHANGE` bucket below -- "the declared interface did not
# move, but the file's content did, by a means this parser cannot see
# inside" -- never silently folded into "nothing changed".
#
# HONESTY, worst-wins in the one direction that matters here: an
# unverifiable file (verible missing, a real syntax error at either
# revision, `git show` failing) is `NOT_AVAILABLE` -- collected separately
# in `unverifiable_files` and NEVER counted as "no interface change", the
# same "an absence of proof about a diff's content must never read as proof
# the diff was safe" rule the Evidence Truth Rule states generally.
#
# WIRING, disclosed rather than implied closed: this is additive and
# REACHED, not WIRED. `compute_change_impact()` / `compute_and_write()` /
# `select_regression()` above and their existing confidence /
# `expand_to_full_regression` / regression-selection behaviour are
# UNCHANGED byte-for-byte by this section -- nothing here alters what a
# caller downstream of the pre-existing pipeline already sees, and no
# `engine.py` call site invokes it (the same "prefer a standalone front
# door over touching a large, concurrently-edited engine/gates/cli module"
# choice several sibling 2026-09-06 additions in this project already
# disclose, made the same way here since this multi-agent batch runs
# alongside other work touching `engine.py`). A caller who wants the
# semantic verification calls `compute_semantic_change_impact()` directly,
# or `python -m dv_harness.change_impact semantic-diff --root <dir> --base
# <sha> [--head <sha>] [--json]`.


def _import_verible_parser():
    """Lazy, degrade-never-raise import -- mirrors `file_to_module_map()`'s
    own try/except-on-import convention above, so a checkout without
    `verible_parser` (or a broken install) reports `NOT_AVAILABLE` rather
    than crashing this file's own import."""
    try:
        from . import verible_parser
        return verible_parser
    except Exception:
        return None


RTL_CHANGE_MODULE_ADDED = "MODULE_ADDED"
RTL_CHANGE_MODULE_REMOVED = "MODULE_REMOVED"
RTL_CHANGE_PORT_ADDED = "PORT_ADDED"
RTL_CHANGE_PORT_REMOVED = "PORT_REMOVED"
RTL_CHANGE_PORT_DIRECTION_CHANGED = "PORT_DIRECTION_CHANGED"
RTL_CHANGE_PORT_TYPE_OR_WIDTH_CHANGED = "PORT_TYPE_OR_WIDTH_CHANGED"
RTL_CHANGE_PARAM_ADDED = "PARAMETER_ADDED"
RTL_CHANGE_PARAM_REMOVED = "PARAMETER_REMOVED"
RTL_CHANGE_PARAM_TYPE_CHANGED = "PARAMETER_TYPE_CHANGED"
RTL_CHANGE_PARAM_DEFAULT_CHANGED = "PARAMETER_DEFAULT_CHANGED"
RTL_CHANGE_SIGNAL_ADDED = "SIGNAL_ADDED"
RTL_CHANGE_SIGNAL_REMOVED = "SIGNAL_REMOVED"
RTL_CHANGE_SIGNAL_TYPE_CHANGED = "SIGNAL_TYPE_CHANGED"

# Which of the above change a module's own EXTERNAL CONTRACT -- what a
# testbench, a bind, or an instantiating parent module can depend on --
# versus an internal-only fact. Ports/parameters (and the module's own
# existence) are the contract; a module-level signal declared but never
# exposed as a port is not, because nothing outside the module can ever
# legally reference it by name -- the same external-interface-vs-internal
# -implementation line `phy_boundary.py`/`connectivity.py` already draw,
# for a different purpose, one layer down.
INTERFACE_IMPACTING_CHANGE_KINDS = frozenset({
    RTL_CHANGE_MODULE_ADDED, RTL_CHANGE_MODULE_REMOVED,
    RTL_CHANGE_PORT_ADDED, RTL_CHANGE_PORT_REMOVED,
    RTL_CHANGE_PORT_DIRECTION_CHANGED, RTL_CHANGE_PORT_TYPE_OR_WIDTH_CHANGED,
    RTL_CHANGE_PARAM_ADDED, RTL_CHANGE_PARAM_REMOVED,
    RTL_CHANGE_PARAM_TYPE_CHANGED, RTL_CHANGE_PARAM_DEFAULT_CHANGED,
})


@dataclass
class SemanticRtlChange:
    """One real, cited before/after structural fact about one module in one
    file -- never a guessed summary of what a diff "probably" did."""
    file: str
    module: Optional[str]
    kind: str
    detail: str
    interface_impacting: bool

    def to_dict(self) -> dict:
        return asdict(self)


def rtl_file_content_at_revision(root: Path, sha: str, rel_path: str) -> dict:
    """Real `git show <sha>:<rel_path>`, degrade-never-raise exactly like
    every other git call in this module (see `_git()` above). Returns
    `{"status", "content", "detail"}`; `status` is PRESENT /
    NOT_PRESENT_AT_REVISION / NO_GIT. A nonzero exit here almost always
    means "this path did not exist at this revision" (added or deleted
    somewhere across base..head) -- a real, honest structural fact in its
    own right, never a silent empty diff."""
    rc, out, err = _git(root, ["show", f"{sha}:{rel_path}"])
    if rc == 127:
        return {"status": "NO_GIT", "content": None, "detail": err}
    if rc != 0:
        return {"status": "NOT_PRESENT_AT_REVISION", "content": None, "detail": err}
    return {"status": "PRESENT", "content": out, "detail": None}


def _parse_rtl_content(vp, content: str, rel_path: str, verible_bin: str) -> dict:
    """Writes `content` to a throwaway temp file (verible really parses
    those real bytes -- this never fabricates a parse result from diff text
    alone) and runs the REAL `verible_parser.parse_file()` against it.
    Returns `{"status", "modules", "detail"}`: PARSED / VERIBLE_UNAVAILABLE
    / PARSE_ERROR -- the same three-way distinction `verible_parser.py`'s
    own two exception types already carry, never collapsed into one."""
    suffix = Path(rel_path).suffix or ".sv"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        result = vp.parse_file(tmp_path, verible_bin=verible_bin)
        return {"status": "PARSED", "modules": result.modules, "detail": None}
    except vp.VeribleUnavailableError as e:
        return {"status": "VERIBLE_UNAVAILABLE", "modules": None, "detail": str(e)}
    except vp.VeribleParseError as e:
        return {"status": "PARSE_ERROR", "modules": None, "detail": str(e)}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _diff_port_lists(file_path: str, module_name: Optional[str],
                      old_ports: list, new_ports: list) -> List[SemanticRtlChange]:
    changes: List[SemanticRtlChange] = []
    old_by_name = {p.name: p for p in old_ports if p.name}
    new_by_name = {p.name: p for p in new_ports if p.name}
    for name in sorted(set(new_by_name) - set(old_by_name)):
        p = new_by_name[name]
        changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_PORT_ADDED,
            f"port {name!r} added ({p.direction} {p.data_type})", True))
    for name in sorted(set(old_by_name) - set(new_by_name)):
        p = old_by_name[name]
        changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_PORT_REMOVED,
            f"port {name!r} removed (was {p.direction} {p.data_type})", True))
    for name in sorted(set(old_by_name) & set(new_by_name)):
        o, n = old_by_name[name], new_by_name[name]
        if (o.direction or "") != (n.direction or ""):
            changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_PORT_DIRECTION_CHANGED,
                f"port {name!r} direction {o.direction!r} -> {n.direction!r}", True))
        if (o.data_type or "") != (n.data_type or ""):
            changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_PORT_TYPE_OR_WIDTH_CHANGED,
                f"port {name!r} type/width {o.data_type!r} -> {n.data_type!r}", True))
    return changes


def _diff_param_lists(file_path: str, module_name: Optional[str],
                       old_params: list, new_params: list) -> List[SemanticRtlChange]:
    changes: List[SemanticRtlChange] = []
    old_by_name = {p.name: p for p in old_params if p.name}
    new_by_name = {p.name: p for p in new_params if p.name}
    for name in sorted(set(new_by_name) - set(old_by_name)):
        p = new_by_name[name]
        changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_PARAM_ADDED,
            f"parameter {name!r} added (default={p.default_text!r})", True))
    for name in sorted(set(old_by_name) - set(new_by_name)):
        p = old_by_name[name]
        changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_PARAM_REMOVED,
            f"parameter {name!r} removed (was default={p.default_text!r})", True))
    for name in sorted(set(old_by_name) & set(new_by_name)):
        o, n = old_by_name[name], new_by_name[name]
        if (o.type_text or "") != (n.type_text or ""):
            changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_PARAM_TYPE_CHANGED,
                f"parameter {name!r} type {o.type_text!r} -> {n.type_text!r}", True))
        if (o.default_text or "") != (n.default_text or ""):
            changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_PARAM_DEFAULT_CHANGED,
                f"parameter {name!r} default {o.default_text!r} -> {n.default_text!r}", True))
    return changes


def _diff_signal_lists(file_path: str, module_name: Optional[str],
                        old_signals: list, new_signals: list) -> List[SemanticRtlChange]:
    changes: List[SemanticRtlChange] = []
    old_by_name = {s.name: s for s in old_signals if s.name}
    new_by_name = {s.name: s for s in new_signals if s.name}
    for name in sorted(set(new_by_name) - set(old_by_name)):
        s = new_by_name[name]
        changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_SIGNAL_ADDED,
            f"internal signal {name!r} added ({s.data_type})", False))
    for name in sorted(set(old_by_name) - set(new_by_name)):
        s = old_by_name[name]
        changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_SIGNAL_REMOVED,
            f"internal signal {name!r} removed (was {s.data_type})", False))
    for name in sorted(set(old_by_name) & set(new_by_name)):
        o, n = old_by_name[name], new_by_name[name]
        if (o.data_type or "") != (n.data_type or "") or (o.unpacked_dims or "") != (n.unpacked_dims or ""):
            changes.append(SemanticRtlChange(file_path, module_name, RTL_CHANGE_SIGNAL_TYPE_CHANGED,
                f"internal signal {name!r} type {o.data_type!r}{o.unpacked_dims or ''} -> "
                f"{n.data_type!r}{n.unpacked_dims or ''}", False))
    return changes


def _diff_modules(file_path: str, base_modules: list, head_modules: list) -> List[SemanticRtlChange]:
    changes: List[SemanticRtlChange] = []
    base_by_name = {m.name: m for m in base_modules if m.name}
    head_by_name = {m.name: m for m in head_modules if m.name}
    for name in sorted(set(head_by_name) - set(base_by_name)):
        changes.append(SemanticRtlChange(file_path, name, RTL_CHANGE_MODULE_ADDED,
            f"module {name!r} added", True))
    for name in sorted(set(base_by_name) - set(head_by_name)):
        changes.append(SemanticRtlChange(file_path, name, RTL_CHANGE_MODULE_REMOVED,
            f"module {name!r} removed", True))
    for name in sorted(set(base_by_name) & set(head_by_name)):
        b, h = base_by_name[name], head_by_name[name]
        changes += _diff_port_lists(file_path, name, b.ports, h.ports)
        changes += _diff_param_lists(file_path, name, b.parameters, h.parameters)
        changes += _diff_signal_lists(file_path, name, b.signals, h.signals)
    return changes


def semantic_diff_rtl_file(root: Path, base_sha: str, head_sha: str, rel_path: str,
                            *, verible_bin: str = "verible-verilog-syntax") -> dict:
    """The one real per-file entry point: WHAT changed in this one RTL/SV
    file between `base_sha` and `head_sha`, at verible_parser.py's own
    documented declaration-level scope. Returns:
        status: FILE_ADDED / FILE_REMOVED / FILE_UNCHANGED_STRUCTURALLY /
                BODY_ONLY_CHANGE / CHANGED / NOT_AVAILABLE
        changes: list[dict] (SemanticRtlChange.to_dict())
        interface_impacting: bool -- True iff any real change touches a
                module/port/parameter (see INTERFACE_IMPACTING_CHANGE_KINDS)
        detail: the real reason when status is NOT_AVAILABLE

    NOT_AVAILABLE is the honest "we could not verify" state and must never
    be read as "nothing changed structurally". BODY_ONLY_CHANGE is the
    honest "the file's bytes differ but every module's own declared
    interface is identical" state -- the change is inside a procedural
    body, a comment, or formatting, beyond this parser's declared scope."""
    vp = _import_verible_parser()
    if vp is None:
        return {"status": "NOT_AVAILABLE", "changes": [], "interface_impacting": False,
                "detail": "dv_harness.verible_parser could not be imported"}

    base_file = rtl_file_content_at_revision(root, base_sha, rel_path)
    head_file = rtl_file_content_at_revision(root, head_sha, rel_path)
    if base_file["status"] == "NO_GIT" or head_file["status"] == "NO_GIT":
        return {"status": "NOT_AVAILABLE", "changes": [], "interface_impacting": False,
                "detail": "git not available"}

    base_present = base_file["status"] == "PRESENT"
    head_present = head_file["status"] == "PRESENT"

    if not base_present and not head_present:
        return {"status": "NOT_AVAILABLE", "changes": [], "interface_impacting": False,
                "detail": f"{rel_path!r} not present at either revision"}

    if base_present and head_present and base_file["content"] == head_file["content"]:
        return {"status": "FILE_UNCHANGED_STRUCTURALLY", "changes": [],
                "interface_impacting": False, "detail": "byte-identical content at both revisions"}

    base_parsed = _parse_rtl_content(vp, base_file["content"], rel_path, verible_bin) if base_present else None
    head_parsed = _parse_rtl_content(vp, head_file["content"], rel_path, verible_bin) if head_present else None
    for parsed in (base_parsed, head_parsed):
        if parsed is not None and parsed["status"] != "PARSED":
            return {"status": "NOT_AVAILABLE", "changes": [], "interface_impacting": False,
                    "detail": f"{parsed['status']}: {parsed['detail']}"}

    if not base_present:
        changes = [SemanticRtlChange(rel_path, m.name, RTL_CHANGE_MODULE_ADDED,
                                      f"new file adds module {m.name!r}", True)
                   for m in (head_parsed["modules"] or []) if m.name]
        return {"status": "FILE_ADDED", "changes": [c.to_dict() for c in changes],
                "interface_impacting": True, "detail": None}

    if not head_present:
        changes = [SemanticRtlChange(rel_path, m.name, RTL_CHANGE_MODULE_REMOVED,
                                      f"file removed, taking module {m.name!r} with it", True)
                   for m in (base_parsed["modules"] or []) if m.name]
        return {"status": "FILE_REMOVED", "changes": [c.to_dict() for c in changes],
                "interface_impacting": True, "detail": None}

    changes = _diff_modules(rel_path, base_parsed["modules"] or [], head_parsed["modules"] or [])
    if not changes:
        return {"status": "BODY_ONLY_CHANGE", "changes": [], "interface_impacting": False,
                "detail": ("content differs but no declaration-level (module/port/parameter/"
                           "signal) difference was found -- the change is inside a procedural "
                           "body, a comment, or formatting, beyond this parser's declared scope")}
    interface_impacting = any(c.kind in INTERFACE_IMPACTING_CHANGE_KINDS for c in changes)
    return {"status": "CHANGED", "changes": [c.to_dict() for c in changes],
            "interface_impacting": interface_impacting, "detail": None}


def compute_semantic_change_impact(root: Path, *, base_sha: str, head_sha: str = "HEAD",
                                    diff: Optional[dict] = None,
                                    verible_bin: str = "verible-verilog-syntax",
                                    rtl_suffixes: Sequence[str] = _RTL_SUFFIXES) -> dict:
    """WHAT the diff means for every RTL/SV file it touches -- additive to,
    and independent of, `compute_change_impact()` above: this function reads
    no state that one writes and changes nothing about its confidence /
    `expand_to_full_regression` / regression-selection behaviour. Only files
    whose suffix is in `rtl_suffixes` (`_RTL_SUFFIXES`, the exact same set
    `classify_risk()` already uses -- imported, not re-typed) are
    semantically diffed; every other changed file is reported under
    `non_rtl_files_skipped`, never silently dropped."""
    root = Path(root)
    diff = diff if diff is not None else changed_files(root, base_sha, head_sha)
    base = diff.get("base_sha") or base_sha
    head = diff.get("head_sha") or head_sha

    if diff.get("status") != "REAL_DIFF":
        return {
            "base_sha": base, "head_sha": head, "status": "NOT_AVAILABLE",
            "detail": f"underlying diff status {diff.get('status')!r}: {diff.get('detail')}",
            "per_file": [], "interface_impacting_files": [], "body_only_files": [],
            "unverifiable_files": [], "non_rtl_files_skipped": [],
        }

    per_file: List[dict] = []
    interface_impacting_files: List[str] = []
    body_only_files: List[str] = []
    unverifiable_files: List[str] = []
    non_rtl_files_skipped: List[str] = []

    for f in diff.get("files") or []:
        base_name = f.rsplit("/", 1)[-1]
        suffix = ("." + base_name.rsplit(".", 1)[-1]) if "." in base_name else ""
        if suffix.lower() not in rtl_suffixes:
            non_rtl_files_skipped.append(f)
            continue
        result = semantic_diff_rtl_file(root, base, head, f, verible_bin=verible_bin)
        result["file"] = f
        per_file.append(result)
        if result["status"] == "NOT_AVAILABLE":
            unverifiable_files.append(f)
        elif result.get("interface_impacting"):
            interface_impacting_files.append(f)
        elif result["status"] == "BODY_ONLY_CHANGE":
            body_only_files.append(f)

    return {
        "base_sha": base, "head_sha": head, "status": "COMPUTED", "detail": None,
        "per_file": per_file,
        "interface_impacting_files": interface_impacting_files,
        "body_only_files": body_only_files,
        "unverifiable_files": unverifiable_files,
        "non_rtl_files_skipped": non_rtl_files_skipped,
    }


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    """Standalone front door -- `python -m dv_harness.change_impact
    semantic-diff --root <dir> --base <sha> [--head <sha>] [--json]`. Not
    wired into `cli.py` (a large, concurrently-edited file in this
    project's own batch, per that file's own disclosed-scope convention).
    Exit 0: no interface-impacting file found. 1: at least one real
    interface-impacting file found. 2: NOT_AVAILABLE or a usage error."""
    import argparse
    parser = argparse.ArgumentParser(prog="python -m dv_harness.change_impact")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("semantic-diff",
                        help="WHAT changed in RTL/SV files between two revisions, not just which files")
    p.add_argument("--root", default=".")
    p.add_argument("--base", required=True)
    p.add_argument("--head", default="HEAD")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.cmd != "semantic-diff":
        return 2

    report = compute_semantic_change_impact(Path(args.root), base_sha=args.base, head_sha=args.head)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"status: {report['status']}")
        if report["status"] != "COMPUTED":
            print(f"detail: {report['detail']}")
        else:
            for pf in report["per_file"]:
                print(f"- {pf['file']}: {pf['status']} "
                      f"(interface_impacting={pf.get('interface_impacting')})")
                for c in pf.get("changes") or []:
                    print(f"    {c['kind']}: {c['detail']}")
            print(f"interface_impacting_files: {report['interface_impacting_files']}")
            print(f"body_only_files: {report['body_only_files']}")
            print(f"unverifiable_files: {report['unverifiable_files']}")

    if report["status"] != "COMPUTED":
        return 2
    return 1 if report["interface_impacting_files"] else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return execute_verb(argv)


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
