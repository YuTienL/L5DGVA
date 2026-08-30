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

What is confirmed vs. inferred about fsdbreport itself (WebSearch, 2026-08-29):
- CONFIRMED (general, from Synopsys-adjacent and EDA-community sources):
  fsdbreport is a real Verdi/VCS command-line utility that generates an
  ASCII text report of signal value changes from an FSDB file, intended for
  batch/scripted use without opening the Verdi GUI. `-h`/`-help` prints its
  usage. This matches this project's own debug-agent.md/dv-workflow SKILL.md
  guidance to run `fsdbreport -h` before scripting against it.
- NOT independently confirmed against an official Synopsys command
  reference or a real fsdbreport run in this session: the exact flag names
  (candidates seen in secondary/community sources include things like -s
  for signal selection, -o for output file, -bt/-et for begin/end time,
  -level for scope depth, -exp/-strobe for conditional reporting, -f for a
  config file) or the precise text layout of its output. This machine has
  no Verdi/fsdbreport install (Windows dev box; the real tool runs on the
  Linux DV server), so none of this could be exercised against a real
  .fsdb file here. Treat any specific flag/format claim beyond "it's a real
  text-report CLI tool" as unverified until confirmed by an actual
  `fsdbreport -h` / real run output on the server, per the Tool Usage
  Verification Gate.

Every function here is best-effort and never raises for a real runtime
condition (binary missing, file missing, nonzero exit, timeout) -- same
convention as KnowledgeCenterClient in dv_harness/knowledge_center.py.
FsdbReportError is reserved for programmer-error inputs only.
"""

from __future__ import annotations
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

    cmd = [fsdbreport_bin, *(extra_args or []), str(fsdb_file)]
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


def parse_fsdbreport_output(report_text: str) -> Dict[str, Any]:
    """Extract structure from fsdbreport's text report.

    This project has NOT independently confirmed fsdbreport's real output
    format against an official command reference or a real run (see module
    docstring) -- so rather than invent a structured schema that might not
    match reality, this is a conservative pass-through. Once a real
    fsdbreport run's output has been inspected on the Linux DV server
    (e.g. via the Tool Usage Verification Gate's `fsdbreport -h` +
    real-run step), this should be replaced with real parsing logic and
    this docstring updated accordingly.
    """
    return {
        "raw_text": report_text,
        "parsed": False,
        "note": "output format not verified against a real fsdbreport run -- "
                "treat report_text as opaque until confirmed against real output",
    }
