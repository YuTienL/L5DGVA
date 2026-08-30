---
name: focused-fsdb-rerun
description: Re-run only when deep waveform debug is needed, using WAVE=1 from time 0 through first-error-time + 200us, then stop simulation and kill the job.
---
# Focused FSDB Rerun

Use only when WAVE=0 log/semantic analysis determines waveform evidence is required.

Inputs:
- first meaningful error/divergence timestamp `T_error`
- exact original testcase/command/seed/config/build identity

Rerun policy:
- `WAVE=1`
- `FSDB_START=0`
- `FSDB_STOP=T_error + 200us`
- preserve command/test/seed/config/build identity unless the workflow explicitly documents a controlled fix
- stop the simulation at `FSDB_STOP`
- kill/terminate the LSF job after the focused capture completes
- never let the focused rerun continue wasting simulation resources
- launch `fsdbreport`/waveform RCA workflow on the captured interval
- re-enter the main workflow after RCA

If `fsdbreport` syntax/tool usage is uncertain, consult the local/manual reference first and only then external documentation.
