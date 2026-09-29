# M1 — Absolute-Path Runtime-Dependency Scan

Per instruction #13. Scope: `dv_harness/*.py` (canonical runtime source), excluding
test files. Separates real runtime dependency from migration-provenance /
historical-documentation / example text.

## Method

`grep` for Windows drive-letter paths (`[A-Za-z]:[\\/]...`) and Linux absolute
paths (`/home/...`) across every `dv_harness/*.py`, then manually inspected the
context of every real hit (most regex matches were false positives from URL
schemes like `http://`/`ipy://` and f-string patterns like `d:\n` — excluded).

## Real candidates found and disposition

| Hit | File:line | Classification | Evidence |
|---|---|---|---|
| `D:/DV/Task/USB/usb31_dev_uvm` | `agent_checkpoint_check.py:23` | Documentation example (illustrates a non-DVHarness build tree) | Prose, not a code literal |
| `D:/DV/Task/DV_Agent_Harness_L5/ATB` | `atb_reference_inventory.py:21` | Documented, NOT a runtime dependency — module's own docstring states "used only by this module's own tests... a caller may point this at a different reference tree" | `discover_atb_capabilities(root, ...)` always takes `root` as a caller-supplied parameter |
| `D:\\DV\\Task\\USB\\VIP\\...` | `context_budget.py:149` | Docstring example (illustrates cross-shell path normalization) | Prose, not a code literal |
| `C:\\...` | `dut_knowledge_graph.py:216` | Comment example (illustrates Windows-drive-letter colon-parsing edge case) | Prose, not a code literal |
| `C:/ProgramData/chocolatey/bin/obsidian-cli.exe` | `memory_vault.py:720` | OS-standard external-tool search path (a well-known Chocolatey install location probed as one of several candidates) | Not a repo/bootstrap path; doesn't depend on this repo's own location at all |
| `/home/svcacct/AI/Agent` | `cli.py:2099`, `env_manifest.py:126`, `harness_deploy.py:7,430`, `multi_user_coordination.py:17` | Documentation/policy citation only (quotes `USAGE_MULTI_USER_SAFETY.md`'s own standing-policy text) — re-verified: **never** appears as an actual string literal assigned to a variable or used in a real path/file operation anywhere in these files | `grep` confirms every occurrence is inside a `#`/`#:`/docstring comment, backtick-quoted as a citation |

No hit represents a real functional dependency on the bootstrap absolute path, a
historical source repository's absolute path, or a coupling between local and
remote path spaces.

## Result

```
ABSOLUTE_BOOTSTRAP_PATH_RUNTIME_DEPENDENCIES = 0
HISTORICAL_SOURCE_PATH_RUNTIME_DEPENDENCIES = 0
LOCAL_REMOTE_PATH_COUPLING = 0
```

(`HARDCODED_GATEWAY_HOST_IN_RUNTIME = 0` and `HARDCODED_REMOTE_EDA_HOST_IN_RUNTIME = 0`
already established separately in `M1_EXECUTION_PROFILE_EXTRACTION.md`.)

## Related, out-of-scope-for-this-scan finding (disclosed, not fixed)

Several `dv_harness/syoscb_*.py` / `dv_harness/system_phase1_report.py` modules
cite a `POLICY_DOC`/`SYSTEM_LEVEL_DOC`/`SYOSCB_DOC`/`TAXONOMY_DOC` constant
naming `"DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_..."` — a
**relative filename reference**, not an absolute path, so it does not count
against any of the three fields above. Confirmed via `find` that no file by
that name exists anywhere in this canonical repository — a real,
pre-existing (not introduced by M1) dangling documentation citation inherited
from the v50 baseline. Not fixed here: out of scope for an absolute-path scan,
and not a runtime failure (the constant is a citation string, not something
the code opens/reads).
