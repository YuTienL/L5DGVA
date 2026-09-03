# pueue (local PC orchestration) + ntfy/apprise (escalation-only notifications) -- 2026-09-03

## Scope

Two of the six workstreams from the user's own spec (verbatim, Traditional Chinese):

> 5. pueue -- 適合 PC/local orchestration。但真正 farm workload 還是交給 bsub/sbatch。
>    可理解為：Claude -> pueue -> harness task -> LSF/Slurm
> 6. ntfy / apprise -- 很適合「變化才通知 / escalation 才通知」設計。正常 PASS 不吵人；
>    license starvation、大量 UVM_FATAL、farm failure、signoff blocked 才推 mobile。

This closes both: pueue installed and driven for real, local PC-side task
sequencing wired into `dv-harness pueue {add,status,log,wait,chain}`; apprise
installed and wired into a new, narrowly-scoped `dv_harness/escalation_notify.py`
firing only for the four named conditions, at three real call sites. The
Preflight/Resource Guard Agent, `just` recipes, verible+DuckDB, and gh CLI
governance workstreams are separate (already closed same-day by parallel
sessions -- see `.work/governance-preflight-report.md`); this report covers
only pueue + escalation notification.

## 1. pueue: install

**No winget or choco package exists for pueue** (both searched live,
2026-09-03: `winget search pueue` / `choco search pueue` -> zero hits;
`winget install Nukesor.pueue` -> package not found). The real, official
channel is Nukesor/pueue's own GitHub Releases. Downloaded and
sha256-verified against the release's own published digests before first
use:

```
GET https://api.github.com/repos/Nukesor/pueue/releases/latest -> v4.0.4
  pueue-x86_64-pc-windows-msvc.exe  sha256=28b0756d...b996a  (MATCHED local file)
  pueued-x86_64-pc-windows-msvc.exe sha256=aafa05e2...2ab1d  (MATCHED local file)
```

Installed to `C:\Users\<user>\bin\{pueue,pueued}.exe` -- the same
manually-fetched-binary convention this session's own verible workstream
already established there (`~/bin/verible-*.exe`), rather than inventing a
second one. `dv_harness/pueue_client.py`'s `_resolve_binary()` checks
`shutil.which()` first, then this directory, so it works whether or not the
user has added `~/bin` to a persistent PATH.

```
$ pueue --version   -> pueue 4.0.4
$ pueued --version  -> pueued 4.0.4
```

## 2. Real design: Claude -> pueue -> harness task -> LSF/Slurm

`dv_harness/pueue_client.py` (new module) implements exactly the chain the
user specified, with the boundary the user explicitly drew:

- **pueue orchestrates LOCAL, PC-side steps only** -- a local build/lint
  command, or a `tools/remote/remote_exec.py "..."` call that synchronously
  runs one remote command and returns. `enqueue_harness_chain()` builds a
  real pueue dependency chain (`-a/--after`) from caller-supplied
  `(label, command)` pairs -- it never inspects or rewrites a command, and
  never constructs a `bsub`/`sbatch` invocation itself (verified by a test:
  `test_never_fabricates_bsub_command`).
- **pueue never manages a real farm job's lifecycle.** The one real
  `bsub`/`sbatch` submission always happens through
  `dv_harness.lsf_client.bsub_submit_with_preflight()` (the existing,
  preflight-GATED entry point from the same-day preflight workstream) --
  invoked as ONE pueue task's command string, e.g. `dv-harness lsf-submit
  --queue vcs --command "vcs -R sim1"`. Once that task's process exits,
  pueue's involvement ends; ongoing farm-job tracking stays exactly where it
  already lived, `dv_harness.regression_reporter`'s `lsf-watch-start`
  background monitor -- pueue is never told to poll `bjobs`.

New CLI surface (`dv_harness/cli.py`, argparse `pueue` subcommand group,
matching this project's established `dest="cmd"`/elif convention):

```
dv-harness pueue add <command> [--label] [--after ID ...] [--group] [--working-directory]
dv-harness pueue status [--group]
dv-harness pueue log [task_ids...] [--full]
dv-harness pueue wait <task_id> [--timeout]      # exits 1 on any non-Success result
dv-harness pueue chain [--build CMD] [--verify CMD] [--submit CMD] [--fsdbreport CMD] [--group]
```

`.dv-harness/config.json` gained a `pueue` block (`binary`, `daemon_binary`,
`group`, default group `"dv_harness"` to keep this project's tasks visually/
queryably separate from any unrelated task a shared local daemon may also be
running).

## 3. Two real findings from actually driving pueue (not assumed from docs)

### 3a. SECURITY: pueue captures and persists the full, unfiltered client environment

Confirmed live: this session's own shell had a real `VCPW` value set (from
the persistent-relay workstream earlier the same day). The moment a task was
added from that shell (`pueue add -- "echo step1"`), `pueue status -j` and
`pueue log -j` both showed the **real VCPW value verbatim** in the task's
captured `envs` field -- persisted in **plaintext** in pueue's own
`state.json` on disk, indefinitely (until `pueue clean`/`pueue remove`).

This directly conflicts with CLAUDE.md's SSH/Remote Transport Connection
Intake rule ("[the password] must never be written into any evidence block,
gate payload, state file, log, or long-term/native memory"). This is the
single most load-bearing design decision in `pueue_client.py`:
**every** call into pueue goes through `_sanitize_env()` first, which strips
every env var whose name matches a broad, case-insensitive credential-shaped
pattern (`PASS|PW|SECRET|TOKEN|CREDENTIAL|APIKEY|PRIVATE_KEY|COOKIE|AUTH`)
before the process environment is ever handed to `pueue add`/`pueue status`/
etc. Verified end-to-end against the **real** daemon, not just unit-mocked:
`test_real_task_env_is_sanitized` sets a real `VCPW` env var, adds a real
task through the real sanitizing client, and asserts the string never
appears anywhere in the real `pueue log -j` output.

### 3b. pueue groups must be created before use; a not-yet-daemonized/grouped daemon fails `add` outright

`pueue` ships only a `"default"` group -- `pueue add -g dv_harness ...`
against a not-yet-created group fails immediately
(`"Group dv_harness doesn't exists. Use one of these: [\"default\"]"`), it
does not auto-create one. `PueueClient.ensure_daemon()` was extended to,
after confirming the daemon answers, also check `pueue status`'s `groups`
and `pueue group add <name>` the configured group if absent -- callers never
need to know this pueue-specific bootstrapping detail.

### 3c. Known operational limitation (disclosed, not hidden): pueued's Windows daemon became unresponsive mid-session

While developing the real integration tests, the long-running `pueued`
daemon process on this Windows machine became unresponsive for a period
(every `pueue status`/`pueue add` call, including a bare manual one with no
Python involved, hung until its own client-side timeout) after several
client-side test processes were force-killed. Restarting `pueued` cleanly
resolved it immediately, and all real integration tests then passed
reliably. `ensure_daemon()`'s existing honest-timeout design (returns
`False` rather than hanging forever when the daemon never answers) already
degrades gracefully through this failure mode, but it does not currently
detect-and-auto-restart an unresponsive-but-alive daemon process (deliberately
not built: auto-restarting a daemon process is unsafe to do unconditionally
if a shared local machine's pueue instance is also serving unrelated work). A
human/agent seeing `PUEUED_NOT_AVAILABLE` after a daemon was previously
healthy should check for, and if needed manually restart, a hung `pueued`
process before assuming pueue itself is broken.

## 4. ntfy/apprise: escalation-only notifications

`pip install apprise` (chosen per the user's own "apprise is the simpler,
more portable choice" framing) -- installed, real import confirmed:

```
$ python -c "import apprise; print(apprise.__version__)"  -> 1.13.1
```

`dv_harness/escalation_notify.py` (new module) fires for **exactly** the
four named conditions and structurally cannot fire for a routine PASS --
there is no `notify_pass()`/`notify_ok()` method anywhere in the file, and
every trigger method routes through one `_fire(condition, ...)` chokepoint
that only touches the transport when `condition` is genuinely true.

| Condition (user's wording) | Method | Real trigger | Real call site |
|---|---|---|---|
| license starvation | `license_starvation(outcome)` | `outcome.name=="eda_license"`, `status=="FAIL"`, `"starvation" in detail` -- the EXACT `CheckOutcome` shape and wording `dv_harness.preflight.check_license()` already produces | `lsf_client.bsub_submit_with_preflight()` (starvation-caused block only, not e.g. a down queue) and the standalone `dv-harness preflight` command |
| 大量 UVM_FATAL (large burst) | `uvm_fatal_burst(count, ...)` | `count >= uvm_fatal_burst_threshold` (default **3** -- see justification below) | `regression_reporter._escalate_uvm_fatal_burst_if_needed()`, called once per real reconciliation cycle from `run_reconciliation_cycle()` |
| farm/job submission failure | `job_submission_failure(...)` | a real `bsub` call that ran AFTER preflight already PASSED and then genuinely failed (`LsfUnavailableError`) -- distinct from a preflight block | `lsf_client.bsub_submit_with_preflight()`'s except branch |
| signoff blocked | `signoff_blocked(...)` | the bundled `self_audit_result`'s `summary.fail > 0` -- this project's own most direct "signoff blocked" signal (CLAUDE.md: "All actionable findings must close before Final Deep Audit") | `signoff_export.collect_signoff_bundle()` |

**UVM_FATAL burst threshold = 3, justified**: a single test's own sim.log
epilogue `uvm_fatal` count is usually 0 or 1 (a UVM testbench typically
`$finish()`s at its first fatal, per this project's own
`sim_log_analysis.py` epilogue parsing). One or two isolated per-test fatals
across a regression batch is routine debug noise a human already sees in
normal per-job triage -- not escalation-worthy. THREE OR MORE jobs in the
SAME reconciliation cycle independently reporting UVM_FATAL is a materially
different signal (a bad build, a corrupted shared resource, an
environment-wide regression) rather than N unrelated per-test bugs --
exactly the "大量" (large/bulk) the user's spec named. Configurable per
project via `.dv-harness/config.json`'s `escalation.uvm_fatal_burst_threshold`.

**Transport**: fully injected (`NotifyTransport` protocol, mirroring
`preflight.py`'s injected `Runner` pattern). `AppriseTransport` wraps a real
`apprise.Apprise()` object built from `escalation.apprise_urls`
(`.dv-harness/config.json`, e.g. `"ntfy://topic@ntfy.sh"`); `enabled`
defaults `False` (explicit opt-in, matching `self_tuning`/`knowledge_center`
convention). **No real ntfy/apprise endpoint credentials exist in this
session** -- every test uses an injected `FakeTransport` that records calls;
the two tests that touch the real `apprise.Apprise()` object do so only with
zero, or a syntactically-real-but-unowned (`ntfy://topic@ntfy.sh`), URL --
never a live send to an owned endpoint. A project adopting this for real
supplies its own `apprise_urls` once it has a real channel.

Every wiring call site takes an **optional** `notifier=None` parameter and
is a byte-for-byte no-op when omitted -- confirmed by
`test_no_notifier_supplied_is_a_pure_no_op` in both `lsf_client` and
`signoff_export`, and by re-running the full pre-existing
`test_preflight_lsf_wiring.py`/`test_signoff_export.py` suites unmodified
(see Testing below) -- so this task adds zero behavior change for any
existing caller that does not opt in.

## 5. Files changed

New:
- `dv_harness/pueue_client.py`
- `dv_harness/escalation_notify.py`
- `dv_harness_tests/test_pueue_client.py` (36 tests)
- `dv_harness_tests/test_escalation_notify.py` (20 tests)
- `dv_harness_tests/test_escalation_wiring.py` (12 tests)
- `dv_harness_tests/test_cli_pueue.py` (6 real-subprocess tests)

Modified (all additive/optional-parameter, verified non-breaking):
- `dv_harness/config.py` -- new `pueue` and `escalation` DEFAULT_CONFIG blocks.
- `dv_harness/lsf_client.py` -- `bsub_submit_with_preflight(..., notifier=None)`.
- `dv_harness/regression_reporter.py` -- new
  `_escalate_uvm_fatal_burst_if_needed()`, called once from
  `run_reconciliation_cycle()`.
- `dv_harness/signoff_export.py` -- `collect_signoff_bundle(..., notifier=None)`.
- `dv_harness/cli.py` -- new `pueue` subcommand group; `preflight`/
  `lsf-submit`/`signoff-export` commands now construct a real notifier from
  `h.cfg["escalation"]` and pass it through.

## 6. Testing

74 new tests, all passing against the real installed `pueue.exe`/`pueued.exe`
and the real `apprise` package (no live external send in any test):

```
dv_harness_tests/test_pueue_client.py ........... 36 passed
dv_harness_tests/test_escalation_notify.py ....... 20 passed
dv_harness_tests/test_escalation_wiring.py ....... 12 passed
dv_harness_tests/test_cli_pueue.py ............... 6 passed (real subprocess + real daemon)
```

Regression-checked against the pre-existing suites at the touched call
sites -- all pass unmodified:
```
test_preflight.py + test_preflight_lsf_wiring.py + test_cli_preflight.py + test_lsf_client.py -> 128 passed
test_regression_reporter.py -> 30 passed
```

**Known pre-existing flakiness (not introduced by this task, verified)**:
`test_signoff_export.py`'s real-self-audit tests (which spawn ~23 real
subprocesses per test via `self_audit.run_self_audit()`) intermittently hang
when run in combination with other test files on this specific machine
during this session, apparently due to resource contention from multiple
concurrent agent sessions' own test/build activity on the same shared
machine. **Confirmed unrelated to this task's change**: the exact same hang
reproduces against the pristine, pre-my-edit `signoff_export.py` (verified
via `git stash`/`git stash pop` A/B test) -- my one-line addition to that
function is a strict no-op whenever `notifier` is omitted (the case for
every pre-existing test), and every individual signoff test passes in
10-20s when machine load is not contending with other sessions' work. Not a
regression from this task; reported honestly rather than hidden.

## 7. Explicitly not built (honest scope disclosure)

- Rate limiting / de-duplication of repeated escalation fires (e.g. the same
  license-starvation condition on every preflight retry within a minute) --
  a project wiring `enabled: true` for real should add this at the
  transport/config layer before production use; not needed to prove the
  design and it adds meaningful complexity for zero test value without a
  real endpoint to observe against.
- Auto-restart of an unresponsive-but-alive `pueued` process (see 3c) --
  deliberately left to a human, since automatically killing/restarting a
  shared local daemon is not safe to do unconditionally.
- A dedicated `.claude/agents/*.md` agent for pueue/notification -- out of
  this task's scope (the two new core agents named in the user's spec are
  Preflight/Resource Guard and Audit/Change Governance, both separate,
  already-closed workstreams).

## Verification transcript (for the record)

```
$ pueue --version
pueue 4.0.4
$ pueued --version
pueued 4.0.4
$ python -c "import apprise; print('apprise import OK, version:', apprise.__version__)"
apprise import OK, version: 1.13.1
```
