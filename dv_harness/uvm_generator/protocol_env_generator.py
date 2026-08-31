"""dv_harness/uvm_generator/protocol_env_generator.py -- real subdirectory-shaped
protocol UVM environment generator, superseding generator.py's flat-file
layout.

BUG FIX (2026-08-29, 9-policy audit / USB regen-fidelity plan Phase 1 item 4):
generator.py (this module's sibling; its per-class emit methods are live
and authoritative for their DSL schemas, but its own top-level flat
generate() orchestration is deprecated in favor of this module -- see its
own corrected NOTICE) writes every emitted file into one flat directory
when called directly via that deprecated path. The catalogued
USB_UVM_Handoff package's real tree is not flat: tb/agents, tb/env, tb/seq,
tb/tests, tb/top, tb/patterns/common, filelist/ are real, separate
subdirectories. This module reuses generator.py's per-class emit functions
UNCHANGED (config/vseq/base_vseq/scoreboard/coverage/env/base_test/
smoke_test/tb_top/sv_id) -- the SV/text content is not the gap, only where it
lands on disk is -- and relocates each emitted file into the matching real
subdirectory.

WHAT THIS DOES NOT DO: emit tb/agents content (no per-class agent emitter
exists yet in generator.py; the directory is created empty, matching the
real tree's shape but not yet its content -- a future agent-emitter is a
separate, larger piece of work, not scoped into this pass), or produce the
vPlan .xlsx / static-check-script layer (explicitly out of scope; see the
usb-regen-fidelity-plan synthesis digest).
"""
from __future__ import annotations

import json
from pathlib import Path

from .generator import UVMEnvironmentGenerator, sv_id
from ..qualification import QualificationTier

LAYOUT = {
    "pkg": "tb/env",
    "config": "tb/env",
    "virtual_sequencer": "tb/seq",
    "base_vseq": "tb/seq",
    "scoreboard": "tb/env",
    "coverage": "tb/env",
    "env": "tb/env",
    "base_test": "tb/tests",
    "smoke_test": "tb/tests",
    "tb_top": "tb/top",
}
EXTRA_DIRS = ["tb/agents", "tb/patterns/common"]
FILELIST_DIR = "filelist"
FILELIST_NAME = "dv_uvm_files.f"


class ProtocolEnvGenerator:
    """Composition, not inheritance: only UVMEnvironmentGenerator's per-file
    emit methods are reused (via self.emitter); its own flat-directory
    generate() orchestration is never called."""

    def __init__(self, out_dir):
        self.emitter = UVMEnvironmentGenerator(out_dir)
        self.out = self.emitter.out

    def generate(self, m: dict):
        p = sv_id(m["protocol"])
        pkg_name = p + "_env_pkg"
        smoke = m.get("smoke_tests") or [{"name": "smoke"}]
        e = self.emitter

        placed = {}
        placed[f"{LAYOUT['pkg']}/{pkg_name}.sv"] = e.pkg(m, p, pkg_name, smoke)
        placed[f"{LAYOUT['config']}/{p}_config.sv"] = e.config(m, p)
        placed[f"{LAYOUT['virtual_sequencer']}/{p}_virtual_sequencer.sv"] = e.vseq(m, p)
        placed[f"{LAYOUT['base_vseq']}/{p}_base_vseq.sv"] = e.base_vseq(m, p)
        placed[f"{LAYOUT['scoreboard']}/{p}_scoreboard.sv"] = e.scoreboard(m, p)
        placed[f"{LAYOUT['coverage']}/{p}_coverage.sv"] = e.coverage(m, p)
        placed[f"{LAYOUT['env']}/{p}_env.sv"] = e.env(m, p)
        placed[f"{LAYOUT['base_test']}/{p}_base_test.sv"] = e.base_test(m, p)
        for t in smoke:
            n = sv_id(t.get("name", "smoke"))
            placed[f"{LAYOUT['smoke_test']}/{p}_{n}_test.sv"] = e.smoke_test(m, p, n)
        placed[f"{LAYOUT['tb_top']}/tb_top.sv"] = e.tb_top(m, p, pkg_name)

        for extra in EXTRA_DIRS:
            (self.out / extra).mkdir(parents=True, exist_ok=True)

        filelist_rel = f"{FILELIST_DIR}/{FILELIST_NAME}"
        placed[filelist_rel] = "\n".join(sorted(placed.keys())) + "\n"

        manifest = dict(m)
        manifest["generated_files"] = sorted(placed.keys()) + ["environment_manifest.json"]
        manifest["qualification_status"] = QualificationTier.ENV_GENERATED.value

        for rel, content in placed.items():
            dest = self.out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        (self.out / "environment_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")

        return sorted(placed.keys()) + ["environment_manifest.json"]
