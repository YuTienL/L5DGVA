---
name: regression-core
description: Protocol-agnostic targeted-test/regression workflow with seed/config capture, signature clustering and rerun policy.
allowed-tools: Read Grep Glob PowerShell
---
# Regression Core

Prefer smallest representative test before full regression.

Record:
protocol, testcase, seed, config, command, result, log, signature.

Failure:
collect -> normalize -> cluster -> representative -> debug -> fix -> targeted rerun -> relevant regression.

Do not rerun blindly without a changed hypothesis/evidence.
