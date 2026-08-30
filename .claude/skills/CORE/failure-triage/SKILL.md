---
name: failure-triage
description: Efficient large-log triage with first causal evidence, normalized signatures, failure clustering and representative repro selection.
allowed-tools: Read Grep Glob PowerShell
---
# Failure Triage

Never read a large log from start to finish first.

1. identify run/test/seed/result/log
2. inspect final status/tail
3. search high-value signatures
4. locate earliest causal failure
5. read narrow context
6. normalize transient data
7. cluster
8. select representative
9. deep-debug representative only

Search examples:
UVM_FATAL, UVM_ERROR, Error-, Fatal, assertion, timeout, mismatch, scoreboard, protocol, license, killed, memory, crash.


# v16.1 Early-Fail Log Gate

## Strong Early-Fail Conditions

以下任一條若有明確 log evidence，可提早停止該 simulation job：

- UVM_FATAL > 0
- UVM_ERROR > configured threshold（預設 > 0）
- Simulator fatal / crash / internal error
- Unrecoverable assertion failure
- Explicit testcase FAIL marker
- DUT/VIP fatal protocol violation configured as terminal
- No-progress watchdog / deadlock signature confirmed by project rule
- Known fatal signature from failure signature database

## Do Not Kill On Weak Evidence

下列內容不得單獨觸發 kill：
- 單純字串包含 "error" 但屬文件/訊息描述
- warning
- recoverable UVM_WARNING
- 已知 benign error allowlist
- 尚未確認 log 屬於該 JOB_ID
- temporary license/queue message that does not invalidate simulation

## Early Kill Sequence

DETECT
-> VALIDATE JOB_ID / RUN_DIR / LOG
-> SAVE EVIDENCE
-> MARK EARLY_FAIL
-> `bkill <EXACT_JOB_ID>` 或 project-approved kill wrapper
-> VERIFY job actually stopped
-> DEBUG AGENT TRIAGE
-> ROOT CAUSE
-> FIX PROPOSAL
-> FINDING REGISTRY

嚴禁 wildcard kill、user-wide kill、queue-wide kill。
