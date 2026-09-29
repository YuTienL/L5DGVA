# CAP-M5-VIP-001 — Semantic Merge Plan

Preconditions satisfied before this plan was written (instruction's own
gate): `UNKNOWN_PUBLIC_APIS = 0`, `UNKNOWN_RUNTIME_CALLERS = 0` — every
symbol in `M5_COHORT_3_VIP_SYMBOL_API_INVENTORY.csv` carries a real
classification, every caller in `M5_COHORT_3_VIP_CALLER_SWEEP.csv` is
confirmed either unaffected or the direct, lockstep-updated target.

## Source of the merged capability

100% of the real, new capability in this Cohort comes from **B7B only** —
Parent/v50/B7A/B8 are byte-identical to canonical for this file (confirmed
via `diff -q` across all 6 sources). This is a single-source adoption, not
an N-way reconciliation across disagreeing sources — disclosed honestly
rather than manufacturing a merge narrative where none exists.

## Steps (in commit order)

1. **`_NAME_SUFFIX_CATEGORY_GROUPS`**: append `"transfer"` to the
   `IR_VIP_TRANSACTION` suffix tuple, with the same evidence-citing comment
   B7B wrote (citing `.work/intake-vip_examples-report.md` and the real
   `svt_usb_transfer` class name) — kept because it documents *why*, not
   *what*, and is not stale.
2. **`_VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY`**: add the new table verbatim
   (8 Synopsys SVT entries), including B7B's extended rationale comment
   (kept verbatim — it explains the non-obvious *why*: unindexed vendor
   base classes, `pragma protect` opacity, and the intended future
   multi-vendor extension point).
3. **`classify_by_inheritance()`**: change return type to the 5-tuple,
   add the vendor-marker fallback branch exactly as in B7B's diff, update
   the docstring to describe `via_vendor_marker`.
4. **`VIPCapabilityRecord`**: add `inheritance_via_vendor_marker: bool =
   False` as the 14th field, with B7B's docstring comment explaining it
   marks weaker (name-only vendor-marker) evidence distinctly from a
   provably-closed indexed chain.
5. **`extract_vip_capabilities()`**: update the unpack to 5 values, add
   the `VENDOR_BASE_LIBRARY_MARKER` evidence-entry block, wire
   `inheritance_via_vendor_marker=via_vendor_marker` into both the
   ambiguous-disagreement `VIPCapabilityRecord` construction and the
   normal-classification construction (B7B's diff touches both paths —
   verified by re-reading the full diff hunk, not assumed from the summary
   line alone).
6. **Tests**: port all 4 of B7B's own new tests verbatim into
   `dv_harness_tests/test_vip_capability_extraction.py` (already
   independently confirmed passing in B7B's own worktree — see
   `M5_COHORT_3_VIP_TEST_EVIDENCE.md`).

## What is explicitly NOT changed

- No change to any of the 4 real external consumer files
  (`cli.py`, `vip_callback_hook_extraction.py`,
  `scenario_pattern_command_txt_correspondence.py`,
  `vip_config_field_usage_coverage.py`) — none require any edit, since
  none touch the changed symbols.
- No new JSON schema is created for this module's output (none existed
  before; inventing one now would be scope creep beyond what this
  capability's own source evidence asks for).
- No second vendor's marker table is invented (see Provider Model doc's
  honest evidence-scope disclosure).

## Capability-loss check

Every one of canonical's pre-existing 13 `VIPCapabilityRecord` fields,
every pre-existing naming suffix, every pre-existing inheritance-marker
entry, and every pre-existing public function signature survives
unchanged. `SOURCE_CAPABILITY_LOSS = 0`.
