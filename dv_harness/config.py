from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG = {
    "adapter": "cli",
    "claude": {
        "command": "claude",
        "max_turns": 40,
        "permission_mode": "dangerously-skip-permissions",
        "output_format": "json",
        "allowed_tools": []
    },
    "policy": {
        "language": "zh-TW",
        "max_stage_retries": 2,
        "auto_advance_on_pass": True,
        "stop_on_blocked": True,
        "stop_on_wait_user": True,
        "require_exact_server_sha": True,
        "require_second_pass_audit": True,
        "require_all_actionable_findings_closed": True,
        "require_stage_gate_evidence": True,
        "require_dv_review_cosign": False,
        # Content-driven inner ReAct loop (2026-08-29, evidence-grounded-react
        # design pass) -- see dv_harness/react_loop.py. enable_inner_react_loop
        # is the global escape hatch (per-stage opt-out is graph.Node.react);
        # the two max_* values are safety backstops, never the intended
        # termination path (see InnerReactLoop.run()'s priority-ordered
        # termination conditions).
        "enable_inner_react_loop": True,
        "inner_react_max_iterations": 3,
        "inner_react_max_adapter_calls": 2
    },
    "dashboard": {
        "host": "127.0.0.1",
        "port": 8765
    },
    "knowledge_center": {
        # Cross-user shared knowledge center (Engineering/Organizational Memory
        # + Corner-Case Library) on a fixed Linux-server path. Deliberately
        # OFF and EMPTY by default: CLAUDE.md's SSH/Remote Transport
        # Connection Intake rule requires the user to be asked before any
        # remote path is assumed, and this harness must never guess or
        # hardcode someone else's server path -- see `dv-harness knowledge
        # setup`, which is the only code path allowed to fill `remote_root`
        # in and always does so via an interactive prompt.
        "enabled": False,
        "remote_root": "",
        "hop_script": "",
        # vchost/vchop: which persistent relay (tools/remote/remote_relay.py)
        # to route Knowledge Center traffic through -- see
        # dv_harness/knowledge_center.py's _invoke() docstring for the real
        # incident (2026-09-01) this replaced: the client used to spawn its
        # own tools/remote/remote_hop.py subprocess directly, which reads
        # VCPW from ITS OWN process environment -- exactly the credential
        # exposure pattern CLAUDE.md's "Remote Linux Execution" section
        # already forbids for remote_relay.py. Empty by default (falls back
        # to the VCHOST/VCHOP env vars already used to start the relay, same
        # convention tools/remote/remote_exec.py's own client uses) so no
        # server identity is ever guessed or hardcoded.
        "vchost": "",
        "vchop": "",
        "categories": [
            "usb", "pcie", "amba4", "ethernet", "mipi_csi2", "mipi_dsi",
            "can_fd", "emmc", "sd_sdio", "_general"
        ],
        "sync_on_promote": True,
        "max_age_days": 180,
        "configured_by": "",
        "configured_at": None
    },
    # rtl_write_scope_guard_gate's real enforcement boundary (2026-09-02,
    # RTL-write-scope-guard gap-closure pass): a project declares the real,
    # absolute DUT/VIP RTL roots it must never let the harness write into
    # here -- never guessed or hardcoded inside the gate script itself, same
    # convention as knowledge_center.remote_root above. Empty by default: a
    # project that has not populated this list gets an honest no-op PASS
    # from that gate (see its own module docstring), not a silently-false
    # sense of protection.
    "rtl_protection": {
        "protected_paths": []
    },
    # Obsidian+Git/Markdown Hybrid Engineering Memory vault (2026-09-03,
    # obsidian-memory-core foundational layer -- see dv_harness/memory_vault.py).
    # ADDITIVE to memory.py's JSON MemoryStore, never a replacement: on an
    # ENGINEERING_MEMORY/ORGANIZATIONAL_MEMORY promotion, memory_router.py's
    # route_and_store() also writes a human-browsable Markdown+YAML note here.
    # `vault_path` empty (never hardcoded, same convention as
    # knowledge_center.remote_root above) resolves to a project-relative
    # `.dv-harness/vault` default -- see memory_vault.resolve_vault_path().
    # `obsidian_cli`: "auto" probes for a real Obsidian CLI every call and
    # safely falls back to the filesystem adapter when (as on every machine
    # confirmed so far) none is found or wired; "disabled" skips probing
    # Obsidian entirely and always uses the filesystem adapter.
    # `git_enabled` defaults False (opt-in), same convention as
    # knowledge_center.enabled/self_tuning.enabled above -- confirmed via a
    # real full-suite regression run (2026-09-03) that defaulting it True
    # makes every route_and_store() call that auto-loads this config
    # silently `git init`+commit inside the vault, and on Windows a plain
    # shutil.rmtree() of a directory containing a real .git tree fails with
    # PermissionError on git's read-only object files -- broke 10
    # pre-existing tests whose tmp-dir teardown never anticipated a git repo
    # appearing inside it. A project that wants real git history for its
    # vault opts in explicitly via config.json.
    "memory": {
        "provider": "hybrid",
        "vault_path": "",
        "obsidian_cli": "auto",
        "git_enabled": False,
    },
    "self_tuning": {
        # Autonomous gate self-tuning (2026-09-02 design). Disabled by
        # default -- a project must explicitly opt in. See
        # docs/superpowers/specs/2026-09-02-autonomous-gate-self-tuning-design.md.
        "enabled": False,
        "review_every_n_executions": 20,
    }
}

def load_config(project_root: Path) -> Dict[str, Any]:
    p = project_root / ".dv-harness" / "config.json"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        # BUG FIX (2026-08-28): this used to `return DEFAULT_CONFIG` -- the
        # literal module-level dict object, not a copy. Any caller that
        # mutates its own harness's cfg (e.g. `h.cfg["policy"][...] = X`,
        # done throughout this test suite and by real callers adjusting
        # policy at runtime) was silently corrupting the shared global
        # default for every OTHER DVHarness in the same process whose
        # config.json didn't exist yet -- confirmed via test-order-dependent
        # failures (test_constraint_and_correction_are_folded_into_next_stage_prompt's
        # `h.cfg["policy"]["require_stage_gate_evidence"] = False` leaked into
        # later fresh-tmp-dir harnesses' gate evaluation). Deep-copy here,
        # matching the pattern already used in the "file exists" branch below.
        return json.loads(json.dumps(DEFAULT_CONFIG))
    cfg = json.loads(p.read_text(encoding="utf-8"))
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for k,v in cfg.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged


def save_config(project_root: Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Durable write side of load_config(), added for the CLI/GUI
    require_dv_review_cosign toggle (2026-08-28 GUI/CLI gap-closure pass):
    before this, .dv-harness/config.json's policy block was hand-edit-only,
    with no code path that ever wrote it back. Reuses the same atomic
    tmpfile + os.replace pattern as storage.StateStore.save()/
    dashboard._save_project_meta() rather than a plain write_text(), for the
    same reason their docstrings give: a concurrent GET /api/state read
    (dashboard.py's own _read_json_file, which already retries a transient
    PermissionError on Windows) must never observe a half-written file."""
    from .storage import _atomic_replace
    p = project_root / ".dv-harness" / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="config.", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return cfg
