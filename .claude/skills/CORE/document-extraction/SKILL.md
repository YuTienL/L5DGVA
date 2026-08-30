---
name: document-extraction
description: Extract and normalize engineering evidence from PHY docs, programming guides, register maps, VIP manuals/examples/source/class references and project documents.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Document Extraction

Required behaviors:
- detect document type
- version/hash identity
- incremental reuse when unchanged
- extract section hierarchy, tables, registers, examples and references
- preserve document/page/section/source-location traceability
- never treat extracted text without source identity as final evidence
