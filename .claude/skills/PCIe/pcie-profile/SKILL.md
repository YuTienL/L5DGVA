---
name: pcie-profile
description: PCIe Gen2-Gen6 DV profile for RC/EP/Switch, lane/boundary discovery, LTSSM, config/TLP, interrupts, error, power management and evidence-enabled advanced features.
allowed-tools: Read Grep Glob PowerShell
---
# PCIe Profile

Detect:
- Gen2/Gen3/Gen4/Gen5/Gen6
- Root Complex / Endpoint / Switch
- lane width
- serial/PIPE/controller boundary
- LTSSM/link-training scope
- configuration-space/BAR/capabilities
- memory/IO/config transactions
- completion/ordering
- INTx/MSI/MSI-X
- AER/error injection
- ASPM/LTR/power features when present
- SR-IOV/ATS/PASID/PRI/Atomic only when evidence enables them

Do not infer every optional Gen6 feature merely from generation.
