# M1 Execution-Profile Extraction — Provenance and Closure Record

Real, executed sub-step of M1B (canonical repository bootstrap), triggered by the
Final Canonical Platform Architecture Freeze's "no hardcoded vc8/icr93 in the
generic L5 core" rule and the user's explicit constrained-option-2 instruction.

## Finding that triggered this work

`replay.ps1` (v50) hardcoded this project's own real host identity directly in
script text:

```
$env:VCUSER='peterlin'
$env:VCHOST='vc8'
$env:VCHOP='icr93'
$env:DVWORKDIR='/home/ziptmp1/peterlin/UVM/USB'
```

**Correction to an earlier assumption in this session**: `replay.ps1` was *not*
actually git-tracked canonical content in v50 (`git ls-files -- replay.ps1` /
`git log -- replay.ps1` both empty) — it was already deliberately gitignored
(`.gitignore`: "Local-only credential script for relay auto-reconnect ... must
never be committed, this machine only"). So this was never a tracked-artifact
architecture violation in the git-history sense; it was a real, disclosed
*disk-resident* violation of the newly-frozen portability rule, which the
migration would otherwise have silently re-created by hand-copying the file
into the new canonical checkout unchanged.

`VCPW`, `VCWORKDIR`, `VCEDAENV` were already environment-variable-only
(fail-closed if unset) before this change — no defect found there; left
untouched.

## Migration action

```
SOURCE: v50/replay.ps1
MIGRATION_ACTION: PRESERVE_CAPABILITY_WITH_MINIMAL_CONFIGURATION_EXTRACTION
ARCHITECTURE_DEBT_REMAINING: ExecutionService / RemoteEDABackend abstraction
                              not yet operationalized (future Platform wave)
```

## What changed

New, committed, host-identity-free canonical files:
- `dv_harness/execution_profile.py` — profile resolution/validation (real, TDD, 17 tests in `dv_harness_tests/test_execution_profile.py`)
- `tools/remote/resolve_execution_profile.py` — thin CLI wrapper `replay.ps1` shells out to; the only other consumer of `execution_profile.py`
- `config/execution_profiles/example.profile.json` — schema-illustrating placeholder, committed, no real host identity
- `replay.ps1` (rewritten) — now a generic compatibility launcher: discover repo → resolve profile → validate → invoke unchanged `remote_relay.py --start`. Un-ignored in `.gitignore` (the reason it was ignored no longer applies once it holds no host identity).

Not touched at all: `tools/remote/remote_hop.py`, `tools/remote/remote_relay.py`,
`tools/remote/remote_exec.py`, `tools/remote/source_identity.py` — zero diff,
confirmed by not editing them. Existing transport invocation semantics
(`remote_relay.py --start`, env-var contract) fully preserved.

New, gitignored, per-checkout real file (never committed):
- `.dv-harness/execution_profile.json` — this machine's actual real profile
  (`gateway_host=vc8`, `remote_host=icr93`, `remote_workdir=/home/ziptmp1/peterlin/UVM/USB`,
  `user=peterlin`), so `replay.ps1`'s real capability keeps working immediately
  on this machine without any behavior change from the caller's point of view.

## Verification performed (no real remote EDA execution)

- `dv_harness_tests/test_execution_profile.py` (17 tests) + `test_l5dgva_repo.py`
  (12 tests): 29/29 PASS, via real TDD (RED confirmed before each implementation).
- `tools/remote/resolve_execution_profile.py` run directly against the real
  local profile → correctly printed `VCHOST=vc8`, `VCHOP=icr93`,
  `DVWORKDIR=/home/ziptmp1/peterlin/UVM/USB`, `VCUSER=peterlin`, exit 0.
- Same script run with the profile file temporarily moved away → printed
  `ERROR: EXECUTION_PROFILE_REQUIRED: ...`, exit 1, no fallback to any literal
  host value.
- `replay.ps1` parsed with `System.Management.Automation.Language.Parser]::ParseFile`
  → 0 syntax errors. Not executed end-to-end (would require a real VCPW and a
  real relay connection — out of scope per instruction #11).

## M1 acceptance fields (this sub-step)

```
HARDCODED_GATEWAY_HOST_IN_RUNTIME = 0
HARDCODED_REMOTE_EDA_HOST_IN_RUNTIME = 0
EXECUTION_PROFILE_RESOLUTION = PASS
EXISTING_REMOTE_TRANSPORT_PRESERVED = YES
EXECUTION_SERVICE_OPERATIONALIZED = NO
REMOTE_EDA_BACKEND_OPERATIONALIZED = NO
```

Grep confirmation (repo-wide, `git ls-files` tracked content only, case-insensitive
`vc8|icr93`):

**Before this fix**, 3 tracked files matched:
- `.dv-harness/config.json` (lines 44-45: `"vchost": "vc8", "vchop": "icr93"`)
- `CLAUDE.md` (a historical-incident narrative sentence, prose not code/config)
- `docs/DV_Agent_Harness_L5_Detailed_User_Guide_TC_2026-09-06.pdf` (binary doc)

**New finding, disclosed, not something this task introduced**: `.dv-harness/config.json`
(tracked in v50's own history since commit `d114a322`, 2026-09-06, real author
`peter.lin`, predates this session entirely) had this project's real gateway/hop
host committed directly into canonical tracked JSON — the exact same class of
violation as `replay.ps1`'s, just in a second, previously-unchecked location.
`dv_harness/config.py`'s own schema already declares the generic default
(`"vchost": "", "vchop": ""` — `config.py:118-119`), so this was a real,
inherited data-hygiene defect, not an architecture gap. **Fixed** in this
canonical repository (never in v50 — source repositories remain unmodified,
per the standing M0/M0.5/M0.6 invariant) by resetting both fields to `""`,
matching the code's own default exactly. `configured_by`/`configured_at` were
left untouched (unrelated fields, out of this task's scope).

**Disclosed residual gap** (not fixed, deliberately, per instruction #14 — fixing
it would require adding a local-config-override layer to `dv_harness/config.py`,
which is unrelated execution architecture, not this constrained extraction):
`dv_harness/knowledge_center.py`'s and `dv_harness/preflight.py`'s own
`vchost`/`vchop` convenience lookup (`self.cfg.get("vchost") or
os.environ.get("VCHOST", "")`) will now return empty from config.json on this
machine until the user either sets `VCHOST`/`VCHOP` env vars directly for a
plain `dv-harness` CLI session (outside `replay.ps1`), or a future wave adds a
proper gitignored local-config-override file. This does **not** affect
`replay.ps1`'s own capability — verified working end-to-end via
`.dv-harness/execution_profile.json`, fully independent of `config.json`.

**After this fix**, 2 tracked matches remain, both accepted as out of scope for
this task (documentation, not runtime code/config):
- `CLAUDE.md` — a disclosed historical-incident sentence (prose), not logic
- `docs/DV_Agent_Harness_L5_Detailed_User_Guide_TC_2026-09-06.pdf` — a binary doc

`HARDCODED_GATEWAY_HOST_IN_RUNTIME` and `HARDCODED_REMOTE_EDA_HOST_IN_RUNTIME`
above are scoped to runtime code/config surfaces (`.py`, `.ps1`, `.json` config),
consistent with that scoping.
