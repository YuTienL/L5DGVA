# CAP-M5-VIP-001 — Compatibility Plan

Per instruction items 10-14: prefer additive extension over breaking
change; every adapter needs OLD_CONTRACT/NEW_CONTRACT/CALLERS/OWNER_WAVE/
REMOVAL_CONDITION.

## Decision: no compatibility adapter is required

An adapter (a shim preserving the old 4-tuple return alongside the new
5-tuple) is the standard tool for a signature break with real external
callers. This Cohort's caller sweep (`M5_COHORT_3_VIP_CALLER_SWEEP.csv`)
found **zero** real external callers of `classify_by_inheritance()` —
its only caller anywhere in canonical is `extract_vip_capabilities()` in
the same file, updated in lockstep. Building an adapter for a function
with no external caller would itself violate the project's own "no
overly abstract naming" / no-speculative-abstraction discipline (an
adapter for a hypothetical future caller is exactly the kind of
premature generalization the project guidance prohibits). The change is
therefore adopted directly, as a private-module-internal signature
change, not as a public-compatibility-break requiring a shim.

## What IS treated as a compatibility-preserving extension (no adapter needed, additive by construction)

| Change | OLD_CONTRACT | NEW_CONTRACT | CALLERS | OWNER_WAVE | REMOVAL_CONDITION |
|---|---|---|---|---|---|
| `_NAME_SUFFIX_CATEGORY_GROUPS` gains "transfer" | 5-suffix tuple for IR_VIP_TRANSACTION | 6-suffix tuple (adds "transfer") | `classify_by_name()`, `assert_naming_categories_disjoint()` (both read the table, no caller enumerates/counts suffixes) | M5 Cohort 3 | N/A — pure evidence-backed addition, no removal condition |
| `VIPCapabilityRecord` gains `inheritance_via_vendor_marker: bool = False` | 13-field dataclass | 14-field dataclass, new field defaults False | All 4 real external consumers read specific named fields only (never iterate/assert exact field count) | M5 Cohort 3 | N/A — additive, no schema anywhere constrains field count |
| `extract_vip_capabilities()` internal evidence list gains a `VENDOR_BASE_LIBRARY_MARKER` entry kind when `via_vendor_marker=True` | evidence list entries: `NAMING_SUFFIX` / `INHERITANCE_CHAIN` kinds only | adds a 3rd possible kind, only emitted when a real vendor-marker fallback fired | No caller enumerates/validates the closed set of evidence `kind` values (confirmed via caller sweep) | M5 Cohort 3 | N/A |

## classify_by_inheritance() signature change record (for completeness, not because an adapter is needed)

| Field | Value |
|---|---|
| OLD_CONTRACT | `(by_name, class_name, *, base_library_prefixes=...) -> Tuple[Optional[str], List[str], bool, Optional[str]]` (4-tuple) |
| NEW_CONTRACT | same params `-> Tuple[Optional[str], List[str], bool, Optional[str], bool]` (5-tuple, appends `via_vendor_marker`) |
| CALLERS | `extract_vip_capabilities()` in the same file only (updated in lockstep in this same merge) |
| OWNER_WAVE | M5 Cohort 3 |
| REMOVAL_CONDITION | N/A — this is the adopted contract going forward, nothing to remove |

## Multi-vendor VIP discovery behavior preservation (instruction item 9)

No existing multi-vendor behavior (Cohort 1's `env_manifest.py`
`_VENDOR_VIP_HOME_ENVS`/`vendor=` support) is touched, narrowed, or
special-cased by this Cohort. The new `_VENDOR_BASE_LIBRARY_MARKER_TO_
CATEGORY` table is itself vendor-generic in shape (a flat name->category
dict) even though its current contents are Synopsys-only per the honest
evidence-scope disclosure in `M5_COHORT_3_VIP_PROVIDER_MODEL.md`.
