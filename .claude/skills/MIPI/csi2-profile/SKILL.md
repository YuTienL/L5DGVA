---
name: csi2-profile
description: MIPI CSI-2 DV profile for RX/TX over D-PHY/C-PHY or packet boundary, including lanes/trios, VC, data types, packet/frame sequencing, ECC/CRC and errors.
allowed-tools: Read Grep Glob PowerShell
---
# MIPI CSI-2 Profile

Detect:
- RX/TX direction
- D-PHY/C-PHY/packet boundary
- lane/trio count and lane rate
- CSI-2 version if documented
- virtual channels
- enabled data types: RAW/YUV/RGB/embedded/user-defined
- short/long packets
- frame/line sequencing
- ECC/CRC
- filtering/interleaving
- error injection/recovery
- ISP/bridge boundary

Resolution/frame rate is blocking only when fixed by design/requirements.
