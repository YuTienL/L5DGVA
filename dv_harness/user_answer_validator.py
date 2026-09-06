"""Validates a raw, user-typed intake answer against REAL evidence already
produced by this codebase's own parsers/manifests -- never against the
answer's own wording.

THE GAP THIS CLOSES. Intake conversations collect free-text answers such as
"DUT top = usb_core" or "build includes file usb3_link_ctrl.v". Nothing in
this repo checked such an answer against anything real: an agent (or a
human) typing the answer was the only source for it, so a wrong or
hallucinated answer would sit in the intake record indistinguishable from a
correct one. Per CLAUDE.md's Evidence Truth Rule, a claim like this must be
checked against a REAL producer, and where it genuinely cannot be checked
the module must say so honestly (UNVERIFIABLE) rather than accept it as
true by default.

REUSE, NOT REINVENTION.
  - Module/file EXISTENCE inside a supplied RTL file set is answered by
    running the REAL `verible_parser.parse_file()` against each supplied
    file (the same verible-verilog-syntax front end `env_manifest.py`
    itself extends) and checking whether the claimed module name is really
    among what verible extracted. This module parses RTL through no other
    path.
  - Build INCLUSION is answered by reading `env_manifest.py`'s own already-
    recorded `dut_facts.rtl` facts (produced by `build_dut_facts_rtl()` or
    loaded from a real `env.manifest.json` via `load_env_manifest()`) and
    checking whether the claimed file appears among the file paths that
    were REALLY parsed into that manifest. This module never re-parses a
    build's file list itself and never re-derives what "the build" is.

FOUR HONEST STATUSES, never collapsed into three.
  - VALIDATED -- the claim matches real evidence exactly.
  - PARTIALLY_VALIDATED -- real evidence supports a WEAKER form of the same
    claim (a module of that name exists but under different letter case; a
    file of that name is recorded but at a different path than claimed).
    This is a real, disclosed, weaker match -- never silently promoted to
    VALIDATED and never silently dropped.
  - CONTRADICTED -- real evidence was fully consulted and the claim is
    false: the named module is absent from every RTL file this module
    could successfully parse, or the named file is absent from every file
    path recorded in the build facts.
  - UNVERIFIABLE -- this module could not check the claim against real
    evidence at all: no RTL file set / no build facts were supplied, the
    real verible binary could not be run, some of the supplied RTL could
    not be parsed (a real verible syntax error) and the claim was not found
    among what DID parse (so absence there is not proof of absence overall
    -- reporting CONTRADICTED in that case would be an unearned claim), or
    the answer's own text could not be parsed into a checkable claim in the
    first place. UNVERIFIABLE is never silently accepted as VALIDATED.

WHAT THIS MODULE DOES NOT DO. It does not decide which intake answer is
"the" answer, does not write to any question queue, decision store, or
manifest, and does not run any build, job, or LSF submission. It reads two
already-real evidence sources and reports what they say."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dv_harness import env_manifest
from dv_harness import verible_parser

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

VALIDATED = "VALIDATED"
PARTIALLY_VALIDATED = "PARTIALLY_VALIDATED"
CONTRADICTED = "CONTRADICTED"
UNVERIFIABLE = "UNVERIFIABLE"

VERDICTS = (VALIDATED, PARTIALLY_VALIDATED, CONTRADICTED, UNVERIFIABLE)

CLAIM_MODULE_EXISTENCE = "MODULE_EXISTENCE"
CLAIM_FILE_BUILD_INCLUSION = "FILE_BUILD_INCLUSION"
CLAIM_UNKNOWN = "UNKNOWN_CLAIM_TYPE"

CLAIM_TYPES = (CLAIM_MODULE_EXISTENCE, CLAIM_FILE_BUILD_INCLUSION, CLAIM_UNKNOWN)

# ---------------------------------------------------------------------------
# Claim extraction -- structural regex parsing of the raw text, never a
# guess at the target's real identity. An answer whose phrasing matches
# none of these patterns yields CLAIM_UNKNOWN, which validate_answer() below
# always turns into UNVERIFIABLE -- it is never silently skipped or treated
# as a pass.
# ---------------------------------------------------------------------------

# A bare SystemVerilog-legal identifier.
_IDENT = r"[A-Za-z_]\w*"
# A file-path-shaped token: word chars, path separators (both slash
# conventions), a drive-letter colon, dot and dash -- deliberately permissive
# since this is only used to CAPTURE the claimed target text, never to judge
# it; the real judgment happens against recorded evidence afterward.
_PATH_TOKEN = r"[\w./\\:-]+"

_MODULE_EXISTENCE_PATTERNS = [
    re.compile(r"\bdut\s+top\s+module\s*(?:is|=|:)\s*(" + _IDENT + r")", re.IGNORECASE),
    re.compile(r"\bdut\s+top\s*(?:is|=|:)\s*(" + _IDENT + r")", re.IGNORECASE),
    re.compile(r"\btop\s+module\s*(?:is|=|:)\s*(" + _IDENT + r")", re.IGNORECASE),
    re.compile(r"\bmodule\s+name\s*(?:is|=|:)\s*(" + _IDENT + r")", re.IGNORECASE),
    re.compile(r"\bmodule\s+(" + _IDENT + r")\s+exists\b", re.IGNORECASE),
    re.compile(r"\bmodule\s*(?:is|=|:)\s*(" + _IDENT + r")", re.IGNORECASE),
    re.compile(r"\b(" + _IDENT + r")\s+is\s+(?:a\s+)?(?:real\s+)?module\b", re.IGNORECASE),
]

_FILE_BUILD_INCLUSION_PATTERNS = [
    re.compile(r"\bbuild\s+includes?\s+file\s+(" + _PATH_TOKEN + r")", re.IGNORECASE),
    re.compile(r"\bfile\s+(" + _PATH_TOKEN + r")\s+is\s+included\s+in\s+(?:the\s+)?build\b", re.IGNORECASE),
    re.compile(r"\b(" + _PATH_TOKEN + r"\.\w+)\s+is\s+(?:part\s+of|included\s+in)\s+(?:the\s+)?build\b",
               re.IGNORECASE),
    re.compile(r"\bbuild\s+file\s*list\s+(?:includes|contains)\s+(" + _PATH_TOKEN + r")", re.IGNORECASE),
    re.compile(r"\bfile\s+(" + _PATH_TOKEN + r")\s+is\s+in\s+the\s+build\b", re.IGNORECASE),
]


@dataclass
class AnswerClaim:
    """What was structurally extracted from a raw answer's text -- not yet
    checked against anything. `target` is None whenever `claim_type` is
    CLAIM_UNKNOWN."""
    raw_text: str
    claim_type: str
    target: Optional[str] = None


def extract_claim(raw_text: str) -> AnswerClaim:
    """Structural regex extraction only. Never inspects any evidence source
    -- it only decides what KIND of claim the text seems to make and what
    target it names, so the answer can then be checked for real."""
    if raw_text is None or not raw_text.strip():
        return AnswerClaim(raw_text=raw_text, claim_type=CLAIM_UNKNOWN, target=None)
    text = raw_text.strip()
    for pattern in _MODULE_EXISTENCE_PATTERNS:
        m = pattern.search(text)
        if m:
            return AnswerClaim(raw_text=raw_text, claim_type=CLAIM_MODULE_EXISTENCE, target=m.group(1))
    for pattern in _FILE_BUILD_INCLUSION_PATTERNS:
        m = pattern.search(text)
        if m:
            target = m.group(1).rstrip(".,;:")
            return AnswerClaim(raw_text=raw_text, claim_type=CLAIM_FILE_BUILD_INCLUSION, target=target)
    return AnswerClaim(raw_text=raw_text, claim_type=CLAIM_UNKNOWN, target=None)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class AnswerValidation:
    raw_text: str
    claim_type: str
    target: Optional[str]
    status: str
    reason: str
    evidence: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "claim_type": self.claim_type,
            "target": self.target,
            "status": self.status,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }


def _normalize_path_str(p: str) -> str:
    """Best-effort path normalization for comparing a claimed path string
    against a recorded one -- collapses `./`/`../`-style segments and unifies
    separators, never resolves against a filesystem (the recorded path may
    not exist relative to this process's cwd)."""
    return os.path.normpath(str(p)).replace("\\", "/")


# ---------------------------------------------------------------------------
# Module/file existence -- reuses verible_parser.py (read-only import)
# ---------------------------------------------------------------------------

def check_module_existence(target_module: str, rtl_files,
                            verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN):
    """Checks whether `target_module` is a module verible really extracts
    from the supplied `rtl_files`. Returns (status, reason, evidence_list).

    Never re-implements RTL parsing: every module name it compares against
    comes straight out of `verible_parser.parse_file()` -- the same real
    verible-verilog-syntax front end `env_manifest.build_dut_facts_rtl()`
    itself calls."""
    paths = [Path(p) for p in (rtl_files or [])]
    if not paths:
        return (UNVERIFIABLE,
                "no RTL file set was supplied to validate this module-existence claim against",
                [])

    parsed_modules = []   # list[(file_path, module_name)]
    failed_files = []     # list[(file_path, reason)]

    for p in paths:
        try:
            result = verible_parser.parse_file(p, verible_bin=verible_bin)
        except verible_parser.VeribleUnavailableError as exc:
            # The tool itself could not be run at all -- nothing about ANY
            # file could be checked, so this is UNVERIFIABLE for the whole
            # claim, never a per-file finding.
            return (UNVERIFIABLE,
                    f"verible-verilog-syntax could not be run to check this claim: {exc}",
                    [])
        except verible_parser.VeribleParseError as exc:
            failed_files.append((str(p), str(exc)))
            continue
        except OSError as exc:
            failed_files.append((str(p), f"could not be read: {exc}"))
            continue
        for m in result.modules:
            if m.name:
                parsed_modules.append((str(p), m.name))

    exact = [(fp, name) for fp, name in parsed_modules if name == target_module]
    if exact:
        evidence = [f"module '{name}' parsed from {fp} (verible-verilog-syntax)" for fp, name in exact]
        return (VALIDATED,
                f"module '{target_module}' was really parsed out of the supplied RTL file(s)",
                evidence)

    ci_matches = [(fp, name) for fp, name in parsed_modules if name.lower() == target_module.lower()]
    if ci_matches:
        evidence = [f"module '{name}' parsed from {fp} (case differs from claimed '{target_module}')"
                    for fp, name in ci_matches]
        return (PARTIALLY_VALIDATED,
                f"a module named '{ci_matches[0][1]}' really exists in the supplied RTL, but its "
                f"letter case does not exactly match the claimed '{target_module}'",
                evidence)

    if failed_files:
        # Some of the supplied RTL genuinely could not be parsed (a real
        # verible syntax error). The module was not found among what DID
        # parse, but that is not proof it is absent from the file(s) that
        # could not be checked -- CONTRADICTED would be an unearned claim.
        evidence = [f"{fp}: verible reported real syntax errors, not checked -- {err}"
                    for fp, err in failed_files]
        return (UNVERIFIABLE,
                f"module '{target_module}' was not found among {len(parsed_modules)} successfully-"
                f"parsed module(s), but {len(failed_files)} of the supplied RTL file(s) failed to "
                f"parse and could not be checked",
                evidence)

    evidence = [f"checked {len(paths)} RTL file(s), {len(parsed_modules)} module(s) really parsed, "
                f"none named '{target_module}'"]
    return (CONTRADICTED,
            f"module '{target_module}' does not exist in any of the {len(paths)} supplied, "
            f"successfully-parsed RTL file(s)",
            evidence)


# ---------------------------------------------------------------------------
# Build inclusion -- reuses env_manifest.py (read-only import)
# ---------------------------------------------------------------------------

def check_build_inclusion(target_file: str, dut_facts_rtl) -> tuple:
    """Checks whether `target_file` appears among the file paths REALLY
    recorded in `dut_facts_rtl` -- the exact shape
    `env_manifest.build_dut_facts_rtl()` produces (and what
    `env.manifest.json`'s own `dut_facts.rtl` layer carries once loaded via
    `env_manifest.load_env_manifest()`). Returns
    (status, reason, evidence_list).

    Never re-derives what "the build" contains: it only reads what that
    module already recorded."""
    if not isinstance(dut_facts_rtl, dict):
        return (UNVERIFIABLE,
                "no recorded RTL build facts (env_manifest.py dut_facts.rtl) were supplied to "
                "validate this build-inclusion claim against",
                [])

    status = dut_facts_rtl.get("status")
    if status != "PARSED":
        reason = dut_facts_rtl.get("reason") or "no reason recorded"
        return (UNVERIFIABLE,
                f"the recorded RTL build facts report status {status!r} rather than PARSED: {reason}",
                [])

    files = dut_facts_rtl.get("files") or []
    recorded_paths = [f.get("file_path") for f in files if f.get("file_path")]
    if not recorded_paths:
        return (UNVERIFIABLE,
                "the recorded RTL build facts carry status PARSED but list no file entries at all",
                [])

    target_norm = _normalize_path_str(target_file)
    target_name = Path(target_file).name

    exact = [rp for rp in recorded_paths if _normalize_path_str(rp) == target_norm]
    if exact:
        evidence = [f"recorded file_path: {rp}" for rp in exact]
        return (VALIDATED,
                f"file '{target_file}' really appears among the recorded RTL build facts",
                evidence)

    basename_matches = [rp for rp in recorded_paths if Path(rp).name == target_name]
    if basename_matches:
        evidence = [f"recorded file_path: {rp}" for rp in basename_matches]
        return (PARTIALLY_VALIDATED,
                f"a file named '{target_name}' is recorded in the build facts, but at a different "
                f"path than the claimed '{target_file}'",
                evidence)

    evidence = [f"recorded file_path: {rp}" for rp in recorded_paths]
    return (CONTRADICTED,
            f"file '{target_file}' does not appear among the {len(recorded_paths)} RTL file(s) "
            f"really recorded in the build facts",
            evidence)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def validate_answer(raw_text: str, *, rtl_files=None, dut_facts_rtl=None, manifest: Optional[dict] = None,
                     verible_bin: str = verible_parser.DEFAULT_VERIBLE_BIN) -> AnswerValidation:
    """Validates one raw user-typed intake answer.

    `rtl_files`: a supplied RTL file-path set to check a MODULE_EXISTENCE
    claim against (real verible parse, via check_module_existence()).

    `dut_facts_rtl`: an already-built `dut_facts.rtl` dict (the exact shape
    `env_manifest.build_dut_facts_rtl()` returns) to check a
    FILE_BUILD_INCLUSION claim against. `manifest`, if supplied instead (a
    full env.manifest.json-shaped dict, e.g. from
    `env_manifest.load_env_manifest()`), is read for its own
    `dut_facts.rtl` sub-layer when `dut_facts_rtl` is not separately given.

    An answer whose claim type cannot be extracted, or whose extracted
    claim type has no matching evidence input supplied, is UNVERIFIABLE --
    never silently accepted."""
    claim = extract_claim(raw_text)

    effective_dut_facts_rtl = dut_facts_rtl
    if effective_dut_facts_rtl is None and isinstance(manifest, dict):
        effective_dut_facts_rtl = manifest.get("dut_facts", {}).get("rtl") if manifest.get("dut_facts") else None

    if claim.claim_type == CLAIM_MODULE_EXISTENCE:
        status, reason, evidence = check_module_existence(claim.target, rtl_files, verible_bin=verible_bin)
    elif claim.claim_type == CLAIM_FILE_BUILD_INCLUSION:
        status, reason, evidence = check_build_inclusion(claim.target, effective_dut_facts_rtl)
    else:
        status = UNVERIFIABLE
        reason = ("could not extract a checkable claim (module existence or file build inclusion) "
                   "from this answer's own text -- reporting UNVERIFIABLE rather than guessing at "
                   "its meaning")
        evidence = []

    return AnswerValidation(
        raw_text=raw_text,
        claim_type=claim.claim_type,
        target=claim.target,
        status=status,
        reason=reason,
        evidence=evidence,
    )
