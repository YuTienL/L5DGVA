# Gap-close: env.manifest.json 3 fact-source layers (VIP / DUT / Env)

**Verdict: DONE.** All 4 BLOCKED requirements closed for real; 5 READY requirements
re-confirmed unchanged; 0 NEEDS_SEPARATE_EFFORT.

**Commit**: `085b809` on branch `gap-close/env-manifest-fact-sources`
(branched off `master` — not committed to a protected branch, per CLAUDE.md's
gh CLI + PR-Only Governance Policy).

**Test summary**: 34 new tests in `dv_harness_tests/test_env_manifest_fact_sources.py`
all pass (including a real end-to-end `pypdf` extraction against this repo's own
20-page PDF); 288 pass across the 8 pre-existing env_manifest / MCP / blackboard /
context-budget suites that consume this contract.

---

## Re-verification note: the file had moved since the audit

The audit measured `dv_harness/env_manifest.py` at 420 lines. On starting this pass it
was **625 lines and staged** — a concurrent workflow had added two bridges
(`ingest_rtl_parse_to_evidence_db`, `sync_to_blackboard`). I re-read it fresh rather
than patching against the audit's line numbers. Both bridges are unrelated to the 4
gaps, all of which re-verified as still open against the current file:

```
$ grep -rn "DESIGNWARE_HOME" dv_harness/ --include=*.py
dv_harness/uvm_generator/templates/sim_scripts/check/make_order.py:46:  'VERDI_HOME', 'DESIGNWARE_HOME'}   <- an env-var allow-list, not extraction
$ grep -n "address_map\|clock_reset" dv_harness/env_manifest.py     -> no hits
$ grep -ni "testlist\|vplan\|coverage" dv_harness/env_manifest.py   -> 1 hit, inside an
   unrelated comment naming dashboard._ingest_coverage_summary_to_evidence_db
```

`generated/01_architecture/clock_reset_map/` exists but is **empty**, so there was no
real SoC-pipeline output to wire — which is why gap 6 landed as an input contract
rather than an extractor (see below).

---

## READY requirements — re-confirmed, not modified

| # | Requirement | Evidence re-checked |
|---|---|---|
| 1 | `svt_*_configuration` zero-time dump | `dv_env_manifest_pkg.sv:242-256` end_of_elaboration_phase; `env_manifest.py` `parse_vip_config_dump`/`build_vip_config` unchanged by this work |
| 4 | Ports/params via `verible-verilog-syntax --export_json` | `verible_parser.py:125-145` real subprocess; `build_dut_facts_rtl` still calls it unmodified |
| 5 | Register map via RAL/IP-XACT JSON, never raw Excel | `register_map.schema.json` input contract; no xlsx/openpyxl path in `env_manifest.py` |
| 7 | `uvm_top.print_topology()` + `+UVM_CONFIG_DB_TRACE` | `dv_env_manifest_pkg.sv:249`; `parse_config_db_trace_log` envelope-only parse with `parse_confidence` |
| — | Extends the existing JSON IR pipeline | Same `Draft202012Validator` + `SCHEMA_PATH`-under-`schemas/` + validate/load/save triad; the 3 new sub-layers follow the identical builder shape and the identical `NOT_AVAILABLE`-with-honest-`reason` contract |

---

## BLOCKED requirements — closed

### Gap 2 — VIP version / release notes / feature matrix from `$DESIGNWARE_HOME`

`env_manifest.scan_designware_home()` + `build_vip_release()` →
`vip_config.vip_release`.

A real filesystem walk of both layouts `dw_vip_setup` produces
(`vip/svt/<pkg>/<ver>` and `vip/<pkg>/<ver>`), locating each package's real
release-notes / feature-matrix file by case-insensitive filename fragment, bounded to
3 directory levels.

Deliberate properties, each with a test:
- Documents are recorded as **path + sha256 + bytes, never content** — env.manifest.json
  is a tier-2 always-resident artifact, so inlining a vendor changelog would push it into
  every session's context in perpetuity.
- A package that genuinely ships no feature matrix gets an all-null ref, so
  "looked, and there is none" stays visible instead of being omitted.
- **Unset** `$DESIGNWARE_HOME` and **set-but-nonexistent** are distinct NOT_AVAILABLE
  reasons, and the bad path survives into `source.path` so a typo stays diagnosable.

A real bug was found here **by the tests, not by inspection**: because the `vip` root
contains the `vip/svt` root, the first implementation reported `svt` as a package whose
"versions" were the real package names — a wrong answer that still looked structurally
plausible in the manifest. Fixed by skipping any candidate that is itself a configured root.

### Gap 3 — User guide PDF distilled OFFLINE, never loaded into runtime context

New module `dv_harness/vip_user_guide_distill.py` + `dv-harness vip-user-guide distill`
+ `vip_config.user_guide_refs`.

**"Offline" is enforced structurally, not by intention**: this is the only module that
ever opens a source document, it runs as its own CLI command, and `env_manifest.py` reads
only the small `.reference.json` it leaves behind. A generation run therefore cannot pull
a guide's text into context even by accident, because that code path is not on it.

Three artifacts per document: `<stem>.fulltext.txt` (targeted-read target),
`<stem>.reference.md` (bounded section index — heading, page, char offset),
`<stem>.reference.json` (the record the manifest consumes). The manifest itself stores
pointers plus a section **count** — not the headings, not one word of prose — and
`assert_no_user_guide_body_in_manifest()` runs on every `generate_env_manifest()` to make
that checkable (the schema polices shape but cannot notice prose parked in a legitimately
string-typed field).

The section index is mechanical heading detection, not a generated summary — the same
"what exists and where, then ONE targeted read" discipline `vip_symbol_index.py` already
established. A prose summary would be invented content nothing downstream could verify.

Verified against the real PDF in this repo:

```
$ python -m dv_harness vip-user-guide distill --source docs/DV_Agent_Harness_L5_Detailed_User_Guide_TC.pdf ...
  "extraction": {"tool": "pypdf", "tool_version": "5.9.0", "method": "pdf_text_extraction"},
  "source_document": {..., "page_count": 20}, "section_count": 17
```

**Correction shipped alongside**: `context_budget.policy.json`'s `NEVER-RAW-PDF` rule
routed to `dv_harness/doc_extraction.py` and asserted it "really does handle .pdf (see
its SUPPORTED set)". That claim is **false** — `doc_extraction.py` merely *lists* `.pdf`
in a suffix set; all 71 of its lines are sha256/index/record-normalisation and it
contains no PDF text extraction whatsoever. The tier-1 denial's route forward therefore
pointed at a script that could not perform it. Both the policy and CLAUDE.md now name
the real distiller and record the correction.

### Gap 6 — Address map / clock-reset topology from the SoC spec pipeline

New `dv_harness/schemas/soc_arch_map.schema.json` input contract +
`load_soc_arch_map()` / `build_dut_facts_address_map()` / `build_dut_facts_clock_reset()`
→ `dut_facts.address_map`, `dut_facts.clock_reset`.

**Why a contract and not an extractor**: `generated/01_architecture/clock_reset_map/` is
empty and dv_harness owns no SoC, so there is nothing here to extract *from*. An
"extractor" would have to invent architecture, which the Evidence Truth Rule forbids.
This follows `register_map.schema.json`'s already-established precedent exactly.

**What earns the layer its place beyond passthrough**: a register map and an address map
both claim a base address per block, and carrying both without comparing them is how an
environment ends up with a decoder at one base and a RAL model at another, each
internally consistent. Every entry gets a real `register_map_agreement`:

- `AGREES` / `DISAGREES` — **compared as integers**, so `0x01000` and `0x1000` agree
  (a string compare would manufacture a disagreement that does not exist).
- `NOT_IN_REGISTER_MAP` vs. `NOT_AVAILABLE` — "compared, and absent" is deliberately kept
  distinct from "nothing to compare against"; they are different findings.
- A `DISAGREES` is **surfaced, never auto-resolved** — the address map keeps its own value
  untouched, per Source Authority Order.

Reset `active_level` is required by the contract and never defaulted (an assumed reset
polarity is among the cheapest ways to hold a DUT in reset for an entire run while every
machine gate still reports PASS). A reset naming a clock the same document never declares
reports `UNKNOWN_CLOCK` rather than being carried silently.

### Gap 8 — Testlist / vPlan / coverage-model correspondence

New `dv_harness/schemas/testplan_sources.schema.json` +
`build_testplan_correspondence()` → `env_topology.testplan_correspondence`.

The join is the deliverable. Each list read alone always looks healthy — the testlist
runs, the vPlan has rows, the covergroups compile. Only the join exposes:
a vPlan item claiming a test no regression runs (`BROKEN_TEST_REF`); one measured by a
covergroup nobody wrote (`BROKEN_COVERAGE_REF`); verification intent with nothing attached
(`UNCLAIMED`); and both orphan directions — tests burning sim time against no stated
intent, coverage collected against none.

Matching is a **literal name join, never fuzzy** — the entire value of the layer is that
its `*_missing` and `orphans` lists can be trusted.

Two honesty properties, each with a test:
- An item whose claims could not be checked because that axis was not supplied reports
  **`NOT_CHECKED`, never `LINKED`** — reporting LINKED for claims nothing verified would
  be exactly the false reassurance this layer exists to prevent.
- Orphan lists are only populated when both sides were supplied, so an empty list can
  never silently mean "we could not look".

Scope note: `LINKED` means "every name this item cites is real". It does **not** mean the
test exercises the item or that bins are hitting — that is a coverage-*result* question
owned by `coverage_analysis.py`, and is not claimed here.

---

## Schema version: a deliberate breaking bump

`env_manifest.schema.json` 1.0 → **1.1**, with the 5 new sub-layers as **REQUIRED** keys.
A stale 1.0 manifest now fails `load_env_manifest()` loudly rather than silently presenting
an environment as having no address map and no testplan correspondence — a claim about the
environment it cannot support. `env_manifest.py` is the sole writer and no `env.manifest.json`
exists anywhere in this repo (`find . -name env.manifest.json` → nothing), so the fix is
regeneration, never migration.

`dv_harness_tests/mcp_manifest_fixture.py` was updated to the real 1.1 contract — that
fixture's own docstring says it exists to match the real generator's contract, so leaving it
at 1.0 would have made it lie. Its address-map entry deliberately AGREES and its
testplan item VP-002 deliberately carries a broken test ref, so the fixture models a
realistic environment rather than an all-clean one.

## Blackboard summary extended

`summarize_for_blackboard()` now also carries the installed VIP package name+version list,
distilled guide titles + section counts, the **names** of disagreeing address regions, and
the **ids** of broken/unclaimed vPlan items — the conflicts themselves, not merely their
counts, because a reading stage must not have to open a file to discover them. Still
prompt-sized: no document prose, no parse trees, no per-item coverage detail (asserted).

## Files

Modified: `CLAUDE.md`, `dv_harness/cli.py`, `dv_harness/context_budget.policy.json`,
`dv_harness/env_manifest.py`, `dv_harness/schemas/env_manifest.schema.json`,
`dv_harness_tests/mcp_manifest_fixture.py`.
Added: `dv_harness/vip_user_guide_distill.py`,
`dv_harness/schemas/soc_arch_map.schema.json`,
`dv_harness/schemas/testplan_sources.schema.json`,
`dv_harness_tests/test_env_manifest_fact_sources.py`.

## Concurrency handling

Per the brief's warning about concurrent workflows: `git status` was checked before every
file touch; `env_manifest.py` and `cli.py` had both been changed by other workflows and were
re-read fresh rather than patched from the audit's line numbers. Before committing,
`git diff -U0 dv_harness/env_manifest.py | grep "^-"` was inspected line by line to confirm
every deletion in the staged hunks was mine. Only the 10 files above were staged — no broad
`git add`. Committed to a feature branch, never to `master`.
