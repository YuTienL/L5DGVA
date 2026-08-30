# Provider-Neutral DV DevOps Pipeline Reference

Do not copy blindly. First inspect existing CI.

Stages:
1. source_sync
2. preflight
3. build
4. target_verify
5. regression_submit
6. regression_monitor
7. failure_triage
8. regression_report
9. signoff

Required identity:
repo + branch + commit SHA + submodule SHA + server/workdir/env.
