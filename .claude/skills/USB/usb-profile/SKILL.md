---
name: usb-profile
description: USB Host/Device routing and DV profile for USB2 FS/HS plus USB3 Gen1/Gen2, including role, PHY boundary, enumeration, transfer types, endpoints/ports, link/power and error behavior.
allowed-tools: Read Grep Glob PowerShell
---
# USB Profile

First resolve DUT role:
HOST or DEVICE.

Supported defaults:
USB2 FS / HS
USB3 Gen1 / Gen2

## Host facts
- host controller architecture if observable
- USB2/USB3 enabled ports
- PHY boundary: UTMI/ULPI/PIPE/serial/custom
- enumeration/reset/speed negotiation
- control/bulk/interrupt/isochronous
- hub support if present
- scheduling/ring/TRB behavior if xHCI/custom controller scope includes it
- LPM/link/power states
- retry/STALL/NAK/timeout/error
- VIP role usually device/peripheral-side

## Device facts
- device-controller architecture
- EP0/control endpoint
- endpoint map/directions/types
- descriptors/configurations/interfaces
- enumeration/address/configuration
- transfer types
- LPM/link/power
- retry/STALL/NAK/timeout/error
- VIP role usually host-side

Infer before asking.
