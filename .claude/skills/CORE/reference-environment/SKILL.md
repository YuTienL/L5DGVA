---
name: reference-environment
description: 管理 Linux Server 上既有 USB UVM Reference Environment，預設唯讀，用來抽取可重用架構、branch、command、VIP integration 與 build/run pattern。
allowed-tools: Read Grep Glob PowerShell
---
# USB UVM Reference Environment

當 Workflow 要使用既有 USB UVM 環境作為參考時，`REFERENCE_ENV_PATH` 是必要資訊。

## 強制規則

Reference Environment 與 Work Environment 是兩個不同概念：

REFERENCE_ENV_PATH
- 既有可工作的 USB UVM reference
- 預設 READ_ONLY
- 用於抽取 architecture/pattern
- 不作為目前修改/push 的工作目錄

WORK_ENV_PATH
- 本次實際修改
- push/build/verify/run 的工作目錄

不得假設兩者相同。

## Discovery

Workflow 先查：
1. project config
2. README / setup docs
3. scripts
4. existing reference declarations
5. prior project evidence

如果無法可靠確定，必須詢問使用者：

- Linux Server 是哪一台？
- Reference Environment 完整 Linux path？
- Reference branch/tag/commit？
- 是否允許 READ_ONLY 以外操作？預設 NO。

## Reference Preflight

確認：
- server 可達
- path exists
- readable
- git branch/commit if applicable
- command.txt/scenarios
- block/branch_a/branch_fw/branch_b structure
- VIP adapter/integration
- build/run/regression scripts
- naming convention
- UVM topology

## Extract, not clone semantics blindly

可跨 protocol 參考：
- BLOCK/branch structure
- branch_fw responsibilities
- command parser/dispatcher pattern
- scenario composition
- regression wrapper
- naming/integration conventions

不得直接當 universal truth：
- USB protocol semantics
- USB Host/Device role
- endpoint/descriptor/enumeration
- USB-specific VIP class/API
- USB checker/coverage
- USB bind points

Reference artifact 應標示：
REFERENCE_ONLY
NOT_AUTHORITATIVE
READ_ONLY_BY_DEFAULT
