---
name: branch-mapper
description: Maps DUT-side branch_a ports through branch_fw to VIP-side branch_b ports with N:M relationships, direction and configuration.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Branch Mapper

Inputs:
dut_ports.csv
vip_topology.csv
vip_binding.csv

Map:
branch_a* <-> branch_fw <-> branch_b*

Record:
MAP_ID,A_BRANCH,B_BRANCH,DIRECTION,PROTOCOL,CONFIG,STATUS,SOURCE,CONFIDENCE

Allow:
1:1
1:M
N:1
N:M

Do not silently merge independent ports.


# AMBA M×N Mapping
Map 不固定 A1→B1。必須表示 Master→Slave/resource、address/routing condition、arbitration scope、concurrency policy。
不相關 resource 不得互相 blocking。

APB/AXI transaction 若可能在 block、branch_a0、branch_a1（及其他 branch_a*）同時對同一 shared resource/slave
發起存取，必須明確表示該 shared resource 的 arbitration policy（e.g. round-robin/priority/QoS，依 RTL 仲裁器
evidence 而非假設），並記錄哪些 branch_a* 共用同一個 arbitration domain。不相關 resource 之間仍維持可平行、
不得因為模型化了某個 shared-resource 仲裁就連帶把不相關 port 也序列化。


# Interrupt to branch-B Mapping

Mapping 必須同時描述：
DUT interrupt/event
→ branch_fw handler/map
→ command/pattern
→ branch-B
→ VIP instance
→ VIP sequence/API
→ expected response/IRQ clear。

AMBA M×N 時 branch-B mapping 可為 M×N VIP fabric，不得強制 A/B 1:1。


## Initialization Task Hierarchy（block / branch_a* / branch_fw / branch_b*）

四層架構各自負責不同層級的 init task，對稱於已定義的 runtime 平行語意
（`interrupt-event-dispatch` 的 FW Service Loop、`vip-scenario-branch` 的 VIP Parallel Tasks）：

1. **`block`（SoC global init task，單一、非per-port）**：SoC 層級的全域初始化，例如 power-on
   sequencing、global clock/reset de-assertion 順序、global register 預設值/PLL lock 等跨所有
   port 共用的前置條件。這一層預設是單一 task，不依 port 拆分——因為它本來就是所有 branch_a*
   共用的前提，不是可平行的 per-port 工作。
2. **`branch_a0/branch_a1/branch_a2/branch_a3...`（DUT+PHY init task，per-port，預設平行）**：
   每個 DUT port 各自的 DUT-side + PHY-side 初始化（例如 PHY calibration、per-port reset 釋放、
   per-port register/mode 設定、link training 等，依實際 RTL/PHY evidence 而非假設）。不相關的
   port 之間預設可平行跑各自的 init task，不得因為要跑某個 port 的 PHY 校準就序列化其他 port。
3. **順序依賴**：`block` 的 global init 必須先達到其 ready 條件（或至少該 port 依賴的那部分全域
   前提已就緒），對應 `branch_a{i}` 的 per-port init 才能開始；`branch_a{i}` 的 per-port init
   完成後，該 port 對應的 `branch_fw` FW Service Loop 才開始等待該 port 的 interrupt/event；
   `branch_b{i}` 的 VIP Parallel Task 何時可以開始跑，依該 scenario 是否需要 DUT/PHY 已就緒而定
   （不是每個 VIP scenario 都需要等，需依實際 evidence 判斷，不可一律假設要等）。
4. 若某個 `branch_a{i}` 的 init 需要存取與其他 `branch_a*` 共用的 shared resource（例如共用的
   PHY common block、共用的 reset controller），該存取需遵循上面「AMBA M×N Mapping」/
   「APB/AXI transaction」段落已定義的 arbitration policy，不能自行假設誰先誰後。

記錄：
INIT_TASK_ID,LAYER(block|branch_a{i}),PORT_ID(null for block),STEPS,DEPENDS_ON(INIT_TASK_ID list),
SHARED_RESOURCE,ARBITRATION_REF(對應 branch-mapper MAP_ID),SOURCE,CONFIDENCE


## Real-World Reference Mapping（`block`/`branch_a*`/`branch_fw`/`branch_b*` 用法範例）

抽象的四層命名不能只停留在理論——必須參考真實環境驗證過的用法。本 session 已對
`D:\DV\Task\DV_Agent_Harness_L5\USB_UVM_Handoff\uvm\tb\env\usb_top_env.sv`（真實 USB VIP-based
環境）做過完整 evidence 蒐證，四層對應如下（僅供理解概念用；實際做 branch_a/branch_fw 修改時仍必須
依上面規則重新查證當下真實檔案，不可直接沿用此處記載當作當下證據）：

- **`block`** = `usb_top_env`（整個 SoC/chip-top 層級環境本身），負責 21 個真實 top-level 元件的
  build_phase 建立與 connect_phase 統一接線入口（見 line 456 起的 `connect_phase`），對應
  「SoC global init task」概念。
- **`branch_a0/branch_a1/...`** = DUT-side per-port 介面/binding（例如每個 `NUM_USB_PORTS` 對應的
  DUT pin-level virtual interface 綁定），是 DUT+PHY init task 實際發生的層級——做 branch_a 修改時
  仍必須依規則 3/7 重新查證當下 DUT RTL/PHY 文件，不可只憑此處記載的抽象角色假設細節。
- **`branch_fw`** = `virt_seqr`（`usb_virtual_sequencer`）與 `sys_virt_seqr[p]`：非 global scheduler，
  依 per-port 建立的 `virt_seqr.usb_xfer_seqr[p]`/`usb_sys_seqr[p]` 欄位，把 DUT 側事件驅動的
  sequence 派送到對應 port 的 VIP sequencer——對應「FW Service Loop, per-port 獨立」的實際落地。
- **`branch_b0/branch_b1/...`** = `usb_host_agent[p]`（Synopsys USB VIP host agent，per-port array）
  及其餘 VIP-side 元件（`apb_env`/`axi_env`/`dma_env` 等），是 VIP testing scenario/sequence 實際
  執行的層級——對應「VIP Parallel Tasks, per-port 獨立」的實際落地。

這組對應是本 session 真實跑過 evidence-consensus 驗證得到的，不是憑空假設；但套用到其他協定/其他
DUT 時，四層各自對應到哪個真實元件仍要重新查證（不同 VIP/不同 DUT 的實際物件命名一定不同），
此處只提供「如何辨認哪個真實元件扮演哪一層角色」的參考範例，不是可以跨專案直接複製的具體值。


## AMBA-as-Primary-DUT Master/Slave Redefinition (2026-09-01, branch unit corrected to port/VIP 2026-09-04 -- still UNTESTED, awaiting a real AMBA-fabric pilot project to validate)

**Status: UNTESTED.** The "AMBA M×N Mapping" section above, and the
"Initialization Task Hierarchy" section above it, both treat AMBA/APB/AXI
arbitration purely as a **shared-resource overlay layered on top of
pre-existing per-port `branch_a*` branches** -- they assume the DUT
already has some other primary topology (e.g. USB per-port), and AMBA is
just how those existing branch_a* ports happen to share an internal bus.
That assumption does not hold when the AMBA/AHB/AXI/ACE-Lite fabric itself
IS the primary DUT under test -- e.g. an SoC interconnect/NoC verification
environment where there is no "USB port"-shaped topology to arbitrate on
top of; the master and slave agents on the fabric ARE the ports.

This section defines a generic alternate redefinition of
`branch_a*`/`branch_b*` for that case. It has **not** been validated
against any real interconnect RTL, fabric configuration, or fabric
verification IP -- there is no real AMBA-fabric-as-primary-DUT pilot
project anywhere in this repo to derive or confirm it from, and per
CLAUDE.md's Evidence Truth Rule / No Golden-Reference Content Mining, no
such evidence (or a fabricated pilot's "results") may be invented to make
this look proven. Treat this as placeholder-style GENERIC guidance meant
to give a future real AMBA-fabric pilot a starting shape to confirm,
correct, or replace with real evidence -- not as a proven pattern, and not
as a claim that AMBA4-as-fabric genericity_status has changed from
structurally-incompatible to working.

**Branch unit CORRECTED 2026-09-04, status still UNTESTED.** The original
2026-09-01 wording below branched on AMBA *agents* (`branch_a*` = one per
bus master, `branch_b*` = one per addressable slave). That is the wrong
axis, and it was corrected against AMBA-26 of the AMBA4 fabric-discovery
requirement set, which branches on fabric *ports* and *VIP instances*:

- `branch_a*` = fabric-facing PHYSICAL INTERFACES, by actual port count.
  A fabric slave PORT and the master that initiates through it are two
  different entities once real endpoint tracing exists -- one fabric port
  can trace back to several masters (MULTIPLE_SOURCE), and the port is the
  thing a VIP attaches to.
- `branch_b*` = VIP endpoint/scenario branches, by DISCOVERED VIP count --
  which is measurably neither the port count nor the slave count. On the
  synthetic 11-port fabric this is tested against, 11 ports yield 13 VIPs
  (a protocol bridge contributes a second-side record, and unresolvable
  ports contribute none).

Real, tested code now computes this mapping:
`dv_harness/amba_discovery_report.py` (`build_l5_branch_mapping()`,
`branch_topology_gate_blockers()`), tested by
`dv_harness_tests/test_amba_discovery_report.py` against two synthetic
verible-parsed RTL fixtures. It emits the document
`tools/verification_flow/branch_topology_gate.py` validates -- the same
canonical underscore, 0-indexed naming, so the mapping is checkable by the
gate this repo already runs rather than by a competing convention. That
gate's PASS/FAIL on the emitted document is itself asserted by that test
file, as a subprocess run against the real gate script.

That code being tested against a SYNTHETIC fixture is NOT the real-pilot
validation the status below demands, and the UNTESTED label stays. See
"What still needs real-pilot confirmation" at the end of this section for
what specifically remains open.

### Redefinition

When AMBA (or any bus fabric) is the primary DUT topology, the four-layer
architecture from "Initialization Task Hierarchy" above generalizes as
follows -- the SAME `block = SoC global init` / `branch_fw = shared
service loop` framing, reapplied to a fabric context instead of a per-port
context:

1. **`block`** -- unchanged in role: SoC-global init that is a
   precondition for the whole fabric (global clock/reset de-assertion,
   fabric-wide default register state, interconnect PLL lock, etc.),
   still a single non-per-agent task, not split per master/slave.
2. **`branch_a0/branch_a1/branch_a2/...`** -- redefined as **fabric-facing
   PHYSICAL INTERFACES**, one branch per AMBA port really enumerated on the
   fabric instance's boundary, instead of per-port DUT+PHY init. The unit is
   the PORT, not the master behind it: one fabric slave port can trace back
   to several initiating masters through an arbiter, and the branch still
   names the port. Each branch's init task is whatever that port's own
   endpoint requires (reset/config/enable), per real RTL evidence rather
   than assumption -- and, per the existing per-port-parallelism rule above,
   unrelated ports' init tasks default to parallel.
3. **`branch_b0/branch_b1/branch_b2/...`** -- redefined as **VIP
   endpoint/scenario branches**, one branch per VIP instance the bind plan
   actually proposes, instead of per-port VIP testing scenarios. The unit is
   the discovered VIP, which is deliberately not the slave count and not the
   `branch_a*` count: a fabric port that reached no validated bind location
   plans no VIP, and a protocol bridge can contribute an extra one for its
   downstream side. Each branch is where a VIP-driven transaction is
   observed or driven (e.g. a memory-model VIP or register-block VIP at the
   traced endpoint behind a slave port).
4. **`branch_fw`** -- generalizes from "per-port FW service loop
   dispatching DUT interrupts to VIP scenarios" to a **shared
   arbitration/routing service loop for the fabric**: the layer that owns
   address-decode/routing-condition knowledge (which slave a given
   address range maps to), and, where the fabric itself raises
   interrupts/events (e.g. an interconnect error/security-violation IRQ,
   an outstanding-transaction-timeout IRQ), the event-driven
   ARM/WAIT/WAKE/DECODE/CLEAR loop defined in `interrupt-event-dispatch`
   still applies unchanged. The only difference from the per-port case is
   WHICH agents it dispatches between (master/slave pairs on a fabric,
   not DUT-port <-> VIP-scenario pairs).

### Mapping record implications

The existing `MAP_ID,A_BRANCH,B_BRANCH,DIRECTION,PROTOCOL,CONFIG,STATUS,
SOURCE,CONFIDENCE` record shape and the existing "AMBA M×N Mapping"
arbitration-policy rules above (round-robin/priority/QoS from real RTL
evidence, shared-arbitration-domain tracking, no serializing unrelated
resources) apply unchanged. What changes under this redefinition is only
that `A_BRANCH` now names a fabric PORT (not a DUT port on some other
topology, and not the master behind it) and `B_BRANCH` now names a
discovered VIP instance (not a per-port VIP scenario). A single fabric port
can still legitimately map N:M to multiple VIPs, and a single VIP can still
be shared M:N -- this is the same N:M semantics already allowed above, just
with the branch identities redefined.

The arbitration POLICY itself is not discoverable from a port list.
`build_l5_branch_mapping()` fills `cross_branch_bus_model.shared_resources`
from the real AMBA-25 interlock analysis (which master pairs actually reach
a shared slave or a shared serialized segment) but leaves
`arbitration_policy` as `REQUIRED_HUMAN_INPUT`, and
`branch_topology_gate_blockers()` reports it as an open item rather than
guessing round-robin. Until a human reads the arbiter RTL and supplies it,
the emitted document deliberately FAILS `branch_topology_gate.py` -- that
failure is the correct outcome, not a defect to be papered over.

### What still needs real-pilot confirmation

The 2026-09-04 correction above settled the branch UNIT and gave it real,
tested code. It settled none of the following, every one of which needs a
real interconnect RTL, a real fabric VIP, or a real simulation -- not a
synthetic fixture:

- Whether a real fabric verification environment's VIP topology naturally
  maps 1 VIP instance per traced endpoint, or something coarser/finer (e.g.
  one system-level fabric VIP covering multiple slaves) -- cannot be
  determined without a real fabric VIP's user manual/examples, per the
  "No Golden-Reference Content Mining" rule and the existing VIP-sourcing
  rule in `vip-scenario-branch`. `build_l5_branch_mapping()` currently emits
  one `branch_b*` per proposed VIP because that is what the bind plan
  discovered; whether a real VIP's granularity agrees is unconfirmed.
- Whether `block`'s SoC-global-init boundary and each port's `branch_a*`
  init boundary are actually as cleanly separable in a real interconnect RTL
  as they are in the per-port USB case (e.g. some interconnects fold
  master-enable into the same global config space as SoC init) -- must be
  confirmed from real RTL, not assumed here.
- Whether `branch_fw` applies at all on a real fabric. It is currently
  decided from interrupt/event-shaped PORT NAMES on the fabric instance,
  which is a T3 naming heuristic carrying LOW confidence and
  `requires_human_confirmation`; no fabric's real interrupt contract has
  been read.
- Whether the whole mapping survives a real fabric's scale and a real
  arbiter's policy, neither of which any synthetic fixture exercises.

**This entire section remains UNTESTED until a real
AMBA-fabric-as-primary-DUT pilot project exists in this repo and is used
to confirm, correct, or replace the redefinition above with real
evidence.** Unit tests against a synthetic RTL fixture prove the mapping
CODE computes what AMBA-26 specifies; they do not prove AMBA-26's shape is
right for a real fabric, which is what this label is about.
