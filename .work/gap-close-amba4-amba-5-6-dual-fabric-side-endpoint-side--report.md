# AMBA-5 / AMBA-6 gap close — dual fabric-side/endpoint-side role classification + per-protocol interface-count table

**Status: DONE**
**Commit:** `57fb148` — `amba(discovery): AMBA-5 dual-perspective roles + AMBA-6 per-protocol count table` (2 files, +1229/-2)
**Tests:** 234 pass in `dv_harness_tests/test_connectivity.py` (+29 new); 534 pass across all 11 test modules importing `connectivity`.

Scope declaration: **LOCAL_ANALYSIS** — pure local read/edit/test, no server, no VCS.

---

## What the audit found, re-verified before building

Both audit verdicts held up against the current tree (the AMBA-4 step's code had landed in the
meantime, in `74ffda3`, and is described by `be19720`):

- **AMBA-5 = PARTIALLY_WIRED.** `determine_role_from_port_direction()` was real, name-free,
  provenance-enforced and wired into `write_connectivity_manifest()` — but it returned one composite
  `vip_role=...` string. Nothing computed or rendered `FABRIC_SIDE_ROLE` / `EXTERNAL_ENDPOINT_ROLE`,
  nothing reported AXI4-Stream SOURCE/SINK, and the `inout` case stopped at an honest
  `AMBIGUOUS_FROM_DIRECTION_ALONE` with no structural follow-up.
- **AMBA-6 = NEVER_BUILT.** `MATRIX_COLUMNS` carried no `protocol` field at all, so there was
  nothing to group by; `verify_self_check_identity()` / `verify_matrix_self_check_identity()` were
  protocol-agnostic scalar counts; `render_matrix_table()` was a flat row dump with no aggregation
  anywhere in the file. Re-confirmed by grep: zero hits for `FABRIC_SIDE_ROLE` /
  `EXTERNAL_ENDPOINT_ROLE` / any per-protocol count table outside the orchestrating workflow script.

## What was built (all in `dv_harness/connectivity.py`, extending — not paralleling — what was there)

### AMBA-5

- `determine_fabric_interface_roles(dut_port_direction=None, *, protocol=None, signal_directions=None)`
  returns an `AmbaInterfaceRoles` record carrying **both** mandated perspectives in the doc's exact
  vocabulary. It **calls `determine_role_from_port_direction()` and dispatches on its verdict** —
  a vocabulary/rendering layer over that one function, deliberately not a second direction→role
  decision — so `assert_role_provenance()` still holds for any matrix row built from the result.
  It takes no interface/module-name parameter (asserted by an `inspect.signature` test), the same
  structural form of AMBA-4's naming prohibition.
- `AmbaInterfaceRoles.render_lines()` always emits both `FABRIC_SIDE_ROLE` and
  `EXTERNAL_ENDPOINT_ROLE`. There is no single-perspective rendering path in the module, so
  "Master"/"Slave" alone cannot be emitted by accident.
- **AXI4-Stream SOURCE/SINK** (`SOURCE_INTERFACE`/`SINK_INTERFACE`/`SOURCE_ENDPOINT`/`SINK_ENDPOINT`)
  is reported *alongside* the memory-mapped pair, never substituted for it — so a mixed-protocol
  table never silently swaps vocabularies.
- **`resolve_fabric_request_direction(signal_directions)`** is the real "requires protocol-specific
  structural analysis" follow-up the audit named as missing. It reads the directions of the
  initiator-driven **request** signals (`AMBA_INITIATOR_DRIVEN_REQUEST_SIGNALS`, per family) and
  resolves the interface's perspective when they all agree; disagreement is reported as
  `CONTRADICTORY_REQUEST_SIGNAL_DIRECTIONS` and absence as `NO_USABLE_REQUEST_SIGNAL_EVIDENCE` —
  never averaged or majority-voted. Port names appear only as keys whose spec-signal identity is
  recovered by the existing `amba_signal_tokens()`; a port carrying no AMBA request token
  contributes nothing, so a name can never supply the direction (tested with a deliberately lying
  `M99_AXI_MASTER_PORT_ENABLE`).

### AMBA-6

- `AmbaFabricInterface` composes the AMBA-4 classification and the AMBA-5 roles into the one record
  the count table groups over; `build_amba_fabric_interface()` / `build_amba_fabric_inventory()`
  build it from real port names + real directions (the classification runs first, because it is what
  tells AMBA-5 whether the stream pair applies).
- `build_protocol_interface_count_table()` emits the ten mandated rows **in the doc's own order,
  including zero-count ones**, plus `total_fabric_slave_ports` / `total_fabric_master_ports` /
  `total_amba_ports`. Three deliberate properties:
  - an AMBA-shaped interface whose **protocol** is unresolved gets its own extra row (present only
    when non-zero, so a clean fabric renders exactly the ten mandated rows) and is counted in TOTAL
    AMBA PORTS — dropping it is AMBA-3's forbidden silent omission, and raising instead would make
    the table unproducible for a bridge/wrapper, which is when a human most needs to read it;
  - an interface whose **role** is unresolved is counted in its protocol's Total and in TOTAL AMBA
    PORTS but in **neither** the slave nor the master column, and every such interface is named
    below the table — so the totals visibly do not add up by subtraction and the renderer says why;
  - a `NOT_AMBA` interface is excluded from every count but listed in `excluded_not_amba`, so the
    exclusion is auditable.
- `render_protocol_interface_count_table()` prints the doc's **exact four-column header** plus the
  three TOTAL lines; the role-unresolved and not-AMBA sets are named blocks *below* the table rather
  than extra columns, preserving the mandated shape without absorbing anything into it.
- `assert_amba_interface_table_fully_resolved()` is the loud refusal, kept separate from table
  construction on purpose (build always works; a step that cannot proceed on unresolved input
  refuses explicitly).

### The generalization of `verify_self_check_identity()`

`verify_per_protocol_interface_count_identity(table, vip_instance_counts, exemptions)` **calls the
existing scalar function** once per protocol bucket and once over the grand total. It does not
re-derive the arithmetic or the "every exemption carries a non-empty reason" rule — there is one
identity implementation in the module, not two. An exemption must carry `protocol` in addition to
`interface`/`reason`, since an unroutable exemption closes the grand total while leaving a
per-protocol gap open.

The dimension this adds is **proven real, not hypothetical**, by
`test_amba6_per_protocol_identity_catches_a_gap_the_aggregate_hides`: one uncovered AXI4 port plus
one spurious extra APB4 VIP make `verify_self_check_identity()` return `True` on the aggregate while
the per-protocol form raises `SELF_CHECK_IDENTITY_MISMATCH`. The test asserts the aggregate really
does reconcile, so the blind spot is demonstrated rather than asserted.

`cross_check_amba_table_against_matrix()` + `count_amba_ports_in_matrix()` stop the two counting
mechanisms drifting: without it, the inventory and the matrix each stay internally consistent while
omitting what the other saw.

### Matrix schema (the audit's own recommendation #1/#2)

`MATRIX_COLUMNS` gains `protocol` and `fabric_side_role` — the two dimensions AMBA-6 groups on,
which the matrix previously had no way to express. Both default to explicit
`PROTOCOL_NOT_CLASSIFIED` / `FABRIC_SIDE_ROLE_NOT_CLASSIFIED` sentinels, kept **distinct** from
`AMBA_PROTOCOL_UNRESOLVED` / `ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS` ("asked, evidence did
not settle it" is a very different statement from "never asked"). A dict row re-loaded from a
pre-change manifest reads as `NOT_CLASSIFIED`, not as `null`. No production consumer of
`MATRIX_COLUMNS` exists outside `connectivity.py` and its tests (verified by grep before the change),
and the existing `list(matrix[0].keys()) == MATRIX_COLUMNS` / `loaded["columns"] == MATRIX_COLUMNS`
assertions compare against the constant, so nothing broke.

`ConnectivityRow.from_amba_fabric_interface()` derives both new columns from the discovery record
and **refuses** an interface with no established perspective (`AMBA_INTERFACE_HAS_NO_ESTABLISHED_DIRECTION`)
— such an interface belongs in the question queue, not in a row asserting a VIP orientation the RTL
evidence does not support.

### Wiring (so this is not DORMANT)

`emit_connectivity_artifacts()` takes an optional `amba_interfaces=` inventory and writes
`amba_interface_counts.md`, cross-checked against the same matrix before it is written. Omitted, no
file is written and the returned key is `None` — absence means "no AMBA inventory was supplied",
never "this fabric has no AMBA ports". Part C's three protocol-agnostic artifacts are unchanged.

## Hard constraint (AMBA-30 / AMBA-31)

No `bind` statement is written, emitted, planned or implied anywhere. `bind_target` in a matrix row
is a planned target string a human reviews, exactly as before. `test_emit_connectivity_artifacts_writes_the_amba6_table_and_no_bind_statement`
asserts this directly of every artifact written: no line starts with `bind ` and
`parse_bind_line()` finds nothing in any of them. All fixtures are synthetic port-name/direction sets
inside the test file.

## Tests (29 new)

Clean topology and genuinely unresolved states, both:

- Clean: the existing 2-slave/4-master mixed-protocol fabric fixture (AXI4 / AXI3 / ACE-Lite / APB4 /
  AHB-Lite / AXI4-Stream), extended with **real per-port directions** built from a signal list
  spelled out literally in the test rather than imported from the constant under test — so
  `resolve_fabric_request_direction()` cannot agree with itself by construction. Totals asserted:
  2 slave / 4 master / 6 AMBA ports.
- Unresolved: `inout` alone (unresolved, never guessed); `inout` resolved structurally from request
  signals; contradictory request-signal directions; a bridge module spanning AHB+APB (unresolved
  protocol, *resolvable* role — the two are independent and are reported independently); a
  non-AMBA USB sideband (excluded but named); a lying port name; an unknown direction string; no
  direction evidence at all.
- Identity: passing case, reasoned per-protocol exemption, unroutable exemption, unexplained
  exemption (reached *through* the scalar function), unknown-protocol VIP count, and the
  aggregate-hides-a-real-gap case above.
- Matrix: schema round-trip, provenance still holding, refusal of an unresolved-perspective row,
  legacy dict row, table↔matrix cross-check agreeing and disagreeing.

Full run: `python -m pytest dv_harness_tests/test_connectivity.py -q` → **234 passed**.
Full relevant suite (all 11 modules importing `connectivity`) → **534 passed**.

## Deliberately NOT done in this step

- `.claude/skills/CORE/branch-mapper/SKILL.md`'s "AMBA-as-Primary-DUT Master/Slave Redefinition"
  section is still marked UNTESTED (2026-09-01), and was left untouched. Confirming/updating that
  placeholder is **AMBA-26 (L5 BRANCH MAPPING)**'s job, not AMBA-5/6's, and that file is one of the
  three flagged as concurrently edited by other active workflows.
- No downstream of `AMBA_PORT_REGISTRY` was touched; no VIP config, no bind, no UVM.
- `connectivity_check.py` (the standing `just connectivity-check` runner) was not changed: it drives
  the 3 machine gates, which are a different question from fabric discovery. Plugging an AMBA
  fabric-discovery pass into it belongs with the later artifact/report steps (AMBA-16/18/19/22/28),
  once there is an inventory *source* to feed it.

## Concurrency handling

`git status` / `git diff` were checked on `dv_harness/connectivity.py` before editing (clean of
other agents' work; the entire working diff was mine — verified line by line, the only two deletions
were my own edits). Staging used the hand-scoped patch technique (`git diff -- <two paths> > patch`
→ `git apply --cached --check` → `git apply --cached`), and the commit used
`git commit --only -- <two paths>`, never a broad `git add`. Another agent's commit (`1836b0b`)
landed between the audit and the commit; this change sits cleanly on top of it.
