# M1 config.json Residual-Consumer Gap — Decision Record

Per the instruction: "determine whether those lookups are required for M1 bootstrap
qualification; if not required, record `EXECUTION_CONFIG_CONSUMER_MIGRATION_PENDING`
for the future ExecutionService/config-unification wave; if they break mandatory M1
behavior, implement only the minimum adapter necessary to read the already-approved
execution-profile abstraction."

## Determination

M1's own approved scope is canonical-repository bootstrap + v50-baseline
qualification -- it explicitly excludes any real remote EDA execution (see
instruction #11 on the execution-profile extraction: "do NOT perform a real
remote EDA execution merely to qualify this configuration extraction"). Neither
`dv_harness/knowledge_center.py`'s nor `dv_harness/preflight.py`'s own
`vchost`/`vchop` convenience lookup is invoked by any M1 bootstrap/qualification
step -- both are only exercised when a caller actually attempts a live
relay-readiness probe or a real preflight check against a remote host, which is
out of scope for M1 by construction.

**Empirical confirmation**: resetting `.dv-harness/config.json`'s `vchost`/`vchop`
to `""` and re-running the full test suite (`.work/phase3-dual-repo-consolidation/M1_full_regression_output.txt`)
is the real evidence for whether any currently-passing test depended on the
tracked file's real committed values rather than its own test fixtures -- see
that file's final tally, cross-checked against the M0/H2-6 baseline failure
signature (21 failed / 13694 passed / 15 skipped), not just a raw count
comparison.

## Decision

**A. Not required for M1 bootstrap qualification** (pending the regression
cross-check above; will be revised to option C below if that regression finds
a NEW, config.json-vchost/vchop-caused failure not present in the M0 baseline
signature).

**B. Recorded**:

```
EXECUTION_CONFIG_CONSUMER_MIGRATION_PENDING = TRUE
  consumers:
    - dv_harness/knowledge_center.py (self._vc_host_hop(), config-then-env-var lookup)
    - dv_harness/preflight.py (RemoteRelayCommandRunner.__init__, config-then-env-var lookup)
  reason: both still read vchost/vchop from cfg.get(...) as their first-choice
    source, which is now honestly empty in canonical tracked config.json. Both
    already fall back to os.environ.get("VCHOST"/"VCHOP", "") as their second
    choice, so a caller running a live command outside replay.ps1 can still
    supply real values via env vars -- no capability is silently lost, only the
    convenience of "read from config.json" is currently unavailable without a
    manual env var or a local, uncommitted config.json edit.
  future_wave: the ExecutionService/config-unification wave (see the Final
    Canonical Platform Architecture Freeze) is the natural place to make these
    two call sites read the same execution-profile abstraction
    (dv_harness/execution_profile.py) that replay.ps1 now uses, so there is
    exactly one profile-resolution mechanism project-wide instead of two
    independent ones. NOT built during M1 (would be a second configuration
    architecture, explicitly out of scope per instruction #3).
```

No config.json host literal was reintroduced. No fallback to vc8/icr93 was
added anywhere.
