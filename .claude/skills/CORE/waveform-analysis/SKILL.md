---
name: waveform-analysis
description: 規範 WAVE=1 full-simulation FSDB、fsdbreport evidence、必要時 Verdi 深入分析與 signoff traceability。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Waveform Analysis

預設正式代表性 run：
WAVE=1
Coverage=OFF
dump start=time 0
dump end=simulation end

先用 fsdbreport 取得自動 evidence：
clock/reset/state/handshake/address/data/response/interrupt/protocol-event 等本 scenario 關鍵項。

若不足：
→ Verdi deeper debug。

記錄：
FSDB path
fsdbreport command/report
signals/events checked
expected vs actual
Verdi used?
root-cause finding
status
