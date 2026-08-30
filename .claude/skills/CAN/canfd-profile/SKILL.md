---
name: canfd-profile
description: CAN-FD DV profile covering Classical CAN coexistence, FD/BRS, identifiers, filtering, arbitration, error counters/states, bus-off and recovery.
allowed-tools: Read Grep Glob PowerShell
---
# CAN-FD Profile

Detect:
- Classical CAN support
- CAN-FD
- ISO/non-ISO if applicable
- nominal/data bit timing or supported ranges
- BRS
- ESI
- standard/extended IDs
- filters
- mailbox/FIFO
- arbitration
- CRC/stuff/error detection
- ACK
- TEC/REC
- error active/passive
- bus-off/recovery
- fault injection

Do not ask bitrates when programmable settings/ranges can be inferred and generic configuration verification is sufficient.
