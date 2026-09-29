# M5 Cohort 2 -- Environment/Architecture Semantic Union -- Capability Analysis

Scope: `CAP-M5-ARCH-001` (`create_environment.py`), `CAP-M5-ARCH-002`
(`soc_environment_composer.py`), `CAP-M5-ARCH-003` (`amba_fabric_generator.py`).
Per instruction: symbol/caller/dependency analysis performed first; the
capability boundary is NOT assumed to equal these three files.

## Real diff sizing (this wave, not assumed)

| File | Parent vs canonical | v50 vs canonical | B8 vs canonical |
|---|---|---|---|
| `create_environment.py` | 46-line diff (real, small) | **0-line diff (byte-identical)** | 161-line diff |
| `soc_environment_composer.py` | 150-line diff (real, substantial) | 11-line diff (real, small) | 103-line diff |
| `amba_fabric_generator.py` | 0-line diff (byte-identical) | 0-line diff (byte-identical) | 140-line diff |

`amba_fabric_generator.py` is the only one of the three where Parent/v50
are both byte-identical to canonical -- a clean 2-way merge target.
`create_environment.py` has a real but small Parent delta plus a larger
B8 delta. `soc_environment_composer.py` is the only genuinely 3-way
target in this cohort (Parent, v50, and B8 each diverge from canonical
independently).

## CAP-M5-ARCH-003 (`amba_fabric_generator.py`) -- CLOSED this wave

**Capability boundary**: exactly two functions
(`scan_designware_home`... no -- `scan_designware_home` was Cohort 1;
here: `generate()`'s fabric-graph wiring) plus two new symbols
(`cross_check_fabric_graph()`, `FabricGraphMismatchError`) and one new
import (`amba_fabric_graph_ir.FABRIC_NODE_KINDS`/`build_amba_fabric_graph`).
`amba_fabric_graph_ir.py` itself (the sibling module B8's delta imports
from) is **already byte-identical** between canonical and B8 -- confirmed
by `diff -q`, not assumed. No other symbol in this file differs across
any of the 3 relevant sources (Parent/v50 are both 0-diff).

**SEMANTIC_CONFLICT found and resolved (not a whole-file copy)**: B8's own
call site (`self.env(t, fabric, fabric_graph_info)`) passes a 3rd
positional argument to `env(self, t, fabric)`, whose signature -- in
canonical **and in B8 itself** -- never gained a 3rd parameter and never
reads `fabric_graph_info` in its body. Verified with real runtime
evidence, not static inference alone: running B8's own unmodified test
suite in B8's own worktree (`cd /d/wt/b8 && python -m pytest
dv_harness_tests/test_amba_fabric_generator.py`) reproduces
`TypeError: AMBAFabricGenerator.env() takes 3 positional arguments but 4
were given` on 4 of B8's 15 tests. B8 also shipped **zero** test coverage
for the new feature itself (`test_amba_fabric_generator.py` diff = 0
lines) -- there was no test in B8 that would have caught its own defect.

Canonical target behavior: adopt B8's real, working capability (the
cross-check computation, `FabricGraphMismatchError`, the two JSON
artifacts it populates) but correct the call site to keep `env(t, fabric)`
at 2 args -- `fabric_graph_info` is surfaced only via
`environment_manifest.json`'s new `fabric_graph_cross_check` key and
`fabric_topology.json`'s new `internal_fabric_nodes` key, which is all
`env()`'s own SV-content generation ever needed from it.

See `M5_COHORT_2_SEMANTIC_MERGE_PLAN.md` for the full behavior-union
table and `M5_COHORT_2_TEST_EVIDENCE.md` for the test run log.

## CAP-M5-ARCH-001 (`create_environment.py`) -- scoped, NOT merged this wave

Real diffs generated and read this wave (Parent: 46 lines; B8: 161
lines; v50: 0, byte-identical to canonical). `create_environment.py` is
explicitly the instruction's own flagged "high-risk shared target" (the
known hard-coded mode-string defect from M1's own prior disposition,
`M1_KNOWN_SOURCE_B_DEFECT_DISPOSITION.md`). Symbol/caller enumeration for
this file has not yet been performed to the same depth as ARCH-003 (no
`CALLER_SWEEP.csv` row exists for it yet). Deferred to the next Cohort-2
session rather than merged under time pressure -- see "Known limitations"
in `M5_COHORT_2_FINAL_REPORT.md`.

## CAP-M5-ARCH-002 (`soc_environment_composer.py`) -- scoped, NOT merged this wave

Real diffs generated this wave (Parent: 150 lines; v50: 11 lines; B8:
103 lines) -- the only genuinely 3-way target in this cohort, and by
diff-line-count the largest single merge in the whole M5 capability
inventory. Not yet read in full or symbol-mapped. Deferred to the next
Cohort-2 session.

## Article 0 (per-capability, Section 12)

| Dimension | CAP-M5-ARCH-003 |
|---|---|
| LOCATION_INDEPENDENT | PASS -- no host/path/user dependency introduced |
| EVIDENCE_GROUNDED | PASS -- `cross_check_fabric_graph()` raises rather than guesses on a real graph/topology disagreement; the defect fix itself is evidence-grounded (real pytest TypeError reproduction in B8's own worktree, not inferred) |
| KNOWLEDGE_DRIVEN | N/A -- not applicable to this capability's own behavior |
| CONTINUOUS_EVOLUTION | N/A this wave |
| END_TO_END_DV_ALIGNMENT | PARTIAL -- closes one real generation-vs-analysis disconnect (topology IR was previously unreachable from generation); does not itself complete AMBA fabric generation end-to-end |

No PASS manufactured where evidence does not support it.
