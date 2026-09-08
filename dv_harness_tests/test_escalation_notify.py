"""Tests for dv_harness/escalation_notify.py -- the escalation-ONLY notifier
(2026-09-03 task). Every test uses an injected FakeTransport that records
calls; the two exceptions (test_apprise_transport_with_no_urls_is_a_safe_noop
and test_apprise_transport_is_used_when_enabled_with_real_urls) exercise the
REAL apprise.Apprise() object -- but only ever with zero, or invalid/
non-existent, target URLs, never a live endpoint (no real ntfy/apprise
credentials exist in this session, per this module's own docstring).
"""
from __future__ import annotations

from dv_harness import preflight as pf
from dv_harness import escalation_notify as esc


class FakeTransport:
    def __init__(self):
        self.calls = []

    def send(self, title, body, tags=None):
        self.calls.append({"title": title, "body": body, "tags": tags})
        return True


class RaisingTransport:
    def send(self, title, body, tags=None):
        raise RuntimeError("network exploded")


# --- config -----------------------------------------------------------


class TestConfigFromDict:
    def test_defaults(self):
        cfg = esc.config_from_dict()
        assert cfg.enabled is False
        assert cfg.apprise_urls == []
        assert cfg.uvm_fatal_burst_threshold == 3

    def test_overrides_win_and_unknown_keys_ignored(self):
        cfg = esc.config_from_dict(
            {"enabled": True, "apprise_urls": ["ntfy://x"], "unknown_future_key": 123},
            uvm_fatal_burst_threshold=5)
        assert cfg.enabled is True
        assert cfg.apprise_urls == ["ntfy://x"]
        assert cfg.uvm_fatal_burst_threshold == 5


# --- default transport selection ---------------------------------------


class TestDefaultTransportSelection:
    def test_disabled_by_default_uses_null_transport(self):
        notifier = esc.EscalationNotifier()
        assert isinstance(notifier.transport, esc.NullTransport)

    def test_enabled_but_no_urls_still_uses_null_transport(self):
        cfg = esc.EscalationConfig(enabled=True, apprise_urls=[])
        notifier = esc.EscalationNotifier(cfg)
        assert isinstance(notifier.transport, esc.NullTransport)

    def test_enabled_with_urls_uses_apprise_transport(self):
        cfg = esc.EscalationConfig(enabled=True, apprise_urls=["ntfy://topic@ntfy.sh"])
        notifier = esc.EscalationNotifier(cfg)
        assert isinstance(notifier.transport, esc.AppriseTransport)

    def test_explicit_transport_always_wins(self):
        fake = FakeTransport()
        cfg = esc.EscalationConfig(enabled=True, apprise_urls=["ntfy://topic@ntfy.sh"])
        notifier = esc.EscalationNotifier(cfg, transport=fake)
        assert notifier.transport is fake


# --- never fires on PASS / non-matching conditions ----------------------


class TestNeverFiresOnRoutinePass:
    def test_license_starvation_does_not_fire_on_pass(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(transport=fake)
        outcome = pf.CheckOutcome(name="eda_license", status="PASS", detail="all good")
        ev = notifier.license_starvation(outcome)
        assert ev.fired is False
        assert fake.calls == []

    def test_license_starvation_does_not_fire_on_non_starvation_failure(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(transport=fake)
        outcome = pf.CheckOutcome(name="eda_license", status="FAIL",
                                   detail="license server 2900@host-a not reported UP")
        ev = notifier.license_starvation(outcome)
        assert ev.fired is False
        assert fake.calls == []

    def test_license_starvation_does_not_fire_on_wrong_check_name(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(transport=fake)
        outcome = pf.CheckOutcome(name="lsf_queue_health", status="FAIL",
                                   detail="license feature(s) fully checked out (starvation): x")
        ev = notifier.license_starvation(outcome)
        assert ev.fired is False
        assert fake.calls == []

    def test_uvm_fatal_burst_does_not_fire_below_threshold(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(esc.EscalationConfig(uvm_fatal_burst_threshold=3),
                                           transport=fake)
        ev = notifier.uvm_fatal_burst(2, total_jobs=10)
        assert ev.fired is False
        assert fake.calls == []

    def test_no_notify_pass_style_method_exists(self):
        """Structural check -- there must be no notify_pass()/notify_ok()
        escape hatch anywhere on the notifier."""
        public_methods = {m for m in dir(esc.EscalationNotifier) if not m.startswith("_")}
        assert not any("pass" in m.lower() or m.lower() in ("ok", "notify_ok") for m in public_methods)


# --- real, exact firing conditions ---------------------------------------


class TestLicenseStarvationFires:
    def test_fires_on_real_starvation_wording_from_preflight_check_license(self):
        """Uses the EXACT CheckOutcome shape
        dv_harness.preflight.check_license() really produces on starvation
        (same field names, same message wording -- see preflight.py's
        check_license())."""
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(transport=fake)
        outcome = pf.CheckOutcome(
            name="eda_license", status="FAIL",
            detail="license feature(s) fully checked out (starvation): ['VCSRuntime']",
            command="lmutil lmstat -a -c 2900@host-a", evidence="...")
        ev = notifier.license_starvation(outcome)
        assert ev.fired is True
        assert ev.delivered is True
        assert len(fake.calls) == 1
        assert "starvation" in fake.calls[0]["body"].lower()
        assert "lmutil lmstat" in fake.calls[0]["body"]
        assert fake.calls[0]["tags"] == ["license_starvation"]


class TestUvmFatalBurstFires:
    def test_fires_at_exactly_threshold(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(esc.EscalationConfig(uvm_fatal_burst_threshold=3),
                                           transport=fake)
        ev = notifier.uvm_fatal_burst(3, total_jobs=20, job_ids=[101, 102, 103])
        assert ev.fired is True
        assert "3" in ev.body
        assert "101" in ev.body and "102" in ev.body and "103" in ev.body

    def test_fires_above_threshold(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(esc.EscalationConfig(uvm_fatal_burst_threshold=3),
                                           transport=fake)
        ev = notifier.uvm_fatal_burst(9, total_jobs=20)
        assert ev.fired is True


class TestJobSubmissionFailureAlwaysFires:
    def test_fires(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(transport=fake)
        ev = notifier.job_submission_failure(command="vcs -R sim1", queue="vcs",
                                              reason="bsub not found on PATH")
        assert ev.fired is True
        assert "vcs -R sim1" in ev.body
        assert "bsub not found" in ev.body


class TestQuestionQueueDigestFiresOnlyWithBlockingQuestions:
    def test_does_not_fire_when_digest_did_not_emit(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(transport=fake)
        ev = notifier.question_queue_digest({"emitted": False, "batch_id": None, "questions": []})
        assert ev.fired is False
        assert fake.calls == []

    def test_does_not_fire_when_batch_is_all_assumed_none_blocking(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(transport=fake)
        digest = {"emitted": True, "batch_id": "DIGEST-1",
                   "questions": [{"id": "Q1", "blocking": False}]}
        ev = notifier.question_queue_digest(digest)
        assert ev.fired is False

    def test_fires_when_batch_has_a_real_blocking_question(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(transport=fake)
        digest = {"emitted": True, "batch_id": "DIGEST-2",
                   "questions": [{"id": "Q1", "blocking": False}, {"id": "Q2", "blocking": True}]}
        ev = notifier.question_queue_digest(digest)
        assert ev.fired is True
        assert "DIGEST-2" in ev.body
        assert "1 blocking / 2 total" in ev.body


class TestSignoffBlockedAlwaysFires:
    def test_fires(self):
        fake = FakeTransport()
        notifier = esc.EscalationNotifier(transport=fake)
        ev = notifier.signoff_blocked(stage="SIGNOFF", reasons=["vplan_completeness_gate"])
        assert ev.fired is True
        assert "vplan_completeness_gate" in ev.body


# --- transport failure never propagates ----------------------------------


class TestTransportFailureIsContained:
    def test_raising_transport_never_escapes(self):
        notifier = esc.EscalationNotifier(transport=RaisingTransport())
        ev = notifier.job_submission_failure(command="x", queue="vcs", reason="y")
        assert ev.fired is True
        assert ev.delivered is False
        assert "network exploded" in ev.reason


# --- real apprise object, zero/fake targets only (no live endpoint) ------


class TestAppriseTransportReal:
    def test_no_urls_is_a_safe_noop(self):
        transport = esc.AppriseTransport([])
        assert transport.send("t", "b") is False

    def test_notifier_from_config_wires_real_apprise_object_when_enabled(self):
        notifier = esc.notifier_from_config({"enabled": True, "apprise_urls": ["ntfy://topic@ntfy.sh"]})
        assert isinstance(notifier.transport, esc.AppriseTransport)
        assert notifier.transport.urls == ["ntfy://topic@ntfy.sh"]

    def test_notifier_from_config_disabled_never_builds_apprise_transport(self):
        notifier = esc.notifier_from_config({"enabled": False, "apprise_urls": ["ntfy://topic@ntfy.sh"]})
        assert isinstance(notifier.transport, esc.NullTransport)
