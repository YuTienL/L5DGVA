"""Persists the 2026-09-03 Obsidian+Git/Markdown Hybrid Engineering Memory
integration's lessons into Engineering Memory, via
memory_router.route_and_store() (auto-loads cfg, pushes to the shared
Knowledge Center automatically).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dv_harness.memory_router import route_and_store

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

RECORD = {
    "kind": "debug_lesson",
    "verified": True,
    "title": "Obsidian+Git/Markdown Hybrid Engineering Memory integration (5-workstream build, 2026-09-03): honest PARTIAL-by-design beats false READY -- real Obsidian CLI capability turned out to be genuinely rich mid-build, but the fallback-first architecture meant that discovery changed nothing structurally",
    "scope": "engine",
    "symptoms": [
        "User specified an extremely detailed 25-phase spec for a hybrid Obsidian+Git/Markdown Engineering Memory layer, explicitly requiring production-ready (not demo) delivery and explicit honesty about PARTIAL vs READY status",
        "Mid-build, the controller separately discovered the OFFICIAL Obsidian CLI is far more capable than initially assumed (full CRUD, search with json/tsv/csv output, YAML property read/write, wiki-link graph traversal, backlinks) -- but it requires the Obsidian desktop GUI app to be running (not just installed), directly conflicting with this project's own 'no required GUI dependency' architecture principle",
    ],
    "root_cause": "N/A -- this is a summary/consolidation record, not a bug record.",
    "fix": (
        "Built dv_harness/memory_vault.py's MemoryProvider abstraction (ObsidianAdapter + FileSystemMarkdownAdapter + "
        "HybridMemoryProvider) BEFORE the mid-build Obsidian-CLI-richness discovery, with the FileSystemMarkdownAdapter "
        "as the real, fully-functional, always-available implementation and ObsidianAdapter as an honest NOT_AVAILABLE "
        "stub. This turned out to be the right call independent of the later discovery: even though the real Obsidian "
        "CLI (once installed and running) has a genuinely rich, well-designed command surface that maps almost 1:1 onto "
        "the MemoryProvider interface, it fundamentally requires the GUI app to be actively running -- which this "
        "project's own architecture explicitly forbids as a hard dependency. The correct integration point is exactly "
        "where the abstraction already put it: ObsidianAdapter's operational methods stay unwired until a real installed "
        "instance is available to observe and design against for real, per the existing 'never guess a command contract' "
        "discipline -- the abstraction did not need to change shape once the richer reality was discovered, only its "
        "future extension point was clarified."
    ),
    "verification": {
        "single_sim": "N/A (Engineering Memory infrastructure, not a simulation fix)",
        "regression": (
            "Full repository suite: 2024 passed, 0 failed (16m27s), independently re-run by a review agent (not trusted "
            "from any workstream's own report). 14/14 Phase-22-required test cases confirmed. Real memory_doctor CLI "
            "invocation, real secret-redaction test against 5 real-shaped secrets, real git-log check confirming "
            "dv_harness/memory.py itself was never touched (pure additive extension)."
        ),
        "reaudit": "Independent review agent APPROVED with zero fabricated claims, zero hidden test failures, zero secret leakage, zero undisclosed backward-compatibility breaks found.",
    },
    "confidence": "CONFIRMED",
    "note": (
        "GENERALIZABLE LESSON: when building an integration against an optional external dependency whose real "
        "capability is unknown or assumed absent, design the abstraction boundary (MemoryProvider here) around the "
        "PERMANENT worst case (dependency absent) rather than trying to anticipate the dependency's eventual real "
        "shape -- this makes a later capability discovery (Obsidian CLI turning out to be much richer than assumed, "
        "found mid-build via the separate `obsidian help` real command-surface investigation) a non-event architecturally, "
        "rather than something requiring a redesign. The project's own standing rule ('never guess a command contract; "
        "wire against a real installed instance only') is what made this genuinely safe: an unwired-but-well-designed "
        "extension point costs nothing to leave unfinished, whereas a guessed-at implementation would have needed "
        "rework or worse, silently wrong behavior, once the real command surface was observed. SECOND LESSON: 'honest "
        "PARTIAL over false READY' as an explicit design/reporting requirement (stated by the user up front) produced a "
        "genuinely more useful final report than chasing full READY would have -- the report's own Remaining Gaps "
        "section (Obsidian unwired, existing 16+ records never backfilled into the vault, a heuristic mismatch in the "
        "large-files doctor check) is exactly the kind of concrete, actionable punch list that lets follow-up work start "
        "immediately, rather than a vague 'mostly done' status that would have hidden the same gaps."
    ),
    "provenance": (
        "dv-agent-harness-l5 session, 2026-09-03, Obsidian+Git/Markdown Hybrid Engineering Memory integration "
        "(5-workstream multi-agent build + independent review). Commits ceab932 (core), 385b395 (CLI/secrets/dedup), "
        "f39238f (debug-flow/git/session), 17ebcaf (docs/skills/CLAUDE.md), 05c6b6a (final tests + E2E demo)."
    ),
}


def main() -> int:
    result = route_and_store(ROOT, RECORD)
    print(f"[{RECORD['title'][:60]}...] -> {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
