# Project Attach / Rehydration Requirements

ROADMAP requirements only. No production code implements this document.

## PROJECT_ATTACH_AND_REHYDRATION (`CAP-VELM-024`)

The act of a Fast Path (or Full L5DGVA) session recognizing a project as
L5DGVA-managed and reconstructing working context from it. Composed of:

```
PROJECT_LOCAL_IDENTITY      (CAP-VELM-025) -- the project knows what it is
PROJECT_CONTEXT_BOOTSTRAP   (CAP-VELM-026) -- Claude discovers that identity
QUALIFIED_ENVIRONMENT_SNAPSHOT (CAP-VELM-005) -- the last known-qualified
                                state to rehydrate FROM
```

## PROJECT_LOCAL_IDENTITY (`CAP-VELM-025`)

Real existing precedent: `dv_harness/l5dgva_repo.py`'s own
`is_l5dgva_repo()` (run at the PREFLIGHT of every wave this session
performed) already proves "can this directory identify itself as
L5DGVA-managed" is a solved problem -- but scoped to the ONE Canonical
repo, not to an arbitrary GENERATED project directory. `PROJECT_LOCAL_
IDENTITY` is the same concept, generalized to every generated project.

Required metadata fields:

```
PROJECT_ID
VERIFICATION_LEVEL
PROTOCOLS
GENERATION_ID
SCHEMA_VERSION
PROJECT_ROOT
MANIFEST_REF
OWNERSHIP_REF
LAST_QUALIFIED_SNAPSHOT_REF
CREATION_PROVENANCE
CURRENT_LIFECYCLE_STATE
```

**No credentials. No absolute bootstrap paths.** Both are hard
requirements, not preferences -- an absolute path would violate
`LOCATION_INDEPENDENT` (Article 0 P1) the moment the project is moved or
copied (Section 28's own explicit requirement: "moved/copied projects
remain attachable after config resolution").

## PROJECT_CONTEXT_BOOTSTRAP (`CAP-VELM-026`)

A compact, project-local file (not yet named/formatted -- a future
design decision, not frozen here) that tells Claude "this directory is
L5DGVA-managed" and points AT the identity/manifest/ownership/snapshot
references above, rather than containing them inline. **Never copies the
full Canonical `CLAUDE.md` into each project** -- this is a hard
requirement from this task's own Section 12, and is the direct
Fast-Path analog of the existing Context Budget's own Tier-1 "never into
context" discipline, applied to a new context boundary (a generated
project directory, not this session's own context window).

## Rehydration is not regeneration

Rehydration reconstructs CURRENT understanding from real, already-
existing evidence:

```
identity, manifests, ownership, provenance, snapshot, and RTL/spec/
OpenSpec/vPlan/files/evidence
```

It never triggers regeneration as a side effect of being asked to
understand a project -- the same discipline `reference_uvm_dut_top_
integration_manifest.py`'s own docstring already states for itself
("THIS MODULE DOES NOT CHANGE GENERATION BEHAVIOR"), generalized here to
the whole rehydration step, not just one discovery module.

## Validation

```
PROJECT_ATTACH_AND_REHYDRATION = ROADMAP_DEFINED
PROJECT_LOCATION_INDEPENDENT   = REQUIRED
```
