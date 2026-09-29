"""Persists the 2026-09-03 "Production-Grade Execution Governance"
6-workstream effort's real lessons into Engineering Memory, via
memory_router.route_and_store() (auto-loads cfg, pushes to the shared
Knowledge Center automatically).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dv_harness.memory_router import route_and_store

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

RECORDS = [
    {
        "kind": "debug_lesson",
        "verified": True,
        "title": (
            "Multi-agent workflow, shared working tree, concurrent uncommitted edits to the same file "
            "(cli.py, CLAUDE.md): whole-file `git add` silently sweeps in a sibling workstream's "
            "in-progress changes -- isolate with a hand-built patch limited to your own hunks, not "
            "`git add <file>`"
        ),
        "scope": "engine",
        "symptoms": [
            "6 parallel workstreams in one Workflow run, several editing dv_harness/cli.py concurrently "
            "(preflight+lsf-submit wiring, pueue subcommand, run-profile subcommand from an unrelated "
            "concurrent session) -- a plain `git add dv_harness/cli.py` after finishing one workstream's "
            "edit stages EVERY other workstream's uncommitted, unrelated, unfinished edits in the same file too",
            "The gh_pr_policy workstream's own report independently describes the same failure mode: its "
            "first commit attempt swept in another session's already-staged, unrelated work; caught via "
            "`git status --short` review before push, fixed with `git reset --soft HEAD~1` + a re-commit "
            "scoped by explicit pathspec",
        ],
        "root_cause": (
            "`git add <path>` stages the CURRENT on-disk content of that path, not a diff scoped to one "
            "author's intent -- when several workstreams edit the same file in a shared, uncommitted "
            "working tree, whole-file staging has no way to distinguish 'my finished hunk' from 'a "
            "sibling's in-progress hunk that happens to be sitting in the same file right now'."
        ),
        "fix": (
            "Generate the current `git diff` for the shared file, identify which @@ hunk(s) are actually "
            "yours (by content, not by line-number proximity -- line numbers shift as sibling hunks land), "
            "extract just those hunks into a standalone patch file with correct context lines, `git reset "
            "<file>` to unstage everything, then `git apply --cached --check` followed by `git apply "
            "--cached` to stage only that patch against the index (which after reset equals HEAD). Verify "
            "with `git diff --cached <file>` before committing that the staged diff is exactly your own "
            "hunk and the working tree still carries every sibling's untouched, uncommitted edit."
        ),
        "verification": {
            "single_sim": "N/A (git workflow lesson, not a simulation fix)",
            "regression": (
                "Applied twice for real in this session: once for a run_profile.json/justfile addition "
                "sharing cli.py with the governance workflow's pueue/escalation_notify hunks (`git apply "
                "--cached --check` passed, `git diff --cached` confirmed exactly 17 lines staged, "
                "commit 55d5b868), and independently re-derived by the governance workflow's own "
                "gh_pr_policy workstream for the same reason against the same shared file."
            ),
            "reaudit": "Independent review phase of the governance workflow confirmed no cross-workstream "
                       "commit ever swept in unrelated hunks -- each of the 6 workstream commits + the "
                       "concurrent run_profile.json commit stayed cleanly scoped to its own files.",
        },
        "confidence": "CONFIRMED",
        "note": (
            "GENERALIZABLE LESSON: any time this harness runs multiple concurrent agents/sessions against "
            "one shared, uncommitted working tree (multi-agent Workflow runs, or a human + Claude Code "
            "session working side by side), a shared frequently-touched file (cli.py, config.py, CLAUDE.md) "
            "is a predictable collision point. The fix is not 'avoid touching shared files' (often "
            "impossible -- a new CLI subcommand has to go in cli.py) but 'never trust whole-file staging "
            "in a shared tree; always inspect `git diff --cached` against the specific hunk you intended "
            "before committing.' Two independent instances of this exact pattern occurring in one session "
            "(gh_pr_policy workstream, and the main session's own run_profile.json commit) suggests this "
            "should be distilled into a reusable skill/checklist rather than re-derived per incident."
        ),
        "provenance": (
            "dv-agent-harness-l5 session, 2026-09-03, Production-Grade Execution Governance workflow "
            "(w79virzvx, 8 agents: preflight/just/evidence_store/gh_pr_policy/pueue_notify/vip_distill/"
            "finish/review) + concurrent main-session run_profile.json/justfile work. Commits 1459f99, "
            "c2dc146, 64bdf6e, 1875494, 4ab5f44, 36d0595, cca8820 (governance); 55d5b86, a705c56 "
            "(concurrent/follow-up)."
        ),
    },
    {
        "kind": "debug_lesson",
        "verified": True,
        "title": (
            "A workflow's own 'finish' consolidation report can misstate its session's real "
            "traceability footprint when concurrent unrelated work shares the git timeline -- an "
            "independent review phase (not the same agent grading its own work) caught it"
        ),
        "scope": "engine",
        "symptoms": [
            "The governance workflow's finish-phase report stated 'Files touched this session: only "
            "test_engine_gates_and_routing.py... No other file was modified or committed' -- literally "
            "false, since commit 55d5b868 (an unrelated 42-test run_profile.json/justfile addition from "
            "the concurrently-running main session) landed inside the same session work window, between "
            "two of the governance workflow's own commits",
        ],
        "root_cause": (
            "The finish-phase agent's own git-log inspection window was scoped to 'commits I recognize as "
            "belonging to my 6 workstreams', and it phrased its accounting claim as an absolute ('no other "
            "file'), not a scoped one ('no other file within my task's 6 workstreams') -- an easy category "
            "error when a session's git history legitimately contains other agents'/sessions' commits "
            "interleaved with your own."
        ),
        "fix": (
            "Not fixed at the source (the finish-phase agent's own commit was already made and the "
            "workflow had already completed by the time this was caught); corrected via a follow-up "
            "addendum file (.work/governance-final-report-addendum.md) and a corrective commit, rather "
            "than editing history."
        ),
        "verification": {
            "single_sim": "N/A",
            "regression": "N/A -- documentation/accounting correction, not a code change",
            "reaudit": "The review phase (a separate agent, not the finish-phase agent grading itself) is "
                       "exactly the mechanism that caught this -- confirms the value of an independent "
                       "review stage even for a report/accounting deliverable, not only for code.",
        },
        "confidence": "CONFIRMED",
        "note": (
            "GENERALIZABLE LESSON: a 'files touched this session' or 'nothing else was modified' claim in "
            "any final report is only as reliable as the reporting agent's own git-log scoping -- in a "
            "shared working tree with concurrent sessions, that claim should be phrased as 'within this "
            "task's own scope' rather than absolute, or independently cross-checked via `git log "
            "--since=<task start>` against the FULL commit list, not just the commits the agent itself "
            "made. The Methodology Consolidation Rule's 'must be able to trace what was done' bar applies "
            "to a workflow's own self-reporting, not only to the code it produced."
        ),
        "provenance": (
            "dv-agent-harness-l5 session, 2026-09-03, Production-Grade Execution Governance workflow "
            "(w79virzvx), review phase finding, corrected in commit a705c56."
        ),
    },
    {
        "kind": "debug_lesson",
        "verified": True,
        "title": (
            "lmstat+scheduler preflight gate is now real, wired in front of the harness's one bsub call "
            "site -- but 'the gate exists and blocks correctly' and 'a real job can get through it' are "
            "two separate facts, and only the first is true today"
        ),
        "scope": "engine",
        "symptoms": [
            "dv_harness/preflight.py's 6 checks (license/queue/host/disk/workdir/EDA-env-vars) were built, "
            "tested (52 new tests), and independently re-verified live against the real remote server "
            "(host-c/vchost-b): license/queue/host/disk/workdir all PASS, but eda_env_vars genuinely FAILs -- "
            "VCS_HOME/UVM_HOME/VERDI_HOME are unset on the persistent relay's shell, so real overall "
            "verdict is BLOCKED",
        ],
        "root_cause": (
            "The persistent relay's shell was never configured to `module load synopsys/vcs/...` (or "
            "equivalent EDA env setup) -- this is a real infrastructure/operations gap, not a preflight.py "
            "code defect. The gate is doing exactly its job: refusing to let bsub_submit_with_preflight() "
            "call the real bsub_submit() when the environment genuinely isn't ready."
        ),
        "fix": (
            "Not fixed this session -- explicitly named as an infra decision requiring the user's own "
            "action (wiring the real module-load step on the remote server's execution shell), correctly "
            "declined to be automated by either the implementing workstream or the finish-phase reviewer."
        ),
        "verification": {
            "single_sim": "N/A",
            "regression": (
                "Live check against the real server, not a mock: lmutil lmstat -a -c 2900@host-a -> UP "
                "(VCSRuntime/VCSCompiler 99/0 in use); bqueues vcs -> Open:Active, 12 RUN; hostname -> "
                "host-c; df -Pk on the real sim dir -> ~1.58 TiB free; workdir exists+writable; EDA env "
                "vars genuinely unset via a real tcsh $?VAR check."
            ),
            "reaudit": "Independent review phase re-ran dv_harness_tests/test_preflight_lsf_wiring.py live "
                       "(6/6 pass) and confirmed via code inspection (lsf_client.py:207-217) that "
                       "PreflightBlockedError is a structural raise, never a logged-but-ignored warning.",
        },
        "confidence": "CONFIRMED",
        "note": (
            "GENERALIZABLE LESSON: when a new gate/guard is built against a real remote environment, 'the "
            "gate's logic is correct' should be reported and tracked SEPARATELY from 'the environment the "
            "gate checks is actually ready' -- conflating the two into one PASS/READY status hides exactly "
            "the kind of real infra gap (missing module load) that the gate exists to catch in the first "
            "place. This mirrors the earlier session lesson about TRUE_PASS semantic verification: a "
            "mechanism working correctly and a target condition being met are different claims."
        ),
        "provenance": (
            "dv-agent-harness-l5 session, 2026-09-03, Production-Grade Execution Governance workflow, "
            "preflight workstream + finish/review phases. Commit 1459f99. See "
            ".work/governance-preflight-report.md."
        ),
    },
]


def main() -> int:
    for record in RECORDS:
        result = route_and_store(ROOT, record)
        print(f"[{record['title'][:70]}...] -> {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
