# USB UVM Environment — Reference Base Policy

The USB UVM environment is included as a Reference Base / Golden Reference Pattern for AI Agent Harness L5.

## What MAY be reused across protocols
- UVM directory / package organization
- tb_top / env / agent / sequence / test layering
- uvm_config_db usage patterns
- virtual sequencer architecture
- sequence library organization
- scenario registry / pattern registry
- dependency / barrier orchestration
- scoreboard framework structure
- coverage collector framework structure
- performance calculator framework structure
- DMA scoreboard framework structure
- monitor -> analysis_port -> scoreboard connectivity pattern
- config object patterns
- RAL integration pattern
- reset / clock control pattern
- build / run / regression Make interface pattern
- smoke-test promotion pattern
- LSF regression integration
- failure triage / first-failure rerun pattern
- Git / exact SHA / evidence provenance pattern
- documentation / manifest structure

## What MUST NOT be reused as truth for other protocols
- USB signal names
- USB2 dp/dm behavior
- USB3 LFPS / TS1 / TS2 / LTSSM assumptions
- endpoint / transfer-type rules
- USB-specific register assumptions
- USB-specific VIP class/config/API assumptions
- USB-specific timing
- USB-specific checker behavior
- USB-specific packet formats
- USB-specific PHY behavior

## Reuse Principle
Reuse architecture, not protocol truth.

USB Reference Base may influence:
- code organization
- builder templates
- framework patterns
- reusable UVM infrastructure

But each target protocol must regenerate its own:
- topology
- role
- interface mapping
- configuration
- protocol checks
- sequences
- scoreboard semantics
- coverage semantics
using CURRENT DUT + Spec + VIP evidence.
