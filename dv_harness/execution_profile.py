"""Execution-profile resolution for the remote EDA transport launcher (replay.ps1).

M1 minimal configuration extraction (Final Canonical Platform Architecture
Freeze -- host identity belongs in execution configuration, never encoded
into the generic L5 core). ``replay.ps1`` used to hardcode one specific
user's own real gateway host, remote-EDA hop host and remote workdir
directly in canonical runtime script text (see the M1 migration provenance
record for the exact former literal values and their source) -- a
location/user-portability violation: another user copying this repository
to a different company/server set would have had to edit canonical script
text, not just supply their own configuration. This module gives
``replay.ps1`` one place to resolve those values from a JSON
execution-profile file instead.

Deliberately narrow, per the governing instruction
(``PRESERVE_CAPABILITY_WITH_MINIMAL_CONFIGURATION_EXTRACTION``): this is
NOT the ``ExecutionService`` / ``RemoteEDABackend`` / ``TelnetSSHTransport``
abstraction described in that same architecture freeze -- that remains a
future Platform-migration wave (``EXECUTION_SERVICE_OPERATIONALIZED = NO``,
``REMOTE_EDA_BACKEND_OPERATIONALIZED = NO``, intentionally, for M1). This
module only answers "which profile file, and what does it say" and never
touches the transport implementation itself -- ``remote_hop.py`` /
``remote_relay.py`` / ``remote_exec.py`` are untouched and keep reading
plain environment variables exactly as they did before this extraction.

Credentials are never part of a profile. ``VCPW`` stays environment
variable-only, supplied by the caller at the moment of connection, exactly
as before -- see ``FORBIDDEN_PROFILE_FIELDS`` below, which makes a
credential-shaped key in a profile file a hard load-time rejection rather
than a silently-ignored field a reviewer could miss.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Union


class ExecutionProfileRequiredError(RuntimeError):
    """Raised when no usable execution profile can be resolved, or the
    resolved one fails validation.

    ``.condition`` is always the literal string ``'EXECUTION_PROFILE_REQUIRED'``
    -- a stable, machine-readable code (matching this project's existing
    convention of a named ``.condition`` attribute, e.g.
    ``l5dgva_repo.WrongL5RepositoryError``) -- so a caller (or replay.ps1's
    own error path) can branch on it without parsing prose. Resolution
    failure never falls back to any literal default host value.
    """

    condition = "EXECUTION_PROFILE_REQUIRED"


REQUIRED_PROFILE_FIELDS = ("gateway_host", "remote_host")
OPTIONAL_PROFILE_FIELDS = ("remote_workdir", "eda_environment", "transport", "user")
# A profile containing any of these keys (case-insensitive) is rejected
# outright, never silently accepted-and-ignored -- credentials must stay
# environment-variable-only (VCPW).
FORBIDDEN_PROFILE_FIELDS = ("password", "vcpw", "secret", "token", "credential")

ENV_VAR_PROFILE_PATH = "L5DGVA_EXECUTION_PROFILE"
DEFAULT_TRANSPORT = "telnet_ssh"


def default_profile_path(repo_root: Union[str, Path]) -> Path:
    """The conventional, never-committed, per-checkout profile location.

    Relative to the discovered repository root, not any absolute machine
    path -- consistent with dv_harness.l5dgva_repo's location-independence
    policy. ``.dv-harness/`` is already this project's own per-checkout,
    gitignored state directory, so a real profile placed here never
    reaches canonical git history by accident.
    """
    return Path(repo_root) / ".dv-harness" / "execution_profile.json"


def resolve_profile_path(repo_root: Union[str, Path], env: Optional[dict] = None) -> Path:
    """Which profile file to load: an explicit env override first, else the default per-checkout path."""
    env = os.environ if env is None else env
    override = env.get(ENV_VAR_PROFILE_PATH)
    if override:
        return Path(override)
    return default_profile_path(repo_root)


def load_execution_profile(repo_root: Union[str, Path], env: Optional[dict] = None) -> dict:
    """Load, validate and return one execution profile as a plain dict.

    Always raises :class:`ExecutionProfileRequiredError` (never a bare
    ``FileNotFoundError``/``KeyError``/``json.JSONDecodeError``) on any
    resolution failure -- missing file, unparseable JSON, a missing
    required field, or a forbidden credential-shaped field -- so a caller
    gets one clear, fail-closed, machine-readable outcome in every case.
    """
    path = resolve_profile_path(repo_root, env)
    if not path.is_file():
        raise ExecutionProfileRequiredError(
            "EXECUTION_PROFILE_REQUIRED: no execution profile found at %s "
            "(set %s to point at one, or create it -- see "
            "config/execution_profiles/example.profile.json for the schema). "
            "Canonical runtime never falls back to a built-in host default."
            % (path, ENV_VAR_PROFILE_PATH)
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ExecutionProfileRequiredError(
            "EXECUTION_PROFILE_REQUIRED: execution profile at %s could not be read/parsed (%s)."
            % (path, exc)
        ) from exc

    if not isinstance(data, dict):
        raise ExecutionProfileRequiredError(
            "EXECUTION_PROFILE_REQUIRED: execution profile at %s must be a JSON object." % path
        )

    lowered_keys = {str(k).lower() for k in data}
    forbidden_found = lowered_keys & set(FORBIDDEN_PROFILE_FIELDS)
    if forbidden_found:
        raise ExecutionProfileRequiredError(
            "EXECUTION_PROFILE_REQUIRED: execution profile at %s contains forbidden "
            "credential-shaped field(s) %s -- credentials must stay environment-variable-only "
            "(e.g. VCPW), never written to a profile file." % (path, sorted(forbidden_found))
        )

    missing = [f for f in REQUIRED_PROFILE_FIELDS if not data.get(f)]
    if missing:
        raise ExecutionProfileRequiredError(
            "EXECUTION_PROFILE_REQUIRED: execution profile at %s is missing required field(s) %s."
            % (path, missing)
        )

    data.setdefault("transport", DEFAULT_TRANSPORT)
    data["_profile_path"] = str(path)
    return data


def profile_to_env_overrides(profile: dict) -> dict:
    """Map a validated profile dict onto the plain env-var names the
    existing, unmodified remote_hop.py / remote_relay.py already read.

    Never includes ``VCPW`` -- that stays whatever the caller's own
    environment already provides (or its own fail-closed check fires,
    unchanged from before this extraction). Never includes ``VCWORKDIR``
    either: that env var was already externalized (fail-closed if unset)
    before this extraction and is deliberately left as-is, since only
    ``DVWORKDIR`` was the literal hardcoded value being removed here.
    """
    overrides = {
        "VCHOST": profile["gateway_host"],
        "VCHOP": profile["remote_host"],
    }
    if profile.get("remote_workdir"):
        overrides["DVWORKDIR"] = profile["remote_workdir"]
    if profile.get("eda_environment"):
        eda = profile["eda_environment"]
        overrides["VCEDAENV"] = ",".join(eda) if isinstance(eda, list) else str(eda)
    if profile.get("user"):
        overrides["VCUSER"] = profile["user"]
    return overrides
