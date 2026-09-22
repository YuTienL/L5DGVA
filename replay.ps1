# L5DGVA remote EDA transport launcher (M1 minimal configuration extraction).
#
# Canonical, generic, host-identity-free: this file is committed to the
# canonical repository. It no longer hardcodes any gateway host, remote-EDA
# hop host, account or remote workdir -- those come from an execution
# profile (see dv_harness/execution_profile.py and
# config/execution_profiles/example.profile.json for the schema). Create
# your own real profile at .dv-harness/execution_profile.json (gitignored,
# per checkout, never committed), or set L5DGVA_EXECUTION_PROFILE to point
# at one elsewhere.
#
# Responsibility: discover the canonical repository -> resolve the
# execution profile -> validate required configuration -> invoke the
# existing, unmodified remote transport. remote_hop.py / remote_relay.py /
# remote_exec.py are untouched by this extraction and still read plain
# VCUSER/VCPW/VCHOST/VCHOP/VCPORT/VCWORKDIR/VCEDAENV/DVWORKDIR env vars
# exactly as before.
#
# RUN THIS FROM YOUR OWN INTERACTIVE TERMINAL -- see remote_relay.py's own
# module docstring for why an AI agent must never invoke this script's
# underlying `remote_relay.py --start` directly with a composed VCPW.

if ([string]::IsNullOrWhiteSpace($env:VCPW)) {
    Write-Error "[replay] VCPW not configured (CREDENTIAL_NOT_CONFIGURED). Fail closed: not starting relay. Set `$env:VCPW before sourcing replay.ps1."
    return
}

$resolverOutput = & python "$PSScriptRoot\tools\remote\resolve_execution_profile.py" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "[replay] $resolverOutput"
    return
}

foreach ($line in ($resolverOutput -split "`n")) {
    $line = $line.Trim()
    if ($line -eq "") { continue }
    $parts = $line -split "=", 2
    if ($parts.Count -eq 2) {
        Set-Item -Path "env:$($parts[0])" -Value $parts[1]
    }
}

if ([string]::IsNullOrWhiteSpace($env:VCWORKDIR)) {
    Write-Error "[replay] VCWORKDIR not configured. Fail closed: not starting relay. Set `$env:VCWORKDIR before sourcing replay.ps1."
    return
}
if ([string]::IsNullOrWhiteSpace($env:VCEDAENV)) {
    Write-Error "[replay] VCEDAENV not configured. Fail closed: not starting relay. Set `$env:VCEDAENV before sourcing replay.ps1 (or add eda_environment to your execution profile)."
    return
}

$env:DV_HARNESS_RELAY_AUTORECONNECT_OK='1'
python "$PSScriptRoot\tools\remote\remote_relay.py" --start
