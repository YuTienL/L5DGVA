"""sim_log_analysis.py -- generic (not USB-specific) sim.log parsing engine.

Implements the analysis this project's own conventions already describe but
never had a real implementation for:
- .claude/skills/CORE/per-job-simlog-analysis/SKILL.md's output schema
  (signature / first / last / count / classification / severity /
  root_cause_hypothesis / proposed_fix / confidence).
- .claude/skills/CORE/failure-triage/SKILL.md's marker vocabulary
  (UVM_FATAL, UVM_ERROR, Error-, Fatal, assertion, timeout, mismatch,
  scoreboard, protocol, license, killed, memory, crash).
- dv_harness/lsf_client.py's JobState fields (uvm_error_count,
  uvm_fatal_count, assertion_failure, last_log_offset) are populated
  elsewhere in the codebase by *self-reporting* (an agent or a thin
  substring gate writes them); this module is the real, evidence-based
  parser those fields were always meant to be checked against -- see
  detect_underreporting() below.

Real documented trap this module exists to catch (not a hypothetical): per
this session's usbrun.sh evidence (.claude/skills/USB/usb-regression/
SKILL.md "長跑 LSF job 的即時健康檢查"), a PLL model in a real project
reported a plain, non-UVM-prefixed "ERROR in PLL model" line that a
UVM_ERROR-only filter missed for roughly an hour. parse_sim_log() therefore
always scans for bare `Error-`/`ERROR` lines in addition to UVM_-prefixed
markers, never only the UVM_ vocabulary.

Design note: every function here is pure (str/dict in, dict/list out) --
no file I/O except the thin parse_sim_log_file() wrapper, no subprocess, no
UVM/simulator dependency -- so this works for any UVM project's sim.log,
not just USB, matching the "generic engine capability" requirement.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# ---------------------------------------------------------------------------
# Marker vocabulary (failure-triage SKILL.md's "Search examples" line, verbatim
# vocabulary, plus the UVM_WARNING/epilogue-only tokens the schema also names).
# Order matters for classification priority (most specific/severe first) --
# see classify_signatures().
# ---------------------------------------------------------------------------

# Each entry: (marker_name, compiled regex). Matched independently per line;
# a single line may hit more than one marker (e.g. a UVM_ERROR line that also
# contains the word "timeout") -- classify_signatures() picks one category
# per signature using MARKER_PRIORITY below, it does not double-count lines.
_MARKER_PATTERNS: List[tuple] = [
    ("UVM_FATAL", re.compile(r"UVM_FATAL")),
    ("UVM_ERROR", re.compile(r"UVM_ERROR")),
    ("UVM_WARNING", re.compile(r"UVM_WARNING")),
    # Bare build/sim-log style errors with no UVM_ prefix -- the documented
    # real trap (PLL-model "ERROR in PLL model"). Matches a line that starts
    # (after optional leading whitespace) with "Error-" (VCS's own bare-error
    # tag, e.g. "Error-[XYZ]") or a standalone "ERROR"/"Error" word that is
    # NOT already part of "UVM_ERROR" (that case is already claimed by the
    # UVM_ERROR pattern above).
    ("BARE_ERROR", re.compile(r"(^\s*Error-)|(?<!UVM_)\bERROR\b", re.IGNORECASE)),
    ("FATAL", re.compile(r"\bFatal\b", re.IGNORECASE)),
    ("ASSERTION", re.compile(r"\bassert(ion)?\b", re.IGNORECASE)),
    ("TIMEOUT", re.compile(r"\btimeout\b|\bdeadlock\b", re.IGNORECASE)),
    ("MISMATCH", re.compile(r"\bmismatch\b", re.IGNORECASE)),
    ("SCOREBOARD", re.compile(r"\bscoreboard\b", re.IGNORECASE)),
    ("PROTOCOL", re.compile(r"\bprotocol\b", re.IGNORECASE)),
    ("LICENSE", re.compile(r"\blicense\b", re.IGNORECASE)),
    ("KILLED", re.compile(r"\bkilled\b", re.IGNORECASE)),
    ("MEMORY", re.compile(r"\bmemory\b", re.IGNORECASE)),
    ("CRASH", re.compile(r"\bcrash\b", re.IGNORECASE)),
]

# Which marker "wins" when a single normalized signature could be tagged with
# more than one marker name (e.g. a UVM_FATAL line that also says "crash").
# Earlier = higher priority. Anything not listed falls back to "other".
_MARKER_TO_CATEGORY = {
    "UVM_FATAL": "uvm_fatal",
    "UVM_ERROR": "uvm_error",
    "BARE_ERROR": "bare_error",
    "FATAL": "uvm_fatal",
    "ASSERTION": "assertion",
    "SCOREBOARD": "scoreboard_mismatch",
    "MISMATCH": "scoreboard_mismatch",
    "TIMEOUT": "timeout",
    "UVM_WARNING": "other",
    "PROTOCOL": "other",
    "LICENSE": "other",
    "KILLED": "other",
    "MEMORY": "other",
    "CRASH": "other",
}

# classify_signatures()'s category-selection priority -- intentionally
# independent of _MARKER_PATTERNS' scan order above. Specific-reason markers
# (SCOREBOARD/MISMATCH/ASSERTION/TIMEOUT -> their own named category) win
# over the generic UVM_FATAL/UVM_ERROR severity wrapper, e.g. a line that is
# both "UVM_ERROR" and mentions "scoreboard" classifies as the more
# actionable scoreboard_mismatch, not the generic uvm_error. But the generic
# UVM_FATAL/UVM_ERROR wrapper still wins over markers that only map to the
# catch-all "other" category (PROTOCOL/LICENSE/KILLED/MEMORY/CRASH/
# UVM_WARNING) -- e.g. "UVM_FATAL ... unrecoverable protocol violation"
# must classify as uvm_fatal, not fall through to "other" because the
# message happens to contain the word "protocol".
_CATEGORY_PRIORITY = [
    "SCOREBOARD", "MISMATCH", "ASSERTION", "TIMEOUT",
    "UVM_FATAL", "FATAL", "UVM_ERROR", "BARE_ERROR",
    "CRASH", "KILLED", "MEMORY", "LICENSE", "PROTOCOL", "UVM_WARNING",
]

# classify_signatures() severity priority order, worst first. Documented
# call (per the task): this is this module's own severity enum, chosen to
# match the per-job-simlog-analysis SKILL.md's "severity" concept, not a
# pre-existing project-wide enum found elsewhere in the codebase.
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

_CATEGORY_SEVERITY = {
    "uvm_fatal": "CRITICAL",
    "bare_error": "HIGH",      # unproven UVM triage path -- treat as at least as
                               # serious as uvm_error until proven benign, since
                               # the real PLL-model incident *was* a genuine bug
    "uvm_error": "HIGH",
    "scoreboard_mismatch": "HIGH",
    "assertion": "MEDIUM",
    "timeout": "MEDIUM",
    "other": "LOW",
}

#: This module's category enum, as data. Exported so a caller that classifies
#: something OTHER than a log line (SYOSCB-21's per-transaction scoreboard
#: result taxonomy is the first) can route its own findings into this triage
#: vocabulary instead of inventing a second one -- the failure mode this
#: project keeps catching. Derived from `_CATEGORY_SEVERITY`, so a category
#: added there is exported here automatically rather than in a second list
#: that would drift.
TRIAGE_CATEGORIES: tuple = tuple(_CATEGORY_SEVERITY)


def severity_for_category(category: str) -> str:
    """The severity this module assigns a triage category.

    Public because `SEVERITY_ORDER` alone does not say WHICH severity a given
    category carries, and a caller reading `_CATEGORY_SEVERITY` through its
    private name -- or, worse, re-typing the mapping -- is how the one severity
    scale becomes two that disagree. An unrecognized category falls back to
    "LOW" exactly as `classify_signatures()` does, because the two must not
    answer the same question differently."""
    return _CATEGORY_SEVERITY.get(category, "LOW")


# ---------------------------------------------------------------------------
# Signature normalization: strip the "obvious variable content" the task
# names explicitly (timestamps, hex addresses, random seeds) so repeated
# occurrences of the same root issue collapse to one signature.
# ---------------------------------------------------------------------------

_NORMALIZE_PATTERNS = [
    # simulation time: "@ 12345 ns", "@ 12345.5ns", "at time 123", "t=123"
    (re.compile(r"@\s*\d+(\.\d+)?\s*(ns|ps|fs|us)\b", re.IGNORECASE), "@ <TIME>"),
    (re.compile(r"\btime\s*=?\s*\d+(\.\d+)?\s*(ns|ps|fs|us)?\b", re.IGNORECASE), "time=<TIME>"),
    (re.compile(r"\bt\s*=\s*\d+(\.\d+)?\b", re.IGNORECASE), "t=<TIME>"),
    # hex addresses/values: 0x1a2b3c, 32'h0000_dead, 'hDEAD
    (re.compile(r"\b0x[0-9a-fA-F_]+\b"), "0x<HEX>"),
    (re.compile(r"\b\d+'h[0-9a-fA-F_]+\b"), "<HEXLIT>"),
    # random seeds: "seed=123", "seed: 123", "ntb_random_seed=123"
    (re.compile(r"\b(ntb_random_)?seed\s*[:=]\s*\d+\b", re.IGNORECASE), "seed=<SEED>"),
    # generic wall-clock/date stamps some loggers prefix lines with, e.g.
    # "[2026-08-29 12:00:01]" or "2026-08-29T12:00:01"
    (re.compile(r"\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?\]?"), "<TIMESTAMP>"),
    # bare large decimal numbers left over (e.g. transaction counters, cycle
    # counts embedded mid-message) -- collapse only runs of 3+ digits so we
    # don't eat small, meaningful numbers like "port 2" or "UVM_ERROR" itself.
    (re.compile(r"\b\d{3,}\b"), "<N>"),
]


def _normalize_signature(line: str) -> str:
    s = line.strip()
    for pattern, repl in _NORMALIZE_PATTERNS:
        s = pattern.sub(repl, s)
    # collapse repeated whitespace so purely-cosmetic spacing differences
    # don't split one real signature into two.
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _match_markers(line: str) -> List[str]:
    hits = []
    for name, pattern in _MARKER_PATTERNS:
        if pattern.search(line):
            hits.append(name)
    return hits


def parse_sim_log(log_text: str) -> Dict[str, Any]:
    """Scan log_text line-by-line for the failure-triage marker vocabulary.

    Returns:
        {
          "total_lines": int,
          "signatures": {
              signature: {
                  "markers": [marker_name, ...],   # union across all occurrences
                  "first_line_no": int,            # 1-indexed
                  "last_line_no": int,
                  "count": int,
                  "example_line": str,             # exact text of first occurrence
              }, ...
          },
          "epilogue": dict|None,   # see parse_epilogue()
        }

    A single physical line that matches more than one marker (e.g. contains
    both "UVM_ERROR" and "timeout") is recorded once under its own
    normalized signature with all matched marker names attached -- it is
    never double-counted as two separate occurrences.
    """
    signatures: Dict[str, Dict[str, Any]] = {}
    lines = log_text.splitlines()

    for idx, line in enumerate(lines, start=1):
        # The epilogue's own "UVM_FATAL = N, UVM_ERROR = N, UVM_WARNING = N"
        # summary line literally contains the substrings "UVM_FATAL"/
        # "UVM_ERROR" as field labels -- it must never be scanned as a
        # per-line marker occurrence (that would fabricate a fake failure
        # signature out of a PASSING epilogue's own N=0 tally, and would
        # double-count against the real occurrences already seen earlier in
        # the log on a FAILING run). This line's counts are extracted
        # separately, once, by parse_epilogue() below.
        if _EPILOGUE_COUNTS_RE.search(line):
            continue
        markers = _match_markers(line)
        if not markers:
            continue
        sig = _normalize_signature(line)
        entry = signatures.get(sig)
        if entry is None:
            signatures[sig] = {
                "markers": list(markers),
                "first_line_no": idx,
                "last_line_no": idx,
                "count": 1,
                "example_line": line.strip(),
            }
        else:
            entry["last_line_no"] = idx
            entry["count"] += 1
            for m in markers:
                if m not in entry["markers"]:
                    entry["markers"].append(m)

    return {
        "total_lines": len(lines),
        "signatures": signatures,
        "epilogue": parse_epilogue(log_text),
    }


def parse_sim_log_file(path: Union[str, Path]) -> Dict[str, Any]:
    """Thin file wrapper around parse_sim_log(). Reads with errors='replace'
    so a stray non-UTF-8 byte in a multi-GB sim.log (real EDA logs sometimes
    carry these from vendor tool output) never raises and aborts analysis --
    matching the "never assume/never crash on real log content" posture the
    rest of this module follows."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_sim_log(text)


def _severity_sort_key(severity: str) -> int:
    try:
        return SEVERITY_ORDER.index(severity)
    except ValueError:
        return len(SEVERITY_ORDER)


def classify_signatures(signatures: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Classify each unique signature into a category + severity, sorted
    worst-severity-first, then most-frequent-first within the same severity.

    category enum: uvm_fatal / uvm_error / bare_error / assertion /
                    timeout / scoreboard_mismatch / other
    severity enum: CRITICAL / HIGH / MEDIUM / LOW / INFO (SEVERITY_ORDER
                    above) -- this module's own call, documented here per
                    the task's instruction, matching the severity *concept*
                    in per-job-simlog-analysis SKILL.md rather than reusing
                    an enum defined elsewhere (none exists in this repo yet).
    """
    results = []
    for sig, entry in signatures.items():
        # pick the highest-priority (most severe) category among all markers
        # that hit this signature. This priority order is deliberately
        # separate from _MARKER_PATTERNS' scan order (which is just the list
        # of things to detect, not a severity ranking) -- e.g. a line that
        # happens to contain both "UVM_WARNING" and "Error-" must classify
        # as bare_error, not fall through to the UVM_WARNING->"other" mapping.
        category = "other"
        for marker_name in _CATEGORY_PRIORITY:
            if marker_name in entry["markers"]:
                category = _MARKER_TO_CATEGORY.get(marker_name, "other")
                break
        severity = severity_for_category(category)
        results.append({
            "signature": sig,
            "category": category,
            "severity": severity,
            "count": entry["count"],
            "first_line_no": entry["first_line_no"],
            "last_line_no": entry["last_line_no"],
            "example_line": entry["example_line"],
            "markers": entry["markers"],
        })

    results.sort(key=lambda r: (_severity_sort_key(r["severity"]), -r["count"]))
    return results


# ---------------------------------------------------------------------------
# Epilogue: real documented format only (task-specified evidence) --
#   FINAL CHECK @ <time> ns
#   UVM_FATAL = N, UVM_ERROR = N, UVM_WARNING = N
#   VERDICT: PASSED|FAILED
# Must degrade gracefully (return None) when absent -- never assumed present.
# ---------------------------------------------------------------------------

_EPILOGUE_HEADER_RE = re.compile(r"FINAL CHECK\s*@\s*(\d+(?:\.\d+)?)\s*ns", re.IGNORECASE)
_EPILOGUE_COUNTS_RE = re.compile(
    r"UVM_FATAL\s*=\s*(\d+)\s*,\s*UVM_ERROR\s*=\s*(\d+)\s*,\s*UVM_WARNING\s*=\s*(\d+)",
    re.IGNORECASE,
)
_EPILOGUE_VERDICT_RE = re.compile(r"VERDICT\s*:\s*(PASSED|FAILED)", re.IGNORECASE)


def parse_epilogue(log_text: str) -> Optional[Dict[str, Any]]:
    """Extract the real documented "FINAL CHECK" epilogue block if present.

    Returns None (never a fabricated/defaulted dict) when the log has no
    such epilogue -- most real logs from other projects/stages won't have
    this exact format, and this must never be assumed.

    Returns, when found:
        {
          "final_check_time_ns": float,
          "uvm_fatal": int,
          "uvm_error": int,
          "uvm_warning": int,
          "verdict": "PASSED"|"FAILED",
        }
    Any field individually not found stays None inside the dict rather than
    causing the whole epilogue to be discarded, since real logs may emit
    these three lines with intervening unrelated output.
    """
    header_m = _EPILOGUE_HEADER_RE.search(log_text)
    counts_m = _EPILOGUE_COUNTS_RE.search(log_text)
    verdict_m = _EPILOGUE_VERDICT_RE.search(log_text)

    if not (header_m or counts_m or verdict_m):
        return None

    result: Dict[str, Any] = {
        "final_check_time_ns": float(header_m.group(1)) if header_m else None,
        "uvm_fatal": int(counts_m.group(1)) if counts_m else None,
        "uvm_error": int(counts_m.group(2)) if counts_m else None,
        "uvm_warning": int(counts_m.group(3)) if counts_m else None,
        "verdict": verdict_m.group(1).upper() if verdict_m else None,
    }
    return result


# ---------------------------------------------------------------------------
# Under-reporting detection: compare a JobState-shaped dict's self-reported
# flags against what parse_sim_log() actually found in the real log text.
# Field names below match lsf_per_job_monitor_gate.py's own vocabulary
# (uvm_error_detected/fatal_detected) exactly, plus lsf_client.JobState's
# uvm_error_count/uvm_fatal_count/assertion_failure -- this function accepts
# either naming (a JobState.asdict() dump uses the *_count/assertion_failure
# names; the monitor gate's own jobs.json uses *_detected names) so it can
# sit in front of either caller without forcing a schema migration.
# ---------------------------------------------------------------------------

def detect_underreporting(job_state: Dict[str, Any], parsed: Dict[str, Any]) -> List[str]:
    """Compare job_state's self-reported flags against parsed (this module's
    own parse_sim_log() output) and return a list of human-readable
    discrepancy strings. Empty list means no discrepancy detected.

    This is additive: it does not replace lsf_per_job_monitor_gate.py's
    existing substring check (see that file's `_has_marker`), it gives that
    gate (or any other caller) a second, evidence-based opinion to compare
    against -- CLAUDE.md's "LSF DONE is not equal to DV PASS" rule applied
    at the log-analysis layer, not just the job-status layer.
    """
    discrepancies: List[str] = []

    # Deliberately checked against raw markers, not the post-classification
    # category bucket: a UVM_ERROR-tagged line that also mentions
    # "scoreboard" classifies as the more-specific scoreboard_mismatch
    # category (see _CATEGORY_PRIORITY), but it is still a real UVM_ERROR
    # occurrence and must still count toward real_error_count here -- an
    # under-reporting check must not lose failures to a classification
    # bucket that exists purely to make the report more actionable.
    classified = classify_signatures(parsed.get("signatures", {}))
    real_fatal_count = sum(c["count"] for c in classified
                            if "UVM_FATAL" in c["markers"] or "FATAL" in c["markers"])
    real_error_count = sum(c["count"] for c in classified
                            if "UVM_ERROR" in c["markers"] or "BARE_ERROR" in c["markers"])
    real_assertion = any("ASSERTION" in c["markers"] for c in classified)

    # Support both naming conventions (see docstring above).
    declared_fatal = bool(job_state.get("fatal_detected", job_state.get("uvm_fatal_count", 0)))
    declared_error = bool(job_state.get("uvm_error_detected", job_state.get("uvm_error_count", 0)))
    declared_assertion = bool(job_state.get("assertion_failure", False))

    if real_fatal_count > 0 and not declared_fatal:
        discrepancies.append(
            f"UNDER_REPORTED_UVM_FATAL: log shows {real_fatal_count} UVM_FATAL/Fatal "
            f"occurrence(s) but job_state did not declare fatal_detected/uvm_fatal_count"
        )
    if real_error_count > 0 and not declared_error:
        discrepancies.append(
            f"UNDER_REPORTED_UVM_ERROR: log shows {real_error_count} UVM_ERROR/bare-error "
            f"occurrence(s) but job_state did not declare uvm_error_detected/uvm_error_count"
        )
    if real_assertion and not declared_assertion:
        discrepancies.append(
            "UNDER_REPORTED_ASSERTION: log shows an assertion-related failure "
            "but job_state.assertion_failure is falsy"
        )

    # Cross-check against the epilogue when present: an explicit VERDICT:
    # FAILED or nonzero UVM_FATAL/UVM_ERROR in the epilogue is authoritative
    # (it is the simulation's own final tally) and must not be silently
    # under-reported either, even if no individual line-level marker
    # happened to be miscategorized above.
    epilogue = parsed.get("epilogue")
    if epilogue:
        if epilogue.get("uvm_fatal") not in (None, 0) and not declared_fatal:
            discrepancies.append(
                f"UNDER_REPORTED_EPILOGUE_UVM_FATAL: epilogue reports "
                f"UVM_FATAL={epilogue.get('uvm_fatal')} but job_state did not declare fatal"
            )
        if epilogue.get("uvm_error") not in (None, 0) and not declared_error:
            discrepancies.append(
                f"UNDER_REPORTED_EPILOGUE_UVM_ERROR: epilogue reports "
                f"UVM_ERROR={epilogue.get('uvm_error')} but job_state did not declare error"
            )
        if epilogue.get("verdict") == "FAILED" and not (declared_fatal or declared_error):
            discrepancies.append(
                "UNDER_REPORTED_EPILOGUE_VERDICT: epilogue VERDICT=FAILED but job_state "
                "declared neither fatal nor error"
            )

    return discrepancies
