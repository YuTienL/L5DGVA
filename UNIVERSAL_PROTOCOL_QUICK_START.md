> **See CREATE_ENVIRONMENT.md** for the current, consolidated procedural guide covering this topic.

# Quick Start

## 1. Check capability truth
python3 tools/universal_protocol/protocol_status.py

## 2. Start a PCIe environment manifest
python3 tools/universal_protocol/create_protocol_manifest.py   --protocol PCIe --dut <dut_name> --role EP --out work/pcie/environment_manifest.json

## 3. Provide current evidence
Attach/point Harness to:
- DUT RTL
- current specification / PHY documents
- programming guide / register spec
- VIP install, manual, examples, source/class reference when available
- compile/run commands and environment

## 4. Run SUBSYSTEM_MODE
Evidence → generate → compile → smoke → debug → qualify.

## 5. Promote only with evidence
Use qualification_gate.py against a qualification evidence JSON.
No evidence = no PRODUCTION_QUALIFIED claim.

## 6. New Interface
Select NEW_INTERFACE and run the learning pipeline.
If no VIP exists, generate a Native UVC and qualify it.
