@echo off
cd /d "%~dp0"
echo 啟動 Claude Code DV Workflow...
echo 模式: --dangerously-skip-permissions
echo Coverage 預設: OFF
echo 驗證流程: PUSH ^> BUILD ^> VERIFY ^> WAVE=1 ^> fsdbreport
claude --dangerously-skip-permissions
