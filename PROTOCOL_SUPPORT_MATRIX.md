> See START_HERE.md for the canonical entry point and current mechanism overview; this page remains accurate for its specific topic.

# Protocol Support Matrix

| Protocol | Builder | Qualification Suite | New Env Generation Framework | Production Qualified by Package Alone |
|---|---|---|---|---|
| PCIe | Yes | Yes | Yes | No |
| USB 2/3.x | Yes | Yes | Yes | No |
| Ethernet | Yes | Yes | Yes | No |
| MIPI CSI-2 | Yes | Yes | Yes | No |
| MIPI DSI | Yes | Yes | Yes | No |
| AMBA4 MM×MS | Yes | Yes | Yes | No |
| eDP | Yes | Yes | Yes | No |
| eMMC | Yes | Yes | Yes | No |
| SD/SDIO | Yes | Yes | Yes | No |
| UCIe | Yes | Yes | Yes | No |
| New Interface | Learn/Generate | Generated | Yes | Must qualify |
| New Spec Revision | Diff/Upgrade | Re-qualify | Yes | Must re-qualify |

"Production Qualified by Package Alone = No" is intentional: real DUT/VIP execution evidence cannot be manufactured inside a generic package.
