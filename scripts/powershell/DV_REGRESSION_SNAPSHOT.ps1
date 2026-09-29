# -Watch cadence defaults to 5 minutes, matching `dv-harness lsf-watch-start`
# and regression_reporter.DEFAULT_INTERVAL_MINUTES. It was 30, which put this
# entry point three times outside self_check_list #41's 10-minute ceiling for
# background job/simulation-log confirmation.
param([int]$IntervalMinutes=5,[switch]$Watch)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($Watch) { python -m dv_harness.regression_reporter --project-root $root --watch --interval-minutes $IntervalMinutes } else { python -m dv_harness.regression_reporter --project-root $root }
