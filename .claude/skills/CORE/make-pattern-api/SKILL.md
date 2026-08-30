---
name: make-pattern-api
description: 定義一般 DE/DV engineer 透過 make 新增、驗證、執行、列出與註冊 pattern 的穩定 User API。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Make Pattern User API

UVM environment 必須允許使用者透過 make 管理 pattern。

最低支援：
make add-pattern
make validate-pattern
make list-patterns
make show-pattern PATTERN=<name>
make run-pattern PATTERN=<name>
make verify-pattern PATTERN=<name>
make regression-add PATTERN=<name>
make regression-remove PATTERN=<name>
make regression
make regression-monitor
make regression-report

建議 pattern 目錄：
patterns/<protocol>/<pattern_name>/
  command.txt
  pattern.yaml
  options.f (若需要)

新增 pattern 流程：
schema validate
→ command validate
→ protocol/profile validate
→ duplicate signature check
→ single simulation
→ WAVE/fsdbreport evidence
→ PASS
→ regression registration
