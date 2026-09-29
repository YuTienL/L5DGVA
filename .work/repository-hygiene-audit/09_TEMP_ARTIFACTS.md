# 09 — Temporary / Generated Artifact Findings

Source: Agent 4 (root-level) + Agent 1 (directory-level). Every artifact below was checked for a producer and a consumer before any disposition was proposed — "looks like test junk" is not treated as proof.

## `.pytest_tmp/` (dir, 179 files, 393,783 bytes)

- **Producer**: no `basetemp=".../.pytest_tmp"` or literal `.pytest_tmp` string exists anywhere in `pyproject.toml`, `dv_harness_tests/conftest.py`, or any `.py`/`.md`/`.yml` file in the repo. pytest's own default tmp root goes to the OS temp dir (confirmed via a real captured `TempPathFactory(...basetemp=WindowsPath('C:/Users/.../pytest-of-.../pytest-3469')...)` in a `.work/` report). This directory can only be explained by someone manually invoking `pytest --basetemp=.pytest_tmp` at repo root at some point (dated 2026-09-08) — **not reproduced by the documented/standard test invocation** (`python -m pytest dv_harness_tests/ -q`, per CI and START_HERE.md).
- **Tracked status**: untracked, and **not** `.gitignore`-covered.
- **Reproducible?** Only if someone repeats the same manual `--basetemp=.pytest_tmp` invocation.
- **Disposition**: `DELETE_GENERATED` with prevention = a new `.gitignore` entry + documenting the standard (no custom `--basetemp`) test invocation. See `14`/`16`.
- **EXECUTED (Phase 2, H2-2, 2026-09-22)**: `.gitignore` prevention landed first in H2-1 (`0634c14`); re-verified immediately before deletion that no file under this directory had an mtime within the prior 2 hours (nothing was actively writing into it); deleted all 179 files (untracked — this produces no git diff by itself, hence this record is the batch's committable evidence). Focused/related tests (import smoke + collection count, matching the H2-0 baseline's 13730 exactly) showed zero regression delta.

## `.pytest_cache/` (dir, 5 files, 1,572,035 bytes)

- Standard pytest cache (`CACHEDIR.TAG`, `v/cache/lastfailed`, `v/cache/nodeids`, pytest's own bundled `.gitignore`).
- **Tracked status**: untracked and **already `.gitignore`-covered** (line 3).
- **Reproducible?** Fully, by any pytest run.
- **Disposition**: no action needed — already correctly handled.

## The 8 `.pytest-tmp-*.tcl`/`.sh` files (a matched set, genuinely surprising finding)

| File | Size | Content |
|---|---|---|
| `.pytest-tmp-clock-table.tcl` | 15,497 B | Real SoC clock-tree Tcl table (`CK_ROOT_TABLE`, `FUNC_CK_TABLE`, real pin paths like `u_gtop/u_gmux/...`) |
| `.pytest-tmp-gen-clocks-fdc.sh` | 33,294 B | A real bash tool: "Industrial table-driven clock FDC generator (ProtoCompiler-friendly)" — the companion generator that consumes the table above |
| `.pytest-tmp-logical-multisource-table.tcl` | 605 B | Same domain |
| `.pytest-tmp-mixed-logical-example.tcl` | 226 B | Same domain |
| `.pytest-tmp-multisource-clock-table.tcl` | 294 B | Same domain |
| `.pytest-tmp-phys-create-clock-table.tcl` | 133 B | Same domain |
| `.pytest-tmp-physical-all-forms-table.tcl` | 655 B | Same domain |
| `.pytest-tmp-phys-include-gen-table.tcl` | 330 B | Same domain |

- **Producer/consumer**: **none found anywhere in this repository.** No `dv_harness/`, `dv_harness_tests/`, or `tools/` file mentions clocks, FDC generation, or Tcl clock tables. These 8 files are internally consistent as a matched set (one generator + seven input-table fixtures/examples) but the whole subject (SoC clock-tree FDC generation) does not otherwise exist anywhere in this Python DV-harness repository.
- **Tracked status**: untracked, and **not** `.gitignore`-covered.
- **Disposition**: `UNKNOWN` — deliberately **not** proposed as `DELETE_GENERATED`. Despite the `.pytest-tmp-` name pattern, there is zero evidence this content came from this repo's own pytest suite; the honest, evidence-backed conclusion is that this is unexplained, domain-unrelated content (possibly dropped/pasted during an unrelated session, or a cross-project mix-up on a shared machine), not "reproducible test garbage." Per the master prompt's own rule ("UNKNOWN blocks physical cleanup"), no deletion is proposed until a human confirms the origin. See `02`/`14`.

## `_tmp_experience_loop_design.txt` (1,782 B)

- **Tracked** — confirmed via `git ls-files`, added in the single "Initial commit" despite its `_tmp_` scratch-shaped name, which is inconsistent with the `_tmp_*` = scratch convention `.gitignore` documents elsewhere.
- **Content**: a crashed Python script's captured stdout/stderr (`UnicodeEncodeError: 'cp950' codec can't encode character '\u2265'`) followed by a manually-written "GAP:" design note about the `EXPERIENCE_READY` promotion-gate dead-end.
- **Disposition**: `UNKNOWN`. Not reproducible by any script (a one-off crash capture); its factual content (the documented `EXPERIENCE_READY` gap) may still have real value even though the artifact itself is scratch-shaped — a human should decide whether to preserve the *content* (e.g. moved into a proper `.work/` design note or `docs/` issue) separately from the *file's* tracked status.

## `_tmp_selfcheck_big5.txt` (22,640 B) and `_tmp_selfcheck_decoded_utf8.md` (23,063 B)

- Both untracked. The first is a manually-pasted Traditional-Chinese self-check/design note, garbled (mojibake) as if written under the Big5 codepage; the second is the same content re-decoded to valid UTF-8 — i.e. the `.md` file is a manual encoding-fix pass of the `.txt` file, not independent content.
- **No producer script** for either.
- `_tmp_selfcheck_decoded_utf8.md` is the **one file in the entire root inventory with zero references of any kind, anywhere** (see `04`).
- **Disposition**: `UNKNOWN` for both — human should decide keep-as-note (probably just the UTF-8 one, since it supersedes the Big5 one) vs. delete.

## `generated/canfd_uvm_env/` and `project_input/04_protocol/canfd_environment_manifest.json` (peripheral, not root-level files themselves)

Untracked, real multi-file generated CAN-FD UVM environment output sitting inside the otherwise-tracked `generated/`/`project_input/` scaffold trees. Structurally different from the temp/cache patterns above (a genuine generated deliverable tree, not cache-shaped). Flagged only for completeness since it surfaced in `git status`; not deep-dived (falls outside the four temp-pattern names this section is scoped to), and not proposed for any action.

## Summary table

| Artifact | Producer found? | Consumer found? | Tracked? | `.gitignore`-covered? | Proposed action |
|---|---|---|---|---|---|
| `.pytest_tmp/` | Weak (manual invocation only) | None | No | **No (gap)** | `DELETE_GENERATED` |
| `.pytest_cache/` | Yes (standard pytest) | n/a | No | Yes | none needed |
| 8× `.pytest-tmp-*.tcl`/`.sh` | **None (unrelated domain)** | None | No | **No (gap)** | `UNKNOWN` |
| `_tmp_experience_loop_design.txt` | None | n/a (has real content value) | **Yes** | n/a | `UNKNOWN` |
| `_tmp_selfcheck_big5.txt` | None | None | No | **No (gap)** | `UNKNOWN` |
| `_tmp_selfcheck_decoded_utf8.md` | None | **Zero refs of any kind** | No | **No (gap)** | `UNKNOWN` |
