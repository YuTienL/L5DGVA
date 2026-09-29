# M1 — Location-Independence + Deployment-Copy-Mode Qualification

Per instructions #11/#12. Both performed as real copy-and-test exercises, not
asserted from code reading alone. Both temp copies deleted after qualification
(pure verification scaffolding, not deliverables).

## A. Relocation qualification (different absolute path AND basename)

`git clone D:\DV\Task\L5_DGVA D:\DV\Task\relocation_test_xyz789` (different
drive-relative path, different basename entirely — no "L5" or "DGVA" in the
name). A **synthetic test execution profile** was created there
(`gateway_host=relocation-test-gateway`, `remote_host=relocation-test-hop`) —
the real local profile was never copied or referenced, per instruction #11's
explicit "do not use the user's real remote profile in the relocated test."

Verified from the relocated copy:
```
discover_repo_root()        -> D:\DV\Task\relocation_test_xyz789 (correct)
detect_mode()                -> DEVELOPER_MODE
cross_check_git_root()       -> MATCH
is_l5dgva_repo()             -> True
execution-profile resolution -> PASS (test profile: VCHOST/VCHOP correctly
                                 resolved to the synthetic values, not vc8/icr93)
dv-harness doctor             -> all 18 fields render correctly, identical
                                 shape to the original checkout
core imports (dv_harness, graph, engine, cli, memory_vault, knowledge_center) -> OK
selected bootstrap tests      -> 42 passed, 1 xfailed (test_l5dgva_repo.py,
                                 test_execution_profile.py, test_dv_doctor.py,
                                 test_security_preservation_gate.py)
```

```
LOCATION_INDEPENDENT = YES
REPOSITORY_RENAME_SUPPORTED = YES
DEVELOPER_MODE_SUPPORTED = YES
```

Not exercised at the relocated copy (correctly out of scope for a repository-
identity/bootstrap qualification, and not required by instruction #11's own
list): OpenSpec (already `MISSING` in the source baseline itself — see
`dv_doctor.py`'s honest finding, not a relocation-specific gap) and Intake was
confirmed via `dv-harness doctor`'s `INTAKE_STATUS` field (`IMPLEMENTED`,
identical to the original checkout) rather than a full intake-flow run, which
is out of scope for a location-independence check.

## B. Deployment-copy-mode qualification (no git history)

`git archive HEAD | tar -x` into `D:\DV\Task\deployment_copy_test` — every
tracked file, zero `.git` directory (confirmed: `ls .git` → No such file or
directory). A synthetic test profile was created there too.

Verified from the git-free copy:
```
discover_repo_root()   -> D:\DV\Task\deployment_copy_test (correct --
                          identity comes from the marker file, not git)
detect_mode()          -> DEPLOYMENT_COPY_MODE (correct)
cross_check_git_root() -> GIT_CAPABILITY_UNAVAILABLE (honest capability gap,
                          never misreported as a generic L5DGVA failure)
dv-harness doctor       -> all 18 fields render; GIT_ROOT_CONSISTENCY correctly
                          shows GIT_CAPABILITY_UNAVAILABLE, every other field
                          identical/correct
selected bootstrap tests -> 38 passed (test_l5dgva_repo.py,
                          test_execution_profile.py, test_dv_doctor.py --
                          test_l5dgva_repo.py's own git-dependent sub-tests
                          still pass because the `git` EXECUTABLE remains on
                          PATH; only this copy's own repository lacks `.git`,
                          which is exactly what DEPLOYMENT_COPY_MODE means)
```

```
DEPLOYMENT_COPY_MODE_SUPPORTED = YES
```

Absence of git is correctly reported as `GIT_CAPABILITY_UNAVAILABLE`, never
classified as a generic L5DGVA bootstrap failure, per instruction #12.
