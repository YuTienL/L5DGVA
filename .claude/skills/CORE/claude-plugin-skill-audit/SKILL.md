---
name: claude-plugin-skill-audit
description: 稽核 Claude Code plugins、Superpowers、user/project skills 與 workflow dependencies。
allowed-tools: Read Grep Glob PowerShell
---
# Claude Plugin / Skill Audit

分開判斷：
1. Plugin installed/enabled
2. Plugin-provided agents/skills/hooks/MCP/LSP
3. User skills
4. Project skills
5. DV Workflow required skills

不得用 `.claude/skills` 目錄內容推論 Superpowers plugin 本體內容。

輸出：
plugin status
skill inventory
missing dependencies
scope collision/duplicate
error state
recommended action
