---
name: simulation-options
description: 統一 Single Simulation、Makefile、Pattern、LSF Regression 的 WAVE/PA/FSDB_START/FSDB_STOP/TIMEOUT option model 與優先級。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Standard Simulation Option Model

所有 Pattern / Single Simulation / Regression 支援：

WAVE=0/1
PA=0/1
FSDB_START=<time>
FSDB_STOP=<time>
TIMEOUT=<time>

語意：
WAVE=0：不產生 FSDB
WAVE=1：啟用 FSDB
PA=0：關閉 PA
PA=1：開啟 PA
FSDB_START：dump start
FSDB_STOP：dump stop
TIMEOUT：simulation timeout

優先級：
CLI / Make override
→ Pattern manifest
→ Regression group config
→ Project defaults

正式代表性 waveform verification 預設：
WAVE=1
FSDB_START=0
FSDB_STOP=simulation_end
Coverage=OFF

一般 LSF Regression 預設：
WAVE=0
PA=0
Coverage=OFF
TIMEOUT=pattern-specific

若 WAVE=0，FSDB_START/STOP 不應驅動 dump。
若 WAVE=1 且未指定，採 project/iron-rule defaults。
