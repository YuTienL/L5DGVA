#!/usr/bin/env python3
# GAP-V2-002 remediation (CAP-M6-GAPV2002-001, DEC-GAP-V2-002 = OPTION_B):
# reclassified INTERNAL_GENERATION_PRIMITIVE. This script is no longer an
# independent, qualified CREATE ENVIRONMENT workflow entry point -- it is
# unmodified generation capability, still fully real and still directly
# runnable, but now reachable through TWO paths instead of one:
#
#   (governed, canonical) dv-harness start --generate
#     -> engine.DVHarness.start_lifecycle() resolves protocol/role through
#        real Field Resolution/Clarification/HumanGate, then calls
#        dv_harness.uvm_generator.create_environment.create_environment()
#        directly (the SAME function this script calls below) --
#        see dv_harness/generation_field_controls.py.
#   (internal primitive, this script) direct invocation, no lifecycle/
#     Field-Resolution/Clarification/HumanGate involvement at all -- kept
#     for the 2 real subprocess-level regression tests that exercise the
#     primitive directly (dv_harness_tests/test_protocol_env_generator.py,
#     test_system_level_soc_composition_wiring.py) and for any low-level/
#     CI/offline use that genuinely needs a lifecycle-free call, the same
#     way run_stage()/.loop() remain reachable internal primitives beneath
#     start_lifecycle() per CAP-M6-DISPATCH-001's own policy.
#
# All 11 .claude/skills/PROTOCOL_BUILDERS/*/SKILL.md now converge on the
# governed path above (GAP_V2_002_GENERATOR_ENTRY_DECISION.md /
# GAP_V2_002_FIELD_CONTROL_DERIVATION.md /
# GAP_V2_002_IMPLEMENTATION_REPORT.md, under
# .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/), never this script
# directly. Its own generation logic (below) is completely unmodified --
# only its role in the architecture, and who is expected to call it, has
# changed.
#
# Mirrors tools/generate_uvm_environment.py's / generate_amba_fabric_environment.py's
# exact shape -- a standalone script, not a dv-harness CLI subcommand.
#
# 2026-09-04 (AI-mechanism re-audit gap #14): this script used to call
# ProtocolEnvGenerator directly -- so CLAUDE.md's "Before CREATE
# ENVIRONMENT, select: SUBSYSTEM_MODE / SYSTEM_LEVEL_MODE" gate had no
# effect here at all, and a genuine multi-subsystem request silently
# produced one subsystem environment. It now goes through
# dv_harness.uvm_generator.create_environment.create_environment(), which
# resolves the mode with the real environment_mode_router and dispatches to
# ProtocolEnvGenerator or to the real SoC composer accordingly. A
# single-protocol manifest (what every builder skill passes) still resolves
# SUBSYSTEM_MODE and reaches the same ProtocolEnvGenerator call as before.
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
#
# 2026-09-04 (AI-mechanism re-audit gap #13): SUBSYSTEM_MODE now also layers
# the protocol's OWN model (PCIe LTSSM, MIPI D-PHY, CAN-FD arbitration, AMBA
# fabric, eMMC/SD command queue) onto that skeleton when the manifest supplies
# `protocol_model_topology` -- previously those five real generators were
# reachable only from their own standalone tools, so this entry point produced
# the identical protocol-agnostic skeleton for every protocol. The
# `protocol_model` block below reports which of "layered" / "no model for this
# protocol" / "no topology supplied" happened, so a skeleton is never mistaken
# for a modelled environment.
from dv_harness.uvm_generator.create_environment import (
    create_environment, EnvironmentModeUnresolvedError, StructuralLintFailedError,
    SubsystemModeRequiredError,
)
from dv_harness.uvm_generator.protocol_model_layer import ProtocolModelLayerError

ap = argparse.ArgumentParser()
ap.add_argument('--manifest', required=True)
ap.add_argument('--out', required=True)
# The project root the REAL subsystem registry
# (.dv-harness/soc-composer/subsystem_environment_registry.json) is read
# from. Defaults to the current working directory, which is the project root
# for every documented invocation; never defaults to this repo's own ROOT,
# which would read a DIFFERENT project's registrations when the harness is
# deployed alongside a project tree.
ap.add_argument('--root', default='.')
a = ap.parse_args()
m = json.loads(pathlib.Path(a.manifest).read_text(encoding="utf-8"))
try:
    result = create_environment(pathlib.Path(a.root), m, out_dir=pathlib.Path(a.out))
except SubsystemModeRequiredError as exc:
    # CLAUDE.md "Environment Generation Mode": build the missing subsystem
    # through SUBSYSTEM_MODE first, then return to composition. Named as a
    # real refusal with the missing names, never a partial generation
    # reported as if it were the requested one.
    print(json.dumps({"status": "SUBSYSTEM_MODE_REQUIRED_FIRST", "detail": exc.detail}))
    sys.exit(2)
except EnvironmentModeUnresolvedError as exc:
    print(json.dumps({"status": "ENVIRONMENT_MODE_UNRESOLVED", "reason": exc.reason,
                      "detail": exc.detail}))
    sys.exit(3)
except StructuralLintFailedError as exc:
    # Only reachable when the manifest itself set "strict_structural_lint":
    # true. The environment WAS written (the lint runs on the generated files,
    # so it cannot run before them); this exit code says the generated UVM has
    # ERROR-severity structural defects that must be fixed before a compile is
    # worth spending -- section 220's "structural lint runs before expensive
    # simulation". Without that opt-in the report is recorded and generation
    # succeeds, exactly as before this check existed.
    print(json.dumps({"status": exc.reason, "detail": exc.detail}))
    sys.exit(5)
except ProtocolModelLayerError as exc:
    # The manifest asked for a protocol model and that model's own validator
    # refused the topology. A refusal, not a partial environment reported as
    # the requested one -- same posture as SUBSYSTEM_MODE_REQUIRED_FIRST above.
    print(json.dumps({"status": exc.reason, "detail": exc.detail}))
    sys.exit(4)
out = {"status": "OK", "environment_mode": result["environment_mode"],
       "generated_files": result["generated_files"], "out": result["out_dir"],
       "environment_mode_decision": result["decision"]}
if "protocol_model" in result:
    out["protocol_model"] = result["protocol_model"]
    out["protocol_model_files"] = result["protocol_model_files"]
# The deterministic pre-simulation structural lint of the UVM just generated
# (dv_harness/uvm_structural_lint.py), also written to
# <out>/uvm_structural_lint.json. Reported always, including when verible is
# unavailable (status NOT_AVAILABLE with a real reason) -- a caller must be
# able to tell "checked and clean" from "could not be checked".
out["structural_lint"] = result["structural_lint"]
print(json.dumps(out))
