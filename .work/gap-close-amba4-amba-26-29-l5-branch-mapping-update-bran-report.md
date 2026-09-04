# Gap close: AMBA-26..29 (L5 branch mapping, confidence rule, 17-item discovery report, readiness)

**Status: DONE**

**Commit:** `5a822a7` — `amba(report): AMBA-26 L5 branch mapping, AMBA-27 confidence, AMBA-28 17-item report, AMBA-29 readiness`
(3 files, +2604/-29)

**Test summary:** 54 new tests in `dv_harness_tests/test_amba_discovery_report.py`, all passing;
496 passed across the full AMBA + connectivity + confidence-vocabulary suite
(`test_amba_discovery_report.py test_amba_fabric_discovery.py test_amba_fabric_analysis.py
test_amba_port_registry.py test_amba_vip_bind_plan.py test_amba_fabric_generator.py
test_confidence_vocabulary_separation.py test_connectivity.py`), 0 failed, 0 skipped
(`verible-verilog-syntax` present on PATH, so no fixture was skipped).

---

## What changed

### New: `dv_harness/amba_discovery_report.py` (1636 lines)

One module for all four requirements, because all four CONSUME facts other modules already
derived and produce no new RTL fact of their own. It imports and composes rather than restating:

| Reused primitive | From | Used for |
|---|---|---|
| `BIND_READINESS_READY/PARTIAL/BLOCKED/UNKNOWN` | `amba_fabric_discovery.py:1710-1714` | AMBA-29's vocabulary — the same four words, not a second enum |
| `_worst_readiness()` | `amba_fabric_discovery.py:2084` | AMBA-29's overall rollup — imported (underscore and all) so AMBA-18's per-branch rollup and AMBA-29's per-fabric rollup cannot disagree about which status is worse |
| `BindTier` / `classify_bind_tier()` | `connectivity.py:137,153` | AMBA-27's confidence is DERIVED from the tier plus real structural facts; no second classifier |
| `render_markdown_table()` | `connectivity.py:2539` | every table |
| `render_amba_topology_summary` / `render_endpoint_trace_report` / `render_fabric_vip_bind_matrix` / `render_unresolved_fabric_port_table` / `render_vip_instance_plan` / `plan.tree` | `amba_fabric_discovery.py` | AMBA-28 items 5,6,7,8,9,11 — called, not reimplemented |
| `render_amba_port_registry()` | `amba_port_registry.py:453` | AMBA-28 item 14 |
| `render_clock_reset_domain_report` / `render_fabric_scaling_report` / `interlocks` | `amba_fabric_analysis.py` | AMBA-28 items 10,13 and AMBA-26's `cross_branch_bus_model.shared_resources` |
| `render_scoreboard_env_report()` | `amba_scoreboard_env.py:721` | AMBA-28 item 12 |
| `branch_topology_gate.py`'s document schema | `tools/verification_flow/branch_topology_gate.py:24-33` | AMBA-26's output shape |
| `assert_no_bind_statement()` | `amba_fabric_discovery.py:2789` | AMBA-30/31 self-check on every rendered artifact |

`test_the_report_composes_the_existing_renderers_rather_than_new_tables` asserts sections
5/6/7/8/9/11/14 are byte-identical to those existing renderers' output, so "composes" is a
checked claim.

#### AMBA-26 — L5 BRANCH MAPPING (was PARTIALLY_WIRED, doc-only)

`build_l5_branch_mapping()` → `L5BranchMapping`:

- `branch_a{i}` = one per **fabric-facing physical interface** (parent matrix rows, excluding
  AMBA-11 second-side rows) — by actual port count.
- `branch_b{j}` = one per **discovered VIP** from the AMBA-20 instance plan. On the 11-port test
  fixture this is 13, which is neither the port count (11) nor the slave count — asserted, because
  that inequality is precisely the placeholder's unit error.
- `block` and `branch_fw` always present.
- **Naming convention resolved deliberately, not silently.** AMBA-26's prose writes
  `branch-a1..N` (dash, 1-indexed). `branch_topology_gate.py:1-13` records itself being
  canonicalised on 2026-08-28 on the underscore, 0-indexed form after *four* incompatible
  conventions were found coexisting, and declares itself "the single source of truth". AMBA-26's
  own instruction is to map into **existing** L5 naming, so the existing canonical spelling wins;
  the module docstring states this rather than leaving it to be re-derived.
- `to_branch_topology()` emits that gate's exact document. `branch_topology_gate_blockers()`
  reports what a human must still supply.
- **Two refusals to round up**: `branch_fw` applicability comes only from interrupt/event-shaped
  PORT NAMES on the real fabric instance → `classify_bind_tier(naming_match=...)` → T3, LOW
  confidence, `requires_human_confirmation=True`. No such port ⇒ `branch_fw_interrupt_driven:
  False` and the gate correctly FAILS. `cross_branch_bus_model.arbitration_policy` stays
  `REQUIRED_HUMAN_INPUT` (round-robin vs priority vs QoS lives in arbiter RTL nobody has read);
  `shared_resources` comes from AMBA-25's real interlock analysis, filtered to the pairs it
  actually found a dependency for.

#### AMBA-27 — EVIDENCE + CONFIDENCE RULE (was PARTIALLY_WIRED)

- `AMBA27_EVIDENCE_KINDS` — the doc's twelve kinds. `EvidenceRef` validates against the tuple and
  refuses an empty `detail` (a bare KIND is a category name, not a citation).
- `Conclusion` enforces both halves at construction: non-UNKNOWN with no evidence raises
  `AMBA27_CONCLUSION_WITHOUT_EVIDENCE`; UNKNOWN with no `missing_evidence` raises
  `AMBA27_UNKNOWN_WITHOUT_MISSING_EVIDENCE`.
- `unresolved_abstractions()` is what makes MEDIUM ("strong structural evidence with **one**
  unresolved abstraction") countable rather than felt: it returns named entries
  (`PROTOCOL_NOT_FULLY_CLASSIFIED`, `FABRIC_SIDE_ROLE_UNRESOLVED`, `OPAQUE_STRUCTURAL_ELEMENT`,
  `HOP_ROLE_RESTS_ON_A_NAME`, `MULTIPLE_BRANCHES_NOT_NARROWED`,
  `ENDPOINT_LIES_BEYOND_A_PROTOCOL_BRIDGE`), each with where and what. Exactly one ⇒ MEDIUM,
  two or more ⇒ LOW. Asserted on the real clean fixture in
  `test_medium_means_exactly_one_countable_unresolved_abstraction`.
- `classify_port_conclusions()` produces **four** conclusions per port (protocol / role /
  endpoint / bind_location) rather than one collapsed label, because the levels genuinely differ
  per axis: on the ambiguous fixture, protocol and role are HIGH on all 11 ports while endpoint
  is UNKNOWN on 5, MEDIUM on 3, HIGH on 3.
- `assert_not_reported_as_confirmed_topology()` enforces the doc's last line.

**The fourth trust vocabulary question is answered, not left open.**
`test_confidence_vocabulary_separation.py` already keeps three trust mechanisms apart, and
AMBA-27 reuses `inference.CONFIDENCE_LEVELS`' three words. Two tests settle it:
`test_amba27s_medium_is_not_expressible_as_an_inference_confidence_score` (score_confidence is
ADDITIVE over citation counts; AMBA-27's MEDIUM is SUBTRACTIVE over a count of unresolved
abstractions — a heavily-cited but structurally-unresolved conclusion is HIGH there and LOW here,
so routing AMBA-27 through it would confirm exactly what AMBA-27 forbids), and
`test_the_existing_three_way_vocabulary_disjointness_is_untouched` (asserts no confidence token
appears inside any `BindTier` or question-queue tier name, that the module carries the
`test_confidence_vocabulary_separation` grep anchor, and that it does not import `inference`).

#### AMBA-28 — DISCOVERY REPORT ORDER (was NEVER_BUILT)

`AMBA28_SECTIONS` is the doc's exact seventeen; `build_discovery_report()` iterates the tuple, so
a section cannot be skipped, reordered or renamed by editing a call site. New renderers exist for
the six with no home elsewhere (1 input resolution, 2 fabric instance, 3 port enumeration,
4 protocol classification, 16 open questions, 17 review gate); the other eleven call the existing
renderers. A section whose input was not supplied renders a visible `NOT SUPPLIED` note naming the
producing function — never omitted, the same property AMBA-17's mandatory-even-when-empty table
has. `assert_report_section_order()` re-reads the **finished text** (a heading a body swallowed,
duplicated or emitted out of order is a real failure mode that checking the source tuple would
not catch) and is tested against all three failure shapes.

Section 17 is AMBA-30's seven gate lines verbatim.

**AMBA-26's mapping is deliberately NOT an 18th section** — AMBA-28 says "produce exactly" that
list. `render_l5_branch_mapping_report()` is a separate document the same review covers.

#### AMBA-29 — READINESS (was NEVER_BUILT)

`compute_port_readiness()` over `AMBA29_REQUIRED_ATTRIBUTES` = the doc's five (protocol, role,
endpoint, bind hierarchy, clock/reset — clock/reset is one attribute in the doc's sentence and is
kept as one). Rule order, each half tested:

1. AMBA-15 DISPROVEN check ⇒ **BLOCKED** (a hierarchy that does not exist is not a location a
   human can approve; it must not average out to PARTIAL). Tested against a real
   `validate_vip_bind_location()` on a non-existent path.
2. Zero of five resolved ⇒ **UNKNOWN** ("insufficient evidence").
3. Identified but no usable endpoint *and* no usable bind location ⇒ **BLOCKED**. Kept distinct
   from UNKNOWN because the doc keeps them distinct: telling a reviewer "insufficient evidence"
   when the real answer is "nowhere for a VIP to sit" sends them after the wrong thing.
4. All five resolved ⇒ **READY**.
5. Otherwise **PARTIAL**, naming the unresolved attributes.

A MULTIPLE_SOURCE/MULTIPLE_DESTINATION port is held at PARTIAL, never BLOCKED — AMBA-12/13
enumerated real branches and forbid choosing one, so the open item is the *choice*, not an absent
endpoint. (This was a real bug found by the ambiguous fixture: the first implementation reported
both such ports BLOCKED.)

`derive_overall_readiness()` is worst-first via the imported reduction, names the governing ports
with their reasons (`preflight.py`'s worklist discipline, not a bare status), and returns UNKNOWN
— not READY — for an empty port set.

`assert_readiness_respects_confidence()` is the one place AMBA-27 and AMBA-29 are coupled: a READY
port is a confirmed-topology claim, so a READY port whose weakest conclusion is LOW/UNKNOWN raises.
Both real fabrics satisfy it.

**Deliberate, documented difference from AMBA-15/18's readiness**: that one is thirteen checks
including every signal width. A port with an unprovable USER width is PARTIAL there and may be
READY here. Both are reported side by side (`PortReadiness.bind_location_readiness`), and the one
coupling that does exist (a DISPROVEN check) is enforced.

### Changed: `.claude/skills/CORE/branch-mapper/SKILL.md`

The 2026-09-01 placeholder branched on AMBA **agents** (`branch_a*` = one per bus master,
`branch_b*` = one per addressable slave). That is a different axis from AMBA-26's, and it was
corrected: `branch_a*` = fabric **ports**, `branch_b*` = discovered **VIP instances**. Added a
dated "Branch unit CORRECTED 2026-09-04" block citing the real code and test, corrected the
"Mapping record implications" paragraph (including that `arbitration_policy` is refused rather
than guessed), and rewrote "What still needs real-pilot confirmation" into four specific open
items.

**The UNTESTED label is NOT removed**, per the audit's own recommendation. Unit tests against a
synthetic verible-parsed fixture prove the mapping CODE computes what AMBA-26 specifies; they do
not prove AMBA-26's shape is right for a real fabric, which is what that label is about. The
closing paragraph now says exactly that, so a reader cannot mistake "tested code exists" for
"validated against real interconnect RTL". No real AMBA-fabric pilot exists in this repo, and
AMBA-30/31 put every step that would create one behind human approval.

The heading keeps its original leading text so `CLAUDE.md`'s cross-reference
("AMBA-as-Primary-DUT Master/Slave Redefinition" section) still resolves.

---

## Tests (`dv_harness_tests/test_amba_discovery_report.py`, 54 tests)

Two REAL RTL fixtures, both imported rather than copied so this module is proven against the exact
topologies AMBA-7..25 were proven against:

- **Ambiguous** (`test_amba_fabric_discovery.write_fabric_fixture`) — 11 fabric ports reaching all
  ten AMBA-14 termination states across AXI4/APB4/AHB-Lite, with **no clock or reset ports
  anywhere**, so AMBA-29's clock/reset attribute genuinely cannot resolve on any port. Result:
  0 READY, 9 PARTIAL, 2 BLOCKED, overall BLOCKED.
- **Clean** (`test_amba_fabric_analysis.write_fixture`) — clocked two-master AXI4 SoC with a CDC
  wrapper and an AXI→APB bridge. This is what proves READY and HIGH/MEDIUM are reachable at all
  rather than being unreachable states a permissive test would never notice.

Notable coverage:

- `test_the_mapping_is_checked_by_the_real_existing_branch_topology_gate` runs
  `tools/verification_flow/branch_topology_gate.py` as a **real subprocess** against the emitted
  document, twice: as discovered it must FAIL with a reason the blockers named, and with the two
  human answers filled in it must PASS reporting `dut_ports: 11`.
- `test_no_port_of_a_clockless_fabric_is_ready_and_each_names_clock_reset` — the failure a
  permissive readiness rule makes: four-fifths of the evidence must not reach READY.
- `test_a_multiple_branch_port_is_partial_not_blocked` — the bug this fixture actually caught.
- `test_no_bind_statement_in_the_module_or_any_artifact_it_renders` over the module source and
  every artifact from both fixtures, plus
  `test_a_report_that_somehow_contained_a_bind_would_be_refused`, which gives that check real
  detection power instead of being a check that never looked.

---

## AMBA-30 / AMBA-31 compliance

No `bind` statement is written anywhere. The only SystemVerilog written by this change is the
synthetic fixture RTL inside the imported test fixtures (which contain none), and every rendered
artifact — the 17-item report, the AMBA-26 mapping report, the conclusions table, the readiness
table — is run through `assert_no_bind_statement()` before it is returned. Section 17 of every
report is AMBA-30's gate text. Nothing downstream of AMBA_PORT_REGISTRY is auto-applied.

## Notes / not done

- **No standing runner wired.** Like AMBA-1..25 before it, this module has no `just` recipe or
  `connectivity_check.py` hook yet — the AMBA modules are importable and tested but not on an
  automated flow. That is a single wiring task across AMBA-1..29 rather than a per-step one, and
  it is out of this step's scope; flagging it so it is not assumed done.
- **Sibling trees not synced.** `../industrial/.claude/skills/CORE/branch-mapper/SKILL.md` and
  `../PACKAGE/...` already differed from `v50` HEAD before this change (pre-existing drift from
  other concurrent work, and neither tree is a git repo), so syncing them would have meant
  overwriting another effort's in-flight edits. Left alone deliberately.
- **Concurrent-agent safety.** `CLAUDE.md`, `dv_harness/engine.py`,
  `dv_harness_tests/test_waveform_dump_scope_human_confirmation.py` and a `.work/` report were
  staged in the index by another agent while this ran. The commit was made with an explicit
  pathspec (`git commit -- <my three files>`), and `git diff --cached` after the commit confirms
  all four of their staged files are still staged and uncommitted.
