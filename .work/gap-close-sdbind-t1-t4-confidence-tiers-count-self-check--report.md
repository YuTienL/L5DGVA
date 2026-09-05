# Gap-close: T1–T4 confidence tiers + count self-check equation

**Scope**: `dv_harness/connectivity.py` — the 4-tier bind-confidence classifier, the required
9-column matrix, the self-check identity, and the three VIP-count-mismatch sources.

**Verdict: DONE.** One real, empirically-reproduced gap found and closed; the audit's own
PARTIAL had already been closed by concurrent work before I started.

Commit: `fc82ff1` — *connectivity: wire count-mismatch source 1 (ACTIVE-interface count) to the
real matrix* (2 files, +364/−5).

Test summary: **175 pass** in `dv_harness_tests/test_connectivity.py` (13 new); **545 pass**
across all 11 suites that consume `connectivity`.

---

## The audit was working from a stale file

The audit cited `connectivity.py` at 1453 lines and `test_connectivity.py` at 976, with 90
tests. Current, re-verified live: **2749 / 1899 lines, 162 tests passing** before my change.
Concurrent commits (`ab4589f`, `3fa5468`, `656c8c6`, `5e373dc`) landed in between. All line
citations below are re-verified against the current file, not carried over.

## Re-confirmation of the READY items

| Requirement | Verdict | Current evidence |
|---|---|---|
| T1–T4 classifier | READY | `classify_bind_tier()` `connectivity.py:141-202`; `BindTier` `:125-129`. Priority enforced by if/elif order at `:160,169,183,196`. T3 hard-codes `auto_acceptable=False` at `:192-193` with no signature parameter able to flip it. |
| `assert_t3_never_auto_accepted()` | READY | `:205-220`, raises `BindTierError("T3_MUST_NEVER_AUTO_ACCEPT")`. |
| Required matrix, 9 exact columns | READY | `MATRIX_COLUMNS` `:1049-1052`, exact order match. |
| Self-check identity equation | READY | `verify_self_check_identity()` `:1013-1042`; `lhs != rhs` raises `ConnectivitySelfCheckError`, never a bool. Exemption `reason` checked first at `:1022-1027`. |
| Mismatch source 2 (path-combination) | READY as a primitive | `compute_path_combination_count()` `:990-1010`. |
| Mismatch source 3 (role from port direction) | READY **and now wired** | `determine_role_from_port_direction()` `:971-987`; enforced matrix-level by `assert_role_provenance()` `:1151` called from `write_connectivity_manifest()` `:1254`. |

**The audit's PARTIAL ("no caller invokes these from a real generation flow") was already
closed** by concurrent work, verified by real grep rather than by the CLAUDE.md prose claiming
it:
- `uvm_generator/bind_mechanism_generator.py:125-126` imports and calls
  `enforce_bind_tier_policy(bind_entries, require_tier=require_tier)` inside
  `validate_bind_entries()`, which `emit_bind_sv()` calls at `:136` **before** writing any bind
  text. That is the "downstream consumer" `assert_t3_never_auto_accepted()`'s docstring named.
- `connectivity.py:1254-1255` — `write_connectivity_manifest()` runs `assert_role_provenance()`
  and `verify_matrix_self_check_identity()` before writing.

## The real remaining gap: mismatch source 1 was still unwired, and its input column unvalidated

`check_vip_instance_count_matches_active_interfaces()` (`:951`) had **no caller outside its own
test** — grep over `dv_harness/`, `tools/`, `dv_harness_tests/` returned only the definition and
two test cases. The matrix's `active_passive` column — the only evidence for the ACTIVE-interface
count that source 1 is *defined in* — was read by nothing but the mermaid renderer (`:1327`,
`:1364`, `:1381`).

Four holes, each **reproduced live** against the real module before being closed:

| Hole | Reproduced behavior before |
|---|---|
| **A/B** vocabulary | `active_passive="actve-ish maybe?"` wrote a manifest with no complaint. |
| **C** stray exemption | An exemption naming `a_totally_unrelated_if` (not in the matrix at all) closed the identity for a *different*, genuinely uncovered interface. `verify_self_check_identity()` is handed integers and can only `len()` exemptions. |
| **D** double-count | An exemption naming a row that already **has** a VIP passed, absorbing another row's real gap. |
| **E** cancellation | 1 passive-monitor VIP (+1) and 1 uncovered ACTIVE interface (−1) cancel to `delta: 0` → `ok: True`. Two real findings of opposite sign hid each other. |

### What was built

Extending `connectivity.py` in place (no parallel mechanism):

- `ACTIVE_INTERFACE`/`PASSIVE_INTERFACE`/`ACTIVE_PASSIVE_VALUES` + `assert_active_passive_vocabulary()`
  — hard-rejects a value that is neither, since a typo silently drops a row out of the count.
  Case/whitespace tolerant.
- `count_active_interfaces_in_matrix()`, `matrix_vip_instance_records()` — read the ACTIVE count
  and build the real `VipInstanceRecord` list off the matrix, giving source 1 the caller it
  never had.
- `reconcile_exemptions_against_matrix()` — the row-aware layer the scalar identity cannot be:
  an exemption must name a real **uncovered no-VIP** interface of this matrix
  (`EXEMPTION_INTERFACE_NOT_IN_MATRIX`, `EXEMPTION_COVERS_AN_INTERFACE_THAT_HAS_A_VIP`,
  `DUPLICATE_EXEMPTION`), and one covering an ACTIVE interface is flagged
  `exempts_an_active_interface` in the manifest — the serious kind, no longer indistinguishable
  from an exempted passive one.
- `verify_matrix_vip_active_interface_count()` — decomposes the scalar delta into its two
  independent halves so neither hides the other, and **names the offending interface** instead
  of a bare `gap: 1`.
- `_row_has_vip()` / `_row_active_passive()` shared helpers; `count_vip_instances_in_matrix()`
  refactored onto the former rather than duplicating the marker test.

All of it flows into the artifact through the existing `verify_matrix_self_check_identity()` →
`write_connectivity_manifest()` path, so the manifest on disk now carries a `vip_count_check`
block and `exemptions_reconciled` records.

### Ordering is the design, not an implementation detail

The row-aware checks run **before** the scalar identity. Reason, verified live: an uncovered
ACTIVE interface previously reported as `SELF_CHECK_IDENTITY_MISMATCH {gap: 1}`, naming no
interface. Running the row-aware checks first means the most specific true statement is the one
raised, with the arithmetic left as the backstop for the uncovered-**PASSIVE** case they cannot
see.

I caught and fixed a real defect in my own first draft here: with exemption reconciliation
enforcing a bijection between exemptions and uncovered rows, the `ACTIVE_INTERFACE_WITHOUT_VIP`
raise was **provably unreachable** behind the identity check — dead code. The reorder is what
makes it reachable and useful. `test_an_uncovered_passive_interface_still_falls_to_the_scalar_identity`
exists specifically to prove the reorder did not *replace* the arithmetic backstop.

A legitimate passive-monitor matrix stays **passing** and is recorded as explained
(`scalar_ok: false`, `delta_fully_explained: true`, `passive_vip_instances: [...]`) — the check
reports, it does not block a valid environment. Guards run before any write; verified no partial
artifact is left on disk.

### Tests

13 new tests in `test_connectivity.py`, covering each hole plus the legitimate passing case, the
end-to-end manifest content, and `emit_connectivity_artifacts()` leaving nothing behind.

One pre-existing test changed: `test_matrix_with_an_uncovered_no_vip_interface_fails_loudly` now
asserts `ACTIVE_INTERFACE_WITHOUT_VIP` with the interface named, rather than the old generic
`SELF_CHECK_IDENTITY_MISMATCH {gap: 1}`. Its intent ("an uncovered no-VIP interface fails
loudly") is unchanged and more precisely met — this is a behavior improvement the test was
updated to describe, not a test bent to pass.

```
python -m pytest dv_harness_tests/test_connectivity.py -q          -> 175 passed
+ test_connectivity_check, test_bind_mechanism_generator,
  test_bind_verification_lint, test_question_queue,
  test_blackboard_subsystem_wiring, test_source_authority          -> 329 passed
+ test_amba_fabric_generator, test_asset_processing_artifacts,
  test_context_budget, test_four_key_judgments_enforcement         -> 216 passed
```
= 545 passing across every module and test file that references `connectivity`.

## Scoped out, reported honestly

**Mismatch source 2 (interconnect path-combination count) remains a correct, tested primitive
with no production caller, and I deliberately did not fake-wire it.** The matrix carries `role`
(master_initiator / slave_responder) but has **no fabric or reachability column**. A
matrix-level full-mesh count across all rows would multiply masters and slaves belonging to
unrelated protocols and fabrics, producing a confidently wrong number — worse than no number.
Wiring it needs a real fabric/reachability evidence source (address-decode or fabric-topology
input) that this matrix does not yet carry: **NEEDS_SEPARATE_EFFORT**, small and well-defined,
but a schema change rather than a wiring change.

**Not modified**: `CLAUDE.md`. Its "Bind-Location Rules" section describes the tier and matrix
guarantees accurately as of this change; the new checks strengthen the existing
`write_connectivity_manifest()` guarantee it already documents rather than adding a new
user-facing rule.

## Concurrency note

Per the brief, `git status` was checked before touching anything and re-checked before staging.
`connectivity.py` and `test_connectivity.py` were **clean** at start (not among the files other
active workflows had modified) and showed only my own 8 hunks at commit time. Staged with an
explicit two-path `git add --`, never a broad add. The full-repo `pytest dv_harness_tests` run
was abandoned deliberately: it exceeded 600s and sweeps files other live workflows are actively
mutating, which would make its result unattributable to my change. The targeted 545-test sweep
across every real consumer of this module is the sounder evidence and is what I report on.
