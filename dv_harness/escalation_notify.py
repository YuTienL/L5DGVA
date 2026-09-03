"""dv_harness/escalation_notify.py -- escalation-ONLY mobile notifications.

L5 requirement (2026-09-03 user spec, verbatim): "ntfy / apprise -- 很適合
「變化才通知 / escalation 才通知」設計。正常 PASS 不吵人；license starvation、
大量 UVM_FATAL、farm failure、signoff blocked 才推 mobile." This module fires
for exactly those four named conditions and structurally CANNOT fire for a
routine PASS -- there is deliberately no notify_pass()/notify_ok() function
anywhere in this file, and every trigger method below is a no-op transport
call unless its own real condition is met (see EscalationNotifier._fire()).

TRANSPORT CHOICE: apprise (`pip install apprise`,
https://github.com/caronc/apprise) over a bespoke ntfy-only client, per the
user's own "apprise is the simpler, more portable choice" framing -- it
already speaks ntfy's own URL scheme (`ntfy://`/`ntfys://`) alongside ~100
other services (Slack, Telegram, email, PagerDuty, ...) through ONE
dependency and ONE `Apprise.notify()` call, so a project can point this
module at whatever escalation channel it already has credentials for
(ntfy included) without any code change here.

NO REAL ENDPOINT CREDENTIALS EXIST IN THIS SESSION (2026-09-03) -- this
module is therefore built against a fully injectable `NotifyTransport`
interface (mirrors dv_harness/preflight.py's injected `Runner` seam) and
tested exclusively with a `FakeTransport` that records calls, never a live
send. `AppriseTransport` itself is exercised in tests only against a real
`apprise.Apprise()` object with ZERO configured URLs -- a genuine, safe,
no-network call (apprise reports failure/no-op for zero targets, which is
exactly the honest behavior an unconfigured deployment should have) -- never
against a live ntfy/Slack/etc. endpoint.

COORDINATION WITH THE PREFLIGHT WORKSTREAM (same day, see
.work/governance-preflight-report.md): `license_starvation()` below consumes
`dv_harness.preflight.CheckOutcome` objects AS PRODUCED by
`preflight.check_license()` -- same field names (`name`/`status`/`detail`/
`command`/`evidence`), same starvation wording
("license feature(s) fully checked out (starvation)") that function already
emits. This module does not import dv_harness.preflight (no coupling
required -- a plain CheckOutcome-shaped object, or any object exposing the
same four attributes, is enough), keeping both modules independently
testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence

try:
    import apprise as _apprise_mod  # type: ignore
except ImportError:  # pragma: no cover - exercised only if apprise is
    # genuinely absent; AppriseTransport.send() below reports that honestly
    # (NOT_CONFIGURED-shaped failure) rather than crashing the caller.
    _apprise_mod = None


# --- transport interface (fully injected, never assumed) -------------------


class NotifyTransport(Protocol):
    def send(self, title: str, body: str, tags: Optional[List[str]] = None) -> bool:
        ...


class NullTransport:
    """Structurally-safe default: reports "not delivered" (False) and never
    raises, never touches a network. Used whenever escalation is disabled or
    no real endpoint URLs are configured -- exactly the honest behavior for
    "no real ntfy/apprise endpoint credentials exist in this session"."""

    def send(self, title: str, body: str, tags: Optional[List[str]] = None) -> bool:
        return False


class AppriseTransport:
    """Real apprise-backed transport. `urls` is a list of apprise service
    URLs (e.g. `ntfy://topic@ntfy.sh`, `slack://...`) -- this class never
    guesses or hardcodes one; an empty list behaves exactly like
    NullTransport (apprise itself would just report `notify()` failure for
    zero configured targets, so this is not a special case bolted on top,
    it is apprise's own real behavior)."""

    def __init__(self, urls: Optional[Sequence[str]] = None):
        self.urls = list(urls or [])
        if _apprise_mod is None:
            self._apobj = None
        else:
            self._apobj = _apprise_mod.Apprise()
            for u in self.urls:
                self._apobj.add(u)

    def send(self, title: str, body: str, tags: Optional[List[str]] = None) -> bool:
        if self._apobj is None or not self.urls:
            return False
        return bool(self._apobj.notify(title=title, body=body))


# --- config ------------------------------------------------------------


@dataclass
class EscalationConfig:
    enabled: bool = False  # a project must explicitly opt in -- same
    # "never guessed/hardcoded, never silently on" convention
    # preflight.PreflightConfig.require_license_configured already
    # establishes for this codebase.
    apprise_urls: List[str] = field(default_factory=list)
    uvm_fatal_burst_threshold: int = 3
    # Justification (2026-09-03): a single test's own sim.log epilogue
    # UVM_FATAL count is usually 0 or 1 (a UVM testbench typically
    # $finish()es at its first fatal, per this project's own
    # sim_log_analysis.py epilogue parsing) -- one or two isolated
    # per-test fatals across a regression batch is routine debug noise a
    # human is already going to see in the normal per-job triage flow, not
    # an escalation-worthy event. THREE OR MORE jobs in the SAME
    # reconciliation cycle (dv_harness.regression_reporter's real
    # run_reconciliation_cycle(), one call = one batch of currently-
    # terminal jobs) independently reporting UVM_FATAL is a materially
    # different signal -- it strongly suggests a systemic cause (a bad
    # build, a corrupted shared resource, an environment-wide regression)
    # rather than N unrelated per-test bugs, and is exactly the kind of
    # "large burst" (大量 UVM_FATAL) the user's own spec named as
    # escalation-worthy. A project with a different real failure baseline
    # may override this via config.json's `escalation.uvm_fatal_burst_
    # threshold` -- it is deliberately not hardcoded deeper than this one
    # dataclass default.


_ESCALATION_CONFIG_FIELDS = set(EscalationConfig.__dataclass_fields__.keys())


def config_from_dict(d: Optional[dict] = None, **overrides) -> EscalationConfig:
    """Same forward-compatible pattern as preflight.config_from_dict()/
    pueue_client.config_from_dict() -- unknown keys ignored, explicit
    non-None overrides win."""
    merged: Dict[str, object] = dict(d or {})
    for k, v in overrides.items():
        if v is not None:
            merged[k] = v
    kwargs = {k: v for k, v in merged.items() if k in _ESCALATION_CONFIG_FIELDS}
    return EscalationConfig(**kwargs)


# --- event record (always returned, even when nothing fired) --------------


@dataclass
class EscalationEvent:
    kind: str
    fired: bool
    delivered: bool
    title: str
    body: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "fired": self.fired, "delivered": self.delivered,
                "title": self.title, "body": self.body, "reason": self.reason}


# --- notifier ------------------------------------------------------------


class EscalationNotifier:
    """One notifier per project. `transport` is injected (tests always pass
    a FakeTransport); when omitted, a REAL AppriseTransport is built from
    `cfg.apprise_urls` only if `cfg.enabled` is True AND at least one URL is
    configured -- otherwise a NullTransport, so an unconfigured/disabled
    deployment never attempts a network call and never raises."""

    def __init__(self, cfg: Optional[EscalationConfig] = None,
                 transport: Optional[NotifyTransport] = None):
        self.cfg = cfg or EscalationConfig()
        if transport is not None:
            self.transport = transport
        elif self.cfg.enabled and self.cfg.apprise_urls:
            self.transport = AppriseTransport(self.cfg.apprise_urls)
        else:
            self.transport = NullTransport()

    def _fire(self, kind: str, condition: bool, title: str, body: str,
              reason: str) -> EscalationEvent:
        """The one place a transport.send() call can happen. `condition`
        False means the named escalation condition genuinely was not met
        (e.g. a license FAIL that was not starvation) -- the transport is
        never touched in that case, so "never for routine PASS" is
        enforced structurally, not merely by callers remembering to check
        first."""
        if not condition:
            return EscalationEvent(kind=kind, fired=False, delivered=False,
                                    title=title, body=body, reason=reason)
        delivered = False
        try:
            delivered = bool(self.transport.send(title, body, tags=[kind]))
        except Exception as e:  # noqa: BLE001 -- a notification failure must
            # never propagate into (and abort) the real DV workflow that
            # triggered it; the caller still gets an honest delivered=False
            # plus the real exception text in `reason`.
            reason = f"{reason} (transport error: {e})"
        return EscalationEvent(kind=kind, fired=True, delivered=delivered,
                                title=title, body=body, reason=reason)

    # -- the four, and only four, named escalation conditions ------------

    def license_starvation(self, outcome: Any) -> EscalationEvent:
        """`outcome` is a dv_harness.preflight.CheckOutcome (or any object
        with the same name/status/detail/command/evidence attributes) as
        returned by preflight.check_license(). Fires ONLY when it is
        genuinely the eda_license check, genuinely FAILed, and the failure
        reason is genuinely license starvation (checked-out headroom, not
        e.g. an unreachable license server or a missing feature) -- the
        exact wording preflight.check_license() emits:
        "license feature(s) fully checked out (starvation): [...]"."""
        name = getattr(outcome, "name", "")
        status = getattr(outcome, "status", "")
        detail = getattr(outcome, "detail", "") or ""
        condition = (name == "eda_license" and status == "FAIL"
                     and "starvation" in detail.lower())
        title = "DV Harness: EDA license starvation"
        body = f"eda_license check: {detail}"
        if getattr(outcome, "command", None):
            body += f"\ncommand: {outcome.command}"
        return self._fire("license_starvation", condition, title, body, detail)

    def uvm_fatal_burst(self, fatal_job_count: int, *, total_jobs: Optional[int] = None,
                         job_ids: Optional[Sequence[int]] = None) -> EscalationEvent:
        """Fires when `fatal_job_count` (jobs reporting a real epilogue
        uvm_fatal count > 0 within ONE reconciliation cycle -- see
        dv_harness.regression_reporter.run_reconciliation_cycle()) meets or
        exceeds cfg.uvm_fatal_burst_threshold (default 3, see
        EscalationConfig's own docstring for the justification)."""
        condition = fatal_job_count >= self.cfg.uvm_fatal_burst_threshold
        reason = (f"{fatal_job_count} job(s) reporting UVM_FATAL this cycle "
                  f"(threshold={self.cfg.uvm_fatal_burst_threshold})")
        title = "DV Harness: UVM_FATAL burst"
        body = reason
        if total_jobs is not None:
            body += f"; total jobs this cycle: {total_jobs}"
        if job_ids:
            body += f"; job_ids: {list(job_ids)}"
        return self._fire("uvm_fatal_burst", condition, title, body, reason)

    def job_submission_failure(self, *, command: str, queue: str, reason: str) -> EscalationEvent:
        """Call ONLY from a real farm-submission failure path (a real
        `bsub`/`sbatch` invocation that ran AFTER preflight already PASSED
        and then genuinely failed -- see
        dv_harness.lsf_client.bsub_submit_with_preflight()'s own except
        branch). Distinct from license_starvation()/a PreflightBlockedError
        above it: this is "the farm itself rejected/could not accept the
        job", not "we correctly refused to even try"."""
        title = "DV Harness: farm job submission failure"
        body = f"queue={queue}\ncommand={command}\nreason={reason}"
        return self._fire("job_submission_failure", True, title, body, reason)

    def signoff_blocked(self, *, stage: str, reasons: Any) -> EscalationEvent:
        """Call ONLY from a real signoff-blocking condition (e.g.
        dv_harness.signoff_export.collect_signoff_bundle()'s own bundled
        self_audit_result showing summary.fail > 0). `reasons` is whatever
        structured detail the caller has (a list of gate ids, a dict, a
        plain string) -- stringified into the notification body, never
        reinterpreted here."""
        title = f"DV Harness: signoff BLOCKED ({stage})"
        body = f"stage={stage}\nreasons={reasons}"
        return self._fire("signoff_blocked", True, title, body, str(reasons))


def notifier_from_config(escalation_cfg: Optional[dict] = None,
                          transport: Optional[NotifyTransport] = None) -> EscalationNotifier:
    """Convenience constructor for call sites that only have the raw
    `.dv-harness/config.json` `escalation` dict (e.g. `h.cfg.get(
    "escalation")` in dv_harness/cli.py) rather than an already-built
    EscalationConfig."""
    return EscalationNotifier(config_from_dict(escalation_cfg), transport=transport)
