---
name: protocol-isolation-gate
description: Prevent protocol-specific assumptions from a reference environment from contaminating a different protocol environment generator.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Protocol Isolation Gate

Before generating a non-USB protocol environment:
- identify reused reference patterns
- verify each reused pattern is protocol-neutral
- reject USB-specific signal/register/VIP/timing/sequence/checker assumptions
- require current target-protocol evidence for all protocol-specific implementation decisions

Failure of this gate blocks code generation.
