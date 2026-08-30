> **See CREATE_ENVIRONMENT.md** for the current, consolidated procedural guide covering this topic.

# AI Agent Harness L5 — Extensible Protocol / Interface Builder Framework

Goal:
Support future specifications, proprietary interfaces and new standards without changing the Harness core.

## Plugin Contract
Every new protocol/interface plugin provides:
- protocol_id / version
- role model
- topology model
- interface/boundary model
- signal/schema definition
- register/programming evidence schema
- VIP/tool integration description
- sequence/scenario model
- checker/scoreboard semantics
- coverage/assertion plan
- smoke tests
- error injection model
- performance metrics
- documentation sources
- builder skill
- self-test package

## Onboarding Flow
New Spec / New Interface
-> Doc Extraction
-> Protocol Discovery
-> Plugin Manifest
-> Multi-Agent Evidence Acquisition
-> Independent Synthesis
-> Protocol Isolation Gate
-> Generate Protocol Builder
-> Compile
-> Smoke
-> Self-Repair
-> Register Plugin
-> Reuse in Block/IP / Subsystem / Full SoC

## Key Principle
The Harness core remains stable.
New protocols are added as plugins, not hard-coded branches.
