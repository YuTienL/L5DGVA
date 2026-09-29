#!/usr/bin/env python3
"""urg_summary_reduce.py -- reduces a Synopsys VCS `urg` coverage report
directory into the plain JSON shape dv_harness.coverage_analysis.
parse_coverage_summary() consumes:
    {"categories": [{"name", "percent", "bins_total", "bins_hit"}, ...]}

STATUS: SKELETON ONLY -- see the NotImplementedError in parse_urg_report()
below, and .work/coverage-generator-design-report.md's Part 2 / "Open
questions" section (blocking items #1-#2). This is a DELIBERATE stop, not
an oversight: this repo has no real `urg` report sample (no dashboard.txt/
dashboard.html/any text or HTML urg output exists anywhere in this repo to
derive a column layout / DOM structure from) and no confirmation of which
VCS/urg version the real Linux DV server actually has installed -- urg's
report layout is version-dependent, so a schema derived without that
evidence could easily be wrong for whatever version is actually deployed.
Guessing it anyway would be exactly the kind of fabricated-evidence mistake
CLAUDE.md's Evidence Truth Rule and "No Golden-Reference Content Mining"
sections exist to prevent. Everything ELSE in this script (CLI parsing,
self-validation against the real downstream reader, atomic write, the
fixed metric-name constants the project's own Makefile already commits to)
is real, working code -- only the actual report-parsing step is blocked.

Real, already-committed context for the constants below (see
dv_harness/uvm_generator/templates/sim_scripts/Makefile, real lines cited
in the coverage-generator design report's "Real existing patterns to
reuse" section):
  CM_OPTS  := line+cond+fsm+tgl+branch   (Makefile line 1364 -- the 5
    code-coverage metrics VCS's own -cm option is fixed to for this
    project)
  urg -dir $(CM_DIR) $(COV_VDBS) -format both -show tests \
      -report $(COVDIR)/urgReport                  (Makefile lines 3553-3554)
  FCOV=1 gates VIP-covergroup functional coverage   (Makefile lines 1407-1431)

Usage:
  python tools/coverage/urg_summary_reduce.py \
      --urg-report <SIM_ROOT_PATH>/coverage/urgReport \
      --out .dv-harness/coverage/summary.json

Mirrors tools/analyze_coverage.py's own standalone-script convention (not a
dv-harness CLI subcommand) and reuses its own "call
parse_coverage_summary() as this script's own validation step" pattern --
this script must never write a summary.json its real downstream readers
(dashboard.py's GET /api/coverage, tools/analyze_coverage.py) would reject.

Real, already-committed transport for pulling a Linux-produced summary.json
back to the PC-side .dv-harness/coverage/ tree (once this script's parsing
step is real -- future work, not this pass, per the design report's own
scope boundary): tools/remote/remote_exec.py's --get flag, e.g.
  python tools/remote/remote_exec.py --get <remote_summary.json> \
      .dv-harness/coverage/summary.json
(real evidence: tools/remote/remote_exec.py lines 77-78/100-103's --put/--get
file-transfer ops over the persistent relay). No new transport code is
needed here -- this script only ever reads/writes LOCAL paths; getting a
report directory off the real Linux DV server first is the caller's own
job, exactly like analyze_coverage.py already assumes for its own
--summary input.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dv_harness.coverage_analysis import parse_coverage_summary, CoverageAnalysisError  # noqa: E402
from dv_harness.storage import _atomic_replace  # noqa: E402

# The 5 real code-coverage metrics VCS's own -cm option is fixed to for this
# project (Makefile CM_OPTS, see this module's own docstring) -- declared as
# CONSTANTS this script exposes, NOT yet populated from a real parse (see
# parse_urg_report()'s NotImplementedError below).
CODE_COVERAGE_METRICS = ("line", "cond", "fsm", "tgl", "branch")

# One additional category placeholder for VIP-covergroup functional
# coverage (gated by the real Makefile's FCOV=1, see this module's own
# docstring) -- also not yet populated from a real parse.
FUNCTIONAL_COVERAGE_CATEGORY = "functional"

ALL_CATEGORY_NAMES = CODE_COVERAGE_METRICS + (FUNCTIONAL_COVERAGE_CATEGORY,)


def parse_urg_report(urg_report_dir: pathlib.Path) -> list:
    """Reduces a real `urg -report <dir>` output directory into the
    "categories" list parse_coverage_summary() validates: one
    {"name": <one of ALL_CATEGORY_NAMES>, "percent": float,
    "bins_total": int, "bins_hit": int} dict per metric.

    BLOCKED -- see this module's own top-of-file docstring and
    .work/coverage-generator-design-report.md's "Open questions" #1-#2:
    this repo has no real urg report sample and no confirmation of which
    VCS/urg version the real Linux DV server has installed, and urg's
    report layout (text dashboard.txt column positions, or dashboard.html
    DOM structure) is version-dependent. Implementing the actual
    per-category percent/bins_total/bins_hit extraction here without that
    evidence would be exactly the fabricated-evidence mistake this
    project's Evidence Truth Rule / "No Golden-Reference Content Mining"
    discipline (CLAUDE.md) exists to prevent -- so this stops here,
    deliberately, rather than guessing a plausible-looking column layout.

    When that evidence becomes available (a real urg report sample AND a
    confirmed VCS/urg version from the real Linux DV server), this
    function is where the real extraction goes -- returning exactly the
    list shape build_summary() below already expects and self-validates
    via parse_coverage_summary()."""
    raise NotImplementedError(
        "BLOCKED: no real urg report sample or version-pinned schema "
        "available in this repo -- see "
        ".work/coverage-generator-design-report.md Open Questions 1-2 "
        "(urg_report_dir=%r)" % (str(urg_report_dir),)
    )


def build_summary(urg_report_dir: pathlib.Path) -> dict:
    """Builds the full summary dict and self-validates it against
    dv_harness.coverage_analysis.parse_coverage_summary() BEFORE returning
    it to the caller -- never hands write_summary_atomic() a shape its own
    downstream reader would reject. Propagates whatever parse_urg_report()
    raises (today: NotImplementedError -- see above) or
    CoverageAnalysisError if a future real parse ever produced a malformed
    shape."""
    categories = parse_urg_report(urg_report_dir)
    return parse_coverage_summary({"categories": categories})


def write_summary_atomic(summary: dict, out_path: pathlib.Path) -> None:
    """Writes `summary` to out_path atomically, via the same
    storage._atomic_replace primitive dv_harness.coverage_analysis.
    append_history_sample() already uses for the sibling history file --
    reused here rather than reimplemented, per this project's own
    reuse-existing-primitives convention. Creates out_path's parent
    directory if it does not exist yet."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="summary.", suffix=".json", dir=str(out_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Reduce a Synopsys VCS urg coverage report directory into "
                     "the plain JSON summary dv_harness.coverage_analysis consumes. "
                     "SKELETON ONLY -- see this script's own module docstring: the "
                     "actual urg report parse is not implemented (blocked on real "
                     "evidence, not guessed).",
    )
    ap.add_argument("--urg-report", required=True, dest="urg_report",
                     help="path to a real `urg -report <dir>` output directory "
                          "(e.g. $(COVDIR)/urgReport, per the real Makefile's own "
                          "`cov` target)")
    ap.add_argument("--out", required=True,
                     help="path to write the reduced summary.json to "
                          "(e.g. .dv-harness/coverage/summary.json)")
    args = ap.parse_args(argv)

    urg_report_dir = pathlib.Path(args.urg_report)
    out_path = pathlib.Path(args.out)

    try:
        summary = build_summary(urg_report_dir)
    except NotImplementedError as e:
        print(json.dumps({"error": "NOT_IMPLEMENTED", "detail": str(e)}))
        return 2
    except CoverageAnalysisError as e:
        print(json.dumps({"error": e.reason, "detail": e.detail}))
        return 1

    write_summary_atomic(summary, out_path)
    print(json.dumps({"wrote": str(out_path), "categories": len(summary["categories"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
