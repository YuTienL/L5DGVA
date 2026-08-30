---
name: vcs-build
description: Canonical compile/elaboration evidence workflow with first-causal-error extraction and environment/tool failure separation.
allowed-tools: Read Grep Glob PowerShell
---
# Build Workflow

Discover existing build entry point first.

Capture command, cwd, tool/version, exit status, log.

Triage:
tail/status -> error/fatal search -> earliest causal error -> narrow context -> classify.

Classifications:
syntax / package / symbol / type / interface / elaboration / config / tool / license / resource / environment.

Do not edit source to mask infrastructure failures.
