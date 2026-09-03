# Gap close — Section 4: Harness reliability (dry-run, checkpoint/rollback, degradation, self-test)

**Verdict: DONE** (4a, 4b re-confirmed READY, no change; 4c and 4d were both
genuinely bounded PARTIALs and are now closed for real).

Date: 2026-09-04. Scope: Section 4 only. Every other file in this repo was
left alone; `dv_harness/engine.py` was patched by hand-scoped edits (3 hunks,
63 lines, all mine — verified with `git diff` before staging) because other
workflows are concurrently active in it.

---

## 4a — Dry-run mode: READY, re-confirmed, no change

Re-confirmed the cited evidence rather than taking it on trust:

- `dv_harness/engine.py` `_dry_run_stage()` reuses `_gather_stage_context(dry_run=True)`
  — the same context-building path a real run uses, so the plan is byte-identical
  to what would have been sent, not an approximation.
- CLI-wired on both `start` and `run-stage` (`--dry-run`), ORed with
  `config.json`'s `dry_run.enabled`; documented in
  `docs/ENGINE_STAGE_LIFECYCLE.md` §2.
- `TestDryRun` passes in the full reliability suite run below.

Nothing to build. No file touched for this item.

## 4b — Checkpoint and rollback: READY, re-confirmed, no change

Re-confirmed: `_auto_checkpoint()` fires at every real stage transition (PASS
and FAIL paths), retention (`prune_auto_checkpoints`, keep=10) provably never
deletes a human-named snapshot or a `_pre_restore_` undo backup,
`session_snapshot.restore_session()` is CLI-wired (`dv-harness restore-session`)
and auto-backs-up what it is about to overwrite so a rollback is itself
reversible. `TestAutoCheckpoint` passes in the run below. No file touched.

---

## 4c — Degradation path: PARTIAL → **closed**

### What the audit found (and what I re-verified before building)

`dv_harness/degradation.py`'s three triggers were real and correct, but two of
the three could not fire. The license-full and farm-congested triggers need a
probe transport, and:

- `degradation.probe_resources` defaulted `False` (`dv_harness/config.py`),
- `DVHarness.degradation_runner` defaulted `None`,
- and `grep -rn "degradation_runner\|probe_resources" dv_harness/cli.py`
  returned **0 matches** — re-confirmed at the start of this pass.

So on this project's own deployment shape (PC-side, REMOTE_EXECUTION) only the
Claude-API trigger was live. The two farm triggers were correct, tested, and
**structurally unreachable** unless a human hand-edited `config.json` *and*
wrote Python to assign the attribute. That is a real, bounded, closeable gap:
the mechanism existed, the activation did not.

### What was built

**1. `preflight.resolve_transport()` — evidence-based transport resolution**
(`dv_harness/preflight.py`). New `TransportDecision` (requested / resolved /
available / reason / evidence / runner). `auto` arms a transport **only when a
real probe confirms one**:

- relay if `remote_exec.read_relay_info()` reports READY for the configured
  `$VCHOST`/`$VCHOP` hop (the same function `RemoteRelayCommandRunner` itself
  calls, so it can never claim a relay the runner would find missing), else
- `LocalCommandRunner` if `lmutil` **and** `bqueues` are genuinely on PATH, else
- **nothing** — `resolved="none"`, `runner=None`.

That last branch is why `auto` is safe as a default: a machine that can confirm
neither transport behaves exactly as before. Turning "command not found" into a
DEGRADED verdict — the fabricated conclusion `probe_resources` was made opt-in
to prevent — remains impossible. An explicit `local`/`remote_relay` request is
honoured (that is what explicit means) but still carries the real probe
evidence, so "you asked for local and lmutil is not on PATH" is visible instead
of silent. A typo in `config.json` fails toward `none`, never toward an
unintended live probe.

**2. An injected Runner arms the probe on its own** (`degradation.evaluate()`).
Exactly the rule `engine._execution_preflight_gate()` already stated for its own
transport — an injected transport *is* the statement that a real probe is
possible here. Without this, a resolved transport still could not reach
`check_license()`/`check_queue_health()`, because `evaluate()` returned
immediately on `not probe_resources`.

**3. Wiring, so something shipped actually chooses.**
- `DVHarness.__init__` resolves and installs the transport
  (`degradation_transport` / `degradation_runner`); `_resolve_degradation_transport()`
  is best-effort so a broken resolution leaves the harness transport-less
  rather than unbootable.
- `DVHarness.set_degradation_transport()` — the CLI flag's call site.
- `dv-harness --degradation-transport {auto,local,remote_relay,off}`, a
  top-level flag (the harness is constructed once, so it applies to every
  subcommand).
- `$DV_HARNESS_DEGRADATION_TRANSPORT` per-process override, and
  `degradation.transport` in `config.json` (default `"auto"`).
  Precedence: flag > env > config.
- `dv-harness status` now prints `degraded_probe_transport` (the full decision
  with its evidence) and `degraded_resource_triggers_armed`, so "those two
  triggers cannot fire on this machine" is a printed answer, not a silence.
- `docs/ENGINE_STAGE_LIFECYCLE.md` §4 rewritten — it previously documented the
  hand-write-Python route as the answer.

### Real end-to-end evidence (not just tests)

On this actual machine, right now:

```
$ python -m dv_harness.cli --project-root . status
"degraded_probe_transport": {"requested": "auto", "resolved": "remote_relay",
  "available": true, "reason": "auto: persistent relay is READY for the
  configured VCHOST/VCHOP hop -- probing the real DV server through it.",
  "evidence": {"relay": {"ready": true, "detail": "RELAY_READY",
  "vchost": "vchost-b", "vchop": "host-c"}}}
"degraded_resource_triggers_armed": true
```

and the resolved transport really probes the real server:

```
resolved: remote_relay True
  eda_license      SKIP | License check not configured; skipped per require_license_configured=False.
  lsf_queue_health PASS | queue 'vcs' status=Open:Active
```

That `Open:Active` is real `bqueues vcs` output from the real Linux DV server,
fetched through the sanctioned credential-free relay by the auto-resolved
transport. The farm-congested trigger is now genuinely live on this deployment.
(The license check SKIPs because this project has never configured
`preflight.license_server` — preflight's own three-valued outcome, and SKIP
never triggers degradation. That is the correct non-fabricating answer, not a
failure.)

### Test-suite safety

`degradation.transport: "auto"` resolving to a LIVE relay on a developer
machine would have made the test suite issue real `lmstat`/`bqueues` round
trips to production from `DVHarness.__init__` onward. Added
`dv_harness_tests/conftest.py`, which pins `$DV_HARNESS_DEGRADATION_TRANSPORT`
to `off` for the whole suite at conftest import time (before collection, so a
module-level `DVHarness(...)` is covered). `test_harness_reliability._fresh()`
now asserts the pin held, so this cannot silently regress.

---

## 4d — Harness self-test CI: PARTIAL → **closed**

### What the audit found

`tools/testing/self_test.py` is real and passes, but **nothing ran it
automatically**. `tools/self_test.sh` is typed by hand;
`.github/workflows/dv-harness-ci.yml` is well-formed but has never fired —
re-confirmed: `origin` exists (`https://github.com/YuTienL/DV_Agent_Harness.git`)
but `git ls-remote origin` returns no refs, so there has never been an Actions
run. "Real, correct, and only run when a human remembers" is exactly the
silent-infrastructure-rot failure mode the script was written against.

### What was built

**1. A trigger that genuinely fires here today.** `core.hooksPath` is already
`tools/git-hooks`, so `tools/git-hooks/pre-push` gained a second gate after the
existing governance gate: it runs the fast harness-specific checks
(`import-sanity` + `self-audit`, ~50s) and **aborts the push** on failure.
`cli-help-sanity` is deliberately excluded — ~7 minutes would train people to
bypass the gate; it stays in the full manual/CI pass. Fails OPEN only on an
unrelated environment problem (no python, script absent); a self-test that
really ran and really failed fails CLOSED. Documented bypass:
`DV_HARNESS_SKIP_SELF_TEST=1`.

**2. A run record**, so "has an automated trigger ever actually executed this?"
is answerable from a file rather than from memory. `--record` / `--trigger
{manual,pre-push,ci,scheduled}` appends to `.dv-harness/self_test/runs.jsonl`
and rewrites `last_run.json` (ts, trigger, per-check ok/seconds, failed checks,
git sha, host, user, python). Opt-in, so an ordinary hand-run does not dirty
the tree and the history stays an honest record of *automated* runs.
Gitignored — a per-machine execution log, not shared history.

**3. CI honesty + a standing trigger.** The workflow's "no GitHub remote is
configured" disclosure was stale; corrected against real command output (remote
exists, is reachable, is empty, has never run). Added a nightly `schedule:`
trigger — push/PR only fire when someone is already changing something, and a
harness nobody touched for two weeks while a dependency moved would report
nothing. Added a `--record --trigger ci|scheduled` step plus artifact upload.

### A real defect this surfaced

Wiring the trigger immediately found something a hand-run never had:
`import-sanity` **failed** on `dv_harness.mcp.server` because the hook's
interpreter has no `mcp` SDK. Two real findings, both fixed:

- **`mcp` is an OPTIONAL dependency.** `requirements-harness.txt`'s first line
  is "Core harness uses Python standard library only" and every entry there is
  annotated "Optional"; `pyproject.toml` declares no runtime dependencies at
  all. So the check was reporting absent-by-choice as broken — and it would
  have done the same on a GitHub runner, where `pip install -e .` installs
  nothing. `run_import_sanity()` now reports a `ModuleNotFoundError` for a
  declared-optional package as **SKIPPED with the real reason** (read from the
  real requirements file, not hardcoded), printed on every run, never silent. A
  `ModuleNotFoundError` naming a `dv_harness.*` module still FAILS, as does any
  other exception. Verified both ways: `python3` (no `mcp`) → PASS with one
  printed SKIP; `python` (has `mcp`) → PASS with no skips.
- **`python3` and `python` are different installs on this machine**
  (`...\pythoncore-3.14-64` vs `C:\Python314`), only one with the project's
  optional packages. "Whichever is on PATH first" is not a safe assumption for
  a gate, so the hook gained `DV_HARNESS_HOOK_PYTHON` to pin the interpreter;
  both gates use the same one.

---

## Tests

New: `dv_harness_tests/test_self_test_gate_e2e.py` (8 tests) and
`TestDegradationTransportResolution` + `TestDegradationTransportWiring`
(13 tests) in `dv_harness_tests/test_harness_reliability.py`. Plus
`dv_harness_tests/conftest.py`.

End-to-end, not unit-level:

- **A real `git push`** into a throwaway local bare remote, through git's own
  hook runner against this repo's real `tools/git-hooks/pre-push`, running the
  real `self_test.py` against this repo — asserts the push succeeded and a real
  `trigger=pre-push` record with a non-zero check duration landed.
- **A failing self-test really aborts a real push** — asserted on the remote's
  refs (`[] == _remote_refs(remote)`), not on hook output.
- The documented bypass really bypasses, and records nothing.
- A missing script fails open.
- **The governance gate still runs first and still blocks an agent**, and the
  self-test does not run after a governance BLOCK — a regression guard on the
  hook's stdin-ordering (git feeds the refspecs on stdin and stdin can be read
  only once).
- A real stage `run_stage()` degrades through the resolved transport: parks in
  WAIT_USER on `farm_queue_congested`, with **zero adapter calls** (只收集資料、
  不做判斷). Only the Runner object is a mock.
- The run record is written for a FAILING run too (an audit trail that only
  exists on success is not an audit trail).

Also adapted `dv_harness_tests/test_git_hooks_e2e.py` to set the documented
bypass — those tests are about the governance gate and would otherwise pay ~50s
of self-test per push; the self-test gate has its own coverage above, including
the ordering assertion.

**Test summary — all green:**

| run | result |
|---|---|
| `test_harness_reliability.py` | **40 passed** (was 27; +13 new) |
| `test_self_test_gate_e2e.py` | **8 passed** (new) |
| `test_git_hooks_e2e + test_preflight + test_git_governance + test_execution_preflight_wiring` | **97 passed** |
| every remaining test file that constructs `DVHarness` (18 files — the full blast radius of the engine + conftest change) | **455 passed** in 40:49 |
| `tools/testing/self_test.py --skip-pytest` | import-sanity **PASS**, cli-help-sanity **PASS** (every subcommand's `--help`, incl. the new flag), self-audit **PASS** |

`python -m pytest dv_harness_tests/ -q` (all 3348) reached 45% before being cut
short — three other workflows were running the same full suite concurrently on
this machine. It surfaced exactly **one** failure,
`test_dashboard_interactive.py::test_start_loop_true_advances_through_multiple_stages_in_background`,
which is a wall-clock deadline test (90s for 33 stages × 145 real gate-script
subprocesses). **Proved pre-existing, not mine**: it fails identically at
unmodified HEAD in a clean `git worktree` with none of these changes and no
`conftest.py` present (139.85s). The blast-radius run above covers every file
that could actually be affected by the engine/conftest change, with zero
failures.

---

## Adjacent gap NOT closed (out of scope, reported not fixed)

`DVHarness.execution_preflight_runner` (`_execution_preflight_gate()`, added by
a concurrent workflow earlier today) has the **identical** structural gap 4c
had: `execution_preflight.probe_resources` defaults False, the runner defaults
None, and nothing in `cli.py` injects one. The resolver built here
(`preflight.resolve_transport()`) is deliberately generic and would wire it in a
few lines, but that gate belongs to the governance-architecture workstream, not
Section 4, and its owner is concurrently editing `engine.py`. Flagged for
whoever owns it.
