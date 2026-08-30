---
name: compile-once-run-many
description: Prevent concurrent testcase launchers from recompiling/elaborating into the same output directory; enforce compile/elab ownership and STOP_AFTER_SIMV behavior.
---
# Compile Once, Run Many

For regression/local parallel testcase launch:

1. Build/elaboration is a distinct stage with one owner.
2. `STOP_AFTER_SIMV=1` must be used by the build owner when the flow's compile target would otherwise continue into simulation.
3. `usbrun.sh` testcase workers must not invoke a full `make compile` / `usbc.elab` when a valid `simv` already exists for the exact build fingerprint.
4. Never allow concurrent `usbc.elab` jobs to write the same:
   - `output/csrc`
   - `output/simv.daidir`
   - `output/simv`
5. Use a build lock / build fingerprint / atomic completion marker before allowing run workers to start.
6. Parallelism starts only at simulation run level after compile/elab is complete.
7. If per-test recompilation is truly required, each compile must use an isolated output directory keyed by build/test identity; shared output is forbidden.
8. Detect duplicate elaboration jobs and kill/cancel redundant jobs before they corrupt shared artifacts.
