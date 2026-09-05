# GUI-09 gap close: AMBA Fabric / VIP Bind / Scoreboard card + GET /api/amba

NOTE ON THIS FILENAME: the task asked for `.work/gap-close-gui-gui-09:-report.md`.
Windows (NTFS) forbids `:` in a filename — the write fails with EINVAL — so this
report is at `.work/gap-close-gui-gui-09-report.md`, matching the
`gap-close-*-report.md` convention every other report in this directory uses.

**Status: DONE**

Commit `27009a3` on `gap-close/env-manifest-fact-sources`, 2 files, +524 lines,
0 deletions (pure insertion into `dv_harness/dashboard.py`, plus one new test file).

## The gap

`dv_harness/dashboard.py` contained zero occurrences of "amba", while the backend
pipeline (`amba_fabric_discovery.py` 140KB -> `amba_port_registry.py` ->
`amba_scoreboard_env.py`, plus `amba_fabric_analysis.py` /
`amba_route_transform_predictor.py` / `amba_transaction_ir.py` /
`amba_discovery_report.py`) is real and tested. AMBA-22's `AMBA_PORT_REGISTRY` is
the artifact that already JOINS everything a fabric reviewer needs — one row per
discovered fabric port carrying protocol, fabric/endpoint role, traced endpoint
hierarchy, AMBA-15 widths, AMBA-20 `vip_mode` and the AMBA-21 `scoreboard_channel`
that port's proposed VIP monitor would feed. Nothing surfaced it in the GUI.

## What was built

**Backend — `dv_harness/dashboard.py`:**
- `_default_amba_registry_path(root)` -> `.dv-harness/amba/amba_port_registry.json`
  (the file `amba_port_registry.save_amba_port_registry()` writes).
- `_read_amba_registry_state(root, registry_path=None)` — reads it through the REAL
  `amba_port_registry.load_amba_port_registry()` (which runs that module's own
  `assert_registry_complete()` on the way in), and derives the traced
  master/slave/unresolved split through the REAL `registry_endpoints()` and the
  fabric-port count through the REAL `amba_fabric_discovery.parent_matrix_rows()`
  (counting raw rows would count a MULTIPLE_DESTINATION port once per branch).
  Nothing is re-derived locally, so the card cannot disagree with the artifact a
  human reviewed at AMBA-16..22.
- `GET /api/amba` (+ `?registry=<path>` override, mirroring `/api/coverage`'s
  `?summary=`), placed alongside the other read-only GET branches.

**Honest states, reusing the Coverage card's existing contract rather than a new one:**
- no registry on disk -> `{"available": false, "registry_path": ...}`, never a
  fabricated port;
- incomplete registry -> `PortRegistryError`'s real `reason`/`detail`
  (`AMBA_PORT_REGISTRY_INCOMPLETE_ROW`, naming the `port_id` and the missing field);
- unparseable file -> `MALFORMED_REGISTRY_FILE` with the real message;
- a `scoreboard_channel` of `REQUIRED_HUMAN_INPUT` counts as UNmapped in the
  summary — "nothing established where this monitor would feed" is a finding a
  reviewer must see, not something to fold in with a real channel.

**Frontend — same card conventions as Coverage/FSDB:** `#ambaFabricCard` with a
`.tiles` summary row (fabric ports, registry rows, READY/PARTIAL/BLOCKED/UNKNOWN
bind readiness, VIP planned / no VIP planned, scoreboard channels mapped, traced
masters/slaves, unresolved endpoints), a 10-column table (Port / Protocol / Fabric
Role / Endpoint (traced) / Proposed VIP Bind / VIP Mode / Scoreboard Channel /
Trace Status / Readiness / Confidence), a client-side substring filter that
re-renders already-fetched rows (fetch-once, same as the FSDB card), an
"unresolved endpoints" note, and per-row hover carrying clock/reset/the four
AMBA-15 widths/`source_evidence`. `loadAmbaFabric()` is called from `load()`
next to `loadCoverageAnalysis()`. Two CSS values added for the readiness-only
words `READY`/`UNKNOWN` (`PARTIAL`/`BLOCKED` already had colors).

**Read-only by design (AMBA-30 / AMBA-31)**: every `vip_bind_hierarchy` shown is a
PROPOSED location a human approves — approving a fabric bind plan from a browser
form would be exactly the auto-acceptance `amba_port_registry.py`'s own module
docstring refuses — so there is deliberately no POST counterpart. That is stated
in the card note and asserted in the tests.

## Tests

`dv_harness_tests/test_dashboard_amba_card.py` — 7 tests, real
`dashboard.serve()` on a free local port driven over real HTTP, reusing
`test_dashboard_interactive.py`'s own harness helpers (the same cross-test import
convention `test_amba_port_registry.py` already uses). Registry fixtures are
written by the REAL `save_amba_port_registry()`, so a fixture drifting from
AMBA-22's nineteen-field contract fails at write time. The fixture deliberately
carries one fully-traced READY port AND one TRACE_BLOCKED port with no endpoint /
no VIP / no channel — a clean-port-only fixture would prove nothing about the
unresolved half the card exists to surface.

1. honest empty state when no registry exists (and the named path really is absent)
2. real rows + every derived number equal to what the real `registry_endpoints()`
   / `load_amba_port_registry()` return, all 19 fields non-empty
3. incomplete registry -> real `AMBA_PORT_REGISTRY_INCOMPLETE_ROW` reason/detail, not a 500
4. malformed file -> `MALFORMED_REGISTRY_FILE`, not a 500
5. `?registry=` override reads a real registry elsewhere while the default stays empty
6. card is in the served HTML AND called by `load()` (guards against the
   PARTIALLY_WIRED shape)
7. `assert_no_bind_statement()` — the same gate `amba_port_registry.py` runs over
   its own rendered report — run over the served HTML and the endpoint payload

## Test summary

`pytest dv_harness_tests/test_dashboard_interactive.py test_dashboard_cli_checklist_rendering.py test_dashboard_amba_card.py` -> **72 passed** (95.9s); `test_amba_port_registry.py` -> **50 passed**.

## Deferred / not done (scope boundary, stated rather than implied closed)

- Only the AMBA-22 registry is surfaced. `amba_fabric_analysis.py`,
  `amba_route_transform_predictor.py`, `amba_transaction_ir.py` and
  `amba_discovery_report.py`'s conclusions / confidence-legend / L5-branch-mapping
  artifacts have no card yet; the registry was chosen because it is the one
  artifact that already joins the per-port facts from all of AMBA-15..21.
- No write path (by design, see AMBA-30/AMBA-31 above) — approving a bind plan
  stays outside the GUI.
- This harness repo has no AMBA RTL of its own, so its own default registry path
  is legitimately absent and the card renders its honest empty state here. The
  endpoint is proven against a real registry file in the tests, not against a
  fabricated one committed into this project's real artifact tree.

## Files changed

- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\dashboard.py` (+202)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_dashboard_amba_card.py` (new, +322)

`dv_harness/config.py` was not touched. Both files were verified clean
(`git diff --stat`) before editing, the finished diff was reviewed hunk-by-hunk
to confirm all six hunks were mine, and staging was scoped to exactly these two
paths — the concurrent `engine.py` / `question_queue.py` edits in the working
tree were left unstaged.
