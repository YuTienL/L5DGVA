---
name: amba-profile
description: AMBA SoC Bus industrial DV profile for APB2/APB3/AHB/AHB-Lite/AXI3/AXI4/ACE-Lite/AXI-Stream with Multi-Master×Multi-Slave M×N topology.
allowed-tools: Read Grep Glob PowerShell
---
# AMBA SoC Bus Profile

支援 APB2、APB3、AHB、AHB-Lite、AXI3、AXI4、ACE-Lite、AXI-Stream。

第一步必須從 DUT hierarchy、RTL、address map、bridge/interconnect config 重建：
- Master count M
- Slave count N
- Master interfaces
- Slave interfaces
- bridges / interconnect / crossbar
- protocol conversions
- clock/reset domains
- address map / default slave / timeout
- verification boundary
- Active / Passive / Monitor-only VIP requirements

不要看到 AXI/APB 就直接決定 VIP 數量。

## M×N Fabric
AMBA branch_fw 必須支援 protocol-aware M×N：
- address routing
- resource-local arbitration
- ordering
- outstanding tracking
- response routing
- backpressure
- concurrency

禁止 Global Scheduler 將整個 fabric 序列化。

### APB2/APB3
shared VIP 可 N:1；只在該 APB resource local serialize。

### AHB/AHB-Lite
依 HTRANS/HBURST/HSIZE/HREADY/HRESP 與 ownership/arbitration 規則建模。

### AXI3/AXI4
必須保留：
- AW/W/B/AR/R independent channels
- AXI ID
- outstanding transactions
- ordering
- burst
- backpressure
- narrow/unaligned（若支援）
- interleaving/response semantics（依版本/VIP能力）

M0→S0 與 M1→S1 預設可平行。
M0/M1→S0 才在 S0 resource scope 內競爭。

### ACE-Lite
M×N，僅使用設計實際存在的 ACE-Lite/domain/barrier/coherency-lite semantics。

### AXI-Stream
per-stream queue、TVALID/TREADY、TKEEP/TSTRB/TLAST/TID/TDEST/TUSER 實際存在的語意與 multi-stream concurrency。

## vPlan
至少評估：
- M0→S0 + M1→S1 parallel
- 多 Master→同一 Slave contention
- 一 Master→多 Slave
- all-master→all-slave constrained random
- outstanding / ID / ordering
- backpressure / burst / error
- bridge / protocol conversion
- reset / recovery
