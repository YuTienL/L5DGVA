# Section 4 — Harness reliability (dry-run, checkpoint/rollback, degradation, self-test)

**Result: DONE** (one scoped commit: `c061983`)

**Test summary:** 59 passed — `test_self_test_gate_e2e` 11 (incl. 3 new), `test_harness_reliability` 40, `test_git_hooks_e2e` 8; `self_test.py --skip-pytest` all three checks PASS; workflow YAML re-parsed (4 triggers, 8 steps intact).

---

## Important context: the incoming audit was already partly stale

The audit finding handed to me marked **4c and 4d PARTIAL**. Re-verifying against *current* evidence rather than assuming, both had already been closed by commit `81ec667` ("reliability: make the DEGRADED farm triggers reachable, and give the self-test a real trigger", 2026-09-04 06:18) — a prior pass of this same task. I did **not** take that commit's own claims as proof. Each item below was re-checked by real execution.

One genuine, unclosed defect remained, which is what I fixed.

---

## 4a — Dry-run mode: **READY** (re-confirmed, untouched)

Line cites in the audit had drifted (engine.py grew); the mechanism is intact at current HEAD:

- `dv_harness/engine.py:2570` `_dry_run_stage()`, reusing `_gather_stage_context()` at `dv_harness/engine.py:2385` — the same context-builder a real run uses, so the plan is byte-identical rather than an approximation.
- CLI-wired at `dv_harness/cli.py:111,116`; config-wired via `dry_run.enabled` (`dv-harness status` reports `dry_run_mode`).
- `TestDryRun` passes within the 40-test `test_harness_reliability.py` suite.

No change made.

## 4b — Checkpoint and rollback: **READY** (re-confirmed, untouched)

- `dv_harness/engine.py:2921` `_auto_checkpoint()` → `dv_harness/session_snapshot.py:696` `save_auto_checkpoint()`, with bounded retention at `dv_harness/session_snapshot.py:673` `prune_auto_checkpoints()`.
- Rollback is real and itself reversible: `dv_harness/session_snapshot.py:750` `restore_session()` writes a `_pre_restore_` backup before overwriting.
- `test_auto_checkpoint_is_restorable_by_the_existing_restore_path` and `test_retention_never_deletes_human_named_or_pre_restore_snapshots` both pass.

No change made.

## 4c — Degradation path: **READY** (was PARTIAL; verified closed, not assumed)

The audit's specific gap was that `probe_resources` defaulted `False` and `degradation_runner` defaulted `None`, so on this project's real PC-side REMOTE_EXECUTION shape only the Claude-API trigger could fire — the license/queue triggers were "correct, tested, structurally unreachable."

Verified closed by **live execution through the shipped CLI**, not by reading code:

```
$ python -m dv_harness.cli --project-root . status
degraded_resource_triggers_armed = true
degraded_probe_transport = {"requested": "auto", "resolved": "remote_relay", "available": true,
  "reason": "auto: persistent relay is READY for the configured VCHOST/VCHOP hop
             -- probing the real DV server through it.",
  "evidence": {"relay": {"ready": true, "detail": "RELAY_READY", "vchost": "vchost-b", "vchop": "host-c"}}}
```

So on this actual deployment the two farm triggers are armed with **no hand-edited `config.json` and no hand-written Python** — exactly what the audit said was missing. The mechanism is `preflight.resolve_transport()` (`dv_harness/preflight.py:330`), which arms a transport only on real evidence and returns `resolved="none"` when nothing is confirmed, so a missing binary still cannot be misread as a full license or a jammed farm — the reason the flag was opt-in in the first place is preserved. Wired at `dv_harness/cli.py:112` (`--degradation-transport`), `$DV_HARNESS_DEGRADATION_TRANSPORT`, and `degradation.transport`.

No change made.

## 4d — Harness self-test: **DONE** — mechanism was real, its disclosure was false

**The trigger half is genuinely closed.** `tools/git-hooks/pre-push` is a real second gate in this repo's live `core.hooksPath` (`git config --get core.hooksPath` → `tools/git-hooks`), and `.dv-harness/self_test/runs.jsonl` holds real automated-execution evidence, including runs that failed and genuinely aborted a push:

```
{"ts":"2026-09-04T03:58:11+0800","trigger":"pre-push","ok":true,  "git_sha":"6f8dfced..."}
{"ts":"2026-09-04T06:44:32+0800","trigger":"pre-push","ok":false,"failed_checks":["self-audit"],"git_sha":"7788edb4..."}
```

That last record is the gate doing its job — and `self-audit` exits 0 at current HEAD, so it was a real transient break, correctly caught and correctly blocked. All three checks pass now: `import-sanity` 4.5s, `cli-help-sanity` 127.5s, `self-audit` 11.5s, Overall PASS.

**What was actually still wrong.** The CI workflow's "HONEST DISCLOSURE" header asserted two things that are now false:

| Claim in the file | Real current evidence |
|---|---|
| `git ls-remote origin` → *(no output)*, remote "is EMPTY" | returns `ff2c09b2… refs/heads/gap-close/env-manifest-fact-sources` |
| "there are no remote branches, and therefore this workflow has still never actually executed a single time" | `git ls-tree -r ff2c09b2` shows that **pushed** commit carries `.github/workflows/dv-harness-ci.yml`, so `push: branches: ["**"]` has had a real opportunity to fire |

Whether an Actions run *executed* is **not knowable from this machine**, and I recorded it as unknown rather than guessing either way: the repo is private (unauthenticated `api.github.com/repos/YuTienL/DV_Agent_Harness` → 404) and `gh` v2.99.0 is unauthenticated (`gh auth login` required), so neither `gh run list` nor the REST API can be consulted.

This is not a cosmetic comment defect. It is the same failure mode the whole section exists for — a reader of that file concludes "there is no CI" and stops looking. It had also gone stale **twice in two days**, both times because nothing compared it to reality.

### The change

1. **Corrected the disclosure** in `.github/workflows/dv-harness-ci.yml` against the real commands above, including the honest "what is still not known" paragraph, and the matching retracted sentence in `dv_harness_tests/test_self_test_gate_e2e.py`'s docstring.
2. **Made it self-checking** so a third silent drift is a test failure, not a comment nobody re-reads. The state claim is now a machine-checked token —

   ```
   # DISCLOSURE-CHECK: remote_pushed_refs=yes
   ```

   — and `TestCiDisclosureIsNotStale` (3 tests) compares it to the real ref state. This reuses the repo's own established prose-held-to-code discipline (`dv_harness/mcp/claude_md_index.py`, `source_authority.assert_doc_matches_code()`) rather than inventing a parallel mechanism.

**Design choice worth flagging:** the check is deliberately **network-free**, reading local `refs/remotes/` evidence rather than calling `git ls-remote`. A network call would fail offline and on any runner lacking credentials for a private repo, and a flaky truth check is one that gets deleted. Ref *absence* is genuinely ambiguous (a fresh clone that never fetched looks identical to an empty remote), so that case **skips** rather than asserting something it cannot support.

### Proof the tests aren't vacuous

Passing tests prove little by themselves, so I mutation-tested the gate: flipping the token to `=no` and restoring the retracted sentence made **both** gates fail —

```
FAILED ...::TestCiDisclosureIsNotStale::test_the_disclosed_state_matches_the_real_remote
FAILED ...::TestCiDisclosureIsNotStale::test_the_disclosure_does_not_reassert_the_retracted_empty_remote_claim
2 failed, 1 passed
```

— then restored the file and re-ran to green.

---

## Scope and honesty notes

- **Concurrent-agent safety:** both touched files were confirmed clean (`git status`) before editing and staged individually by path; the commit diffstat is exactly 2 files. `CLAUDE.md`, `engine.py`, and `cli.py` were **not** touched.
- **Not claimed:** I did not verify that GitHub Actions has ever run, and the commit does not assert it. That remains answerable only from the repo's Actions tab.
- **Not done, deliberately:** pushing the branch to activate CI. That is a human action under this repo's PR-only governance policy, and the pre-push hook plus `git-guard` exist precisely to keep an agent from taking it.
