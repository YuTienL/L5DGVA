# `just` recipe layer for push -> build -> verify -> run -> fsdbreport (2026-09-03)

## Scope

Third item on the user's own priority list, item 2 ("just -- 把目前 push -> build
-> verify -> run -> fsdbreport 變成固定 recipes。Claude 不需要自己拼長 command，
降低誤操作"), building directly on the Preflight/Resource Guard workstream (DONE,
`dv_harness/preflight.py` + `dv-harness preflight`/`lsf-submit`, see
`.work/governance-preflight-report.md`). This closes it: `just` installed, a real
project-root `justfile` with fixed recipes for the actual PUSH/BUILD/VERIFY/WAVE=1
RUN/FSDBREPORT pipeline, every job-submission-capable recipe gated by the real
preflight check, plus real tests.

## What was built

### `just` installed

`winget install --id Casey.Just` (package id confirmed first via `winget search
just` -- `Casey.Just`, not guessed). Installed version `1.58.0`.

### `D:\DV\Task\DV_Agent_Harness_L5\v50\justfile` (new)

Every recipe is composed from real, already-existing sources -- never invented:

- **`.claude/skills/CORE/remote-executor/SKILL.md`** -- the canonical
  PUSH -> BUILD -> VERIFY -> WAVE=1 RUN -> FSDBREPORT sequence this project
  already documents, including its no-git-remote PUSH variant (`tar czf` ->
  `remote_exec.py --put` -> `tar xzf`) and its Transport note that a long-running
  BUILD/regression should submit under `nohup ... &` and be polled, not run in
  the foreground.
- **`dv_harness/uvm_generator/templates/sim_scripts/Makefile`** -- the real
  `make compile`/`make sim`/`make regress`/`make check`/`make list_patterns`
  targets, their real variables (`FLOW`, `PATTERN`, `SEED`, `WAVE`, `SUITE`,
  `LSF_QUEUE`, ...) and defaults (`FLOW ?= fourstep`, `PATTERN ?= smoke`,
  `SUITE ?= all` generalized to this project's own `sanity`, `SEED ?= 1`), and
  its own `$(error VIP_HOME is not set...)`-style guards (confirmed: GNU make's
  `ifdef` is false for an explicitly empty value, so forwarding `VIP_HOME=`
  unconditionally still triggers the Makefile's real error rather than silently
  building against nothing).
- **`dv_harness/preflight.py` + `dv-harness preflight`/`lsf-submit`
  (`dv_harness/cli.py`)** -- the real lmstat + scheduler preflight gate from the
  Preflight/Resource Guard workstream. Confirmed via a real (non-remote)
  subprocess call before wiring it into the justfile:
  `python -m dv_harness.cli --project-root . preflight --queue vcs --workdir
  /home/svcacct/DV/UVM/USB/usb_uvm/sim --license-server 2900@host-a` really runs
  and really exits 1 on `BLOCKED` (`dv_harness/cli.py`:
  `raise SystemExit(0 if result.overall == "PASS" else 1)`).
- **`tools/remote/remote_exec.py` + `tools/remote/remote_hop.py`** -- the real
  Windows-PC-side transport (`--status`/`--put`/`--get`/positional `cmd`/`--cwd`/
  `--timeout`), and `fsdb_report.py`'s own module docstring for `fsdbreport`'s
  CONFIRMED real flag grammar (`fsdbreport <fsdb> -bt <t0> -et <t1> -s
  <hier_path> [...] [-verilog|-csv|-of h] -o <outfile>`, file path first).

Recipes (see the justfile's own header for the full source-mapping):

| Recipe | What it runs | Gated by `preflight`? |
|---|---|---|
| `relay-status` | `remote_exec.py --status` | no |
| `preflight [queue] [workdir] [license_server]` | `dv-harness preflight --remote ...` | -- (is the gate) |
| `push <local_dir> <remote_dir> [archive]` | `tar czf` -> `--put` -> `tar xzf` (no-git-remote PUSH variant) | no (not a job) |
| `push-file <local_file> <remote_file>` | `remote_exec.py --put` | no |
| `pull <remote_file> <local_file>` | `remote_exec.py --get` | no |
| `build [queue] [workdir] [license_server]` | `make compile FLOW=... VIP_HOME=... ...` | **yes** (`LSF_COMPILE` defaults to `LSF=1`) |
| `verify <pattern> [seed] ...` | `make sim PATTERN=<n> WAVE=0 ...` (targeted, Coverage/FSDB off) | **yes** (`LSF_SIM` defaults to `LSF=1`) |
| `regress <suite> ...` | `nohup make regress LSF=1 SUITE=<n> ... > regress_<suite>.out 2>&1 &` | **yes** |
| `regress-log <suite> [lines]` | `tail -n <lines> regress_<suite>.out` | no |
| `check` | `make check` (static checks, seconds) | no |
| `list-patterns` | `make list_patterns` | no |
| `run <pattern> [seed] ...` | `make sim PATTERN=<n> WAVE=1 ...` (First-Failure Waveform Rerun) | **yes** |
| `fsdbreport <fsdb> <bt> <et> <signals> <out> [fmt]` | real `fsdbreport` binary, confirmed grammar | no (post-processing only) |
| `pipeline <pattern> [seed] ...` | `build` -> `verify` -> `run`, chained | yes (once, deduplicated -- see below) |

`export MSYS_NO_PATHCONV := "1"` / `export MSYS2_ARG_CONV_EXCL := "*"` at the top
of the justfile carry forward the exact real, already-documented fix in
`tools/remote/remote_exec.py`'s own 2026-09-02 comment block for Git-Bash/MSYS
silently mangling a bare `/home/...` argument before Python ever sees it --
necessary here because `set windows-shell := ["D:/Program Files/Git/bin/sh.exe",
"-cu"]` (just's own documented Windows pattern for POSIX-style recipe bodies,
matching this project's existing scripts' quoting conventions) runs every
recipe line through exactly that MSYS shell.

### `dv_harness_tests/test_justfile.py` (new, 21 tests)

Real `just` subprocess tests, matching the task's own two-part scope:

1. **Parses/lists cleanly**: `just --list` and `just --summary` (a second,
   independent parse path) both exit 0 and name every recipe; a static guard
   confirms the justfile itself never carries the real VCPW value or a
   `VCPW`-shaped assignment (CLAUDE.md's password-handling rule, checked as
   committed-file content, not just runtime behavior).
2. **Generated command strings are correct**: every recipe verified via `just
   --dry-run <recipe> <args>` -- a real `just` subprocess that renders the exact
   command a real run would execute without spawning it. No test reaches a real
   remote server or submits a real LSF job.

Also verifies the gating property directly: `build`/`verify`/`run`/`regress`
each show `preflight --remote` appearing *before* the `make`/`nohup` line in
dry-run output order; `check`/`list-patterns`/`fsdbreport`/`regress-log`/
`relay-status` are confirmed to carry **no** `preflight` call (they never
submit a job, so gating them would be theater, not safety).

All 21 pass. Full existing suite (`pytest --collect-only`) still collects its
2304 tests cleanly with this new file added -- no import/collection regression.

## Real findings from actually running `just` against this justfile (not assumed)

- **`just --dry-run` writes to STDERR, not stdout.** Confirmed via a direct
  subprocess probe: `--list`/`--summary` print to stdout as expected, but
  `--dry-run`'s echoed command lines came back on stderr with stdout empty.
  The test helper concatenates both streams so every assertion is stream-
  agnostic; documented in the test file's own docstring so a future reader
  doesn't "fix" a phantom stdout bug that isn't there.
- **`just --list`'s long-signature line wrapping is cosmetic, not a parse
  defect.** Bisected empirically (a minimal repro justfile, binary-searching
  parameter name length): once a recipe's own signature (name + all
  `param=default` pairs) exceeds roughly 45-50 columns, `just --list` prints
  the doc comment on its own line above the bare signature instead of appending
  it after, on the same line. This is `just`'s own list-rendering choice for
  readability, confirmed by reproducing the exact threshold on trivial
  justfiles with no comments/backticks/quotes involved at all (several other
  hypotheses -- backticks, `$()`, embedded quotes, multi-line comment blocks --
  were tested and ruled out first). It looks like a "doc comment lost its
  recipe" at a glance; it is not. Recipe names here (`build`, `verify`, `run`,
  `regress`, `preflight`, `pipeline`) all have long `queue=queue
  workdir=preflight_workdir license_server=license_server`-style signatures for
  self-documentation reasons, so this cosmetic wrapping is visible in this
  project's real `just --list` output -- captured verbatim below.
- **`just` deduplicates identical dependency invocations within one run.**
  `pipeline`'s three stages (`build`/`verify`/`run`) each declare their own
  `(preflight queue workdir license_server)` dependency; when `pipeline` is run
  with no per-stage override, all three resolve to the byte-identical
  `preflight` call, and `just` runs it exactly once, not three times (confirmed
  via `just --dry-run pipeline ...`'s output, and asserted in
  `test_pipeline_chains_build_verify_run_in_order_gated_once_each`). This is a
  desirable property, not a gap: `just build`/`just verify` run standalone each
  still perform their own real preflight check, since separate `just`
  invocations share no dependency graph.
- **Invoking `just` itself from an MSYS/Git-Bash shell with a literal
  `/home/...` argument on the command line gets mangled one layer ABOVE where
  the justfile's own `MSYS_NO_PATHCONV`/`MSYS2_ARG_CONV_EXCL` exports can help.**
  Those two exports only protect subprocesses `just` itself spawns (the
  recipe's own shell lines calling `remote_exec.py`). Reproduced live this
  session: calling `just push local_dir=... remote_dir="/home/..."` from this
  environment's Bash tool (Git Bash) silently rewrote `/home/...` into a
  `D:/Program Files/Git/home/...` Windows path before `just.exe` ever parsed
  it -- the exact same MSYS auto-conversion class of bug `remote_exec.py`'s own
  2026-09-02 comment already documents, one layer up. **Practical guidance
  (documented in this report since it is about the calling shell, not
  something the justfile itself can fix):** invoke `just` from PowerShell (this
  session's own primary shell, confirmed unaffected) for any recipe taking a
  literal `/home/...` argument, or prefix the invocation with
  `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'` when invoking from a Git-Bash-
  style shell instead.

## Real `just --list` output (this project's actual justfile, 2026-09-03)

```
Available recipes:
    # a real job-submission step, hence the `preflight` dependency.
    build queue=queue workdir=preflight_workdir license_server=license_server
    check                                            # help text: "seconds not minutes -- run it before a long build").
    default                                          # List every recipe -- `just` with no argument does the same.
    fsdbreport fsdb bt et signals out fmt="-verilog" # (post-processing an FSDB that already exists), so no preflight dependency.
    list-patterns                                    # `list_patterns:` target, line 3196) -- read-only, no job submitted.
    # =============================================================================
    pipeline pattern=pattern seed=seed queue=queue workdir=preflight_workdir license_server=license_server
    # stops every gated recipe below before its `make`/bsub-triggering command.
    preflight queue=queue workdir=preflight_workdir license_server=license_server
    pull remote_file local_file                      # of the same real mechanism.
    push local_dir remote_dir archive="dv_push.tgz"  # variant -- not a `git push`/`git pull` -- is the real mechanism.
    push-file local_file remote_file                 # tools/remote/remote_exec.py's own module docstring example).
    # suite -- poll with `just regress-log`.
    regress suite=suite queue=queue workdir=preflight_workdir license_server=license_server
    regress-log suite=suite lines="80"               # pattern: `nohup make regress LSF=1 SUITE=sanity > regress.out 2>&1 &`).
    relay-status                                     # with `python tools/remote/remote_exec.py --status`").
    # LSF_SIM job-submission path as VERIFY, so the same preflight dependency.
    run pattern=pattern seed=seed queue=queue workdir=preflight_workdir license_server=license_server
    # $(LSF)`), hence the same `preflight` dependency.
    verify pattern=pattern seed=seed queue=queue workdir=preflight_workdir license_server=license_server
```

(The stray-looking `# ...` lines above certain recipes are the cosmetic
long-signature wrapping explained above -- each one IS that recipe's own doc
comment, `just` just chose to print it on the row above instead of appended
after a signature that would otherwise run past the terminal width.)

## Real `just --dry-run` output samples (generated command strings, verified)

```
$ just --dry-run build
python -m dv_harness.cli --project-root "D:\DV\Task\DV_Agent_Harness_L5\v50" preflight --remote --queue vcs --workdir /home/svcacct/DV/UVM/USB/usb_uvm/sim --license-server 2900@host-a
python "D:\DV\Task\DV_Agent_Harness_L5\v50/tools/remote/remote_exec.py" --cwd "/home/tmpacct/devuser/UVM/USB" --timeout 3600 "make compile FLOW=fourstep VIP_HOME= DUT_ROOT_PATH= UVM_ROOT_PATH= LSF_QUEUE=vcs"

$ just --dry-run verify usb20_enum
python -m dv_harness.cli --project-root "..." preflight --remote --queue vcs --workdir /home/svcacct/DV/UVM/USB/usb_uvm/sim --license-server 2900@host-a
python ".../tools/remote/remote_exec.py" --cwd "/home/tmpacct/devuser/UVM/USB" --timeout 1800 "make sim PATTERN=usb20_enum SEED=1 WAVE=0 VIP_HOME= DUT_ROOT_PATH= UVM_ROOT_PATH= LSF_QUEUE=vcs"

$ just --dry-run run usb20_enum 7
... "make sim PATTERN=usb20_enum SEED=7 WAVE=1 VIP_HOME= DUT_ROOT_PATH= UVM_ROOT_PATH= LSF_QUEUE=vcs"

$ just --dry-run regress sanity
... "nohup make regress LSF=1 SUITE=sanity VIP_HOME= DUT_ROOT_PATH= UVM_ROOT_PATH= LSF_QUEUE=vcs > regress_sanity.out 2>&1 & echo submitted pid=$!"

$ just --dry-run fsdbreport /home/x/run/usb20_enum_1/usb20_enum.fsdb 0 500000 "uvm_test_top.env.usb_host_agent_0.link" /home/x/report/link.txt
... "fsdbreport /home/x/run/usb20_enum_1/usb20_enum.fsdb -bt 0 -et 500000 -s uvm_test_top.env.usb_host_agent_0.link -verilog -o /home/x/report/link.txt"

$ just --dry-run push "D:/DV/Task/USB/uvm" "/home/tmpacct/devuser/UVM/USB/uvm"
tar czf ".../.work/dv_push.tgz" -C "D:/DV/Task/USB/uvm" .
python ".../remote_exec.py" --put ".../.work/dv_push.tgz" "/home/tmpacct/devuser/UVM/USB/uvm/dv_push.tgz"
python ".../remote_exec.py" --cwd "/home/tmpacct/devuser/UVM/USB/uvm" "tar xzf dv_push.tgz && rm -f dv_push.tgz && find . -type f | wc -l"
rm -f ".../.work/dv_push.tgz"
```

## Testing

```
$ python -m pytest dv_harness_tests/test_justfile.py -v
...
21 passed in 7.57s

$ python -m pytest --collect-only -q
...
2304 tests collected in 37.02s   (no regression from the new file)
```

No real remote job was ever submitted by any test -- every generated-command
assertion goes through `just --dry-run`, which renders but never executes.

## Gaps / follow-ups (explicitly out of this task's scope)

- `.claude/skills/CORE/remote-executor/SKILL.md`'s full "Server exact-commit
  sync" / git-free `source_identity.py` three-way md5 diff
  (`tools/verification_flow/server_sync_identity_gate.py`) is a real, separate,
  more elaborate evidence gate (JSON evidence payload with local/remote md5sum
  transcript files) meant for the agent-orchestrated workflow, not a one-line
  shell recipe -- `push` includes only a lightweight real post-extraction file
  count as immediate feedback, not a replacement for that gate. Wiring a
  `just`-level recipe for the full three-way identity check, if wanted, is a
  follow-up.
- `fsdbreport` calls the real `fsdbreport` binary directly over the relay
  rather than `dv-harness fsdb-report`, since this session found no evidence
  `dv_harness` itself is deployed/installed on the remote Linux server (only
  the raw persistent-relay + shell-command transport is confirmed there). If a
  future session confirms `dv_harness` IS deployed remotely, switching this one
  recipe to `dv-harness fsdb-report` would additionally get the module's own
  JSON parsing of the report text for free.
- `verible --export_json` + DuckDB (item 3 on the user's list) and gh CLI +
  PR-only governance (item 4, already landed as a CLAUDE.md section by a
  parallel workstream this session) are separate, not built here.
