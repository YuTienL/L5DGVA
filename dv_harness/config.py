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
        # Whether a recorded Qualified Conclusion that did NOT qualify blocks
        # SIGNOFF (policy.can_signoff). Distinct from require_second_pass_audit
        # above: that one asks whether RE_AUDIT reached PASS, this one asks
        # what it concluded.
        "require_qualified_conclusion": True,
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
    },
    # lmstat + scheduler preflight gate (2026-09-03, highest-priority
    # workstream per the user's own spec -- see dv_harness/preflight.py and
    # `dv-harness lsf-submit`, which builds a PreflightConfig from this
    # block via preflight.config_from_dict()). `license_server`/`workdir`
    # deliberately empty by default -- same "never guessed or hardcoded"
    # convention as knowledge_center.remote_root/rtl_protection.protected_paths
    # above: a project must explicitly fill these in with ITS real license
    # server (e.g. "2900@host-a") and real remote working directory once
    # discovered (this project's own real values were confirmed live
    # 2026-09-03 -- see .work/governance-preflight-report.md -- but are not
    # hardcoded here since dv_harness ships to other projects/servers too).
    # An empty license_server FAILS (blocks) the license check by default
    # (see PreflightConfig.require_license_configured's own docstring) --
    # never a silent pass.
    "preflight": {
        "queue": "vcs",
        "workdir": "",
        "required_env_vars": ["VCS_HOME", "UVM_HOME", "VERDI_HOME"],
        "min_free_disk_gb": 20.0,
        "license_server": "",
        "license_features": ["VCSRuntime"],
        "lmutil_path": "lmutil",
        "shell": "csh",
        "require_license_configured": True,
    },
    # Planner -> Execution Layer gate (2026-09-04, governance-architecture
    # routing pass). Wires the `preflight` block above into
    # engine.DVHarness.run_stage() itself for BUILD/REGRESSION-family stages
    # -- i.e. any graph node declaring one of `skills` below -- so the full
    # 6-check preflight suite runs as part of the Planner's own flow instead
    # of only from `dv-harness preflight` / `dv-harness lsf-submit`. A BLOCKED
    # verdict parks the stage in WAIT_USER before any agent is dispatched.
    # There is no second preflight config: this block only says WHEN to run
    # the gate, never WHAT to check.
    #
    # `probe_resources` OFF by default for exactly the reason the
    # `degradation` block below states for its own identical flag: the checks
    # shell out to real `lmutil`/`bqueues`/`df`/csh env probes that exist only
    # server-side, and reading "command not found" as a jammed farm would be a
    # fabricated BLOCK. Turn it on for a server-side deployment, or assign
    # engine.DVHarness.execution_preflight_runner a
    # preflight.RemoteRelayCommandRunner() to probe the real server from a
    # PC-side session (an injected runner arms the gate on its own).
    "execution_preflight": {
        "enabled": True,
        "probe_resources": False,
        "skills": ["devops-pipeline", "vcs-build"],
    },
    # --- Reliability blocks (2026-09-03 user spec: dry-run / checkpoint 與
    # 回滾 / 降級路徑). All three are read by dv_harness/engine.py's
    # run_stage(); see docs/ENGINE_STAGE_LIFECYCLE.md for how each one
    # changes the stage lifecycle.
    #
    # dry-run ("agent 產出完整計畫但不執行，人可事前檢視。導入初期與大改動前必
    # 用"): OFF by default -- dry-run is a deliberate per-invocation choice
    # (`dv-harness run-stage --dry-run`), and a config file that silently
    # made every stage a no-op would be a far worse failure mode than
    # forgetting the flag. Setting `enabled` true here is for exactly the
    # case the spec names: an onboarding/large-change period where EVERY
    # stage should be planned-and-reviewed before it is allowed to execute.
    # The CLI flag ORs with this -- it can turn dry-run on, never off.
    "dry_run": {
        "enabled": False,
    },
    # Automatic stage-transition checkpoints ("每個階段留可回復點, agent 走偏
    # 時不必從頭"). ON by default, unlike the opt-in blocks above, for the
    # reason evidence_db gives for its own default: this is purely local
    # file copying under .dv-harness/sessions/ -- no network call, no
    # credential, no external binary -- and the whole value of a recovery
    # point is that it already exists when you discover you need it.
    # `keep_last` bounds the growth (see session_snapshot.
    # prune_auto_checkpoints(), which only ever deletes `auto_`-prefixed
    # snapshots -- never a human's --name snapshot, never a _pre_restore_
    # undo backup). 0 or less disables pruning rather than deleting
    # everything.
    "auto_checkpoint": {
        "enabled": True,
        "keep_last": 10,
    },
    # DEGRADED mode ("Claude API 不可用、license 全滿、farm 塞車時, harness 應
    # 降級成「只收集資料、不做判斷」"). See dv_harness/degradation.py's module
    # docstring for what each trigger reuses and why.
    #
    # `enabled` on by default: the adapter-failure trigger it gates costs
    # nothing (it only counts outcomes run_stage() already computes) and its
    # whole purpose is to stop a broken-adapter run from thrashing.
    # `adapter_failure_threshold` is deliberately policy.max_stage_retries
    # (2) + 1 -- degradation begins only after the EXISTING stage-retry
    # budget has been spent and the adapter is still failing; this adds no
    # parallel retry mechanism of its own.
    #
    # `probe_resources` OFF by default: the license/queue triggers shell out
    # to real `lmutil lmstat`/`bqueues`, which per preflight.py's own
    # transport docstring only exist when dv_harness runs server-side on the
    # Linux DV server. On a PC-side session those commands are simply
    # absent, and treating "command not found" as evidence of a full license
    # or a jammed farm would be a fabricated conclusion. Turn this on for a
    # server-side deployment (it reuses the `preflight` block above for the
    # license server/queue names -- there is no second place to configure
    # them).
    #
    # `transport` (2026-09-04) is what finally makes those two triggers
    # REACHABLE without hand-written Python. Until it existed, the only
    # documented way to probe the real DV server from a PC-side
    # REMOTE_EXECUTION session was to assign engine.DVHarness.
    # degradation_runner yourself, so in practice only the Claude-API trigger
    # was ever live. Values: "auto" (default -- resolve on real evidence:
    # persistent relay if READY for the configured VCHOST/VCHOP hop, else
    # local if lmutil/bqueues are genuinely on PATH, else NOTHING is armed),
    # "local", "remote_relay", "off". Overridable per invocation with
    # `dv-harness --degradation-transport ...`, and always visible in
    # `dv-harness status` (degraded_probe_transport). "auto" is safe as a
    # default precisely because it arms nothing it has not confirmed -- see
    # preflight.resolve_transport()'s comment block.
    "degradation": {
        "enabled": True,
        "adapter_failure_threshold": 3,
        "probe_resources": False,
        "probe_min_interval_sec": 60,
        "transport": "auto",
    },
    # Local PC-side task orchestration (2026-09-03, see dv_harness/
    # pueue_client.py). `group` keeps this project's pueue tasks visually/
    # queryably separate from any unrelated task a shared local pueue
    # daemon may also be running.
    "pueue": {
        "binary": "pueue",
        "daemon_binary": "pueued",
        "group": "dv_harness",
    },
    # Escalation-ONLY notifications (2026-09-03, see dv_harness/
    # escalation_notify.py) -- fires ONLY for license starvation, a large
    # UVM_FATAL burst, a real farm job submission failure, or a blocked
    # signoff; never for a routine PASS. `enabled` defaults False (same
    # explicit-opt-in convention as self_tuning/knowledge_center above) --
    # a project must supply its own real apprise URL(s)
    # (e.g. "ntfy://topic@ntfy.sh") once it has a real endpoint; none are
    # hardcoded here since no real endpoint credentials exist in this
    # session (see .work/governance-pueue-notify-report.md).
    "escalation": {
        "enabled": False,
        "apprise_urls": [],
        "uvm_fatal_burst_threshold": 3,
    },
    # Local DuckDB evidence store (2026-09-03, evidence-db-wiring step 1 --
    # see dv_harness/evidence_db.py and regression_reporter.
    # _write_reconciliation_evidence_if_configured(); evidence-db-wiring
    # step 2 added regression_reporter._write_normalized_evidence_if_
    # configured(), the vip_distill.py -> normalized_evidence bridge, gated
    # by this SAME flag rather than a second one). Writes land ONLY in a
    # local `.dv-harness/evidence/evidence.duckdb` file on this machine --
    # no network call, no credential, unlike knowledge_center/escalation
    # above -- so this block defaults ENABLED rather than opt-in: a project
    # gets its reconciliation cycle's real job/regression-verdict/
    # normalized-evidence rows persisted automatically, with an explicit
    # off-switch for a dry-run environment or a machine without the duckdb
    # package installed (a failed EvidenceStore construction is caught and
    # logged, never fatal to the cycle either way).
    "evidence_db": {
        "enabled": True,
    },
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
