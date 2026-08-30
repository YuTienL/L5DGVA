---
name: new-protocol-onboarding
description: Onboard a new standard, proprietary protocol or interface into AI Agent Harness L5 using a plugin manifest and evidence-driven builder generation.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# New Protocol Onboarding
Steps:
1. Collect current spec/interface documents and DUT source.
2. Detect roles, topology, boundary and version.
3. Collect VIP docs/examples/source/class reference if available.
4. Create protocol plugin manifest.
5. Define protocol-specific scoreboard/coverage/assertions/scenarios.
6. Generate builder skill.
7. Compile and smoke-test.
8. Self-repair until baseline-ready.
9. Register plugin in protocol registry.
