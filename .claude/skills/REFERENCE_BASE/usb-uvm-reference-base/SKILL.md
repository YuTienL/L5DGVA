---
name: usb-uvm-reference-base
description: Use the proven USB UVM environment as a golden reference for reusable UVM architecture and workflow patterns without leaking USB-specific protocol assumptions.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# USB UVM Reference Base

Purpose:
Extract reusable UVM engineering patterns from the USB environment.

Allowed reuse:
- hierarchy / packaging
- config patterns
- virtual sequencer
- scenario registry
- scoreboard framework
- DMA scoreboard framework
- performance framework
- coverage framework
- build/run/regression structure
- failure rerun flow

Forbidden:
Do not transfer USB-specific topology, signal semantics, LTSSM, LFPS, transfer rules, VIP APIs, register assumptions or timing into non-USB builders.
