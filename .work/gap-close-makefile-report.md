# Report: Makefile/sim-scripts migration gap closed

Scope executed per `.work/gap-close-makefile-investigation.md`: migrate `analyze_sim.sh`,
`apb_timing_report.sh`, `dpdm_report.sh`, `irq_report.sh`, `check/gen_scaledown.py` from
`USB_UVM_Handoff/sim/scripts/` into `dv_harness/uvm_generator/templates/sim_scripts/`,
genericized to the same `TARGET_IP`/`IP_PREFIX` convention already established by the
migrated `Makefile`, `waves.tcl`, `lsf_regress.sh`, `ip_run.sh`, and `check/reg_audit.py`.

## What was migrated

1. **`analyze_sim.sh`** — copied near-verbatim (log-triage mechanics are already
   protocol-agnostic: `UVM_ERROR` count, `FINAL_CHECK`/`SvtTestEpilog` marker count, error
   signature histogram). The one protocol-specific line (`grep -ac usb_dma_sb`) is now
   `grep -ac "${IP_PREFIX}dma_sb"`, `IP_PREFIX` defaulting to `usb_`. Header explains the
   scoreboard-component-name caveat (confirm against the current project's own
   `env/*_scoreboard.sv`, do not assume the name matches `${IP_PREFIX}dma_sb` literally).

2. **`fsdb_signal_report.sh`** (new — not one of the 5 named files, but required to migrate
   the other three without tripling boilerplate; the investigation report flagged this
   explicitly as "the stronger migration" with a documented fallback). Shared engine: parses
   `<fsdb> [begin-time-ns] [end-time-ns]`, loops over a `SIGNALS` env var
   (whitespace-separated `label=hierarchical.path` tokens), runs `fsdbreport` once per
   signal, reports `wc -l` per output file. Carries no signal list of its own — sourced
   (`.`, not `sh ...`) by each per-question wrapper below, which supplies `SIGNALS` and the
   `ET` default before sourcing. Chose `=` as the label/path delimiter instead of `:`
   because a real signal path in this family (`interrupt[19:0]`) already contains a colon in
   its bit-select syntax; verified this would have silently truncated the path had `:` been
   kept, before choosing `=`.

3. **`apb_timing_report.sh`**, **`dpdm_report.sh`**, **`irq_report.sh`** — kept as the three
   named per-question wrapper files (matching the task's explicit file list and the source
   project's discoverability-by-filename layout), each now ~25 lines: define
   `TARGET_IP`/`IP_PREFIX`, centralize the hierarchical path variables using waves.tcl's own
   variable names (`TB`/`DUT`/`SSVOUT`/`IPTOP_IDX0`/`IPTOP_IDX1`/`IP0`/`IP1`) so the
   interactive (`waves.tcl`) and headless (these scripts) tools stay in sync, build a
   `SIGNALS` list from those variables, set the `ET` default, then `. fsdb_signal_report.sh`.
   Each carries a `GENERIC TEMPLATE NOTE` explaining what is shape (generic, reusable) versus
   subject (USB-specific, re-derive per protocol) — `dpdm_report.sh`'s note is the most
   explicit per the investigation's finding that `dp`/`dm` is the one file whose *subject*,
   not just its hardcoded paths, is USB-2.0-specific, with a "drop this file entirely rather
   than force-fit it" instruction for a protocol with no equivalent electrical pair.

4. **`check/gen_scaledown.py`** — framework-preserved, content-lifted-to-data migration
   mirroring `reg_audit.py`'s precedent exactly: `TARGET_IP`/`IP_PREFIX`/`IP_PREFIX_STEM` env
   vars; VIP config class path built from `IP_PREFIX_STEM` (`svt_{stem}_configuration.sv`)
   with the same "not guaranteed to match every VIP" caveat `reg_audit.py` already carries;
   `RENAME`, `MODE_COLUMNS` (was an inline `('USB 2.0', 1), ('SuperSpeed', 0)` tuple, now a
   named, commented constant), `LEGACY_DEDUP` (was two inline regex matches in the loop body,
   now a named list of `(pattern, modern-name-format)` pairs so a project with zero legacy
   dedup cases can pass an empty list instead of editing loop logic), and `FAMILY_SUFFIXES`
   are all top-of-file data with a header block explaining each is USB's real worked instance
   and must be re-derived per VIP/spreadsheet. Output naming (`gen_%s.svh`,
   `host_cfg[p].<field>`) is now `SCALEDOWN_OUT_PATTERN`/`SCALEDOWN_DEST_MEMBER_FMT`
   env-overridable instead of hardcoded, since a future project's DUT-config consumer class
   will not be named `usb_top_cfg.sv`. Also fixed the original's silent
   `except ImportError` gap for `xlrd` (now reported instead of crashing on the first
   `xlrd.open_workbook` call with no explanation) while preserving the framework's actual
   logic and comments verbatim otherwise.

## What was genericized vs. left as documented USB-specific

Genericized (structure, one edit point via named variables, `TARGET_IP`/`IP_PREFIX`):
job/module naming prefixes; the `fsdbreport`-export loop shape; the VIP-class-vs-spreadsheet
cross-check framework in `gen_scaledown.py`.

Left as explicit, labeled USB worked-example content (per the "No Golden-Reference Content
Mining" rule applied to documentation authoring, and CLAUDE.md's "no overly abstract naming"
rule — a hierarchical RTL path is a DUT fact, not a runtime knob to genericize away):
- Every hierarchical signal path (`sysn063`, `u_lan063`, `u_ss_vout`, `u_udc_usb31_top`,
  `usb_s_psel`/`pready`/`penable`, `dp`/`dm`, `usbirq`, `interrupt[19:0]`,
  `u_usbwrapper_usb`) — centralized into named variables reusing `waves.tcl`'s own
  vocabulary, with a header instruction to re-derive from the current DUT's RTL, never assume
  carry-over.
- `dpdm_report.sh`'s subject (`dp`/`dm` as a USB 2.0 electrical concept) — flagged as
  narrower than the other two wrappers' reusable shape, with an explicit "drop this file for
  a protocol with no equivalent pair" instruction.
- `gen_scaledown.py`'s `RENAME`/`MODE_COLUMNS`/`LEGACY_DEDUP`/`FAMILY_SUFFIXES` — one-off
  USB-VIP-vs-spreadsheet naming history that cannot be generalized, only re-derived per
  project.
- `irq_report.sh`'s `ET=2000000` default — kept as a real value with a comment that it is a
  tuning constant from this template's original project's own pattern timing, not a
  structural default.

No file was force-genericized past what the investigation judged provable; none needed the
"too USB-specific to genericize" escape hatch (unlike, e.g., the non-USB topology variants
elsewhere in this codebase) — all 5 had a real, defensible generic/specific split.

## Makefile

Not touched. Confirmed (grep across the full 3600+-line migrated `Makefile` and the original
`USB_UVM_Handoff/sim/scripts/Makefile`) that none of the 5 source files, nor the new shared
`fsdb_signal_report.sh`, are invoked by any `make` target in either tree — all are standalone,
hand-invoked engineer utilities. No new target was added, per the task's instruction to leave
the Makefile alone unless a migrated script genuinely needs one to be invokable.

## Verification

- `python -m py_compile check/gen_scaledown.py` — passes.
- `sh -n` on all 5 new/changed `.sh` files — passes.
- Functional smoke test: built a fake `$VERDI_HOME/bin/fsdbreport` stub that records the
  `-s <signal-path>` and `-o <outfile>` it was called with, then ran `apb_timing_report.sh`,
  `dpdm_report.sh`, and `irq_report.sh` against it. Confirmed: correct signal paths built
  from the `TB`/`SSVOUT`/`IP0`/`IP1` variables (including the `IP_PREFIX`-driven
  `u_${IP_PREFIX}top[N]` instance name, matching `waves.tcl`'s existing convention exactly,
  underscore-doubling and all); the `interrupt[19:0]` bit-select path passed through the
  `=`-delimited `SIGNALS` list intact (this is what caught the `:`-delimiter bug during
  development, before switching to `=`); correct `wc -l` summary lines and output filenames
  (`p1_psel.txt`, `p0_dp.txt`, `p0_intr.txt`, etc., matching the originals' own naming).
- Ran the existing automated test suite's Makefile/template-related subset:
  `python -m pytest dv_harness_tests -k "makefile or template or sim_scripts" -q` →
  **41 passed**, 0 failed (all pre-existing tests target the `Makefile` itself or unrelated
  template machinery; none of them enumerate or check `sim_scripts/`'s file list, so this
  confirms no regression rather than covering the new files).
- Grepped the whole repo for `analyze_sim|apb_timing_report|dpdm_report|irq_report|
  gen_scaledown` before this change: zero automated-test references existed. **No test suite
  in this repo covers `templates/sim_scripts/` file existence or content** beyond the
  Makefile-specific tests above — closing this gap did not have, and still does not have, a
  dedicated regression test. If future work wants one, the natural shape (per this repo's own
  test conventions in `dv_harness_tests/test_makefile_patterns_stub_targets.py`) would be a
  file-existence + `TARGET_IP`/`IP_PREFIX`-override smoke test for each of the 6 files this
  migration adds.
- Grepped `dv_harness/uvm_generator/*.py` for any hardcoded file-copy list that enumerates
  `sim_scripts/` contents (e.g. a `shutil.copytree` allowlist) — found none; this directory
  functions as a reference/survey target for agents rather than an auto-copied set, so no
  generator code needed updating for the new files to become visible.

## Files touched

- `dv_harness/uvm_generator/templates/sim_scripts/analyze_sim.sh` (new)
- `dv_harness/uvm_generator/templates/sim_scripts/fsdb_signal_report.sh` (new, shared engine)
- `dv_harness/uvm_generator/templates/sim_scripts/apb_timing_report.sh` (new)
- `dv_harness/uvm_generator/templates/sim_scripts/dpdm_report.sh` (new)
- `dv_harness/uvm_generator/templates/sim_scripts/irq_report.sh` (new)
- `dv_harness/uvm_generator/templates/sim_scripts/check/gen_scaledown.py` (new)
- `CLAUDE.md` (consolidation-status note updated: Makefile/sim-scripts migration gap marked
  closed 2026-09-03, one gap — command.txt/pattern content architecture — remains open)
- `Makefile` — not touched (no migrated script needs a new target; verified by grep against
  both the migrated and original Makefiles)
