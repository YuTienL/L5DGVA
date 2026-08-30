---
name: real-protocol-semantic-synthesizer
description: Fuse DUT/spec/PHY/register/VIP evidence into the semantic model consumed by the UVM generator.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# real-protocol-semantic-synthesizer

Fuse DUT/spec/PHY/register/VIP evidence into the semantic model consumed by the UVM generator.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
