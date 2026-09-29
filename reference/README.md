# reference/

Read-only, reference-only material. Nothing under this directory is a source
the generator (`dv_harness/uvm_generator/`) is allowed to read FROM when
producing content for a new project -- see CLAUDE.md's "No Golden-Reference
Content Mining" rule.

## USB_UVM_Handoff/

The canonical structural template named in CLAUDE.md's "Architecture-
conformance audit" section (a user-produced USB VIP-based verification
environment, built via plain Claude CLI). Consolidated into this path on
2026-09-04 so an agent can check structural/organizational conformance
without reaching outside the project tree.

Permitted uses:
- Structural/organizational conformance checking (directory layout, naming
  conventions) against a newly generated environment.
- Post-hoc fidelity/gap measurement -- comparing an ALREADY, INDEPENDENTLY
  generated environment's structure against this one, after generation.

Forbidden use:
- Reading protocol-behavior CONTENT (virtual sequence/pattern logic,
  scoreboard checking logic, coverage bins, vPlan entries, command.txt
  scenario content) from this tree to produce a new project's generated
  content. That content must come from primary sources: VIP examples/user
  manual/source code for VIP-driven content, DUT RTL/PHY documents for
  DUT-driven content.

This is enforced in code, not just policy text: `dv_harness/prompts.py`'s
`EVIDENCE_QUOTE_NOT_FOUND_IN_FILE` check fails any generation-evidence quote
whose resolved path contains `USB_UVM_Handoff` -- consolidating the tree
into this repo does not weaken that gate.

**Not tracked in git** (see `.gitignore`): the tree contains real internal
identifiers (service accounts, internal hostnames) from the original DE
handoff. It is present on disk for any agent/tool to read, but never
committed.
