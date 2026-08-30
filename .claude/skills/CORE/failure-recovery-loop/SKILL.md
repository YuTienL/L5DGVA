---
name: failure-recovery-loop
description: 強制 Functional Failure 進入 Log + FSDB/fsdbreport → root cause → fix → verify → rerun 的閉環。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Failure Recovery Loop

任何 Functional/Unknown failure：

FAILURE
→ log analysis
→ WAVE=1 representative rerun
→ FSDB
→ fsdbreport
→ 必要時 Verdi
→ root cause
→ implementation fix
→ BUILD
→ targeted VERIFY
→ representative WAVE=1 verify
→ LSF regression rerun
→ result reclassification

若 rerun 再 FAIL，重新進入同一 loop。

禁止：
- 只 rerun 不分析
- 只看最後一行 log
- 只靠 waveform 不看 log
- functional failure 直接人工忽略
- fix 後跳過 targeted verify
