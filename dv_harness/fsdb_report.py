"""fsdb_report.py -- wraps the real Synopsys Verdi/VCS `fsdbreport`
command-line utility, which converts an FSDB waveform dump into an ASCII
text report. This is the project's actual "waveform/FSDB viewer" path per
CLAUDE.md's fsdbreport-based Execution Gate (PUSH -> BUILD -> VERIFY ->
WAVE=1 -> fsdbreport -> REVIEW -> SIGNOFF) and debug-agent.md's "Tool Usage
Verification Gate" (fsdbreport usage must be confirmed against `-h`/manual/
official docs before scripting, never guessed) -- see
.claude/skills/CORE/dv-workflow/SKILL.md's "Confirmed drift (2026-08-29)"
note, which records a real debug session running `fsdbreport -h` for
exactly this reason. FSDB itself is a proprietary binary format with no
open-source parser; fsdbreport (the real Synopsys CLI tool, run on the
Linux DV server where Verdi/VCS is installed) is the supported way to get
signal-level evidence out of it from a script, without needing a binary
FSDB parser in this harness.

What is confirmed vs. inferred about fsdbreport itself:
- CONFIRMED (general, from Synopsys-adjacent and EDA-community sources,
  WebSearch 2026-08-29): fsdbreport is a real Verdi/VCS command-line
  utility that generates an ASCII text report of signal value changes from
  an FSDB file, intended for batch/scripted use without opening the Verdi
  GUI. `-h`/`-help` prints its usage.
- CONFIRMED (real debug session, dv-workflow/SKILL.md's 2026-08-29
  "Confirmed drift" entry): a real session actually ran `fsdbreport -h`
  per the Tool Usage Verification Gate, then exercised the real
  invocation `fsdbreport f.fsdb -period <T> -level 1 -csv` -- so the
  `-period`, `-level` and `-csv` flags (in that order, file path before
  the flags) are confirmed real usage, and `-csv` confirms the output is
  CSV-shaped. That entry does NOT record the CSV's actual column header
  names/count, so parse_fsdbreport_output() below parses the CSV
  structurally (via the stdlib `csv` module, whatever headers a real run
  emits) rather than hardcoding an assumed set of column names.
- STILL NOT independently confirmed: any flag beyond -period/-level/-csv
  (candidates seen in secondary/community sources include things like -s
  for signal selection, -o for output file, -bt/-et for begin/end time,
  -exp/-strobe for conditional reporting, -f for a config file) and the
  exact CSV column names within the confirmed -csv output. This machine
  has no Verdi/fsdbreport install (Windows dev box; the real tool runs on
  the Linux DV server), so none of this could be exercised against a real
  .fsdb file here. Treat any flag/format claim beyond what's confirmed
  above as unverified until confirmed by an actual real run on the
  server, per the Tool Usage Verification Gate.

Every function here is best-effort and never raises for a real runtime
condition (binary missing, file missing, nonzero exit, timeout) -- same
convention as KnowledgeCenterClient in dv_harness/knowledge_center.py.
FsdbReportError is reserved for programmer-error inputs only.
"""

from __future__ import annotations
import csv
import io
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


class FsdbReportError(ValueError):
    """Raised only for programmer-error inputs (e.g. a missing required
    argument) -- never for a real runtime condition like the fsdbreport
    binary not being installed, which run_fsdbreport() reports as a normal
    {"ok": False, ...} result instead."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def run_fsdbreport(fsdb_path: str, fsdbreport_bin: str = "fsdbreport",
                    extra_args: Optional[List[str]] = None,
                    timeout: int = 60) -> Dict[str, Any]:
    """Invoke the real `fsdbreport` binary against fsdb_path. Never raises
    for a real runtime condition -- callers must check the returned dict's
    "ok" key, matching KnowledgeCenterClient's documented convention.

    Returns one of:
      {"ok": True, "report_text": <stdout>, "stderr": <stderr>}
      {"ok": False, "error": "FSDB_FILE_NOT_FOUND"}
      {"ok": False, "error": "FSDBREPORT_BINARY_NOT_FOUND", "detail": str}
      {"ok": False, "error": "FSDBREPORT_NONZERO_EXIT", "returncode": int, "stderr": str}
      {"ok": False, "error": "FSDBREPORT_TIMEOUT"}
    """
    if not fsdb_path:
        raise FsdbReportError("MISSING_FSDB_PATH", "fsdb_path is required")

    fsdb_file = Path(fsdb_path)
    if not fsdb_file.is_file():
        return {"ok": False, "error": "FSDB_FILE_NOT_FOUND"}

    # File path before flags -- matches the confirmed-real invocation shape
    # (`fsdbreport f.fsdb -period <T> -level 1 -csv`, dv-workflow/SKILL.md's
    # 2026-08-29 confirmed-drift entry), not the previously-guessed
    # flags-before-file order this had before that invocation was confirmed.
    cmd = [fsdbreport_bin, str(fsdb_file), *(extra_args or [])]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        return {"ok": False, "error": "FSDBREPORT_BINARY_NOT_FOUND", "detail": str(e)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "FSDBREPORT_TIMEOUT"}

    if proc.returncode != 0:
        return {"ok": False, "error": "FSDBREPORT_NONZERO_EXIT",
                 "returncode": proc.returncode, "stderr": proc.stderr or ""}

    return {"ok": True, "report_text": proc.stdout or "", "stderr": proc.stderr or ""}


def _unparsed(report_text: str, reason: str) -> Dict[str, Any]:
    """The shared honest-degradation shape: same as this function returned
    before real CSV parsing existed (raw_text/parsed=False/note), now also
    naming the specific structural reason it didn't look like real
    `fsdbreport ... -csv` output, without ever raising."""
    return {
        "raw_text": report_text,
        "parsed": False,
        "note": "output format not verified against a real fsdbreport run -- "
                f"treat report_text as opaque until confirmed against real output ({reason})",
    }


def parse_fsdbreport_output(report_text: str) -> Dict[str, Any]:
    """Extract structure from fsdbreport's real `-csv` output.

    The confirmed-real invocation (dv-workflow/SKILL.md's 2026-08-29
    "Confirmed drift" entry) is `fsdbreport f.fsdb -period <T> -level 1
    -csv`, which confirms the output is CSV. What that entry does NOT
    record is the CSV's actual column header names/count -- so rather than
    hardcode an assumed schema (e.g. guessing specific column names) that
    might not match a real run, this parses the CSV structurally with the
    stdlib `csv` module: whatever header row a real run actually emits
    becomes each record's field names verbatim. A real run on the Linux DV
    server producing e.g. `signal,timestamp,value` header rows yields
    records shaped exactly like that; a run with different real column
    names yields records shaped like those instead -- either way this
    parses it for real, without inventing names beyond what the input
    itself declares.

    Returns one of:
      {"parsed": True, "fieldnames": [...], "records": [{...}, ...]}
        when report_text looks like real CSV: at least one header line
        followed by at least one data line, all with the same, >1 column
        count.
      {"raw_text": ..., "parsed": False, "note": ...} -- the same honest
        pass-through shape this function has always returned -- for
        anything that doesn't look like that (empty input, a single line,
        inconsistent column counts, or a genuine `csv` parse error).
        Never raises on malformed input.
    """
    if not report_text or not report_text.strip():
        return _unparsed(report_text, "empty report_text")

    try:
        rows = [row for row in csv.reader(io.StringIO(report_text)) if row]
    except csv.Error as e:
        return _unparsed(report_text, f"csv parse error: {e}")

    if len(rows) < 2:
        return _unparsed(report_text, "fewer than 2 non-blank lines -- need a header row plus >=1 data row")

    header, data_rows = rows[0], rows[1:]
    if len(header) < 2:
        return _unparsed(report_text, "header row has fewer than 2 columns")
    if any(len(r) != len(header) for r in data_rows):
        return _unparsed(report_text, "inconsistent column count across rows")

    return {
        "parsed": True,
        "fieldnames": header,
        "records": [dict(zip(header, r)) for r in data_rows],
    }
