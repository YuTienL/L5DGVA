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

What is confirmed about fsdbreport's real I/O model and flag grammar:
- CONFIRMED (2026-09-01, distilled from a real sibling project's own
  committed report scripts -- see the "reverse-distillation" rule in
  IP_UVM_DV_Gen.md/ip-uvm-dv-gen/SKILL.md; this fact is about fsdbreport
  itself, not specific to that project or to any one target IP):
  **fsdbreport ALWAYS writes its report to a FILE, never to stdout.** An
  explicit `-o <path>` names that file; if `-o` is omitted, fsdbreport
  silently writes a default `report.txt` into the current working
  directory instead. Every real invocation observed either passes `-o`
  explicitly or immediately reads a fixed default-named file afterward --
  none of them treat the process's own stdout as the report. Code that
  reads `proc.stdout` for the report content will see an empty string on
  every real run; `run_fsdbreport()` below always supplies an explicit
  `-o <tmp_path>` and reads the report back from that file for exactly
  this reason (this was a real functional bug in an earlier version of
  this module, found during that 2026-09-01 distillation pass -- fixed
  here, not merely documented).
- CONFIRMED (2026-09-01, same distillation): the real flag grammar is
  `fsdbreport <fsdb> -bt <t0> -et <t1> -s <hier_path> [<hier_path2> ...]
  [-verilog | -csv | -of h] -o <outfile>`. `-bt`/`-et` bound the report to
  a time window (a full-run window is normal for a sparse, asynchronous
  signal such as an interrupt/event line; a narrow microsecond window is
  normal when the question is about one specific transaction or edge).
  `-s` accepts either one hierarchical path or several space-separated
  quoted hierarchical paths in a single call (batching multiple signals
  into one report). Exactly one format flag selects the output shape:
  `-verilog` for plain per-signal text, `-csv` for CSV, `-of h` for a
  hex-formatted combined multi-signal file; omitting all three yields the
  tool's own plain default format. Flag order is not fixed (`-s` has been
  seen both before and after `-bt`/`-et` in real invocations) but the file
  path always comes first, before any flag.
- CONFIRMED (real debug session, dv-workflow/SKILL.md's 2026-08-29
  "Confirmed drift" entry, retained as a secondary confirmed variant, not
  the primary assumption): `fsdbreport f.fsdb -period <T> -level 1 -csv`
  is also real, confirmed usage -- `-period`/`-level` are a different,
  also-real way to bound/scope a report from `-bt`/`-et`/`-s`. That entry
  does NOT record the CSV's actual column header names/count, so
  `parse_fsdbreport_output()` below parses the CSV structurally (via the
  stdlib `csv` module, whatever headers a real run emits) rather than
  hardcoding an assumed set of column names.
- STILL NOT independently confirmed: `-exp`/`-strobe` (conditional
  reporting) and `-f` (a config file), both seen only in secondary/
  community sources. This machine has no Verdi/fsdbreport install
  (Windows dev box; the real tool runs on the Linux DV server), so none
  of this could be exercised against a real .fsdb file here. Treat any
  flag/format claim beyond what's confirmed above as unverified until
  confirmed by an actual real run on the server, per the Tool Usage
  Verification Gate.

Every function here is best-effort and never raises for a real runtime
condition (binary missing, file missing, nonzero exit, timeout) -- same
convention as KnowledgeCenterClient in dv_harness/knowledge_center.py.
FsdbReportError is reserved for programmer-error inputs only.
"""

from __future__ import annotations
import csv
import io
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


class FsdbReportError(ValueError):
    """Raised only for programmer-error inputs (e.g. a missing required
    argument) -- never for a real runtime condition like the fsdbreport
    binary not being installed, which run_fsdbreport() reports as a normal
    {"ok": False, ...} result instead."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def build_fsdbreport_cmd(fsdb: str, bt: Optional[str] = None, et: Optional[str] = None,
                          signals: Optional[Sequence[str]] = None,
                          out_path: Optional[str] = None,
                          fmt: str = "verilog") -> List[str]:
    """Build a real fsdbreport argv (everything after the binary name) from
    the confirmed flag grammar documented in this module's docstring:
    `<fsdb> -bt <t0> -et <t1> -s <sig1> [<sig2> ...] [-verilog|-csv|-of h]
    -o <out_path>`. `signals` accepts one or many hierarchical paths --
    real usage batches several signals into a single call via repeated
    `-s` arguments. `fmt` selects the output-format flag: "verilog" (the
    common plain per-signal text default used by this helper), "csv",
    "hex" (`-of h`), or None to omit a format flag entirely and take
    fsdbreport's own default. Does not invoke anything -- callers pass the
    result as `extra_args` to run_fsdbreport()."""
    if not fsdb:
        raise FsdbReportError("MISSING_FSDB_PATH", "fsdb is required")
    args: List[str] = []
    if bt is not None:
        args += ["-bt", str(bt)]
    if et is not None:
        args += ["-et", str(et)]
    for sig in (signals or []):
        args += ["-s", str(sig)]
    if fmt == "verilog":
        args.append("-verilog")
    elif fmt == "csv":
        args.append("-csv")
    elif fmt == "hex":
        args += ["-of", "h"]
    elif fmt is not None:
        raise FsdbReportError("UNKNOWN_FSDBREPORT_FORMAT", str(fmt))
    if out_path is not None:
        args += ["-o", str(out_path)]
    return args


def run_fsdbreport(fsdb_path: str, fsdbreport_bin: str = "fsdbreport",
                    extra_args: Optional[List[str]] = None,
                    timeout: int = 60) -> Dict[str, Any]:
    """Invoke the real `fsdbreport` binary against fsdb_path. Never raises
    for a real runtime condition -- callers must check the returned dict's
    "ok" key, matching KnowledgeCenterClient's documented convention.

    fsdbreport always writes its report to a FILE, never stdout (see
    module docstring). If `extra_args` does not already contain an `-o
    <path>` pair, this function synthesizes a temp file, appends `-o
    <tmp_path>` itself, reads the report back from that file after the
    subprocess exits, and deletes the temp file. If the caller already
    supplied `-o <path>` in `extra_args`, that path is used as-is for the
    read-back and is left in place (the caller owns it).

    Returns one of:
      {"ok": True, "report_text": <file contents>, "stderr": <stderr>}
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

    args = list(extra_args or [])
    caller_supplied_o = "-o" in args
    if caller_supplied_o:
        out_path = Path(args[args.index("-o") + 1])
        tmp_fd = None
    else:
        tmp_fd, tmp_name = tempfile.mkstemp(suffix=".fsdbreport.txt")
        os.close(tmp_fd)
        out_path = Path(tmp_name)
        args = args + ["-o", str(out_path)]

    # File path before flags -- matches every confirmed-real invocation
    # shape (both the `-bt/-et/-s/.../-o` grammar and the secondary
    # `-period/-level/-csv` variant), not the previously-guessed
    # flags-before-file order this had before either was confirmed.
    cmd = [fsdbreport_bin, str(fsdb_file), *args]
    try:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as e:
            return {"ok": False, "error": "FSDBREPORT_BINARY_NOT_FOUND", "detail": str(e)}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "FSDBREPORT_TIMEOUT"}

        if proc.returncode != 0:
            return {"ok": False, "error": "FSDBREPORT_NONZERO_EXIT",
                     "returncode": proc.returncode, "stderr": proc.stderr or ""}

        if out_path.is_file():
            report_text = out_path.read_text(encoding="utf-8", errors="replace")
        else:
            # A real run that exits 0 but writes nothing (e.g. an empty
            # time window with no matching signal changes) is honest empty
            # evidence, not a failure -- never fabricate report_text here.
            report_text = ""
        return {"ok": True, "report_text": report_text, "stderr": proc.stderr or ""}
    finally:
        if not caller_supplied_o:
            try:
                out_path.unlink()
            except OSError:
                pass


def write_topic_report(fsdb_path: str, topic: str, out_dir: str,
                        bt: Optional[str] = None, et: Optional[str] = None,
                        signals: Optional[Sequence[str]] = None,
                        fmt: str = "verilog",
                        fsdbreport_bin: str = "fsdbreport",
                        timeout: int = 60) -> Dict[str, Any]:
    """Headless, purpose-named topic report -- the non-GUI complement to an
    interactive Verdi signal-setup TCL. Distilled 2026-09-01 from a real
    sibling project's convention of a small `<topic>_report.sh` per
    diagnostic question (e.g. a bus-handshake-timing question, a
    line-state/analog question, an interrupt/event question), each
    hardcoding a time window sized to that question -- narrow for a
    specific transaction/edge, full-run for a sparse asynchronous signal --
    and finishing with a non-empty sanity check. Writes
    `<out_dir>/<topic>.txt` via build_fsdbreport_cmd() + run_fsdbreport(),
    and returns run_fsdbreport()'s own result dict plus the written path
    under "out_file" on success. Never raises for a real runtime
    condition, matching this module's other functions.
    """
    if not topic:
        raise FsdbReportError("MISSING_TOPIC", "topic is required")
    out_path = Path(out_dir) / f"{topic}.txt"
    args = build_fsdbreport_cmd(fsdb_path, bt=bt, et=et, signals=signals,
                                 out_path=str(out_path), fmt=fmt)
    result = run_fsdbreport(fsdb_path, fsdbreport_bin=fsdbreport_bin,
                             extra_args=args, timeout=timeout)
    if result.get("ok"):
        result["out_file"] = str(out_path)
    return result


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


# ---------------------------------------------------------------------------
# fsdbreport -> vip_distill -> evidence_db bridge (2026-09-04)
# ---------------------------------------------------------------------------
#
# THE GAP THIS CLOSES. `vip_distill.distill_fsdbreport()` was real,
# unit-tested code with ZERO live call sites anywhere in this repo -- a
# repo-wide grep for it hit only its own definition, docstrings, and test
# bodies. The one real production producer of fsdbreport output, the CLI's
# `fsdb-report` command, ran the real `fsdbreport` binary through
# `run_fsdbreport()` + `parse_fsdbreport_output()` and then only printed or
# file-dumped the raw JSON: FSDB evidence never reached the Distillation
# layer, and never reached DuckDB. The architecture diagram draws
# `FSDB -> Distillation -> vip_distill.py -> DuckDB`; that edge did not
# exist in code. This function is that edge.
#
# It lives HERE, in the module that owns the real fsdbreport producer,
# rather than inside vip_distill.py -- vip_distill's own AST-enforced test
# (test_vip_distill.py::test_module_does_not_import_orchestration_or_memory_
# modules) permanently forbids it importing `evidence_db`, so the store-side
# half of the bridge can never live there. Same placement rule the two
# already-wired bridges follow: regression_reporter._write_normalized_
# evidence_if_configured() (sim.log) and dashboard._ingest_coverage_summary_
# to_evidence_db() (coverage) each sit in the module owning their producer,
# not in the producer library and not in the store.
#
# vip_distill and evidence_db are imported INSIDE the function, not at
# module scope: vip_distill imports THIS module at its own module scope
# (`fsdb_report_mod`), so a top-level import back would be a hard circular
# import at load time.

def ingest_report_to_evidence_db(root, *, fsdb_path: str,
                                  report_text: Optional[str] = None,
                                  parsed_report: Optional[Dict[str, Any]] = None,
                                  topic: Optional[str] = None,
                                  job_id: Optional[int] = None,
                                  pattern: Optional[str] = None) -> Optional[str]:
    """Normalize one real fsdbreport extract through
    `vip_distill.distill_fsdbreport()` and land it as a `normalized_evidence`
    row in this project's DuckDB evidence store. Returns the written
    `evidence_id`, or None when nothing was written.

    Exactly one of `report_text`/`parsed_report` is passed straight through
    to `distill_fsdbreport()`, which enforces that contract itself -- this
    function never re-shapes or second-guesses the envelope vip_distill
    returns, it only stores it (the identical discipline
    regression_reporter's sim.log bridge documents).

    Best-effort, same as every other evidence-store write in this project:
    a duckdb-not-installed / locked-file / disabled-store condition returns
    None and prints, and must never break the real `fsdb-report` run whose
    report the caller already has in hand. Returns None (writing nothing)
    when the evidence store is disabled via config's `evidence_db.enabled`.
    """
    try:
        from . import config as _config
        if not _config.load_config(Path(root)).get("evidence_db", {}).get("enabled", True):
            return None
        from . import evidence_db as _evidence_db
        from . import vip_distill as _vip_distill
        envelope = _vip_distill.distill_fsdbreport(
            report_text=report_text, parsed_report=parsed_report,
            fsdb_path=fsdb_path, topic=topic, job_id=job_id, pattern=pattern)
        with _evidence_db.EvidenceStore(_evidence_db.default_db_path(Path(root))) as store:
            store.insert_normalized_evidence(envelope)
        return envelope.get("evidence_id")
    except Exception as e:
        print(f"[fsdb-report] normalized evidence store write failed: {e}", flush=True)
        return None
