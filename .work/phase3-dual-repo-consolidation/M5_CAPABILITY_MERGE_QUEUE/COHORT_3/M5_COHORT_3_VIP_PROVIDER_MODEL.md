# CAP-M5-VIP-001 — Provider Identity Model

Per instruction item 8: determine what "provider identity" means for VIP
capability extraction — protocol vs vendor/provider vs version vs
installation root vs instance vs interface binding vs source path vs
capability/features — and disclose honestly rather than assume.

## What this module actually models

`vip_capability_extraction.py` does not model a VIP *instance*, *install
root*, or *version* at all — those identities belong to `env_manifest.py`'s
`build_vip_release()`/`scan_designware_home()` (Cohort 1, CAP-M5-ENV-001),
a different module in a different pipeline stage. This module's own scope
is narrower and structurally different: given an already-built
`vip_symbol_index` (a static scan of `.sv`/`.svh` source under some root),
classify each indexed CLASS by IR capability category
(`IR_VIP_CONFIG` / `IR_VIP_TRANSACTION` / `IR_VIP_SCENARIO_PATTERN` /
`IR_VIP_CHECKER_CAPABILITY` / `IR_VIP_COVERAGE_CAPABILITY`), using two
independent evidence sources: class **naming convention** and class
**inheritance chain**.

## The identity axis this Cohort's diff actually touches: vendor base-class family

B7B's real change (`_VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY`) introduces
exactly one new identity concept: a **vendor base-class-library marker** —
the name of an intermediate, vendor-owned base class (e.g. `svt_transaction`)
that a real VIP class chain climbs through before ever reaching a bare
`uvm_*` terminal, used as a classification fallback when that intermediate
base class's own file was never indexed (excluded from scan roots, or
opaque behind `pragma protect`).

This is a real, narrow, evidence-backed axis — it is not "provider" in the
`env_manifest.py` sense (no install root, no version, no vendor env-var
identity is read or stored here). It is purely a **class-naming-convention
family**, keyed by literal base-class identifier string.

## Honest disclosure: today's table is Synopsys-only, and that is what the evidence supports

`_VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY` currently has exactly 8 entries,
every one a documented Synopsys SVT base-class name (`svt_transaction`,
`svt_sequence_item`, `svt_sequence`, `svt_virtual_sequence`,
`svt_configuration`, `svt_config`, `svt_monitor`, `svt_scoreboard`). Per
instruction item 9 ("no Synopsys-only hardcoding if evidence supports
multiple providers"): the ONLY citations in B7B's diff, and the only
citations found by this Cohort's own independent check of
`.work/intake-vip_source-report.md` and `.work/intake-vip_examples-report.md`,
are Synopsys USB SVT sources (`svt_transaction.sv`, `svt_configuration.sv`,
`svt_sequencer.sv`, `svt_agent.sv`, `svt_xactor.sv`, `svt_usb_transfer`).
**No Cadence VIP Catalog or Mentor/Siemens Questa VIP evidence exists
anywhere in this repo's intake reports, B7B's diff, or any of the other 4
sources (Parent/v50/B7A/B8).** Extending the table to another vendor without
that evidence would itself be the prohibited pattern ("no Synopsys-only
hardcoding" cuts against inventing entries as much as it cuts against
leaving only Synopsys entries when other evidence exists) — since no other
evidence exists, the table stays Synopsys-only, and this is disclosed as a
**known, evidence-bounded scope limit**, not an oversight.

The table's own design is already vendor-generic (a flat `Dict[str, str]`
keyed by literal base-class name, with no Synopsys-specific code path) —
B7B's own comment block explicitly documents it as "the intended extension
point" for a future Cadence/Mentor addition once real evidence exists. This
Cohort preserves that generic shape unchanged; it does not add a
vendor-specific function or branch.

## Provider identity is out of scope for this capability, by design

No change in this Cohort introduces, requires, or implies a notion of
"active provider" (env_manifest.py's `vendor=`/multi-vendor VIP-home
scanning, Cohort 1). The `_VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY` table
operates purely on already-indexed source text; it has no dependency on,
and does not consume, any `env_manifest.py` VIP-instance/provider record.
This separation is preserved as-is.
