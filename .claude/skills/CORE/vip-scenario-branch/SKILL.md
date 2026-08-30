---
name: vip-scenario-branch
description: 定義 branch_b0/1/2... 為 VIP testing scenario/pattern/sequence 的正式承載層，並建立 vPlan/command 到 VIP sequence 的 traceability。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# branch-B VIP Testing Scenario Layer

branch_b0 / branch_b1 / branch_b2 ... 是 VIP-side testing scenario layer。

每個 branch-B 依 VIP topology 建立，不要求與 branch-A 1:1。

branch-B 負責：
- VIP testing scenario
- pattern interpretation
- VIP sequence/API invocation
- protocol-specific stimulus
- VIP-side response/check hooks
- scenario-local options/state

Traceability：
VP_ID
→ SCENARIO_ID
→ COMMAND_ID
→ PATTERN_ID
→ BRANCH_B_ID
→ VIP_INSTANCE
→ VIP_SEQUENCE/API
→ EXPECTED_RESULT

修改任何 branch-B / VIP pattern 前：
existing project usage
→ VIP examples
→ VIP user manual
→ VIP source code
→ class/API reference
→ 才能修改。

禁止憑猜測 invent VIP API/class/sequence。

## VIP Parallel Tasks（branch_b0/1/2/3...）

對稱於 `interrupt-event-dispatch` 的 FW Service Loop：每個 branch_b0/branch_b1/branch_b2... 是獨立的
VIP testing task/sequence instance，預設彼此平行執行，不是單一序列迴圈依序跑完 branch_b0 才跑
branch_b1：

1. 每個 branch-B instance 各自跑自己的 VIP sequence/scenario（對應 traceability 中的
   `VIP_INSTANCE`/`VIP_SEQUENCE/API`），彼此獨立、不相關的 branch-B 不得互相等待或序列化。
2. 若多個 branch-B 共用同一個 VIP-side shared resource（例如同一個 VIP agent instance、同一條 shared
   bus/fabric），該共用存取需要對應 `branch-mapper` 已定義的 arbitration policy（`ARBITRATION_REF`
   對應 MAP_ID），不能各自 branch-B 任意搶用。
3. 與對側 `branch_fw` 的 FW Service Loop 對應關係：某個 Port 的 service loop dispatch 到哪些
   branch-B，那些 branch-B 的平行執行方式必須與該 Port 的平行語意一致（不相關 Port 平行 → 對應的
   branch-B 也應平行；同 shared resource 才 local arbitration）。

記錄（新增於既有 Traceability 之外）：
BRANCH_B_ID,VIP_INSTANCE,VIP_SEQUENCE/API,PARALLEL_GROUP,SHARED_RESOURCE,ARBITRATION_REF(對應
branch-mapper MAP_ID),SOURCE,CONFIDENCE
