# CAP-M5-ARCH-002 -- VIP Deduplication Analysis

## Finding (Section 11)

**No VIP deduplication or shared-VIP-ownership logic exists anywhere in
`soc_environment_composer.py`, in any of the 3 sources (canonical,
Parent, B8).** Confirmed by reading the full canonical file and both real
diffs in full, not assumed from symbol names.

This module composes one independent per-subsystem virtual-sequencer
handle and one independent per-subsystem environment instance
(`<protocol>_env_inst`) for every registered subsystem -- there is no
concept anywhere of "two subsystems requesting the same VIP" being
reconciled into one shared agent. Each composed subsystem's own VIP
configuration lives entirely inside that subsystem's own already-
generated environment (opaque to this composer).

## What B8's real contribution actually is (not VIP dedup)

B8's `_subsystem_composition_mode()`/`manifest["subsystem_vip_binds"]`
wire is easy to mistake for VIP-dedup-adjacent because it touches
`verification_architecture.VipBindIR`, but it is **not** deduplication:
it is a **per-subsystem bind-chain classification** (does this
subsystem's own bind path cross a bridge, requiring an adapter?),
surfaced as an evidence annotation on that subsystem's own virtual-
sequencer field. It never compares one subsystem's VIP bind against
another subsystem's, never merges two bind records, and never decides
ownership of a resource shared across subsystems (that is
`system_resource_inventory.py`'s job, already delegated, unchanged).

## Disposition

```
what constitutes the same VIP              = N/A -- no cross-subsystem
  VIP identity concept exists in this module in any source
identity key (protocol/interface/instance/provider/source_path)  = N/A
who owns a shared VIP                       = N/A
how multiple subsystem requests reconcile   = N/A (each subsystem's own
  VIP config is opaque to this composer -- no reconciliation attempted)
configuration-conflict detection            = N/A
System-Level VIP reuse-vs-duplicate         = N/A

VIP_DEDUP_BOUNDARY = RESOLVED (genuinely out of scope for this file, in
  every source; not deferred because there is nothing here to defer --
  correctly belongs entirely to CAP-M5-VIP-001/Cohort 3's own scope,
  which operates on env_manifest.py/vip_capability_extraction.py, a
  different pair of files with a real VIP-identity concept)
```

No heuristic with unsupported identity semantics was merged, because none
was found in any source for this file.
