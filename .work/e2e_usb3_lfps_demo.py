"""Phase 23 -- narrated run of the synthetic USB3 Polling.LFPS end-to-end
Engineering Memory chain (obsidian-memory-final).

Execution Mode declaration (CLAUDE.md's Execution Mode Gate):
    LOCAL_ANALYSIS -- 「這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。」

This script is the HUMAN-READABLE view of the chain. The chain itself lives in
`dv_harness_tests/e2e_memory_chain_usb3_lfps.py` and is asserted, link by link,
by `dv_harness_tests/test_e2e_memory_chain_usb3_lfps.py` -- so a regression is
caught by the test suite rather than by someone remembering to run this file.
Keeping one driver means the narration can never describe a chain that differs
from the one under regression.

Run with:  python .work/e2e_usb3_lfps_demo.py
Demo project directory (isolated from the real project's own .dv-harness/memory
and .dv-harness/vault, so this synthetic example never pollutes real production
knowledge): .work/_e2e_demo_usb3_lfps/
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dv_harness_tests.e2e_memory_chain_usb3_lfps import default_cfg, run_memory_chain

DEMO_ROOT = REPO_ROOT / ".work" / "_e2e_demo_usb3_lfps"


def _force_remove_readonly(func, path, exc_info):
    # Windows git objects are written read-only; a plain shutil.rmtree() fails
    # on them with PermissionError. Clear the read-only bit and retry.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main() -> None:
    # Fresh demo project every run, so this script is idempotent/reproducible.
    if DEMO_ROOT.exists():
        shutil.rmtree(DEMO_ROOT, onexc=_force_remove_readonly)
    DEMO_ROOT.mkdir(parents=True)

    result = run_memory_chain(DEMO_ROOT, cfg=default_cfg(), echo=print)

    print(f"\n{'=' * 78}\nSUMMARY\n{'=' * 78}")
    print(f"Demo project root       : {DEMO_ROOT}")
    print(f"Vault path              : {result['vault_path']}")
    print(f"Job Memory note         : {result['job_vault_note_id']}")
    print(f"Engineering Memory note : {result['engineering_vault_note_id']}")
    print(f"Engineering Memory id   : {result['engineering_memory_id']}")
    print(f"Final git commit SHA    : {result['knowledge_commit_sha']}")
    print(f"Promotion outcome       : {result['promotion'].get('reason')}")
    print("Chain result            : COMPLETE (14 real steps; step 7's real-execution portion "
          f"is {result['real_execution_status']} -- no real LSF/VCS run was performed).")
    print("Regression net          : dv_harness_tests/test_e2e_memory_chain_usb3_lfps.py")

    run_log = DEMO_ROOT / "e2e_run_log.json"
    run_log.write_text(json.dumps({"execution_mode": result["execution_mode"],
                                   "chain": result["chain"]}, indent=2, default=str),
                       encoding="utf-8")
    print(f"\nFull structured run log written to: {run_log}")


if __name__ == "__main__":
    main()
