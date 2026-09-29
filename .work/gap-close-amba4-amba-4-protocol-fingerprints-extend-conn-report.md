# AMBA-4: protocol classification from RTL evidence — DONE

**Scope**: build step "AMBA-4 protocol fingerprints: extend connectivity.py
PROTOCOL_FINGERPRINTS with AHB/AHB-Lite/APB/APB3/APB4/AXI3/AXI4/AXI4-Lite/
ACE-Lite/AXI4-Stream signal sets", from the AMBA4 SoC bus-fabric discovery
section (AMBA-1..32) of
`D:/DV/Task/DV_Agent_Harness_L5/DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_AMBA4_CCE_Research.md`
(AMBA-4 body at lines 3703-3736).

**Status**: DONE.

**Prior audit verdict being closed**: AMBA-4 = NEVER_BUILT. Confirmed before
building — `PROTOCOL_FINGERPRINTS` held four coarse AMBA buckets and no
sub-protocol entries, and the only other AMBA sub-protocol handling in the
repo (`dv_harness/protocol_router.py`'s `_ALIASES`) is free-text token
routing onto the single `"amba"` profile, i.e. exactly the naming-based
method AMBA-4 forbids.

**Files changed** (both, entirely):
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/connectivity.py` (+519/-8)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/test_connectivity.py` (+354)

---

## What was built

Extended `connectivity.py` in place — no new parallel module, no second
classifier — per the reuse-first constraint.

### 1. Spec-fixed AMBA signal-set constants (`connectivity.py:673-756`)

One source of truth. The ten `PROTOCOL_FINGERPRINTS` entries are *built from*
these constants, and `classify_amba_protocol()` discriminates using the same
constants. There is deliberately no second AMBA signal table anywhere.

`AHB_CORE_SIGNALS`, `AHB_MULTI_MASTER_ONLY_SIGNALS`,
`AHB_OPTIONAL_EVIDENCE_SIGNALS`, `APB_CORE_SIGNALS`, `APB3_EVIDENCE_SIGNALS`,
`APB4_EVIDENCE_SIGNALS`, `AXI_MM_CORE_SIGNALS`, `AXI_BURST_EVIDENCE_SIGNALS`,
`AXI_ID_EVIDENCE_SIGNALS`, `AXI3_ONLY_EVIDENCE_SIGNALS`,
`AXI4_ONLY_EVIDENCE_SIGNALS`, `AXI4_LITE_EVIDENCE_SIGNALS`,
`ACE_LITE_COHERENCY_SIGNALS`, `AXI4_STREAM_CORE_SIGNALS`,
`AXI4_STREAM_OPTIONAL_EVIDENCE_SIGNALS`, plus `AMBA4_PROTOCOLS` (the ten
mandated labels, `connectivity.py:735`), `AMBA4_DISPLAY_NAMES` (the doc's own
spellings — `"AXI4-Lite"`, not `"AXI4_LITE"` — so a report never invents one),
and `AMBA_FAMILY_CORE_SIGNALS` (`:749`).

### 2. Ten sub-protocol fingerprint entries (`connectivity.py:813-836`)

All ten of `AHB`, `AHB_LITE`, `APB`, `APB3`, `APB4`, `AXI3`, `AXI4`,
`AXI4_LITE`, `ACE_LITE`, `AXI4_STREAM`.

**Two pre-existing entries were corrected rather than left as coarse buckets**,
because `"AHB"` and `"APB"` are themselves mandated AMBA-4 labels and two
meanings under one key is how a report prints a label it never established:
- `"APB"` was `{PSEL,PENABLE,PWRITE,PREADY}` — it omitted `PADDR`/`PWDATA`/
  `PRDATA` and *required* `PREADY`, which is APB3 evidence. It could not match
  a base APB2 interface at all, and matched APB3 while reporting `"APB"`.
- `"AHB"` was `{HTRANS,HADDR,HWRITE,HREADY}`, which matches AHB-Lite exactly as
  well as full AHB.

`"AXI"`/`"AXI_LITE"` are byte-unchanged coarse family buckets; they are not in
`AMBA4_PROTOCOLS`. Verified by grep before the change that no caller anywhere
in the repo read the `"AHB"`/`"APB"` entries — their only consumers are this
module's own matcher and classifier.

### 3. Token matching replaces substring matching for these ten (`:874-965`)

`amba_signal_tokens()` (`:874`) splits port names on non-alphanumeric
boundaries (`S00_AXI_AWVALID` -> `{S00, S, AXI, AWVALID}`) and folds a trailing
index (`HADDR0` -> `HADDR`). `match_protocol_fingerprint()` (`:908`) gained
`strict_tokens`, defaulting to "decide from the protocol": the ten
`AMBA4_PROTOCOLS` use TOKEN matching, **every other protocol keeps the original
substring behavior byte-for-byte**, and the result now carries `match_method`.

This is load-bearing, not tidying. The old matcher was:

```python
present = {sig for sig in required if any(sig in p for p in port_names)}
```

`"WID" in "AWID"` is `True`. AXI-4's own AXI3-vs-AXI4 discriminator is `WID`
presence, and every AXI4 interface carries `AWID` — so a substring-matched
AXI3 fingerprint would have reported AXI3 on **every** AXI4 port list, i.e. the
discriminator would have been exactly inverted. Same class of trap:
`"HREADY" in "HREADYOUT"`, `"TID"` inside a port merely spelled `..._TIDLE`.

### 4. `classify_amba_protocol()` (`:1104-1208`) — the real classifier

Resolves family first (`AHB`/`APB`/`AXI_MM`/`AXI_STREAM`), then applies the
doc's own discriminators:

| decision | discriminator | helper |
|---|---|---|
| AHB vs AHB-Lite | presence of arbitration/split signalling (`HMASTER`/`HSPLIT`/`HBUSREQ`/`HGRANT`/`HLOCK`) | `_resolve_ahb_variant` `:1034` |
| APB vs APB3 vs APB4 | `PREADY`/`PSLVERR` then `PSTRB`/`PPROT` | `_resolve_apb_variant` `:1047` |
| ACE-Lite / AXI3 / AXI4 / AXI4-Lite | coherency signals, then `WID`, then burst/ID presence | `_resolve_axi_mm_variant` `:1061` |
| AXI4-Stream | its own family; reported separately from memory-mapped AXI | inline `:1160` |

`HMASTLOCK` is deliberately **excluded** from the AHB discriminator: AHB-Lite
carries `HMASTLOCK` too, so using it would have misclassified every AHB-Lite
interface as full multi-master AHB. `HLOCK` (master->arbiter, full AHB only) is
distinct from `HMASTLOCK` only under token matching.

**AMBA-4's prohibition is structural, not a review rule**: the function's only
parameter is `port_names`. There is no module-name, instance-name or file-name
parameter to accidentally consult — asserted by a test that reads the real
signature.

### 5. Four distinct unresolved states, never a best guess (`:969-989`)

`AmbaClassificationStatus`: `RESOLVED`, `AMBIGUOUS_MULTIPLE_PROTOCOLS`,
`AMBIGUOUS_CONTRADICTORY_EVIDENCE`, `UNRESOLVED_PARTIAL_EVIDENCE`, `NOT_AMBA`.
Every non-RESOLVED outcome carries `protocol = AMBA_PROTOCOL_UNRESOLVED` (a
real greppable string, same rationale as the existing `REQUIRED_HUMAN_INPUT`
sentinel — never `None`) and `requires_human_confirmation=True`.

- `AMBIGUOUS_MULTIPLE_PROTOCOLS` — the realistic case is a protocol **bridge**
  module: an AHB-to-APB bridge's port list contains both families in full, and
  a single-protocol verdict at module granularity would be an invented fact.
- `AMBIGUOUS_CONTRADICTORY_EVIDENCE` — e.g. ACE-Lite coherency signals (which
  imply an AXI4 base) together with AXI3-only `WID`; AXI4 defines away `WID`,
  so both cannot hold.
- `UNRESOLVED_PARTIAL_EVIDENCE` — names the missing required signals, per
  AMBA-3's "Do not silently omit partial/incomplete interfaces".
- `NOT_AMBA` — including the honestly-disclosed SV-interface-port limitation
  (below).

`AmbaProtocolClassification` (`:992`) is a dataclass with `to_dict()` and a
`display_name` property, JSON-serializable for a downstream topology artifact.

### 6. Wired into the existing 4-tier bind classifier (`:1211-1240`)

`amba_structural_match()` returns a dict in exactly
`match_protocol_fingerprint()`'s shape, so it feeds
`classify_bind_tier(structural_match=...)` directly — no second notion of
"matched". RESOLVED gives `T2_STRUCTURAL_MATCH`; every ambiguous/partial/
non-AMBA outcome gives `matched=False` and therefore falls through to T3
(human confirmation) or T4 (question queue) and **can never be auto-accepted**.
`classify_amba_interfaces()` runs it over a whole
`build_interface_fingerprints()` result.

---

## Hard constraint honored (AMBA-30 / AMBA-31)

No `bind` statement is emitted, planned, or written anywhere by this change.
Nothing downstream of `AMBA_PORT_REGISTRY` is auto-applied. This step is
discovery/classification machinery only. The synthetic fixtures are port-name
sets and `verible_parser` dataclasses inside the test file — there is no
generated UVM environment and no `.sv` output on any path touched here.
Verified by grep over both changed files: the only `bind`-related content is
the pre-existing `parse_bind_line`/`grep_existing_binds` *parser* and its
pre-existing test fixtures, untouched by this change.

---

## Tests

29 new cases in
`D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/test_connectivity.py`
(the AMBA-4 section starting at line 126), including:

- **Table-vs-classifier agreement over all ten protocols** (parametrized): a
  port set that *is* a fingerprint entry must both `matched=True` and classify
  RESOLVED to that same protocol. The two answer different questions and are
  not allowed to contradict.
- **The AWID/WID trap** — asserts both the verdict (AXI4, not AXI3) *and* the
  mechanism (`"WID" not in amba_signal_tokens(axi4_ports)`).
- **The HREADY/HREADYOUT trap** — an AHB port list exposing only `HREADYOUT`
  is reported partial with `HREADY` named as missing.
- **HMASTLOCK must not promote AHB-Lite to full AHB.**
- **Corrected base-APB entry** — no longer requires `PREADY`, now includes
  `PADDR`/`PWDATA`/`PRDATA`, and matches a real APB2 port list.
- **A synthetic 2-master/4-slave mixed-protocol fabric fixture**
  (`_SYNTHETIC_FABRIC_INTERFACES`): AXI4 CPU + AXI3 legacy DMA on the slave
  side; ACE-Lite DDR, APB4 peripheral, AHB-Lite SRAM and AXI4-Stream video on
  the master side. Built through the **real** `verible_parser.ModuleInfo`/
  `PortInfo` dataclasses and the **real** `build_interface_fingerprints()`, so
  the classifier is exercised on the objects a live parse produces, not on
  hand-made sets. All six resolve correctly, each citing its own evidence.
- **The ambiguous/unresolved half, not happy-path only**: the AHB-to-APB
  bridge (`AMBIGUOUS_MULTIPLE_PROTOCOLS`), ACE-Lite+WID and QoS-without-burst/ID
  (`AMBIGUOUS_CONTRADICTORY_EVIDENCE`), an AXI interface missing its whole R
  channel (`UNRESOLVED_PARTIAL_EVIDENCE`, with all four missing signals named),
  a USB port list and an SV-interface-typed port (`NOT_AMBA`). Plus: an
  unresolvable whole-fabric wrapper added to the fixture must **not**
  contaminate the six interfaces that do resolve.
- **Tier integration**: RESOLVED -> T2; ambiguous + a naming match -> T3 with
  `assert_t3_never_auto_accepted()` passing; ambiguous alone -> T4 question
  queue.
- **Name-independence**: `inspect.signature(classify_amba_protocol)` has
  exactly one parameter, and an APB4 port list with a deliberately lying
  `u_axi4_master_bridge` prefix still classifies APB4.
- **Legacy preservation**: `"AXI"`/`"AXI_LITE"` entries byte-identical, still
  `match_method == "SUBSTRING"`, still matching as before.

**Test summary**: `205 passed` in `test_connectivity.py` (176 before, +29);
`540 passed` across every module in the repo that imports `connectivity`
(`test_connectivity`, `test_connectivity_check`, `test_amba_fabric_generator`,
`test_confidence_vocabulary_separation`, `test_protocol_capability`,
`test_protocol_router` = 301; `test_bind_mechanism_generator`,
`test_bind_verification_lint`, `test_four_key_judgments_enforcement`,
`test_waveform_dump_scope_human_confirmation`, `test_context_budget`,
`test_asset_processing_artifacts` = 239). Zero failures.

---

## Disclosed limitations (stated, not implied closed)

1. **SystemVerilog interface ports are invisible.** A fabric port declared as
   `AXI4 s_axi` exposes no individual signals, so it tokenizes to nothing
   AMBA-shaped and lands in `NOT_AMBA`. `verible_parser` does not model
   modports (the same gap the AMBA-2 audit recorded). Classifying it from the
   interface *type name* would be precisely what AMBA-4 forbids, so it is
   reported honestly instead. Covered by a named test. Closing this needs
   modport parsing, which is AMBA-2/AMBA-3 territory, not AMBA-4's.
2. **`AMBA_PARTIAL_EVIDENCE_MIN_SIGNALS = 2`** is the floor below which a lone
   coincidental token (`TDATA` on a non-AMBA module) reads as NOT_AMBA rather
   than as a partial interface. Two co-occurring spec names is the evidence
   threshold; it is a constant, not a magic number buried in a branch.
3. **The AMBA-6 counting table is not built here** — a test proves the
   classification output is *countable* in that shape, but AMBA-5
   (FABRIC_SIDE_ROLE / EXTERNAL_ENDPOINT_ROLE) and AMBA-6 are later steps in
   this sequence.
4. **Not yet run against real AMBA RTL.** Every signal name here is spec-fixed
   (unlike the module's ILLUSTRATIVE CSI2/DSI/USB3/PCIE/SDIO sets, which carry
   their own honesty caveat), and the fixtures are synthetic. The
   AMBA4-UNTESTED_PLACEHOLDER framing from the earlier audit is narrowed by
   this step, not eliminated: no real AMBA4 DUT has been classified yet.

---

## Commit

**The AMBA-4 code and tests are committed and present in `HEAD`**, but landed
inside a *concurrent agent's* commit rather than one of my own:

- I staged exactly my two files via the hand-scoped patch technique
  (`git diff -- <2 paths> > patch`; `git apply --cached --check` -> OK;
  `git apply --cached`), having first confirmed the only other outstanding
  hunk in `connectivity.py` (a comment block at `:119-137` from a concurrent
  agent) had already been committed by them as `4084531`.
- Between my `git apply --cached` and my `git commit`, a concurrent agent ran
  its own commit, which swept my staged index in. My commit then found nothing
  staged.
- Result: **`74ffda3`** ("docs(.work): re-verify AI mechanism #4 Route & Skill
  Resolver, no fix needed") contains my `connectivity.py` (+519/-8) and
  `test_connectivity.py` (+354) alongside that agent's `.work` report.
  `git diff HEAD` for both my files is empty, and `HEAD:dv_harness/connectivity.py`
  contains all the new symbols — the content landed intact and complete.

I deliberately did **not** rewrite `74ffda3` to split it out. Amending or
soft-resetting a shared HEAD while multiple agents are committing into this
repo is exactly the clobbering risk the hand-scoped-patch instruction exists to
avoid, and it would rewrite another agent's commit and message. This report
carries the scoped description that the mixed commit's own message does not,
and its own commit references the SHA.
