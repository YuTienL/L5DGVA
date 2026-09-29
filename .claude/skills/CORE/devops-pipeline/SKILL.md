---
name: devops-pipeline
description: 將 Git commit/push 與 Linux Server build、target verify、LSF regression、monitor、report、signoff 連成 DevOps pipeline。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# DV DevOps Pipeline

Pipeline：

Developer/AI Change
→ Git Sync
→ Branch
→ Modify
→ Review
→ Commit
→ Push
→ CI/Preflight
→ Linux Server exact commit checkout
→ Environment source
→ BUILD
→ Target VERIFY
→ LSF Regression
→ Monitor
→ Failure Recovery
→ Regression Report
→ Signoff
→ optional Tag/Release

## Pipeline Stages

1. SOURCE
   repo/branch/SHA/submodule SHA

2. STATIC GATES
   syntax/config/schema/comment/naming/secret/artifact checks

3. BUILD
   Coverage OFF

4. TARGET VERIFY
   selected patterns

5. REGRESSION
   LSF; WAVE=0, PA=0, Coverage OFF

6. FAILURE CLOSURE
   log + WAVE=1 + fsdbreport + Verdi if needed + fix + rerun

7. REPORT
   build + verify + regression + failure cluster + environment identity

8. SIGNOFF
   exact source SHA + exact server SHA + reports + residual risk

## Real CLI Surface (this project's own, never invented)

不要自己拼長 command。此 project 的 Execution Layer 已經有真實、固定的
entry point，全部 verified 存在於 repo 內：

- `just <recipe>`（`justfile`，repo root）── 固定 recipes：
  `just preflight` / `just build` / `just verify` / `just run` /
  `just regress` / `just regress-log` / `just check` / `just list-patterns`
  / `just pipeline` / `just relay-status`。`build` / `verify` / `run` /
  `regress` / `pipeline` 都已 declare `(preflight ...)` 為 dependency，
  所以 BLOCKED 的 preflight 會在 `make` 之前就停掉整條 recipe chain。
  先 `just --list` 看實際 recipe 與參數，不要假設參數名。
- `dv-harness preflight`（`dv_harness/preflight.py`）── 真實的
  license (`lmutil lmstat`) / queue (`bqueues`) / host / disk (`df -Pk`) /
  workdir / EDA env 六項 gate，standalone 跑、不派 job。加 `--remote` 走
  已 sanctioned 的 persistent relay 去 probe 真的 server。
- `dv-harness lsf-submit`（`dv_harness/lsf_client.py` 的
  `bsub_submit_with_preflight()`）── 這個 repo **唯一**真實的 `bsub`
  submission 入口，submission 前強制跑上面那個 preflight gate。不要自己
  直接呼叫 `bsub`；`--skip-preflight` 是 explicit、會被 audit 的 bypass，
  不是 default。
- `dv-harness lsf` / `lsf-watch-start` / `lsf-watch-status` /
  `lsf-reconcile` / `lsf-kill` ── per-job drill-down 與 monitor（對應上面
  pipeline 的 MONITOR / FAILURE CLOSURE 階段）。
- `dv-harness pueue add|status|log|wait|chain`
  （`dv_harness/pueue_client.py`）── **local PC 端**的 task orchestration，
  不是 farm submission。`pueue chain` 是真實的
  build→verify→submit→monitor chain。

Harness 側已經有 enforcement：`dv_harness/engine.py` 的
`_execution_preflight_gate()` 會在 dispatch 任何 `devops-pipeline` /
`vcs-build` stage 的 agent **之前**跑同一份 `run_preflight()`，BLOCKED 就
把 stage 停在 `WAIT_USER` 並寫 `EXECUTION_PREFLIGHT_BLOCKED` event 到
`.dv-harness/events.jsonl`。也就是說 preflight 不是只有這份文件的文字約束
（同 `CORE/git-push-gate` 與 `dv-harness git-guard` 的關係）。

## Trigger Model

支援：
- manual developer invocation
- push-triggered CI
- merge-request/pull-request validation
- nightly regression
- release/tag regression

若 project 沒有實際 CI server/tool config，不得 invent。
先讀 existing CI files/scripts，再補。
