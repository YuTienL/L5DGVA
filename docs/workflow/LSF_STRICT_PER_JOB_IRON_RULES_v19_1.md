> **Current.** Listed as an accurate, current one-page mechanism guide in START_HERE.md -- not superseded.

# LSF Strict Per-Job Iron Rules v19.1

## Rule 66
所有 LSF submitted jobs 必須各自有一個 Job Agent。
持續快速檢查 exact bjobs + exact sim.log。
內部一直更新；只有狀態真的變化才立即通知。
同時保留固定週期完整 Snapshot。

## Rule 67
每個 Job Agent 若在 sim.log 確認 UVM_ERROR / UVM_FATAL / fatal assertion / simulator crash / explicit FAIL：
保存 evidence -> kill exact JOB_ID -> debug-agent -> root cause -> fix proposal -> closure workflow。

其他 jobs 繼續執行。

LSF DONE != DV PASS.
