"""dv_harness/mutation_testing.py -- mutation testing for THIS repo's own
Python test suite (2026-09-06).

SCOPE, STATED UP FRONT SO IT IS NEVER MISREAD. This is
testing-infrastructure-on-this-repo's-own-Python-code. It injects small,
AST-level faults into a `dv_harness/*.py` MODULE and re-runs that module's
real existing `dv_harness_tests/test_*.py` file to measure whether those
tests actually detect the fault. It is NOT DUT/RTL-level fault injection
(stuck-at / bit-flip / gate-level fault campaigns against a design under
test): that needs a real RTL target and a simulator this repository does
not contain, and nothing here should ever be cited as evidence about a
DUT. The subject is the harness's own test suite; the verdict is about
that test suite's sensitivity and nothing else.

GAP THIS CLOSES. Every gate in this repo is guarded by tests, and the
whole Evidence Truth Rule rests on those tests failing when the thing they
guard breaks. Until now nothing measured that. `self_audit.py` checks
meta-consistency of the repo's registries; `change_blast_radius.py` scores
how far a change reaches; coverage (if it were collected) would only say a
line EXECUTED during a test, which is not the same claim as "a test would
have FAILED had that line been wrong". A test that imports a module and
asserts nothing about its boundaries gets full line coverage and kills
zero mutants. Mutation score is the measurement that separates those two.

HOW A MUTANT IS RUN, AND WHY THE REPO IS NEVER TOUCHED. The usual
mutation-testing implementation (mutmut, cosmic-ray) overwrites the source
file on disk and restores it in a `finally`. That is unacceptable here: a
crash or a Ctrl-C mid-run would leave a deliberately-broken
`dv_harness/*.py` in a working tree whose main/master pushes are governed
by real gates. Instead every mutant is executed in a SUBPROCESS carrying a
`sys.meta_path` finder that serves the mutated source for exactly one
module name, from a temp file, before pytest is imported. The real file is
opened read-only and never written. Anything else importing that module in
the subprocess -- including the tests -- transparently gets the mutant,
which is exactly the semantics wanted.

The subprocess runs real `pytest` against the real test file, so
`dv_harness_tests/conftest.py` loads normally and its existing session-wide
`ENV_TRANSPORT_OVERRIDE = "off"` pin applies to every mutant run. That pin
is REUSED, not re-implemented here: it is already this suite's single
answer to "a test must never issue a live license/scheduler round trip",
and a second copy of it in this module would be exactly the parallel
mechanism CLAUDE.md's Methodology Consolidation Rule forbids. Combined
with `assert_safe_target()` refusing any test path outside
`dv_harness_tests/`, no mutant run can reach a real build, regression or
LSF submission.

BASELINE FIRST, ALWAYS. Killed/survived counts are meaningless if the
unmutated tests do not pass, so the run starts with a baseline execution
through the SAME import hook, serving the UNMUTATED source. That proves
both that the tests are green and that the hook itself is transparent. If
the baseline fails, the report is `BASELINE_FAILED` and no mutant is run
-- never a fabricated score.

SURVIVED IS A FINDING, NOT NECESSARILY A BUG. Some survivors are
EQUIVALENT MUTANTS -- a mutation that cannot change observable behavior
(`x + 0`, an index into a value that is always in range). Standard
mutation testing has no decision procedure for these; they are reviewed by
a human. This module reports survivors with their exact operator and line
so they can be judged, and never claims a survivor proves a missing test.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


# --- the mutation operators ----------------------------------------------
#
# Deliberately a SMALL, standard set. Each one is a single-token change
# whose surviving is a specific, nameable weakness in the tests.

COMPARISON_SWAP = "COMPARISON_SWAP"      # a boundary the tests never probe
BOUNDARY_SHIFT = "BOUNDARY_SHIFT"        # classic off-by-one on a constant
BOOL_OP_SWAP = "BOOL_OP_SWAP"            # and/or, i.e. an unprobed branch pair
BOOL_CONST_FLIP = "BOOL_CONST_FLIP"      # a True/False literal nothing asserts

MUTATION_OPERATORS: Tuple[str, ...] = (
    COMPARISON_SWAP, BOUNDARY_SHIFT, BOOL_OP_SWAP, BOOL_CONST_FLIP,
)

# `<` -> `<=` (and back) rather than `<` -> `>`: shifting the boundary by one
# element is the mutation a weak test misses, while inverting the comparison
# usually breaks so loudly that any test kills it and the mutant teaches
# nothing.
_COMPARE_SWAP = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt,
    ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}
_BOOLOP_SWAP = {ast.And: ast.Or, ast.Or: ast.And}


class MutantOutcome(str, Enum):
    """Per-mutant result.

    KILLED   -- the real test file failed while the mutant was installed.
    SURVIVED -- the tests all passed with a deliberately broken module.
    TIMEOUT  -- the mutant made the tests hang. Counted in its OWN bucket and
                deliberately NOT folded into KILLED: a hang is not the tests
                detecting the fault, and calling it a kill inflates the score.
    NOT_RUN  -- generated but skipped (a `max_mutants` cap, or a failed
                baseline).
    """
    KILLED = "KILLED"
    SURVIVED = "SURVIVED"
    TIMEOUT = "TIMEOUT"
    NOT_RUN = "NOT_RUN"


BASELINE_OK = "BASELINE_OK"
BASELINE_FAILED = "BASELINE_FAILED"


@dataclass
class Mutant:
    mutant_id: str
    operator: str
    lineno: int
    col_offset: int
    original: str
    mutated: str
    # The full mutated module source. Kept off `to_dict()` and off `repr`:
    # a report carrying N copies of a whole module is unreadable and, in the
    # CLI's JSON output, actively harmful.
    source: str = field(default="", repr=False)
    outcome: str = MutantOutcome.NOT_RUN.value
    returncode: Optional[int] = None
    detail: str = ""

    def describe(self) -> str:
        return f"{self.operator} at line {self.lineno}: {self.original} -> {self.mutated}"

    def to_dict(self) -> dict:
        return {
            "mutant_id": self.mutant_id,
            "operator": self.operator,
            "lineno": self.lineno,
            "col_offset": self.col_offset,
            "original": self.original,
            "mutated": self.mutated,
            "outcome": self.outcome,
            "returncode": self.returncode,
            "detail": self.detail,
        }


# --- mutant generation ----------------------------------------------------


def _candidate_sites(tree: ast.AST, operators: Sequence[str]) -> List[tuple]:
    """Every mutable site in `tree`, as (operator, node, slot, payload).

    `slot` is the index into `Compare.ops` for a comparison and None
    otherwise; `payload` is whatever `_apply` needs to install the mutation.
    """
    wanted = set(operators)
    # `-1` is `UnaryOp(USub, Constant(1))`, so the mutable Constant reads as
    # `1` while the source says `-1`. Collect those operands so the report
    # can label the mutation the way the file spells it ("-1 -> -2") instead
    # of the way the AST stores it ("1 -> 2").
    negated = {id(n.operand) for n in ast.walk(tree)
               if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub)
               and isinstance(n.operand, ast.Constant)}
    sites: List[tuple] = []
    for node in ast.walk(tree):
        if COMPARISON_SWAP in wanted and isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                repl = _COMPARE_SWAP.get(type(op))
                if repl is not None:
                    sites.append((COMPARISON_SWAP, node, i, repl))
        elif BOOL_OP_SWAP in wanted and isinstance(node, ast.BoolOp):
            repl = _BOOLOP_SWAP.get(type(node.op))
            if repl is not None:
                sites.append((BOOL_OP_SWAP, node, None, repl))
        elif isinstance(node, ast.Constant):
            # `bool` is a subclass of `int`, so the True/False test must come
            # first or every boolean literal would be "off-by-one"d into 2.
            if node.value is True or node.value is False:
                if BOOL_CONST_FLIP in wanted:
                    sites.append((BOOL_CONST_FLIP, node, None, not node.value))
            elif isinstance(node.value, int) and BOUNDARY_SHIFT in wanted:
                sites.append((BOUNDARY_SHIFT, node,
                              "NEGATED" if id(node) in negated else None,
                              node.value + 1))
    # `ast.walk` is breadth-first, so sort into source order to make mutant
    # ids stable across runs and reviewable against the file.
    sites.sort(key=lambda s: (getattr(s[1], "lineno", 0),
                              getattr(s[1], "col_offset", 0),
                              s[0], str(s[2])))
    return sites


def _apply(site: tuple):
    """Install the mutation, returning the value needed to undo it."""
    operator, node, slot, payload = site
    if operator == COMPARISON_SWAP:
        previous = node.ops[slot]
        node.ops[slot] = payload()
        return previous
    if operator == BOOL_OP_SWAP:
        previous = node.op
        node.op = payload()
        return previous
    previous = node.value
    node.value = payload
    return previous


def _undo(site: tuple, previous) -> None:
    operator, node, slot, _payload = site
    if operator == COMPARISON_SWAP:
        node.ops[slot] = previous
    elif operator == BOOL_OP_SWAP:
        node.op = previous
    else:
        node.value = previous


def _render(site: tuple, value) -> str:
    """A short human label for one side of the mutation."""
    operator = site[0]
    if operator in (COMPARISON_SWAP, BOOL_OP_SWAP):
        # `previous` arrives as an op INSTANCE, the replacement as its CLASS.
        return value.__name__ if isinstance(value, type) else type(value).__name__
    if operator == BOUNDARY_SHIFT and site[2] == "NEGATED":
        return repr(-value)
    return repr(value)


def generate_mutants(source: str, filename: str = "<module>", *,
                     operators: Sequence[str] = MUTATION_OPERATORS,
                     line_range: Optional[Tuple[int, int]] = None) -> List[Mutant]:
    """Every mutant of `source`, in source order.

    Each mutant carries the COMPLETE mutated module source, produced by
    `ast.unparse` of the whole tree with exactly one site changed. Unparsing
    guarantees the mutant is syntactically valid -- a mutation harness that
    can emit un-importable source spends its budget on noise.
    """
    tree = ast.parse(source, filename=filename)
    sites = _candidate_sites(tree, operators)
    mutants: List[Mutant] = []
    for site in sites:
        node = site[1]
        lineno = getattr(node, "lineno", 0)
        if line_range is not None and not (line_range[0] <= lineno <= line_range[1]):
            continue
        # For a comparison the mutated token lives on the operator, whose own
        # position ast does not record; the enclosing node's line is the
        # reviewable location.
        previous = _apply(site)
        mutated_source = ast.unparse(tree)
        mutants.append(Mutant(
            mutant_id=f"m{len(mutants) + 1:03d}",
            operator=site[0],
            lineno=lineno,
            col_offset=getattr(node, "col_offset", 0),
            original=_render(site, previous),
            mutated=_render(site, site[3]),
            source=mutated_source,
        ))
        _undo(site, previous)
    return mutants


# --- running one mutant ---------------------------------------------------


# Installed into the mutant subprocess BEFORE pytest is imported, so the
# mutated source is what every importer sees. Written as a template rather
# than a file in the repo so there is no importable, mutation-serving module
# sitting in the package for anything else to pick up by accident.
_BOOTSTRAP = '''\
import sys
import importlib.util
from importlib.abc import Loader, MetaPathFinder

_TARGET = {target!r}
_ORIGIN = {origin!r}

with open({source_file!r}, "r", encoding="utf-8") as _fh:
    _CODE = compile(_fh.read(), _ORIGIN, "exec")


class _MutantLoader(Loader):
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(_CODE, module.__dict__)


class _MutantFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != _TARGET:
            return None
        return importlib.util.spec_from_file_location(
            fullname, _ORIGIN, loader=_MutantLoader())


sys.meta_path.insert(0, _MutantFinder())

import pytest

raise SystemExit(pytest.main(list({pytest_args!r})))
'''

# `-x` stops at the first failure: once one test has failed the mutant is
# killed and every further test is wasted wall clock. `-p no:cacheprovider`
# keeps mutant runs from writing .pytest_cache into the real repo, and
# `--color=no` keeps ANSI escapes out of the `detail` strings that end up in
# the report's JSON.
DEFAULT_PYTEST_ARGS: Tuple[str, ...] = (
    "-x", "-q", "--no-header", "--color=no", "-p", "no:cacheprovider")

DEFAULT_TIMEOUT_SECONDS = 120


def _last_line(text: Optional[str]) -> str:
    lines = (text or "").strip().splitlines()
    return lines[-1].strip() if lines else ""


def _run_source_under_tests(root: Path, target_module: str, origin: Path,
                            source: str, test_path: Path, *,
                            timeout: float,
                            pytest_args: Sequence[str]) -> Tuple[Optional[int], str]:
    """Run `test_path` with `source` installed as `target_module`.

    Returns (returncode, detail); returncode is None on timeout. `origin` is
    only ever READ from -- it is passed through as the code object's filename
    so tracebacks point at the real file.
    """
    tmpdir = tempfile.mkdtemp(prefix="dv_mutation_")
    try:
        source_file = Path(tmpdir) / "mutant_source.py"
        source_file.write_text(source, encoding="utf-8")
        bootstrap = Path(tmpdir) / "run_mutant.py"
        bootstrap.write_text(_BOOTSTRAP.format(
            target=target_module,
            origin=str(origin),
            source_file=str(source_file),
            pytest_args=tuple(list(pytest_args) + [str(test_path)]),
        ), encoding="utf-8")

        env = dict(os.environ)
        # The repo root must be importable for `import dv_harness` even when
        # the package is not pip-installed into this interpreter.
        env["PYTHONPATH"] = os.pathsep.join(
            [str(root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run(
                [sys.executable, str(bootstrap)],
                cwd=str(root), env=env, capture_output=True, text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return None, f"tests did not finish within {timeout}s"
        # pytest's own last summary line ("5 passed in 0.68s", "1 failed, 4
        # passed ...") is the one useful line out of a whole run; fall back to
        # stderr when the subprocess died before pytest printed anything.
        return proc.returncode, _last_line(proc.stdout) or _last_line(proc.stderr)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# --- the report -----------------------------------------------------------


@dataclass
class MutationReport:
    module: str
    module_path: str
    test_path: str
    baseline: str
    baseline_detail: str
    generated: int
    executed: int
    killed: int
    survived: int
    timeout: int
    not_run: int
    mutation_score: Optional[float]
    mutants: List[Mutant] = field(default_factory=list)

    @property
    def survivors(self) -> List[Mutant]:
        return [m for m in self.mutants if m.outcome == MutantOutcome.SURVIVED.value]

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "module_path": self.module_path,
            "test_path": self.test_path,
            "baseline": self.baseline,
            "baseline_detail": self.baseline_detail,
            "scope": ("this repository's OWN Python test suite -- NOT DUT/RTL "
                      "fault injection"),
            "summary": {
                "generated": self.generated,
                "executed": self.executed,
                "killed": self.killed,
                "survived": self.survived,
                "timeout": self.timeout,
                "not_run": self.not_run,
                "mutation_score": self.mutation_score,
            },
            "mutants": [m.to_dict() for m in self.mutants],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# --- targets --------------------------------------------------------------

# Explicitly chosen, small, real (module -> its real existing test file).
# Deliberately a SHORT list rather than "every module": a mutant costs one
# full pytest process, so an unbounded default target set would be a
# multi-hour job nobody runs. Add a pair here only after checking its test
# file is self-contained and fast.
DEFAULT_TARGETS: Dict[str, str] = {
    "dv_harness.stats_snapshot": "dv_harness_tests/test_stats_snapshot.py",
    "dv_harness.qualification": "dv_harness_tests/test_qualification.py",
}


class UnsafeMutationTargetError(RuntimeError):
    """Raised for a target this harness refuses to mutate or a test file it
    refuses to run. Never downgraded to a warning: the whole safety argument
    for running arbitrary pytest files in a subprocess rests on this."""


def assert_safe_target(root: Path, module_path: Path, test_path: Path) -> None:
    """The two structural constraints that keep a mutation run local.

    1. The mutated module must be a real file inside the `dv_harness/`
       package -- this harness measures THIS repo's own engine code.
    2. The test file must live under `dv_harness_tests/`, the suite whose
       `conftest.py` already pins the resource-probe transport off. That is
       what makes "a mutant run can never issue a real build / regression /
       LSF submission" a structural fact rather than a promise.
    """
    root = Path(root).resolve()
    module_path = Path(module_path).resolve()
    test_path = Path(test_path).resolve()
    package = (root / "dv_harness").resolve()
    suite = (root / "dv_harness_tests").resolve()
    if package not in module_path.parents:
        raise UnsafeMutationTargetError(
            f"{module_path} is not inside {package}; this harness only mutates "
            f"this repository's own dv_harness/ modules")
    if not module_path.is_file():
        raise UnsafeMutationTargetError(f"{module_path} does not exist")
    if suite not in test_path.parents:
        raise UnsafeMutationTargetError(
            f"{test_path} is not inside {suite}; mutants are only ever run "
            f"against this repository's own test suite, whose conftest.py "
            f"pins the resource-probe transport off")
    if not test_path.is_file():
        raise UnsafeMutationTargetError(f"{test_path} does not exist")


def resolve_target(root: Path, module: str,
                   test_path: Optional[str] = None) -> Tuple[Path, Path]:
    """(module file, test file) for a dotted `dv_harness.*` module name."""
    root = Path(root)
    if not module.startswith("dv_harness."):
        module = f"dv_harness.{module}"
    module_file = root.joinpath(*module.split(".")).with_suffix(".py")
    if test_path is None:
        test_path = DEFAULT_TARGETS.get(module)
        if test_path is None:
            raise UnsafeMutationTargetError(
                f"no default test file registered for {module}; pass an explicit "
                f"test path or add the pair to DEFAULT_TARGETS")
    return module_file, root / test_path


# --- the run --------------------------------------------------------------


def run_mutation_test(root: Path, module: str, *,
                      test_path: Optional[str] = None,
                      operators: Sequence[str] = MUTATION_OPERATORS,
                      max_mutants: Optional[int] = None,
                      line_range: Optional[Tuple[int, int]] = None,
                      timeout: float = DEFAULT_TIMEOUT_SECONDS,
                      pytest_args: Sequence[str] = DEFAULT_PYTEST_ARGS,
                      ) -> MutationReport:
    """Mutate `module`, run its real test file against each mutant, report.

    Baseline first: if the unmutated tests do not pass through the same
    import hook, every mutant is left NOT_RUN and the report says
    BASELINE_FAILED rather than producing a score off a red suite.
    """
    root = Path(root)
    module_file, test_file = resolve_target(root, module, test_path)
    if not module.startswith("dv_harness."):
        module = f"dv_harness.{module}"
    assert_safe_target(root, module_file, test_file)

    original_source = module_file.read_text(encoding="utf-8")
    mutants = generate_mutants(original_source, str(module_file),
                               operators=operators, line_range=line_range)

    baseline_rc, baseline_detail = _run_source_under_tests(
        root, module, module_file, original_source, test_file,
        timeout=timeout, pytest_args=pytest_args)
    if baseline_rc != 0:
        return MutationReport(
            module=module, module_path=str(module_file), test_path=str(test_file),
            baseline=BASELINE_FAILED,
            baseline_detail=(baseline_detail or f"pytest exited {baseline_rc}"),
            generated=len(mutants), executed=0, killed=0, survived=0, timeout=0,
            not_run=len(mutants), mutation_score=None, mutants=mutants)

    to_run = mutants if max_mutants is None else mutants[:max_mutants]
    for mutant in to_run:
        rc, detail = _run_source_under_tests(
            root, module, module_file, mutant.source, test_file,
            timeout=timeout, pytest_args=pytest_args)
        mutant.returncode = rc
        mutant.detail = detail
        if rc is None:
            mutant.outcome = MutantOutcome.TIMEOUT.value
        elif rc == 0:
            mutant.outcome = MutantOutcome.SURVIVED.value
        else:
            mutant.outcome = MutantOutcome.KILLED.value

    killed = sum(1 for m in mutants if m.outcome == MutantOutcome.KILLED.value)
    survived = sum(1 for m in mutants if m.outcome == MutantOutcome.SURVIVED.value)
    timed_out = sum(1 for m in mutants if m.outcome == MutantOutcome.TIMEOUT.value)
    not_run = sum(1 for m in mutants if m.outcome == MutantOutcome.NOT_RUN.value)
    decided = killed + survived
    return MutationReport(
        module=module, module_path=str(module_file), test_path=str(test_file),
        baseline=BASELINE_OK, baseline_detail=baseline_detail,
        generated=len(mutants), executed=len(to_run), killed=killed,
        survived=survived, timeout=timed_out, not_run=not_run,
        mutation_score=(round(killed / decided, 4) if decided else None),
        mutants=mutants)
