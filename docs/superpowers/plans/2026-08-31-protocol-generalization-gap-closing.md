# Protocol-Generalization Cross-Cutting Gap Closing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 6 cross-cutting gaps the `protocol-coverage-capability-audit` workflow found across PCIe/Ethernet/MIPI-CSI2/MIPI-DSI/eMMC/SD-SDIO/AMBA, so the harness's already-protocol-agnostic core (generator DSL, gates, intake) stops being undermined by dead duplicate skills, a self-contradictory wiring story, hardcoded USB literals in gate logic, router omissions, un-cross-linked dedicated generators, and under-specified intake evidence.

**Architecture:** Six independent tasks, each touching disjoint files (verified against the audit's evidence lists) — no ordering dependency, run in parallel via fresh subagents. Task 7 (consolidation sync) runs last since it depends on all six being done.

**Tech Stack:** Python 3.10+ (stdlib only, `argparse`/`json`/`pathlib`), pytest, Markdown skill files. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-31-protocol-generalization-gap-closing-design.md`

## Global Constraints

- `v50` is not a git repository — no destructive operations (no hard deletes of the dead skill directories; archive-move only, per spec §4 Task 1 and the explicit user decision).
- Every file edit must remove any comment/description in that file that is now outdated, redundant, or unrelated (CLAUDE.md "Comment hygiene" — applies to every task below, especially Tasks 1 and 2 where stale NOTICE text is exactly what's being fixed).
- No task touches remote execution, real VCS/LSF, or any Linux DV server path — Execution Mode for this whole plan is LOCAL_ANALYSIS.
- Never mine `USB_UVM_Handoff`'s content — every change here is wiring/cleanup/schema-generalization, never protocol-behavior authoring (spec §3 Non-goals).
- All new/edited test files go under `dv_harness_tests/` (the only path in `testpaths` in `pyproject.toml`), importing sibling modules the same way `dv_harness_tests/test_remote_control.py` does (`ROOT = Path(__file__).resolve().parents[1]`, then import via that root).

---

## Task 1: Archive dead duplicate protocol skills

**Files:**
- Move (21 directories, each a full directory move preserving internal structure):
  - `.claude/skills/UNIVERSAL_PROTOCOL/{pcie-production-builder,ethernet-production-builder,mipi-csi2-production-builder,mipi-dsi-production-builder,emmc-production-builder,sd-sdio-production-builder,amba4-multi-master-multi-slave-builder}` → `.claude/skills/_deprecated/UNIVERSAL_PROTOCOL/<same-name>`
  - `.claude/skills/REAL_PROJECT_GENERATION/{pcie-complete-env-generator,ethernet-complete-env-generator,mipi-csi2-complete-env-generator,mipi-dsi-complete-env-generator,emmc-complete-env-generator,sd-sdio-complete-env-generator,amba4-mmxms-complete-env-generator}` → `.claude/skills/_deprecated/REAL_PROJECT_GENERATION/<same-name>`
  - `.claude/skills/REAL_ENV_GENERATION/{pcie-real-env-generator,ethernet-real-env-generator,mipi-csi2-real-env-generator,mipi-dsi-real-env-generator,emmc-real-env-generator,sd-sdio-real-env-generator,amba4-real-env-generator}` → `.claude/skills/_deprecated/REAL_ENV_GENERATION/<same-name>`
- Do NOT move anything else in these three trees (e.g. `edp-*`, `ucie-*`, `usb-*`, `new-interface-*`, `new-spec-*`, `real-compile-closure-engine`, `real-dut-interface-extractor`, `real-protocol-semantic-synthesizer`, `real-smoke-closure-engine`, `real-vip-api-learner`, `real-vip-binder`, `generated-env-compile-repair`, `generated-env-smoke-repair`, `native-uvc-code-generator`, `protocol-semantic-model-builder`, `real-uvm-environment-generator`, `vip-api-binding-agent`, `protocol-capability-truth-enforcer`, `protocol-qualification-suite-runner`, `universal-protocol-builder-router`) — out of scope per spec, not protocol-name duplicates of a `PROTOCOL_BUILDERS/*-environment-builder`.

**Interfaces:**
- Produces: `.claude/skills/_deprecated/` tree, consumed by Task 7's sync step.

- [ ] **Step 1: Pre-move reference check (must find zero live references)**

For each of the 21 directories above, read its `SKILL.md` frontmatter `name:` field, then run:

```bash
cd "D:/DV/Task/DV_Agent_Harness_L5/v50"
NAME="pcie-production-builder"   # substitute each of the 21 names in turn
find .claude/skills -name SKILL.md -print0 | xargs -0 grep -ln "$NAME" 2>/dev/null | grep -v "_deprecated/"
grep -n "$NAME" .dv-harness/builder/protocol_builder_registry.json .claude/agents/*.md 2>/dev/null
```

(the two-star glob `.claude/skills/**/SKILL.md` does not recurse correctly in
plain bash without `shopt -s globstar` — `find` is used instead since the
real skill directories are two levels deep, `CATEGORY/skill-name/SKILL.md`)

Expected: no output for every one of the 21 names, except the grep matching the file's own `SKILL.md` inside its own (pre-move) directory, which is expected and not a "live reference" (a skill's own frontmatter naming itself is not a reference from elsewhere). If any OTHER file references the name, stop and report that directory instead of moving it — do not move a skill that turns out to be referenced.

- [ ] **Step 2: Move the 21 directories**

```bash
cd "D:/DV/Task/DV_Agent_Harness_L5/v50"
mkdir -p .claude/skills/_deprecated/UNIVERSAL_PROTOCOL .claude/skills/_deprecated/REAL_PROJECT_GENERATION .claude/skills/_deprecated/REAL_ENV_GENERATION

for n in pcie-production-builder ethernet-production-builder mipi-csi2-production-builder mipi-dsi-production-builder emmc-production-builder sd-sdio-production-builder amba4-multi-master-multi-slave-builder; do
  mv ".claude/skills/UNIVERSAL_PROTOCOL/$n" ".claude/skills/_deprecated/UNIVERSAL_PROTOCOL/$n"
done

for n in pcie-complete-env-generator ethernet-complete-env-generator mipi-csi2-complete-env-generator mipi-dsi-complete-env-generator emmc-complete-env-generator sd-sdio-complete-env-generator amba4-mmxms-complete-env-generator; do
  mv ".claude/skills/REAL_PROJECT_GENERATION/$n" ".claude/skills/_deprecated/REAL_PROJECT_GENERATION/$n"
done

for n in pcie-real-env-generator ethernet-real-env-generator mipi-csi2-real-env-generator mipi-dsi-real-env-generator emmc-real-env-generator sd-sdio-real-env-generator amba4-real-env-generator; do
  mv ".claude/skills/REAL_ENV_GENERATION/$n" ".claude/skills/_deprecated/REAL_ENV_GENERATION/$n"
done
```

- [ ] **Step 3: Add a one-line README marking the archive's purpose**

Create `.claude/skills/_deprecated/README.md`:

```markdown
# Deprecated Skills

Directories under here are self-flagged duplicates of an actually-wired
`PROTOCOL_BUILDERS/*-environment-builder` skill, archived (not deleted —
this repo has no git history to recover a deletion) on 2026-08-31 per
`docs/superpowers/specs/2026-08-31-protocol-generalization-gap-closing-design.md`
Task 1. Verified at archive time to have zero live references from
`.dv-harness/builder/protocol_builder_registry.json`, any other
`SKILL.md`, or `.claude/agents/*.md`. Do not route to anything in this
tree.
```

- [ ] **Step 4: Verify no dangling references and run self-audit**

```bash
cd "D:/DV/Task/DV_Agent_Harness_L5/v50"
grep -rln "pcie-production-builder\|ethernet-production-builder\|mipi-csi2-production-builder\|mipi-dsi-production-builder\|emmc-production-builder\|sd-sdio-production-builder\|amba4-multi-master-multi-slave-builder\|pcie-complete-env-generator\|ethernet-complete-env-generator\|mipi-csi2-complete-env-generator\|mipi-dsi-complete-env-generator\|emmc-complete-env-generator\|sd-sdio-complete-env-generator\|amba4-mmxms-complete-env-generator\|pcie-real-env-generator\|ethernet-real-env-generator\|mipi-csi2-real-env-generator\|mipi-dsi-real-env-generator\|emmc-real-env-generator\|sd-sdio-real-env-generator\|amba4-real-env-generator" .claude .dv-harness 2>/dev/null | grep -v "_deprecated/"
```

Expected: no output (empty).

```bash
python -m dv_harness.cli self-audit
```

Expected: exit code and failure count unchanged from a baseline run captured before Step 2 (run `python -m dv_harness.cli self-audit > /tmp/self_audit_before.txt` before Step 2 to have that baseline).

- [ ] **Step 5: Commit**

This repo has no git — skip commit. Note completion in the plan tracker instead.

---

## Task 2: Resolve `generator.py` vs. `ProtocolEnvGenerator` wiring contradiction

**Files:**
- Modify: `dv_harness/uvm_generator/generator.py:1-6`
- Modify: `dv_harness/uvm_generator/protocol_env_generator.py:1-22`
- Test: `dv_harness_tests/test_generator_wiring_notices.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new — this task only corrects documentation-as-code (module-header NOTICEs), no behavior change to either module's actual functions.

- [ ] **Step 1: Write the failing consistency test**

```python
# dv_harness_tests/test_generator_wiring_notices.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_generator_py_header_does_not_claim_fully_orphaned():
    text = (ROOT / "dv_harness" / "uvm_generator" / "generator.py").read_text(encoding="utf-8")
    header = text[:800]
    assert "NOT invoked by any executing code path" not in header
    assert "deprecated" in header.lower()
    assert "ProtocolEnvGenerator" in header


def test_protocol_env_generator_py_does_not_call_generator_py_orphaned():
    text = (ROOT / "dv_harness" / "uvm_generator" / "protocol_env_generator.py").read_text(encoding="utf-8")
    header = text[:1200]
    assert "orphaned/unwired" not in header
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest dv_harness_tests/test_generator_wiring_notices.py -v`
Expected: both tests FAIL — `generator.py`'s header still says "NOT invoked by any executing code path" and `protocol_env_generator.py`'s header still says "orphaned/unwired".

- [ ] **Step 3: Fix `generator.py`'s header**

Replace lines 1-6 (the module's leading NOTICE comment) with:

```python
# NOTICE (corrected 2026-08-31, protocol-generalization-gap-closing Task 2):
# the flat top-level generate() orchestration in this module is deprecated
# -- ProtocolEnvGenerator (protocol_env_generator.py) is the one official
# generation entry point, reachable via
# tools/generate_protocol_uvm_environment.py. This module's per-class emit
# methods (config/vseq/base_vseq/scoreboard/coverage/env/base_test/
# smoke_test/tb_top/sv_id) remain live and authoritative for their DSL
# schemas -- ProtocolEnvGenerator composes and reuses them unchanged, only
# relocating their output into USB_UVM_Handoff's real subdirectory layout
# instead of this module's own flat-file layout. Do not call this module's
# top-level generate() directly; do not describe this module as orphaned.
```

- [ ] **Step 4: Fix `protocol_env_generator.py`'s header**

In its module docstring (lines 1-22), change:

```
generator.py (this module's sibling, itself orphaned/unwired -- see its own
NOTICE) writes every emitted file into one flat directory.
```

to:

```
generator.py (this module's sibling; its per-class emit methods are live
and authoritative for their DSL schemas, but its own top-level flat
generate() orchestration is deprecated in favor of this module -- see its
own corrected NOTICE) writes every emitted file into one flat directory
when called directly via that deprecated path.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest dv_harness_tests/test_generator_wiring_notices.py -v`
Expected: PASS

- [ ] **Step 6: Repo-wide grep for any other contradictory claim**

```bash
cd "D:/DV/Task/DV_Agent_Harness_L5/v50"
grep -rln "orphaned" --include="*.py" --include="*.md" . 2>/dev/null | grep -v "_deprecated/\|CHANGELOG"
```

Read every file this returns that mentions `generator.py` near the word "orphaned" and confirm it now agrees with Step 3/4's corrected story (deprecated flat-orchestration, live emit methods, `ProtocolEnvGenerator` is the entry point). `.claude/agents/IP_UVM_DV_Gen.md` was checked during plan authoring and only cites `generator.py` as DSL-schema-authoritative (not as "the entry point to invoke directly"), which does not contradict this — no edit needed there unless this fresh grep finds new contradicting text.

- [ ] **Step 7: Commit**

No git in this repo — skip.

---

## Task 3: Generalize hardcoded USB evidence literals in gate logic

**Files:**
- Modify: `tools/verification_flow/input_source_contract_gate.py:5`
- Modify: `tools/verification_flow/master_requirement_completeness_gate.py:4`
- Test: `dv_harness_tests/test_input_source_contract_gate.py`
- Test: `dv_harness_tests/test_master_requirement_completeness_gate.py`

**Interfaces:**
- Produces: the evidence-class key `PRIMARY_PROTOCOL_REFERENCE` (replaces `USB_REFERENCE`) and the requirement-id key `PROTOCOL_STANDARD_REFERENCE` (replaces `USB_STANDARD_REFERENCE`) — any future skill/agent supplying evidence to the DISCOVERY or REQUIREMENT_CLOSURE gates must use these new names.

- [ ] **Step 1: Write the failing tests**

```python
# dv_harness_tests/test_input_source_contract_gate.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "verification_flow" / "input_source_contract_gate.py"


def run_gate(payload, tmp_path):
    p = tmp_path / "contract.json"
    p.write_text(json.dumps(payload))
    return subprocess.run(
        [sys.executable, str(GATE), "--contract", str(p)],
        capture_output=True, text=True,
    )


def test_pcie_evidence_with_new_key_passes(tmp_path):
    payload = {
        "provided_source_classes": [
            "SPEC", "COMMAND_TXT", "PRIMARY_PROTOCOL_REFERENCE", "RTL_SOURCE", "DE_LOCAL_SIM",
        ],
        "protocol_input_kind": "PUBLIC_STANDARD_SPEC",
        "forbidden_user_prerequisites": [],
    }
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert out["status"] == "PASS"


def test_missing_new_key_still_fails_as_missing_evidence(tmp_path):
    payload = {
        "provided_source_classes": ["SPEC", "COMMAND_TXT", "RTL_SOURCE", "DE_LOCAL_SIM"],
        "protocol_input_kind": "PUBLIC_STANDARD_SPEC",
        "forbidden_user_prerequisites": [],
    }
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert out["status"] == "FAIL"
    assert "PRIMARY_PROTOCOL_REFERENCE" in out["missing"]


def test_old_usb_reference_key_no_longer_satisfies_the_requirement(tmp_path):
    payload = {
        "provided_source_classes": ["SPEC", "COMMAND_TXT", "USB_REFERENCE", "RTL_SOURCE", "DE_LOCAL_SIM"],
        "protocol_input_kind": "PUBLIC_STANDARD_SPEC",
        "forbidden_user_prerequisites": [],
    }
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert out["status"] == "FAIL"
```

```python
# dv_harness_tests/test_master_requirement_completeness_gate.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "verification_flow" / "master_requirement_completeness_gate.py"

BASE_IDS = [
    "STEP_BY_STEP_INTERACTIVE", "FIVE_CORE_INPUTS", "SPEC", "COMMAND_TXT",
    "PROTOCOL_STANDARD_REFERENCE", "REFERENCE_UVM", "RTL_FIRST_ARCH_DISCOVERY",
    "DE_LOCAL_SIM_BASELINE", "VPLAN_FIRST", "VERIFICATION_ARCHITECTURE",
    "SCOREBOARD_CHECKER_ASSERTION", "TEST_GENERATION", "NEGATIVE_TEST",
    "LOCAL_SIM", "COMMAND_SIMLOG_SEMANTIC", "FALSE_PASS_DEFENSE",
    "DUT_TB_BUG_CLASSIFICATION", "WAVEFORM_RCA", "PROTOCOL_CORNER_CASE",
    "LSF_REGRESSION", "PER_JOB_MONITOR", "REMOTE", "COVERAGE_CLOSURE",
    "SYSTEM_LEVEL", "EXPERT_FEEDBACK", "SIGNOFF", "FEATURE_CONTINUITY",
    "EVIDENCE_PROVENANCE",
]


def run_gate(payload, tmp_path):
    p = tmp_path / "matrix.json"
    p.write_text(json.dumps(payload))
    return subprocess.run(
        [sys.executable, str(GATE), "--matrix", str(p)],
        capture_output=True, text=True,
    )


def _req(rid):
    return {"requirement_id": rid, "implemented": True, "pytest_evidence": True, "hard_gate": True}


def test_all_requirements_with_new_key_passes(tmp_path):
    payload = {"requirements": [_req(r) for r in BASE_IDS]}
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert out["status"] == "PASS"


def test_missing_new_key_reported(tmp_path):
    ids_without_reference = [r for r in BASE_IDS if r != "PROTOCOL_STANDARD_REFERENCE"]
    payload = {"requirements": [_req(r) for r in ids_without_reference]}
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert out["status"] == "FAIL"
    assert "PROTOCOL_STANDARD_REFERENCE" in out["missing"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_input_source_contract_gate.py dv_harness_tests/test_master_requirement_completeness_gate.py -v`
Expected: FAIL — the gate scripts still require the literal `USB_REFERENCE`/`USB_STANDARD_REFERENCE` keys.

- [ ] **Step 3: Rename the literal in `input_source_contract_gate.py`**

Line 5, change:
```python
required={"SPEC","COMMAND_TXT","USB_REFERENCE","RTL_SOURCE","DE_LOCAL_SIM"}
```
to:
```python
required={"SPEC","COMMAND_TXT","PRIMARY_PROTOCOL_REFERENCE","RTL_SOURCE","DE_LOCAL_SIM"}
```

- [ ] **Step 4: Rename the literal in `master_requirement_completeness_gate.py`**

Line 4, change:
```python
"STEP_BY_STEP_INTERACTIVE","FIVE_CORE_INPUTS","SPEC","COMMAND_TXT","USB_STANDARD_REFERENCE",
```
to:
```python
"STEP_BY_STEP_INTERACTIVE","FIVE_CORE_INPUTS","SPEC","COMMAND_TXT","PROTOCOL_STANDARD_REFERENCE",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_input_source_contract_gate.py dv_harness_tests/test_master_requirement_completeness_gate.py -v`
Expected: PASS

- [ ] **Step 6: Repo-wide grep for any other consumer of the old key names**

```bash
cd "D:/DV/Task/DV_Agent_Harness_L5/v50"
grep -rln "USB_REFERENCE\|USB_STANDARD_REFERENCE" --include="*.py" --include="*.md" --include="*.json" . 2>/dev/null
```

If this finds a skill/agent file that supplies evidence using the old key name (not just this plan/spec's own prose describing the change), update it to the new key name too — a gate rename with no consumer update just moves the `MISSING_EVIDENCE` failure, it doesn't fix it.

- [ ] **Step 7: Commit**

No git in this repo — skip.

---

## Task 4: Add missing protocol-router routes

**Files:**
- Modify: `.claude/skills/CORE/protocol-router/SKILL.md:8-16`

**Interfaces:**
- Consumes: `.dv-harness/builder/protocol_builder_registry.json`'s `protocols` keys (`emmc`, `sd`) as the source of truth for what must be routable.

- [ ] **Step 1: Add the two missing routes**

In the "Primary routes:" list (lines 10-16), after the `CAN-FD -> \`CAN/canfd-profile\`` line, add:

```
eMMC/MMC -> `eMMC/emmc-profile`
SD/SDIO -> `SD/sdio-profile`
```

(Matches the existing `CATEGORY/protocol-profile` naming convention used by every other entry in this list.)

- [ ] **Step 2: Add normalization aliases**

In the "Normalize:" block (lines 23-30), add two lines following the existing style:

```
MMC -> eMMC/MMC
SDIO -> SD/SDIO
```

- [ ] **Step 3: Verify router/registry key symmetry**

```bash
cd "D:/DV/Task/DV_Agent_Harness_L5/v50"
python3 -c "
import json, re
reg = json.load(open('.dv-harness/builder/protocol_builder_registry.json'))
router = open('.claude/skills/CORE/protocol-router/SKILL.md', encoding='utf-8').read()
missing = [k for k in reg['protocols'] if reg['protocols'][k]['display_name'].split('/')[0].split(' ')[0] not in router and reg['protocols'][k]['display_name'] not in router]
print('possibly unrouted (manual check needed, display-name heuristic only):', missing)
"
```

This heuristic check is approximate (display names don't always literally substring-match the router's prose) — the real check is a human/reviewer read of the router's route list against the registry's `protocols` keys: `pcie`, `ethernet`, `mipi-csi`, `mipi-dsi`, `canfd`, `amba4-soc`, `emmc`, `sd`, `edp`, `ucie`, `usb` (edp/ucie were not in the audit's 8 protocols and are already absent from the router before this task — leave them as a separate, pre-existing, out-of-scope gap, do not add them in this task).

- [ ] **Step 4: Commit**

No git in this repo — skip.

---

## Task 5: Cross-link dedicated generators into builder skills

**Files:**
- Modify: `.claude/skills/PROTOCOL_BUILDERS/pcie-environment-builder/SKILL.md:20-34`
- Modify: `.claude/skills/PROTOCOL_BUILDERS/emmc-environment-builder/SKILL.md:20-35`
- Modify: `.claude/skills/PROTOCOL_BUILDERS/canfd-environment-builder/SKILL.md:20-34`

**Interfaces:** none — prose-only additions to existing "Generate / Integrate" sections.

- [ ] **Step 1: Add the LTSSM generator reference to `pcie-environment-builder/SKILL.md`**

Immediately after the existing paragraph ending "...Read each module's own docstring "WHAT THIS DOES NOT DO" section before assuming more than this." (line 34) and before the `- VIP topology` bullet list, insert:

```markdown

For LTSSM/link-training content specifically, use
`dv_harness/uvm_generator/pcie_ltssm_generator.py` (a real LTSSM
transition model, CLI: `tools/generate_pcie_ltssm_environment.py`) instead
of hand-authoring link-training state logic — it already implements the
transition model this section's "LTSSM/link training" bullet asks for.
```

- [ ] **Step 2: Add the CMDQ generator reference to `emmc-environment-builder/SKILL.md`**

Same insertion point (after the shared paragraph, before its `- command/data sequences` bullet list):

```markdown

For CMDQ/tuning content specifically, use
`dv_harness/uvm_generator/emmc_cmdq_generator.py` instead of
hand-authoring CMDQ queue-management or tuning-sequence logic — it already
implements the mechanics this section's "CMDQ where applicable" and
"tuning" bullets ask for.
```

- [ ] **Step 3: Add the arbitration generator reference to `canfd-environment-builder/SKILL.md`**

Same insertion point (after the shared paragraph, before its `- multi-node topology` bullet list):

```markdown

For arbitration/BRS/ESI/error-state content specifically, use
`dv_harness/uvm_generator/canfd_arbitration_generator.py` instead of
hand-authoring arbitration or error-state logic — it already implements
the mechanics this section's "arbitration", "BRS/ESI", and "error frames"
bullets ask for.
```

- [ ] **Step 4: Verify each file names its module by exact path**

```bash
cd "D:/DV/Task/DV_Agent_Harness_L5/v50"
grep -l "pcie_ltssm_generator.py" .claude/skills/PROTOCOL_BUILDERS/pcie-environment-builder/SKILL.md
grep -l "emmc_cmdq_generator.py" .claude/skills/PROTOCOL_BUILDERS/emmc-environment-builder/SKILL.md
grep -l "canfd_arbitration_generator.py" .claude/skills/PROTOCOL_BUILDERS/canfd-environment-builder/SKILL.md
```

Expected: each command prints its target file's path (match found).

- [ ] **Step 5: Commit**

No git in this repo — skip.

---

## Task 6: Add missing intake evidence fields for AMBA and SD/SDIO

**Files:**
- Modify: `tools/vplan/intake_readiness.py`
- Test: `dv_harness_tests/test_intake_readiness.py`

**Interfaces:**
- Consumes: `d.get("protocols")` (already read by the existing `SUBSYSTEM` branch) to detect whether the current intake targets AMBA or SD/SDIO.
- Produces: two new possible `missing` entries — `fabric_topology_evidence` (AMBA) and `uhs_tuning_evidence` (SD/SDIO) — additive, never triggered for other protocols.

- [ ] **Step 1: Write the failing tests**

```python
# dv_harness_tests/test_intake_readiness.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "vplan" / "intake_readiness.py"


def run_gate(payload, tmp_path):
    p = tmp_path / "intake.json"
    p.write_text(json.dumps(payload))
    return subprocess.run(
        [sys.executable, str(GATE), "--intake", str(p)],
        capture_output=True, text=True,
    )


def _base_subsystem(protocols):
    return {
        "mode": "SUBSYSTEM",
        "target_name": "amba_soc",
        "protocols": protocols,
        "required_artifacts": {
            "protocol_spec": True,
            "dut_design_spec": True,
            "clock_reset_spec": True,
        },
    }


def test_amba_intake_missing_fabric_topology_is_flagged(tmp_path):
    payload = _base_subsystem(["amba4-soc"])
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "fabric_topology_evidence" in out["missing"]


def test_amba_intake_with_fabric_topology_not_flagged(tmp_path):
    payload = _base_subsystem(["amba4-soc"])
    payload["required_artifacts"]["fabric_topology_spec"] = True
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "fabric_topology_evidence" not in out["missing"]


def test_sd_intake_missing_uhs_tuning_is_flagged(tmp_path):
    payload = _base_subsystem(["sd"])
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "uhs_tuning_evidence" in out["missing"]


def test_pcie_intake_unaffected_by_new_fields(tmp_path):
    payload = _base_subsystem(["pcie"])
    result = run_gate(payload, tmp_path)
    out = json.loads(result.stdout)
    assert "fabric_topology_evidence" not in out["missing"]
    assert "uhs_tuning_evidence" not in out["missing"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_intake_readiness.py -v`
Expected: `test_amba_intake_missing_fabric_topology_is_flagged` and
`test_sd_intake_missing_uhs_tuning_is_flagged` FAIL (the new fields don't
exist yet); the other two PASS trivially (nothing to flag yet either way)
— that's fine, they're guard-rail tests for the fields you're about to
add, confirming the change doesn't affect unrelated protocols once it
lands.

- [ ] **Step 3: Add the two protocol-specific checks**

In the `SUBSYSTEM` branch (after the existing `interface_or_clock_reset_evidence` check, still inside the `if mode=="SUBSYSTEM":` block), add:

```python
    protocols_lower = {str(p).lower() for p in (d.get("protocols") or [])}
    if protocols_lower & {"amba", "amba4-soc", "axi", "ahb", "apb"}:
        if empty("fabric_topology_spec"):
            missing.append("fabric_topology_evidence")
    if protocols_lower & {"sd", "sdio", "sd-sdio"}:
        if empty("uhs_tuning_spec"):
            missing.append("uhs_tuning_evidence")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_intake_readiness.py -v`
Expected: PASS (all four)

- [ ] **Step 5: Commit**

No git in this repo — skip.

---

## Task 7: Consolidation sync (runs after Tasks 1-6)

**Files:**
- Read: everything changed by Tasks 1-6
- Copy: `.claude/` (skills + workflows) to `../industrial/.claude/` and `../PACKAGE/.claude/` if those trees exist as siblings of `v50/` (confirm their actual location first — do not assume a path)

**Interfaces:** none — pure sync step.

- [ ] **Step 1: Locate the deliverable trees**

```bash
cd "D:/DV/Task/DV_Agent_Harness_L5"
find . -maxdepth 1 -iname "industrial" -o -maxdepth 1 -iname "PACKAGE"
```

- [ ] **Step 2: Confirm each found tree has its own `.claude/` directory already (i.e. it's a real prior sync target, not something to newly create)**

```bash
ls -d industrial/.claude 2>/dev/null
ls -d PACKAGE/.claude 2>/dev/null
```

- [ ] **Step 3: Sync the changed subtrees only**

For each tree found in Step 2, copy only what Tasks 1-6 actually touched (not a blind full-tree overwrite, to avoid clobbering deliverable-tree-specific state):

```bash
# repeat for each target tree found (industrial, PACKAGE)
TARGET=PACKAGE   # or industrial
rsync -a --delete "v50/.claude/skills/_deprecated/" "$TARGET/.claude/skills/_deprecated/"
for f in UNIVERSAL_PROTOCOL REAL_PROJECT_GENERATION REAL_ENV_GENERATION; do
  rsync -a --delete "v50/.claude/skills/$f/" "$TARGET/.claude/skills/$f/"
done
cp "v50/.claude/skills/CORE/protocol-router/SKILL.md" "$TARGET/.claude/skills/CORE/protocol-router/SKILL.md"
cp "v50/.claude/skills/PROTOCOL_BUILDERS/pcie-environment-builder/SKILL.md" "$TARGET/.claude/skills/PROTOCOL_BUILDERS/pcie-environment-builder/SKILL.md"
cp "v50/.claude/skills/PROTOCOL_BUILDERS/emmc-environment-builder/SKILL.md" "$TARGET/.claude/skills/PROTOCOL_BUILDERS/emmc-environment-builder/SKILL.md"
cp "v50/.claude/skills/PROTOCOL_BUILDERS/canfd-environment-builder/SKILL.md" "$TARGET/.claude/skills/PROTOCOL_BUILDERS/canfd-environment-builder/SKILL.md"
```

If `$TARGET` doesn't have a matching `dv_harness/`/`tools/` layout mirroring `v50`'s (confirm with `ls "$TARGET/dv_harness/uvm_generator/generator.py"` etc. before copying), skip the `dv_harness`/`tools` file copies for that target and report the mismatch instead of forcing a copy into a differently-shaped tree.

- [ ] **Step 4: Run self-audit once more against `v50` (the primary tree) as final confirmation**

```bash
cd "D:/DV/Task/DV_Agent_Harness_L5/v50"
python -m dv_harness.cli self-audit
```

Expected: no new failures versus the Task 1 Step 4 baseline.

- [ ] **Step 5: Commit**

No git in this repo — skip; report the sync as complete in the plan tracker.
