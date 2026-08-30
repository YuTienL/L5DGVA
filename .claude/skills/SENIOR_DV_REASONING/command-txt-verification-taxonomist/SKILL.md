---
name: command-txt-verification-taxonomist
description: Analyze all command.txt verification intent, classify by verification level/domain, create the correct clean directory taxonomy, move commands to the best location, preserve traceability, and remove obsolete directories only after migration validation.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# command-txt-verification-taxonomist
Classify command.txt by BLOCK_IP / SUBSYSTEM / SYSTEM_LEVEL and by protocol/feature/scenario/regression/debug purpose.
Never delete an obsolete directory until every still-valid command has a mapped destination and duplicate/obsolete status is evidenced.
