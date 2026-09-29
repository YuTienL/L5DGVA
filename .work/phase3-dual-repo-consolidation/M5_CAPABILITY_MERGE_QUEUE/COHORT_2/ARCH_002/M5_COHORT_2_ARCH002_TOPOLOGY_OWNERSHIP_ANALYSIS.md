# CAP-M5-ARCH-002 -- Topology / Ownership Contract Analysis

## Mapping to existing Canonical representations (Section 10)

Read the full canonical `soc_environment_composer.py` before concluding.
Result: this module deliberately does **not** define its own topology/
ownership schema. It maps the requested fields as follows:

| Requested field | Canonical representation | Owner |
|---|---|---|
| `ENTITY_ID` | `subsystem_registry_entries[i]["name"]` | this module, unchanged |
| `INSTANCE_ID` | not separately modeled -- one subsystem = one composed instance today (no multi-instance-of-same-subsystem composition exists in any of the 3 sources) | N/A |
| `SUBSYSTEM_OWNER` | the registry entry itself IS the subsystem's own identity record (`release_sha`/`qualification_state`) | `.dv-harness/soc-composer/subsystem_environment_registry.json`, written only by `engine.py`'s `_persist_subsystem_registry_entry()` on a real SIGNOFF PASS |
| `INTERFACE_OWNER` / `SHARED_RESOURCE` / `CONNECTIVITY` | `driver_conflicts`/`stopped_resource_ids`/`held_resource_ids`/`preferred_model` | delegated to `system_resource_inventory.real_cross_subsystem_findings()` via `cross_subsystem_findings()` -- **not reimplemented here** |
| `PROTOCOL` | implicit in the subsystem's own registered environment (never asked for by name -- this module is deliberately protocol-blind, per its own module docstring) | the composed subsystem's own `environment_manifest.json` |
| `SOURCE_PATH` | `subsystem_registry_entries[i]["environment_manifest"]` | resolved via `_resolve_subsystem_manifest()` |
| `VIP_PROVIDER` / `VIP_INSTANCE` | **new this wave, B8's contribution only**: `manifest["subsystem_vip_binds"][name]` (a list of `verification_architecture.VipBindIR` records) -- but only as an evidence ANNOTATION on the virtual-sequencer field, never a new ownership model | `verification_architecture.py` (pre-existing, unchanged), consumed via the new `_subsystem_composition_mode()` helper |
| `PARENT_TOPOLOGY_NODE` | not modeled -- SYSTEM_LEVEL_MODE composition is a flat list of registered subsystems, no nesting in any source | N/A |

## Conclusion

No new field was invented to satisfy this list (per the instruction's own
"the objective is semantic clarity, not schema proliferation"). Every
concept the instruction names either already has a real Canonical home
(delegated to `system_resource_inventory.py`), or genuinely does not
exist in any of the 3 sources (`INSTANCE_ID`, `PARENT_TOPOLOGY_NODE`) and
is correctly left undefined rather than fabricated.

```
TOPOLOGY_OWNERSHIP_SEMANTICS = RESOLVED (mapped to existing delegation;
  nothing new required or merged this wave)
```
