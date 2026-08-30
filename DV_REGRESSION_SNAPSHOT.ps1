param([int]$IntervalMinutes=30,[switch]$Watch)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($Watch) { python -m dv_harness.regression_reporter --project-root $root --watch --interval-minutes $IntervalMinutes } else { python -m dv_harness.regression_reporter --project-root $root }
