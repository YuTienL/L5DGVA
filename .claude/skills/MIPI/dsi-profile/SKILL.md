---
name: dsi-profile
description: MIPI DSI DV profile for Host/Peripheral, command/video mode, D-PHY/C-PHY, pixel/packet behavior, LP/HS transitions, ECC/CRC and error reporting.
allowed-tools: Read Grep Glob PowerShell
---
# MIPI DSI Profile

Detect:
- Host/Peripheral
- D-PHY/C-PHY/packet boundary
- command/video mode
- lane/trio count
- pixel formats
- timing/resolution constraints when fixed
- burst/non-burst
- LP/HS transitions
- short/long packets
- BTA/ACK/error reporting if supported
- ECC/CRC
- initialization/low-power commands
- TE if present

Do not force display-timing questions when programmable generic range testing is sufficient.
