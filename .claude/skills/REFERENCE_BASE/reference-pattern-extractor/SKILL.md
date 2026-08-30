---
name: reference-pattern-extractor
description: Extract generic reusable design-verification patterns from a reference UVM environment and classify them as protocol-neutral vs protocol-specific.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Reference Pattern Extractor

For every reference environment component classify:
- GENERIC_REUSABLE
- PROTOCOL_ADAPTER
- PROTOCOL_SPECIFIC
- PROJECT_SPECIFIC

Only GENERIC_REUSABLE patterns may be automatically reused across protocols.
Protocol-specific and project-specific content requires regeneration from current evidence.
