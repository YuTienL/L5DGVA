"""dv_harness/question_queue.py -- the 3-tier ask-a-human protocol + question
queue mechanics (spec Part B: self-resolve / safe-to-assume / cannot-assume).

Scope note (this module implements Part B only): Part A's env.manifest.json
(VIP/DUT/env fact layers + a read-only MCP server) is a SEPARATE workstream,
and as of 2026-09-04 it EXISTS -- `dv_harness/env_manifest.py` writes the
3-layer manifest and `dv_harness/mcp/` serves its 5 read-only verbs. This
module's Tier-1 self-resolve path is written against a `manifest_lookup`
callable a caller may inject (`lambda path: mcp_client.get(...)`), defaulting
to "nothing resolvable" when omitted -- never a stub that pretends to read a
manifest that isn't there. Disclosed residual: no PRODUCTION caller injects
that callable yet (only `dv_harness_tests/test_question_queue.py` does), so
Tier-1 manifest resolution is available but not in use on the real path.
What Part A does NOT need to exist for is this
module's other guarantee: a question, once answered by a human, is never
asked again. That guarantee is met by this module's OWN persisted decisions
store (`.dv-harness/question_queue/decisions.json` + a generated
`decisions.md`), a DEDICATED store rather than a record folded into
env.manifest.json, for two concrete reasons: (1) env.manifest.json is
Part A's generated, diffable FACT file (VIP-config-dump / DUT-port-export /
topology-print provenance) -- a human's free-text answer + basis + owner is
a different kind of record (a DECISION, not a re-derivable fact) and mixing
the two would make env.manifest.json's own diff noisy with content no
regeneration run would ever reproduce; (2) this module must work standalone
today, before Part A lands, without inventing a fake env.manifest.json
shape to write into. When Part A lands, its MCP `get_*` verbs can and
should consult this same decisions store as one more fact source (see
`find_decision()`) -- no format change needed on this side.

Blackboard mirror (2026-09-04): keeping decisions OUT of env.manifest.json
(above) is not a reason to keep them out of the BLACKBOARD, and a
2026-09-04 audit found this module had no blackboard path at all. A
decision, once made, IS current-run truth -- exactly what CLAUDE.md says
the Blackboard holds -- and without a mirror a later stage had no way to
see "this was already asked and answered / already auto-assumed" short of
knowing to open this module's own private store. `QuestionQueueStore` now
refreshes the `open_questions_decisions` topic from `_save_decisions()` --
the single choke point every decision write and every revocation already
passes through, so the topic cannot drift from decisions.json the way a
second hand-called write could. The mirror is ON by default: an injectable
`blackboard` argument exists (for tests, and for handing in an already-open
board such as `DVHarness.blackboard`), but omitting it resolves to a real
Blackboard at this store's own project root, never to "no mirror" -- every
construction site gets it without having to remember to ask.

Four pieces, matching Part B 1:1:
  - classify_tier() / is_cannot_assume(): the 3-tier decision logic. The
    Tier-3 trigger is a hard-coded, explicit predicate -- never a vague
    heuristic -- per the spec's own "hard-coded trigger, not a judgment
    call" instruction, and it is evaluated FIRST, ahead of both Tier-1
    shortcuts (see classify_tier()'s docstring for why neither shortcut may
    be allowed to run before it).
  - route_owner(): the literal VIP->DV-owner/Synopsys-AE / DUT->designer /
    env->DV-owner routing table.
  - QuestionQueueStore: persists questions (schemas/question.schema.json)
    and decisions (decisions.json + decisions.md), and is the ONLY place a
    repeat ask can resolve at Tier 1 instead of re-escalating.
  - build_digest() / compute_metrics(): daily/end-of-run batching (never a
    real-time ping -- see build_digest()'s own docstring for the three
    trigger windows) and the 4 tracking metrics from Part B.

Exemptions read path (2026-09-04) -- not a fifth Part-B piece, an
integration this module hosts. find_exemption() consults the project's real
exemptions.yaml on every add_question() carrying a context `check_id` (an
ACTIVE entry self-resolves the ask at Tier 1); escalate_expired_exemptions()
turns a lapsed exemption into a real Tier-3 blocking question. It lives here
because dv_harness/exemptions.py's own docstring named this module as the
consumer its review-queue output was shaped for, and until 2026-09-04 no
consumer existed: that store was write-plus-manual-CLI-read only, so "an
agent never re-litigates a deliberately-disabled check" was a guarantee
nothing enforced on any automatic path. See classify_tier()'s step 3 for
why an exemption deliberately does NOT override a Tier-3 hard trigger.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import exemptions as _exemptions

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "question.schema.json"
SCHEMA_VERSION = "1.0"

# ---- Tiers ------------------------------------------------------------------
#
# An ESCALATION ROUTE per question ("can this be self-resolved / safely
# assumed / must a human decide it"), NOT a confidence score, and deliberately
# not expressed through dv_harness.inference.score_confidence() (2026-09-04).
# Tier 3 does not mean "low confidence" -- classify_tier() reaches it from a
# hard trigger about BLAST RADIUS and authority (pass/fail verdict, spec
# intent, read-only file change), which no amount of corroborating evidence
# may downgrade. score_confidence() has no term that can express that, so
# routing this decision through it would silently make a well-evidenced
# spec-intent question auto-assumable. See inference.py's module docstring and
# dv_harness_tests/test_confidence_vocabulary_separation.py.

TIER1_SELF_RESOLVE = 1
TIER2_SAFE_ASSUME = 2
TIER3_CANNOT_ASSUME = 3

TIER_NAMES = {
    TIER1_SELF_RESOLVE: "SELF_RESOLVE",
    TIER2_SAFE_ASSUME: "SAFE_TO_ASSUME",
    TIER3_CANNOT_ASSUME: "CANNOT_ASSUME",
}

# ---- Owner routing (literal, testable table -- Part B) -----------------------

DOMAIN_OWNER_ROUTING = {
    "vip": "DV-owner/Synopsys-AE",
    "dut": "designer",
    "env": "DV-owner",
}


def route_owner(domain: str) -> str:
    """Literal domain -> owner routing rule from Part B. Raises ValueError
    for anything outside the 3 known domains -- an unrouted question must
    never silently default to some owner, it must fail loudly at add_question
    time."""
    d = (domain or "").strip().lower()
    if d not in DOMAIN_OWNER_ROUTING:
        raise ValueError(f"Unknown question domain {domain!r}; must be one of {sorted(DOMAIN_OWNER_ROUTING)}")
    return DOMAIN_OWNER_ROUTING[d]


# ---- Tier classification -----------------------------------------------------

class QuestionValidationError(ValueError):
    """A question dict fails schema validation, or a structural rule the
    schema itself cannot express (e.g. recommendation must be one of
    options[].label). Raised rather than returning False -- a caller must
    never persist/ask an invalid question."""


class DoNotAskError(QuestionValidationError):
    """Raised by `add_question(enforce_do_not_ask=True)` when the SAME
    question_key already has a live, REAL decision on file that makes a
    fresh ask of it redundant -- see `find_redundant_decision()` for exactly
    which decisions qualify and why a Tier-3 hard trigger over a Tier-2
    guess deliberately does NOT. Carries the redundant decision itself so a
    caller can report which one made the new question unnecessary, rather
    than merely knowing something did."""

    def __init__(self, question_key: str, decision: Dict[str, Any]):
        current = decision.get("current") or {}
        self.question_key = question_key
        self.decision = decision
        super().__init__(
            "question_key %r already has a live decision on file (source=%r, answer=%r, "
            "decided_by=%r, decided_at=%r) that already answers it -- refusing to file a "
            "duplicate question. Read the cited decision (or call revoke_decision() first "
            "if it is genuinely wrong) rather than re-asking."
            % (question_key, current.get("source"), current.get("answer"),
               current.get("decided_by"), current.get("decided_at"))
        )


class CosignNotApplicableError(QuestionValidationError):
    """Raised by `QuestionQueueStore.add_decision_cosign()` when the live
    decision for a question_key is not eligible for a second-human
    co-sign: either no live decision is on file at all, or its
    `current.source` is not HUMAN_DECISION_SOURCE.

    This is the load-bearing refusal for the whole co-sign feature: a
    Tier-2 auto-assumption is a machine guess, never a human decision
    (see `_is_human_decision()`), and letting it be co-signed would let a
    SECOND signature dress a machine guess up as human-trusted -- exactly
    the kind of weakening of the existing Tier-3 human-decision-sourcing
    rule this feature must never permit. Carries the live decision (or
    None) so a caller can report exactly why the co-sign was refused."""

    def __init__(self, question_key: str, decision: Optional[Dict[str, Any]]):
        self.question_key = question_key
        self.decision = decision
        if decision is None:
            reason = "no live decision is on file for this question_key"
        else:
            reason = ("current.source is %r, not %r -- only a real recorded human "
                       "answer may be co-signed, never a tier2_auto_assumption or "
                       "any other machine-sourced decision"
                       % ((decision.get("current") or {}).get("source"), HUMAN_DECISION_SOURCE))
        super().__init__("cannot co-sign question_key %r: %s" % (question_key, reason))


def is_cannot_assume(context: Dict[str, Any]) -> bool:
    """The Part-B Tier-3 predicate, HARD-CODED per spec ("a hard-coded
    trigger, not a judgment call"): true iff `context` claims the question
    affects a pass/fail verdict, spec intent, or whether a read-only file
    should change. Any one of the three is sufficient; there is no scoring,
    no threshold, no weighting -- this is a pure boolean OR over 3 literal
    flags the caller must set honestly. The boolean form of hard_triggers();
    the two share one definition so they can never drift apart."""
    return bool(hard_triggers(context))


_SAFE_BLAST_RADII = frozenset({"single_regression"})

# The only decision `source` that may shortcut a question to Tier 1. A
# decision the harness minted for ITSELF (source="tier2_auto_assumption",
# written by add_question's Tier-2 log-and-continue path) is a machine guess,
# not an answer -- treating it as one lets the harness answer its own
# escalation with its own earlier guess. See classify_tier().
HUMAN_DECISION_SOURCE = "human_answer"

#: The literal `current.source` value `_persist_decision`/`add_question` write
#: for a Tier-2 log-and-continue default (see add_question's Tier-2 branch,
#: which has used this exact string since before this constant existed --
#: named here, not re-typed, so `find_redundant_decision()` below shares one
#: spelling with the code that writes it). A REAL auto-resolution (the
#: harness actually reasoned about blast radius and decided this was safe to
#: assume), as distinct from a human answer -- see HUMAN_DECISION_SOURCE and
#: `find_redundant_decision()` for why the two are treated differently.
TIER2_AUTO_ASSUMPTION_SOURCE = "tier2_auto_assumption"

#: classify_tier()'s reason string when an ACTIVE exemptions.yaml entry
#: resolved the ask. Deliberately NOT "decisions_store_hit": a consumer
#: auditing why a question never reached a human must be able to tell an
#: exemption-backed self-resolve (expires on its own valid_until, lives in
#: exemptions.yaml, owned by the exemption's owner) apart from a persisted
#: human answer (never expires, lives in decisions.json).
EXEMPTION_TIER1_REASON = "active_exemption"

#: question_key prefix for the Tier-3 question escalate_expired_exemptions()
#: files when an exemption's valid_until has passed. Derived from the
#: exemption id alone so re-running the escalation over an unchanged
#: exemptions.yaml re-mints the SAME key (and therefore the same Q-ID) and
#: is skipped, rather than growing the queue by one entry per run -- the
#: same idempotence discipline source_authority.escalate_conflict() uses.
EXEMPTION_EXPIRY_KEY_PREFIX = "exemption-expiry"

#: Blackboard topic this module's decisions store mirrors itself into -- see
#: the module docstring's "Blackboard mirror" note and
#: QuestionQueueStore._sync_decisions_to_blackboard().
BLACKBOARD_TOPIC = "open_questions_decisions"


def _is_human_decision(prior_decision: Optional[Dict[str, Any]]) -> bool:
    """True only for a decisions-store entry whose CURRENT value came from a
    real human answer (QuestionQueueStore.answer_question). A
    "tier2_auto_assumption"-sourced entry -- including one whose history
    contains an older human answer that has since been superseded -- is not
    a human answer and must never shortcut a Tier-3 ask."""
    if not prior_decision:
        return False
    return (prior_decision.get("current") or {}).get("source") == HUMAN_DECISION_SOURCE


def find_redundant_decision(prior_decision: Optional[Dict[str, Any]],
                            context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The do-not-ask predicate: is `prior_decision` a REAL resolution
    (`find_decision()`'s live hit for this question_key) that makes a FRESH
    ask of it -- with this `context` -- genuinely redundant? Returns
    `prior_decision` itself when it is (never a bare True/False), so a
    caller can report exactly which decision applies; returns None when no
    real decision is on file, or when one exists but does not (yet) make
    this particular ask redundant.

    Two real sources qualify, and they are NOT treated alike -- deliberately
    mirroring classify_tier()'s own evaluation order rather than inventing a
    second one:
      - A HUMAN answer (`HUMAN_DECISION_SOURCE`) is ALWAYS redundant,
        regardless of this ask's own context. This is classify_tier()'s step
        2 restated as a filing-time refusal: "a human answer on file DOES
        still win over a hard trigger... safe precisely because a human,
        not the harness, supplied it."
      - A Tier-2 auto-assumption (`TIER2_AUTO_ASSUMPTION_SOURCE`) is
        redundant ONLY when this ask's own context trips NO Tier-3 hard
        trigger (`is_cannot_assume(context)` is False). A machine's own
        earlier guess must never suppress a later, genuinely Tier-3-
        triggering ask of the same question_key -- that is review defect
        F3-a, and treating a tier2 guess as blanket-redundant here would
        resurrect it under the do-not-ask feature's own name. A hard-
        trigger ask over a tier2 guess is a real escalation, not a repeat,
        and must still be filed.
      - Anything else (no decision, an unrecognized/legacy source with no
        `current.source` at all) is NOT redundant -- fail toward asking a
        human rather than silently swallowing a question on the strength of
        a record this function cannot positively identify as real."""
    if prior_decision is None:
        return None
    source = (prior_decision.get("current") or {}).get("source")
    if source == HUMAN_DECISION_SOURCE:
        return prior_decision
    if source == TIER2_AUTO_ASSUMPTION_SOURCE and not is_cannot_assume(context):
        return prior_decision
    return None


def hard_triggers(context: Dict[str, Any]) -> List[str]:
    """The names of the Tier-3 hard triggers `context` sets, in fixed order.
    is_cannot_assume() is the boolean form of exactly this list."""
    names = []
    if context.get("affects_pass_fail_verdict"):
        names.append("affects_pass_fail_verdict")
    if context.get("affects_spec_intent"):
        names.append("affects_spec_intent")
    if context.get("affects_read_only_file_change"):
        names.append("affects_read_only_file_change")
    return names


def classify_tier(context: Dict[str, Any], *, prior_decision: Optional[Dict[str, Any]] = None,
                    exemption: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Decide which of the 3 tiers applies to one question.

    `context` fields (all optional, default falsy/low-risk):
      - domain, affects_pass_fail_verdict, affects_spec_intent,
        affects_read_only_file_change: the Tier-3 hard-trigger inputs.
      - resolvable_from_manifest / manifest_value: set when a caller (Part A
        MCP client, once it exists) already looked the fact up.
      - blast_radius: "single_regression" (default) | "multi_regression" |
        "unbounded" -- Part B's own Tier-2 admission bar ("worst case = one
        wasted regression"): anything wider than a single regression is NOT
        low-blast-radius enough to safe-assume, so it escalates to Tier 3
        even without tripping one of the 3 named hard triggers directly.

    `prior_decision`: a decisions-store hit for this question's
    `question_key` (see QuestionQueueStore.find_decision), if any.

    `exemption`: the ACTIVE exemptions.yaml entry covering this question's
    `context["check_id"]`, if any (see QuestionQueueStore.find_exemption).
    An exemption is a human-authored, cited, owned, EXPIRING record that
    says "this check is deliberately off, and here is the document that
    says why" -- the exact knowledge dv_harness/exemptions.py was built to
    stop an agent re-litigating every run. Consulting it here is what makes
    that store READ on the real ask path instead of write-and-manual-CLI-
    read only. Its placement in the order below is deliberately NOT at the
    top; see step 3.

    EVALUATION ORDER (fixed, and the order itself is the security property --
    2026-09-03 review defects F3-a/F3-b, both proven reachable through
    shipped code before this was corrected):

      1. The hard-trigger check runs FIRST, ahead of BOTH Tier-1 shortcuts.
         Previously `resolvable_from_manifest` was consulted before the hard
         triggers, so a pure spec-intent question ("is this drop legal per
         spec, or a real DUT failure?") resolved at Tier 1 with whatever
         unrelated fact the manifest happened to hold at that context_path --
         the lookup is keyed on context_path alone and never checks that the
         fact it found actually answers the question asked (F3-b).
      2. A prior decision shortcuts to Tier 1 ONLY when it came from a real
         human (`current.source == "human_answer"`). A decision the harness
         wrote for itself as a Tier-2 auto-assumption must NOT suppress a
         later, genuinely Tier-3-triggering ask of the same question_key:
         previously it did, so asking a question once in a low-risk framing
         (Tier 2, auto-assumed, decision persisted) permanently disarmed
         every later ask of that key, no matter how many hard triggers it
         set -- answered silently with the harness's own earlier guess, never
         surfaced in a digest (build_digest only batches OPEN/ASSUMED, and
         this resolved as SELF_RESOLVED) and, before `revoke`, not
         reversible either (F3-a).
      3. An ACTIVE exemption covering context["check_id"] resolves the ask
         at Tier 1 -- but it is placed BELOW the hard triggers, not beside
         the human-answer shortcut in step 2, and the difference is not
         timidity. A decisions-store hit is keyed on `question_key`, a
         digest of the exact question text plus context_path, so it is a
         precise match: the human answered THIS question. An exemption is
         matched on `check_id` alone, which says only that the question is
         ABOUT that check -- it cannot establish that "this check is off
         because of an IP restriction" answers "should this failing
         assertion be treated as a real DUT bug". Letting a coarse key
         resolve a hard-trigger ask is precisely review defect F3-b, and it
         is not made safe by the record having a nicer provenance.

         What DOES happen when a hard trigger fires and an exemption is on
         file is step 1's `;covered_by_active_exemption:<id>` annotation:
         the escalation still goes to a human, but it goes carrying the
         exemption's identity, so the human is not re-deriving from scratch
         what an owner already decided and cited. add_question() attaches
         the full citation to the question record either way. That is the
         "never re-litigate" guarantee at Tier 3 -- carry the prior
         decision into the escalation -- as distinct from suppressing the
         escalation, which only a precise-key human answer may do.

         An EXPIRED exemption never reaches this function: find_exemption()
         returns only active entries, so a lapsed exemption stops
         suppressing anything the day it lapses, which is what valid_until
         is for.

      4. The manifest shortcut is additionally gated on
         is_cannot_assume(context) == False -- belt and braces on top of the
         ordering above: if the question's own context trips a hard trigger,
         no manifest lookup may resolve it regardless of what it returns.

    A human answer on file DOES still win over a hard trigger (step 2) --
    that is the intended "once a human answers, never ask again" guarantee,
    and it is safe precisely because a human, not the harness, supplied it.

    Returns {"tier": int, "reason": str, "matched_triggers": [str, ...]}.
    """
    triggers = hard_triggers(context)
    human_prior = _is_human_decision(prior_decision)

    # 1. Hard triggers first -- before every Tier-1 shortcut.
    if triggers:
        if human_prior:
            return {"tier": TIER1_SELF_RESOLVE, "reason": "decisions_store_hit", "matched_triggers": []}
        reason = "hard_trigger:" + ",".join(triggers)
        if prior_decision is not None:
            # Audit signal: this ask escalates for real DESPITE an existing
            # machine-authored decision on file for the same question_key.
            reason += ";overrides_prior_non_human_decision"
        if exemption is not None:
            # Cited, not honoured: the human answering this escalation gets
            # told which exemption already covers this check_id (step 3).
            reason += ";covered_by_active_exemption:%s" % (exemption.get("id"),)
        return {"tier": TIER3_CANNOT_ASSUME, "reason": reason, "matched_triggers": triggers}

    # 2. Prior-decision shortcut -- human answers only.
    if human_prior:
        return {"tier": TIER1_SELF_RESOLVE, "reason": "decisions_store_hit", "matched_triggers": []}

    # 3. Active-exemption shortcut -- ahead of the manifest because an
    #    exemption carries a named owner, a cited basis_document and an
    #    expiry, where a manifest lookup carries only a value found at a
    #    context_path; never for a cannot-assume question (see above).
    if exemption is not None and not is_cannot_assume(context):
        return {"tier": TIER1_SELF_RESOLVE, "reason": EXEMPTION_TIER1_REASON, "matched_triggers": []}

    # 4. Manifest shortcut -- never for a question whose own context is
    #    cannot-assume (unreachable given step 1, kept explicit so the
    #    guarantee survives any future reordering).
    if (not is_cannot_assume(context)
            and context.get("resolvable_from_manifest")
            and context.get("manifest_value") is not None):
        return {"tier": TIER1_SELF_RESOLVE, "reason": "resolvable_from_manifest", "matched_triggers": []}

    blast_radius = context.get("blast_radius", "single_regression")
    if blast_radius not in _SAFE_BLAST_RADII:
        return {"tier": TIER3_CANNOT_ASSUME, "reason": f"blast_radius_exceeds_safe_assume_bound:{blast_radius}",
                 "matched_triggers": ["blast_radius"]}

    return {"tier": TIER2_SAFE_ASSUME, "reason": "no_hard_trigger_low_blast_radius", "matched_triggers": []}


# ---- Schema validation (mirrors uvm_generator/run_profile.py's own pattern) --

def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_question(question: dict) -> None:
    """Validate `question` against schemas/question.schema.json, plus the one
    structural rule JSON Schema alone cannot express: `recommendation` must
    be one of `options[].label` (never a recommendation for an option that
    was never actually offered). Raises QuestionValidationError; returns
    None on success."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise QuestionValidationError(
            "jsonschema package is not installed; cannot validate a question. "
            "Install it rather than skipping validation."
        ) from exc

    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(question), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise QuestionValidationError("question failed schema validation:\n" + "\n".join(lines))

    labels = {opt.get("label") for opt in question.get("options", [])}
    if question.get("recommendation") not in labels:
        raise QuestionValidationError(
            f"recommendation {question.get('recommendation')!r} is not one of the offered "
            f"options[].label {sorted(labels)!r} -- a question must never recommend an option "
            f"it did not actually offer."
        )

    suggested = question.get("suggested_answer")
    if suggested is not None and suggested.get("value") != question.get("recommendation"):
        raise QuestionValidationError(
            f"suggested_answer['value'] {suggested.get('value')!r} must equal recommendation "
            f"{question.get('recommendation')!r} -- a suggested answer IS the recommendation, "
            f"carrying its own real evidence citation; a suggestion that disagreed with the "
            f"question's own recommendation would be two different answers pretending to be one."
        )


# ---- id / key helpers ---------------------------------------------------------

def make_question_key(domain: str, question: str, context_path: str) -> str:
    """Default stable dedup key when a caller does not supply one explicitly
    -- (domain, question text, context_path) identifies "the same question"
    well enough for the common case; a caller with a more precise natural
    key (e.g. a specific register/port/VIP-instance name) should pass
    `question_key=` explicitly to add_question() instead."""
    return f"{domain.strip().lower()}::{context_path.strip()}::{question.strip()}"


def make_question_id(domain: str, question_key: str) -> str:
    digest = hashlib.sha256(question_key.encode("utf-8")).hexdigest()[:8].upper()
    return f"Q-{domain.strip().upper()}-{digest}"


#: Keys an option element may carry -- mirrors question.schema.json's own
#: `options.items` (additionalProperties: false), checked here too so a bad key
#: is a QuestionValidationError naming the key rather than a schema traceback.
_OPTION_KEYS = frozenset({"label", "rationale"})


def normalize_options(options: Any) -> List[Dict[str, str]]:
    """Coerce an options list into the ONE canonical persisted shape --
    `[{"label": str, "rationale": str?}, ...]` -- accepting BOTH the plain
    `["option a", "option b"]` form and the object form.

    Why the string form is accepted at the door but NOT in the schema: a
    question record on disk has exactly one options shape, so every reader
    (validate_question()'s recommendation-in-labels cross-check,
    _render_decisions_md, build_digest) parses one thing rather than
    branching per element. Loosening question.schema.json to allow bare
    strings would put that branch into every reader forever, to buy nothing
    -- the string form is an ergonomic INPUT convenience, not a second
    storage format. So normalization happens once, here, and the persisted
    contract stays single-shaped.

    This is the single definition. Three call sites previously each carried
    their own `o if isinstance(o, dict) else {"label": str(o)}` copy
    (connectivity.build_t4_question_queue_entry,
    run_profile_to_justfile.ask_missing_option_question, cli.py's
    `question-queue add`) precisely because add_question() itself did not
    accept the plain form -- it indexed `o["label"]` directly and a
    string list died on a raw `TypeError: string indices must be integers`,
    which is not a validation error a caller can act on. Those copies also
    each passed a dict straight through unchecked, so a `{"lable": ...}`
    typo surfaced as a schema traceback from deep inside validation rather
    than at the caller's own boundary.

    Raises QuestionValidationError (never TypeError/KeyError) for anything
    that is not a string or a `label`-bearing dict."""
    if isinstance(options, (str, bytes)) or not isinstance(options, (list, tuple)):
        raise QuestionValidationError(
            f"options must be a list of strings or {{'label': ...}} dicts, got {type(options).__name__}"
        )
    normalized: List[Dict[str, str]] = []
    for i, opt in enumerate(options):
        if isinstance(opt, str):
            label, rationale = opt, None
        elif isinstance(opt, dict):
            unknown = sorted(set(opt) - _OPTION_KEYS)
            if unknown:
                raise QuestionValidationError(
                    f"options[{i}] has unknown key(s) {unknown!r}; only {sorted(_OPTION_KEYS)!r} are allowed."
                )
            label, rationale = opt.get("label"), opt.get("rationale")
            if not isinstance(label, str):
                raise QuestionValidationError(
                    f"options[{i}] is missing a string 'label' (got {label!r})."
                )
        else:
            raise QuestionValidationError(
                f"options[{i}] must be a string or a {{'label': ...}} dict, got {type(opt).__name__}"
            )
        if not label.strip():
            raise QuestionValidationError(f"options[{i}] has an empty label.")
        entry: Dict[str, str] = {"label": label}
        if rationale:
            entry["rationale"] = rationale
        normalized.append(entry)
    return normalized


#: Keys a `grounding_evidence` dict may carry -- mirrors question.schema.json's
#: own `grounding_evidence` shape (additionalProperties: false), checked here
#: too so a bad key is a QuestionValidationError naming the key rather than a
#: schema traceback.
_GROUNDING_EVIDENCE_KEYS = frozenset({"summary", "evidence_path"})


def normalize_grounding_evidence(grounding_evidence: Any) -> Optional[Dict[str, str]]:
    """The "why am I being asked this" field (spec: a question record must be
    able to carry WHY it is being asked -- e.g. "found register X in Excel
    but absent from RTL" -- distinct from `context_path`, which says WHERE in
    the evidence the question concerns, not why that location is in question
    at all). Additive and OPTIONAL: `None` (the default) means no caller
    supplied one, which is left as `None` on the record -- never fabricated
    from `question`/`context_path`/`tier_reason` text, per the Evidence Truth
    Rule ("absent evidence must produce an honest status, never silently
    defaulted").

    Accepts only a `{"summary": str, "evidence_path": str}` dict, both
    required together: a WHY with no citation of where that finding actually
    lives is exactly the kind of unsupported claim this field exists to
    prevent, so `summary` alone (a bare narrative) or `evidence_path` alone
    (a bare pointer with no stated reason) are both refused rather than
    silently accepted as partial grounding. Raises QuestionValidationError
    (never TypeError/KeyError, and never silently drops/guesses) on anything
    malformed -- the same discipline `normalize_options()` already applies to
    `options`."""
    if grounding_evidence is None:
        return None
    if not isinstance(grounding_evidence, dict):
        raise QuestionValidationError(
            f"grounding_evidence must be a {{'summary': str, 'evidence_path': str}} dict or None, "
            f"got {type(grounding_evidence).__name__}"
        )
    unknown = sorted(set(grounding_evidence) - _GROUNDING_EVIDENCE_KEYS)
    if unknown:
        raise QuestionValidationError(
            f"grounding_evidence has unknown key(s) {unknown!r}; only "
            f"{sorted(_GROUNDING_EVIDENCE_KEYS)!r} are allowed."
        )
    missing = sorted(_GROUNDING_EVIDENCE_KEYS - set(grounding_evidence))
    if missing:
        raise QuestionValidationError(
            f"grounding_evidence is missing required key(s) {missing!r} -- a WHY with no cited "
            "evidence_path (or a citation with no stated reason) is exactly the unsupported claim "
            "this field exists to prevent; supply both, or omit grounding_evidence entirely."
        )
    summary = grounding_evidence.get("summary")
    evidence_path = grounding_evidence.get("evidence_path")
    if not isinstance(summary, str) or not summary.strip():
        raise QuestionValidationError("grounding_evidence['summary'] must be a non-empty string.")
    if not isinstance(evidence_path, str) or not evidence_path.strip():
        raise QuestionValidationError("grounding_evidence['evidence_path'] must be a non-empty string.")
    return {"summary": summary, "evidence_path": evidence_path}


# ---- Suggest-then-confirm mode (2026-09-07, additive) -----------------------
#
# Every intake question was open-ended: a question carries pre-researched
# options and a recommendation (validate_question()'s own "recommendation
# must be one of options[].label" rule), but nothing ever populated that
# recommendation FROM real, already-computed evidence -- a human always had
# to author it from scratch, even when env_manifest.py or design_source_
# inventory.py already knows the answer. `suggested_answer` is the additive
# field that closes that gap: when a caller's real evidence already suggests
# a likely value, add_question(suggested_answer=...) files the question WITH
# that value as its recommendation, cited to exactly which real evidence
# producer it came from -- the human then confirms it (answer_question() with
# the same value) or corrects it (a different value), never authoring from a
# blank slate. This is additive to the schema (a new OPTIONAL property; no
# schema_version bump, since every pre-existing question record -- which
# simply omits the field -- still validates unchanged) and additive to
# add_question() (a new keyword-only parameter defaulting to `None`, so every
# existing caller's behavior is byte-for-byte unchanged).
#
# THE ONE HARD RULE THIS MODE ENFORCES: a suggestion must always cite its
# real evidence source, never be inferred from the question's own text. That
# is enforced twice: normalize_suggested_answer() below refuses to build one
# with no `source_module`/`source_path` (mirroring normalize_grounding_
# evidence()'s identical "an uncited claim is refused outright" discipline
# one field over), and validate_question() (see its own added check) refuses
# to persist a question whose suggested_answer.value disagrees with its own
# recommendation -- a suggestion IS the recommendation, carrying its own real
# citation, never a second, silently-different answer.

#: The only two real evidence producers this suggest-then-confirm mode
#: currently derives an answer FROM -- both real, structured modules whose
#: own output the two derive_suggested_answer_from_* functions below read
#: verbatim, never re-parsed or guessed at. An open-ended `source_module`
#: string would let a suggestion cite a source nobody could actually go
#: check; restricting it to these two named modules (per this task's own
#: naming of them) keeps every suggestion independently verifiable.
SUGGESTED_ANSWER_SOURCE_MODULES = frozenset({"env_manifest", "design_source_inventory"})

#: Keys a `suggested_answer` dict may carry -- mirrors question.schema.json's
#: own `suggested_answer` shape (additionalProperties: false), checked here
#: too so a bad key is a QuestionValidationError naming the key rather than a
#: schema traceback (same convention as _OPTION_KEYS/_GROUNDING_EVIDENCE_KEYS
#: above).
_SUGGESTED_ANSWER_KEYS = frozenset({"value", "source_module", "source_path", "rationale"})


def normalize_suggested_answer(suggested_answer: Any) -> Optional[Dict[str, str]]:
    """The suggest-then-confirm mode's own evidence-citation contract,
    mirroring normalize_grounding_evidence()'s discipline exactly: `None`
    (the default -- no caller supplied one) stays `None`, never fabricated
    from the question's own text or a guessed default. A real suggestion
    REQUIRES `value` (the suggested answer itself, which must also equal the
    question's own `recommendation` -- checked in validate_question(), since
    that is a cross-field rule JSON Schema alone cannot express), `source_
    module` (which real evidence producer it came from -- restricted to
    SUGGESTED_ANSWER_SOURCE_MODULES, never an open string a reader could not
    actually go check), and `source_path` (WHERE in that producer's own
    output the value was read, e.g. "env.manifest.json#vip_config.vip_
    release.version" or "design_source_inventory#usb3_regmap.version") -- a
    suggested value with no citation of where it came from is exactly the
    unsupported claim this field exists to prevent, the same reasoning
    normalize_grounding_evidence() already applies to its own `evidence_
    path`. `rationale` is optional, free text.

    Raises QuestionValidationError (never TypeError/KeyError, and never
    silently drops/guesses) on anything malformed."""
    if suggested_answer is None:
        return None
    if not isinstance(suggested_answer, dict):
        raise QuestionValidationError(
            f"suggested_answer must be a "
            f"{{'value': str, 'source_module': str, 'source_path': str, 'rationale': str?}} dict "
            f"or None, got {type(suggested_answer).__name__}"
        )
    unknown = sorted(set(suggested_answer) - _SUGGESTED_ANSWER_KEYS)
    if unknown:
        raise QuestionValidationError(
            f"suggested_answer has unknown key(s) {unknown!r}; only "
            f"{sorted(_SUGGESTED_ANSWER_KEYS)!r} are allowed."
        )
    missing = sorted({"value", "source_module", "source_path"} - set(suggested_answer))
    if missing:
        raise QuestionValidationError(
            f"suggested_answer is missing required key(s) {missing!r} -- a suggested value with no "
            "citation of its real evidence source is exactly the unsupported claim this field exists "
            "to prevent; supply all three, or omit suggested_answer entirely."
        )
    value = suggested_answer.get("value")
    source_module = suggested_answer.get("source_module")
    source_path = suggested_answer.get("source_path")
    if not isinstance(value, str) or not value.strip():
        raise QuestionValidationError("suggested_answer['value'] must be a non-empty string.")
    if source_module not in SUGGESTED_ANSWER_SOURCE_MODULES:
        raise QuestionValidationError(
            f"suggested_answer['source_module'] must be one of "
            f"{sorted(SUGGESTED_ANSWER_SOURCE_MODULES)!r} -- the only real evidence producers this "
            f"suggest-then-confirm mode currently derives an answer from -- got {source_module!r}."
        )
    if not isinstance(source_path, str) or not source_path.strip():
        raise QuestionValidationError("suggested_answer['source_path'] must be a non-empty string.")
    result: Dict[str, str] = {"value": value, "source_module": source_module, "source_path": source_path}
    rationale = suggested_answer.get("rationale")
    if rationale:
        if not isinstance(rationale, str):
            raise QuestionValidationError("suggested_answer['rationale'] must be a string when present.")
        result["rationale"] = rationale
    return result


#: env_manifest.py's own real per-layer `status` literals (grepped from that
#: module's real source, not guessed) split into "real evidence is present at
#: this node" vs. "this layer honestly reports absence" -- see derive_
#: suggested_answer_from_env_manifest()'s own walk below. An unrecognized
#: status (neither set) is treated the SAME as absent: this function only
#: ever suggests a value when it can positively confirm the evidence is
#: really there, never on the strength of a status literal it does not
#: recognize.
_ENV_MANIFEST_PRESENT_STATUSES = frozenset({
    "PARSED", "LOADED", "CAPTURED", "SCANNED", "INDEXED", "DECLARED", "RESOLVED",
})
_ENV_MANIFEST_ABSENT_STATUSES = frozenset({"NOT_AVAILABLE", "NOT_DECLARED"})


def derive_suggested_answer_from_env_manifest(manifest: Dict[str, Any], path: Sequence[Any], *,
                                                rationale: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Derive a suggest-then-confirm candidate from a real, already-loaded
    env.manifest.json document -- `env_manifest.load_env_manifest(path)`'s
    own return value, handed in by the caller. This function never reads a
    file itself and never re-derives a fact env_manifest.py already computed
    -- REUSE OVER REINVENT: that module is the sole writer/reader of
    env.manifest.json, and this function only walks its already-produced
    dict.

    `path` walks from the manifest root down to the fact to suggest (dict
    keys and/or list indices), e.g. `["vip_config", "vip_release", "version"]`
    or `["dut_facts", "registers", "blocks", 0, "name"]`.

    Returns `None` -- never a guessed value -- whenever: the path's own most
    SPECIFIC fact-layer node (see below) reports a status that is not a real
    evidence-PRESENT one (see `_ENV_MANIFEST_PRESENT_STATUSES`/
    `_ENV_MANIFEST_ABSENT_STATUSES` above -- env_manifest.py's own NOT_
    AVAILABLE/NOT_DECLARED layers report their absence honestly and must
    never be silently read as available); the path does not resolve (a
    missing key, an out-of-range index, or a `path` that walks into a
    non-container); or the resolved value is empty/None. A resolved scalar
    is used verbatim; a resolved list/dict is JSON-encoded (sorted keys,
    deterministic) so it can be carried as one string value.

    WHY "most specific" rather than "every ancestor": some env.manifest.json
    layers are COMPOSITES whose own top-level `status` describes only ONE of
    several sub-facts merged into the same dict -- concretely,
    `vip_config`'s own `status` describes its zero-time VIP-instance config
    dump only (build_vip_config()'s own field), yet `vip_config.vip_release`
    and `vip_config.user_guide_refs` are separate sub-layers merged into that
    SAME dict by build_vip_config_layer(), each carrying its OWN, genuinely
    independent `status`. Gating every ancestor's status blindly would make
    `vip_config.vip_release` (a real SCANNED $DESIGNWARE_HOME result) read
    as unavailable merely because no VIP config DUMP happens to exist yet --
    two unrelated facts, wrongly conflated. So a node's own `status` is only
    consulted when the CHILD being descended into does not itself carry a
    more specific `status` of its own; when it does, checking is deferred to
    that child on the next step, which is the correct, most-specific source
    of truth for everything beneath it.
    """
    if not isinstance(manifest, dict):
        return None
    current: Any = manifest
    for segment in path:
        if isinstance(current, dict):
            if segment not in current:
                return None
            child = current[segment]
            child_has_own_status = isinstance(child, dict) and "status" in child
            if not child_has_own_status:
                status = current.get("status")
                if status is not None and status not in _ENV_MANIFEST_PRESENT_STATUSES:
                    return None
            current = child
        elif isinstance(current, list):
            if not isinstance(segment, int) or isinstance(segment, bool) or not (0 <= segment < len(current)):
                return None
            current = current[segment]
        else:
            return None
    if isinstance(current, dict):
        status = current.get("status")
        if status is not None and status not in _ENV_MANIFEST_PRESENT_STATUSES:
            return None
    if current is None:
        return None
    if isinstance(current, str) and not current.strip():
        return None
    if isinstance(current, (list, dict)) and len(current) == 0:
        return None
    if isinstance(current, str):
        value_str = current
    else:
        import json as _json
        value_str = _json.dumps(current, sort_keys=True, default=str)
    payload: Dict[str, Any] = {
        "value": value_str,
        "source_module": "env_manifest",
        "source_path": "env.manifest.json#" + ".".join(str(p) for p in path),
    }
    if rationale:
        payload["rationale"] = rationale
    return normalize_suggested_answer(payload)


def derive_suggested_answer_from_design_source_inventory(rows: Optional[Sequence[dict]], source_id: str,
                                                            *, field: str = "version",
                                                            rationale: Optional[str] = None
                                                            ) -> Optional[Dict[str, str]]:
    """Derive a suggest-then-confirm candidate from a real, already-computed
    design-source registry -- `design_source_inventory.build_source_
    registry()`'s (or a single `evaluate_source()`'s) own row list, handed in
    by the caller. Never re-derives freshness/authority/anything else that
    module already computed; it only reads one already-evaluated row's own
    `field`.

    Suggests a value ONLY when the matching row's own `status` is that
    module's real `STATUS_CURRENT` -- a STALE/SUPERSEDED/NOT_AVAILABLE/
    UNKNOWN source is never suggested as an answer, since design_source_
    inventory.py's own module docstring is explicit that a source whose
    content has moved since it was last checked (or that has been
    deliberately retired) must not be trusted as if it still described
    reality; a fact this function cannot positively confirm is CURRENT is
    exactly the honest-absence case suggest-then-confirm must not paper over
    with a stale guess.

    Returns `None` when: `rows` is empty/None; no row matches `source_id`;
    the matching row's status is not CURRENT; or `field` is missing/empty on
    that row."""
    if not rows:
        return None
    row = None
    for r in rows:
        if isinstance(r, dict) and r.get("source_id") == source_id:
            row = r
            break
    if row is None:
        return None
    from . import design_source_inventory as _design_source_inventory
    if row.get("status") != _design_source_inventory.STATUS_CURRENT:
        return None
    value = row.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    payload: Dict[str, Any] = {
        "value": str(value),
        "source_module": "design_source_inventory",
        "source_path": f"design_source_inventory#{source_id}.{field}",
    }
    if rationale:
        payload["rationale"] = rationale
    return normalize_suggested_answer(payload)


def build_suggest_then_confirm_options(suggested_answer: Dict[str, str], *,
                                         alternative_labels: Optional[Sequence[str]] = None
                                         ) -> Dict[str, Any]:
    """Convenience for the suggest-then-confirm mode's own caller contract:
    given an already-derived `suggested_answer` (from derive_suggested_
    answer_from_env_manifest()/derive_suggested_answer_from_design_source_
    inventory(), or any dict normalize_suggested_answer() accepts), builds
    the matching `options`/`recommendation` add_question() needs -- the
    suggested value as one option (its own `rationale` citing the real
    `source_module`/`source_path`), plus 0-2 real caller-declared
    alternatives (never invented here), with `recommendation` set to the
    suggested value so validate_question()'s cross-check passes by
    construction. Returns `{"options": [...], "recommendation": str,
    "suggested_answer": dict}` -- spread the first two into add_question()
    and pass the third through as its own `suggested_answer=` argument.

    Raises QuestionValidationError if `suggested_answer` does not normalize,
    if `alternative_labels` would push the total past question.schema.json's
    own 2-3 option cap, or if an alternative repeats the suggested value
    itself (a real alternative must be a genuinely different candidate)."""
    suggested_answer = normalize_suggested_answer(suggested_answer)
    if suggested_answer is None:
        raise QuestionValidationError(
            "build_suggest_then_confirm_options() requires a real suggested_answer -- "
            "see normalize_suggested_answer()."
        )
    value = suggested_answer["value"]
    rationale = f"Suggested from {suggested_answer['source_module']}: {suggested_answer['source_path']}"
    if suggested_answer.get("rationale"):
        rationale += f" -- {suggested_answer['rationale']}"
    options: List[Dict[str, str]] = [{"label": value, "rationale": rationale}]
    for alt in (alternative_labels or []):
        alt = str(alt)
        if alt == value:
            raise QuestionValidationError(
                f"alternative_labels repeats the suggested value {value!r} -- an alternative must be "
                f"a genuinely different candidate."
            )
        options.append({"label": alt})
    if not (2 <= len(options) <= 3):
        raise QuestionValidationError(
            f"build_suggest_then_confirm_options() would produce {len(options)} option(s); "
            f"question.schema.json requires 2-3 -- supply exactly 1-2 alternative_labels."
        )
    return {"options": options, "recommendation": value, "suggested_answer": suggested_answer}


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---- Atomic JSON read/write (same convention as storage._atomic_replace) -----

def _atomic_write_json(path: Path, data: Any) -> None:
    from .storage import _atomic_replace
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


# ---- Digest batching boundaries ----------------------------------------------

# Natural regression-cycle boundary stages this harness already tracks
# (dv_harness.models.Stage) -- reused rather than inventing a new timer.
# These are the points at which "a batch of questions accumulated during
# this cycle" is genuinely ready to be reported, matching Part B's "daily/
# end-of-run digest, never real-time pings": end of a regression run
# (REGRESSION_MONITOR), end of coverage closure, end of a failure-recovery
# re-audit cycle, and end of the whole run (SIGNOFF).
DIGEST_BOUNDARY_STAGES = frozenset({"REGRESSION_MONITOR", "COVERAGE_CLOSURE", "RE_AUDIT", "SIGNOFF"})


class QuestionQueueStore:
    """Filesystem-backed store for questions + decisions, rooted at
    `<project_root>/.dv-harness/question_queue/`. Mirrors this codebase's
    established per-project `.dv-harness/**` layout (storage.py's
    StateStore, memory.py's MemoryStore, evidence_db's default_db_path, all
    root the same way) rather than inventing a new location convention."""

    def __init__(self, root: Path, *, manifest_lookup: Optional[Callable[[str], Any]] = None,
                   blackboard: Optional[Any] = None, exemptions_path: Optional[Path] = None):
        self.root = Path(root)
        self.dir = self.root / ".dv-harness" / "question_queue"
        self.questions_path = self.dir / "questions.json"
        self.decisions_path = self.dir / "decisions.json"
        self.decisions_md_path = self.dir / "decisions.md"
        # Sibling audit file for request_clarification() (see that function's
        # own module-level comment) -- a real, separate persistence target,
        # never a field smuggled onto question.schema.json's own strict
        # `additionalProperties: false` record.
        self.clarifications_path = self.dir / "clarifications.json"
        # Injected Part-A manifest/MCP reader for Tier-1 resolution -- see
        # this module's own docstring. None (the default) means "nothing is
        # resolvable from the manifest yet", never a fake always-empty stub
        # pretending to have consulted a real source.
        self.manifest_lookup = manifest_lookup
        # Blackboard for the decisions mirror (see the module docstring's
        # "Blackboard mirror" note). Deliberately DEFAULTED ON rather than
        # opt-in: this class is constructed all over the codebase (cli.py's
        # `question-queue`, connectivity.py's two T4 entry points,
        # coverage_analysis.py, source_authority.py, uvm_generator/
        # run_profile_to_justfile.py, and growing), and a mirror every one of
        # them has to remember to switch on is the same "built but never
        # wired" gap this mirror exists to close. Omitting it resolves to a
        # real Blackboard rooted at this store's own project root,
        # constructed lazily in _sync_decisions_to_blackboard() so merely
        # constructing a store creates no directories.
        self.blackboard = blackboard
        # The structured exemptions store this queue consults before asking
        # anyone anything -- see find_exemption(). Defaulted ON to the
        # project's real exemptions.yaml for the same reason the blackboard
        # mirror above is: dv_harness/exemptions.py's own docstring named
        # this module as the intended consumer of its review-queue output
        # and, until 2026-09-04, no consumer existed at all, so the store
        # was write-plus-manual-CLI-read only. An integration every
        # construction site has to remember to switch on would have
        # reproduced exactly that gap. A project with no exemptions.yaml on
        # disk costs nothing: load_exemptions_document() treats a missing
        # file as an empty, valid document.
        self.exemptions_path = (Path(exemptions_path) if exemptions_path is not None
                                 else _exemptions.default_exemptions_path(self.root))

    # -- exemptions -------------------------------------------------------

    def find_exemption(self, check_id: str, *, as_of: Optional[date] = None) -> Optional[dict]:
        """The ACTIVE exemption covering `check_id`, or None -- the real read
        of exemptions.yaml on the ask path.

        Never raises on a store problem. A missing file is already an empty
        document; a file that is present but schema-invalid or carries a
        hand-edited unparseable valid_until raises ExemptionValidationError
        inside exemptions.py, and that must NOT take down an unrelated
        question. Swallowing it here fails toward asking the human, which
        is the safe direction: the worst case is one question that could
        have been suppressed getting asked, never a suppression granted by
        a store nobody could read. `dv-harness exemptions check` is where a
        broken store is meant to be surfaced loudly."""
        if not check_id:
            return None
        try:
            return _exemptions.find_active_exemption(self.exemptions_path, str(check_id), as_of)
        except Exception:
            return None

    @staticmethod
    def _exemption_citation(entry: dict) -> dict:
        """The subset of an exemption a question record carries: enough for
        a reader to act on it (why, where that reasoning is grounded, who
        owns it, when it lapses) without opening exemptions.yaml, and
        nothing that would make the record a second copy of the store."""
        return {
            "id": entry.get("id"),
            "check_id": entry.get("check_id"),
            "reason": entry.get("reason"),
            "basis_document": entry.get("basis_document"),
            "owner": entry.get("owner"),
            "valid_until": entry.get("valid_until"),
        }

    # -- raw storage ------------------------------------------------------

    def _load_questions(self) -> dict:
        return _read_json(self.questions_path, {"schema_version": SCHEMA_VERSION, "questions": []})

    def _save_questions(self, data: dict) -> None:
        _atomic_write_json(self.questions_path, data)

    def _load_decisions(self) -> dict:
        return _read_json(self.decisions_path, {"schema_version": SCHEMA_VERSION, "decisions": {}})

    def _save_decisions(self, data: dict) -> None:
        _atomic_write_json(self.decisions_path, data)
        self._render_decisions_md(data)
        self._sync_decisions_to_blackboard(data)

    def _sync_decisions_to_blackboard(self, data: dict) -> Optional[dict]:
        """Refresh the `open_questions_decisions` Blackboard topic from the
        decisions store that was just written.

        Called from `_save_decisions()` rather than from `_persist_decision`
        / `revoke_decision` individually, because that is the one write path
        both already go through -- a second call site is a second chance for
        the topic and decisions.json to disagree.

        Records the answer/basis/decided_by/decided_at/source of every LIVE
        decision (a revoked one is gone from `decisions`, exactly as
        `find_decision()` sees it, so a reading stage can never act on a
        decision a human has withdrawn) plus the revocation COUNT for
        auditability. `source` is kept per entry so a reader can tell a real
        human answer from a Tier-2 auto-assumption -- collapsing those two
        into an undifferentiated "decided" is precisely the conflation the
        3-tier protocol exists to prevent.

        Never raises: a blackboard write failure must not turn an
        already-written decisions.json into a failed `question-queue answer`
        (same best-effort discipline as env_manifest's evidence-store
        write)."""
        decisions = data.get("decisions") or {}
        entries = {}
        human_answered = 0
        for key, entry in sorted(decisions.items()):
            current = entry.get("current") or {}
            if current.get("source") == HUMAN_DECISION_SOURCE:
                human_answered += 1
            entries[key] = {
                "domain": entry.get("domain"),
                "owner": entry.get("owner"),
                "question": entry.get("question"),
                "answer": current.get("answer"),
                "basis": current.get("basis"),
                "decided_by": current.get("decided_by"),
                "decided_at": current.get("decided_at"),
                "source": current.get("source"),
                "ever_tier2_assumed": bool(entry.get("ever_tier2_assumed")),
                "overturned": bool(entry.get("overturned")),
                # Additive (2026-09-07, second_human_review_cosign): whether
                # this LIVE decision carries a second-human co-sign that
                # still covers its current answer -- the same "recorded
                # cosigns_answer equals the live current answer text" test
                # is_decision_cosigned() applies, computed inline here from
                # `entry`/`current` already in hand rather than a second
                # disk re-read per key. Never affects `source`/trust above;
                # a reading stage that wants the stronger two-human
                # guarantee checks this flag itself, this method never
                # infers it into `source`.
                "cosigned": bool(current.get("source") == HUMAN_DECISION_SOURCE and any(
                    c.get("cosigns_answer") == current.get("answer")
                    for c in (entry.get("cosigns") or []))),
            }
        value = {
            "decisions_path": str(self.decisions_path),
            "decision_count": len(entries),
            "human_answered_count": human_answered,
            "tier2_assumed_count": len(entries) - human_answered,
            "revoked_count": len(data.get("revoked") or []),
            "decisions": entries,
        }
        try:
            blackboard = self.blackboard
            if blackboard is None:
                # Lazy, and inside the try: constructing a Blackboard mkdirs
                # its directory, which is exactly the kind of environment
                # failure that must not take a written decision down with it.
                from .blackboard import Blackboard
                blackboard = Blackboard(self.root)
            return blackboard.write(BLACKBOARD_TOPIC, value, source="question_queue")
        except Exception as e:
            print(f"[question-queue] blackboard decisions sync failed: {e}", flush=True)
            return None

    def ensure_blackboard_topic(self) -> dict:
        """Make the `open_questions_decisions` topic PRESENT on the automatic
        engine path, mirroring the decisions store already on disk
        (2026-09-04).

        `_save_decisions()` above refreshes the topic on every real write, so
        a store that has been written since that mechanism landed already has
        it. What this closes is the OTHER case, confirmed by a 2026-09-04
        audit: `engine.py` has zero references to this module, and answering
        a question is deliberately a human action ("由真人執行", prompts.py),
        so a fully autonomous `engine.loop()` reaching IMPLEMENT /
        FAILURE_RECOVERY / SIGNOFF -- all three declare this topic in
        `blackboard_read` -- against a store written before the sync existed,
        or never written at all, would read nothing at all where an EMPTY
        decision set is itself real, citable current truth ("no question has
        been answered yet"), quite different from "no record".

        Reuses `_sync_decisions_to_blackboard()`, the single sync point, and
        writes nothing to decisions.json -- this is a mirror of what is
        already there, never a decision. Only fills an ABSENT topic, for the
        same reason `env_manifest.ensure_blackboard_topic()` does: the real
        writer already keeps a present one current."""
        try:
            from .blackboard import Blackboard
            blackboard = self.blackboard or Blackboard(self.root)
            if blackboard.read(BLACKBOARD_TOPIC) is not None:
                return {"topic": BLACKBOARD_TOPIC, "action": "ALREADY_PRESENT"}
            self._sync_decisions_to_blackboard(self._load_decisions())
            present = blackboard.read(BLACKBOARD_TOPIC) is not None
            return {"topic": BLACKBOARD_TOPIC,
                    "action": "MIRRORED_FROM_STORE" if present else "SYNC_FAILED",
                    "decisions_path": str(self.decisions_path)}
        except Exception as exc:
            return {"topic": BLACKBOARD_TOPIC, "action": "SYNC_FAILED",
                    "error": f"{type(exc).__name__}: {exc}"}

    def _render_decisions_md(self, data: dict) -> None:
        """Regenerated in full from decisions.json on every write (same
        "generated, diffable" discipline as env.manifest.json itself) --
        never hand-appended, so it can never drift out of sync with the
        JSON store a repeat-question check actually reads."""
        lines = [
            "# Decisions Log",
            "",
            "Persisted answers to question-queue questions (dv_harness/question_queue.py, "
            "spec Part B). A question_key answered by a HUMAN and appearing here is resolved "
            "permanently: re-asking it self-resolves at Tier 1 instead of escalating again. A "
            "`tier2_auto_assumption` entry is only the harness's own provisional guess -- it is "
            "NOT an answer, and a later ask of the same question_key that trips a Tier-3 hard "
            "trigger still escalates for real. Regenerated in full from "
            "`.dv-harness/question_queue/decisions.json` on every write -- do not hand-edit; use "
            "`dv-harness question-queue revoke <question_key> --reason ...` to withdraw one.",
            "",
        ]
        decisions = data.get("decisions", {})
        for key in sorted(decisions.keys()):
            d = decisions[key]
            cur = d.get("current") or {}
            lines.append(f"## {key}")
            lines.append(f"- **Q-ID:** {cur.get('question_id_of_answer', '-')}")
            lines.append(f"- **Domain / Owner:** {d.get('domain', '-')} / {d.get('owner', '-')}")
            lines.append(f"- **Question:** {d.get('question', '-')}")
            lines.append(f"- **Answer:** {cur.get('answer', '-')}")
            lines.append(f"- **Basis:** {cur.get('basis', '-')}")
            lines.append(f"- **Decided by:** {cur.get('decided_by', '-')}")
            lines.append(f"- **Decided at:** {cur.get('decided_at', '-')}")
            lines.append(f"- **Source:** {cur.get('source', '-')}")
            lines.append(f"- **Ever a Tier-2 auto-assumption:** {'yes' if d.get('ever_tier2_assumed') else 'no'}")
            lines.append(f"- **Overturned a prior assumption:** {'yes' if d.get('overturned') else 'no'}")
            cosigns = d.get("cosigns") or []
            current_answer_text = cur.get("answer")
            live_cosigns = [c for c in cosigns if c.get("cosigns_answer") == current_answer_text]
            if live_cosigns:
                names = ", ".join(str(c.get("reviewer_id", "-")) for c in live_cosigns)
                lines.append(f"- **Second-human co-sign(s) of current answer:** {names}")
            elif cosigns:
                lines.append("- **Second-human co-sign(s):** none cover the CURRENT answer "
                              "(a prior answer was co-signed, then the decision was revoked/re-answered)")
            lines.append("")
        revoked = data.get("revoked", [])
        if revoked:
            lines.append("## Revoked decisions")
            lines.append("")
            lines.append("Withdrawn via `question-queue revoke`. No longer shortcuts anything; kept "
                          "so the record of what the harness once believed, and who withdrew it, survives.")
            lines.append("")
            for r in revoked:
                cur = (r.get("revoked_decision") or {}).get("current") or {}
                lines.append(f"- `{r.get('question_key')}` -- was {cur.get('answer', '-')!r} "
                              f"(source {cur.get('source', '-')}), revoked by {r.get('revoked_by', '-')} "
                              f"at {r.get('revoked_at', '-')}: {r.get('reason', '-')}")
            lines.append("")
        self.decisions_md_path.parent.mkdir(parents=True, exist_ok=True)
        self.decisions_md_path.write_text("\n".join(lines), encoding="utf-8")

    # -- decisions ----------------------------------------------------------

    def find_decision(self, question_key: str) -> Optional[dict]:
        """The live persisted decision for this exact question_key, or None
        (a revoked one is gone from here -- see revoke_decision). Returning
        an entry does NOT by itself mean the next ask self-resolves:
        classify_tier() runs its hard-trigger checks first and only honours
        a decision whose `current.source` is "human_answer"."""
        decisions = self._load_decisions().get("decisions", {})
        return decisions.get(question_key)

    def revoke_decision(self, question_key: str, *, reason: str,
                          revoked_by: Optional[str] = None, now: Optional[datetime] = None) -> dict:
        """Invalidate the persisted decision for `question_key` so the next
        ask re-classifies from scratch (a Tier-2 auto-assumption goes back to
        being re-assumed or, if that ask now trips a hard trigger, escalated
        for real; a human answer goes back to being asked).

        The sanctioned undo path. decisions.md tells its reader not to
        hand-edit the store, and before this verb existed a wrong Tier-2
        auto-assumption had no other remedy -- hand-editing decisions.json
        was the only way out, which is exactly what that file forbids.

        The revoked entry is MOVED to the store's `revoked` list rather than
        deleted, with who/when/why attached: `find_decision` stops seeing it
        (so it can no longer shortcut anything) while the audit trail of
        what the harness once believed, and who withdrew it, survives.
        Raises KeyError if no live decision exists for `question_key`."""
        data = self._load_decisions()
        decisions = data.setdefault("decisions", {})
        entry = decisions.pop(question_key, None)
        if entry is None:
            raise KeyError(f"No persisted decision for question_key {question_key!r}")
        revocation = {
            "question_key": question_key,
            "revoked_at": _now_iso(now),
            "revoked_by": revoked_by or "unknown",
            "reason": reason,
            "revoked_decision": entry,
        }
        data.setdefault("revoked", []).append(revocation)
        self._save_decisions(data)
        return revocation

    # -- second-human co-sign of a recorded Tier-3 decision ------------------
    #
    # Every decision path in this module trusts a SINGLE human's recorded
    # answer once `current.source == HUMAN_DECISION_SOURCE` -- by design,
    # per this module's own Tier-3 sourcing rule, and that rule is untouched
    # here. What follows is an ADDITIVE, opt-in verb: a second reviewer may
    # record that they independently reviewed and co-sign an already-
    # recorded human answer, for a downstream consumer that wants that
    # extra assurance before treating a particular Tier-3 answer as
    # trusted. A co-sign is never required to reach HUMAN_DECISION_SOURCE
    # trust (classify_tier(), find_redundant_decision(), _is_human_decision()
    # and every other reader of `current.source` are completely unaware
    # this section exists, and continue to treat a HUMAN_DECISION_SOURCE
    # decision as fully trusted with or without one), and a co-sign can
    # never itself promote a tier2_auto_assumption to human-sourced trust
    # (see CosignNotApplicableError) -- so the existing rule is neither
    # weakened nor bypassed, only optionally strengthened per-decision.
    #
    # Distinct from control_plane.ControlPlane.add_cosign(): that mechanism
    # co-signs a JUDGMENT_FIELDS wrapper value inside a stage's gate
    # evidence block (gates.py Tier-5); this one co-signs a question_queue
    # decisions.json record. Neither reads nor writes the other's store;
    # they share the word "cosign" and the general shape of the idea, and
    # nothing else.

    def add_decision_cosign(self, question_key: str, *, reviewer_id: str,
                              basis: Optional[str] = None, now: Optional[datetime] = None,
                              cosigned_by: Optional[str] = None) -> dict:
        """Record a SECOND human reviewer's co-sign of the live, already-
        recorded HUMAN_DECISION_SOURCE decision for `question_key`.

        Requires the live decision to already be human-sourced --
        `CosignNotApplicableError` when none exists, or when the live
        decision's `current.source` is anything else (most commonly
        `tier2_auto_assumption`): a co-sign of a machine guess would be
        exactly the sourcing-rule weakening this feature must refuse.

        `reviewer_id` must name a REAL, DIFFERENT person from the
        original `current.decided_by` -- a co-sign is a second,
        independent review, not the same person re-affirming their own
        answer; `ValueError` otherwise, and whenever `reviewer_id` itself
        is missing/blank.

        Keyed to the EXACT `current.answer` TEXT being co-signed at the
        moment of the call, mirroring `ControlPlane.add_cosign()`'s own
        exact-value discipline ("a value that later changes ... is NOT
        covered by a stale co-sign; a fresh one ... is required again")
        -- deliberately NOT keyed on `question_id_of_answer`, which
        `make_question_id()` derives from `question_key` alone and is
        therefore IDENTICAL across every answer ever given to the same
        question_key, including two different answer texts. `answer`
        text is what actually changes when a decision is revoked and
        re-answered, or when the same question_key is answered again
        with a genuinely different answer, so it is what
        `is_decision_cosigned()` checks to decide whether an earlier
        co-sign still covers the LIVE current answer. Never mutates
        `current` or `history` -- purely additive metadata appended to
        the entry's own `cosigns` list, so nothing that reads the
        decision's real answer/source/basis is affected by whether a
        co-sign exists."""
        if not reviewer_id or not str(reviewer_id).strip():
            raise ValueError("reviewer_id is required for a co-sign")
        live = self.find_decision(question_key)
        if live is None or not _is_human_decision(live):
            raise CosignNotApplicableError(question_key, live)
        current = live.get("current") or {}
        original_decider = current.get("decided_by")
        if original_decider and str(reviewer_id).strip() == str(original_decider).strip():
            raise ValueError(
                "reviewer_id %r is the same person who made the original decision "
                "(decided_by=%r) -- a co-sign requires a second, independent reviewer, "
                "not the original decider re-affirming their own answer"
                % (reviewer_id, original_decider))
        data = self._load_decisions()
        decisions = data.setdefault("decisions", {})
        entry = decisions.get(question_key)
        if entry is None or not _is_human_decision(entry):
            # Re-checked against the just-reloaded store rather than trusting
            # `live` above across the two loads (revoked/re-answered between
            # the read and here would otherwise let a stale co-sign through).
            raise CosignNotApplicableError(question_key, entry)
        current = entry.get("current") or {}
        cosign = {
            "reviewer_id": str(reviewer_id).strip(),
            "cosigned_at": _now_iso(now),
            "cosigned_by": cosigned_by or reviewer_id,
            "basis": basis,
            "cosigns_answer": current.get("answer"),
            "cosigns_question_id_of_answer": current.get("question_id_of_answer"),
            "cosigns_decided_by": current.get("decided_by"),
            "cosigns_decided_at": current.get("decided_at"),
        }
        entry.setdefault("cosigns", []).append(cosign)
        decisions[question_key] = entry
        self._save_decisions(data)
        return cosign

    def get_decision_cosigns(self, question_key: str) -> List[Dict[str, Any]]:
        """Every co-sign ever recorded for `question_key`'s decision, in
        the order recorded -- including one whose `cosigns_answer` no
        longer equals the live decision's current answer text (a stale
        co-sign, kept for the audit trail; see `is_decision_cosigned()`
        for the "does a LIVE co-sign exist" question). Empty list when
        the question_key has no live decision or none was ever
        co-signed."""
        live = self.find_decision(question_key)
        if live is None:
            return []
        return list(live.get("cosigns") or [])

    def is_decision_cosigned(self, question_key: str) -> bool:
        """True iff `question_key`'s LIVE decision is human-sourced AND
        carries at least one co-sign whose recorded `cosigns_answer`
        exactly equals the live decision's own current `answer` text --
        i.e. a co-sign that genuinely covers the answer as it stands
        right now, never a stale one left over from a since-changed
        answer (see `add_decision_cosign()`'s docstring for why this is
        keyed on the answer text rather than `question_id_of_answer`).

        This is the one place a downstream consumer wanting the stronger
        "two humans reviewed this" guarantee should check; the ordinary
        Tier-3 human-decision-sourcing rule (`_is_human_decision()`) is
        completely unaffected by this method's result either way."""
        live = self.find_decision(question_key)
        if live is None or not _is_human_decision(live):
            return False
        current_answer = (live.get("current") or {}).get("answer")
        return any(c.get("cosigns_answer") == current_answer
                    for c in (live.get("cosigns") or []))

    def _persist_decision(self, *, question_key: str, domain: str, owner: str, question: str,
                            answer: str, basis: str, decided_by: str, source: str,
                            question_id_of_answer: str, now: Optional[datetime] = None) -> dict:
        data = self._load_decisions()
        decisions = data.setdefault("decisions", {})
        entry = decisions.get(question_key)
        current = {
            "question_id_of_answer": question_id_of_answer,
            "answer": answer, "basis": basis, "decided_by": decided_by,
            "decided_at": _now_iso(now), "source": source,
        }
        overturned_this_time = False
        if entry is None:
            entry = {
                "question_key": question_key, "domain": domain, "owner": owner, "question": question,
                "current": current, "ever_tier2_assumed": source == "tier2_auto_assumption",
                "overturned": False, "history": [current],
            }
        else:
            prior_current = entry.get("current") or {}
            if prior_current.get("source") == "tier2_auto_assumption" and source == "human_answer":
                if str(prior_current.get("answer", "")).strip().lower() != str(answer).strip().lower():
                    overturned_this_time = True
            entry["current"] = current
            entry["domain"], entry["owner"], entry["question"] = domain, owner, question
            if source == "tier2_auto_assumption":
                entry["ever_tier2_assumed"] = True
            if overturned_this_time:
                entry["overturned"] = True
            entry.setdefault("history", []).append(current)
        decisions[question_key] = entry
        self._save_decisions(data)
        return entry if not overturned_this_time else {**entry, "_overturned_this_time": True}

    # -- questions ------------------------------------------------------------

    def add_question(self, *, domain: str, question: str, context_path: str,
                       options: Any, recommendation: str,
                       assumption_if_unanswered: str, question_key: Optional[str] = None,
                       context: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None,
                       enforce_do_not_ask: bool = False,
                       grounding_evidence: Optional[Dict[str, str]] = None,
                       suggested_answer: Optional[Dict[str, str]] = None,
                       authority_role: Optional[str] = None) -> dict:
        """Ask one question. NEVER pings/notifies -- it only persists the
        record (see build_digest() for the only aggregation/reporting path,
        per Part B: "never real-time pings"). Returns the full persisted
        question record, already tier-classified and, if a prior decision
        or Tier-2 default applied, already resolved.

        `options` accepts either the plain `["option a", "option b"]` form or
        the `[{"label": ..., "rationale": ...}]` form; both normalize through
        normalize_options() to the single persisted shape (see its docstring
        for why the string form is an input convenience and not a second
        storage format). A malformed element raises QuestionValidationError
        here, before anything is persisted.

        `enforce_do_not_ask` (default False, disclosed-default like this
        module's other opt-in strictness flags): when True, refuse to file a
        new record at all -- raising `DoNotAskError` rather than persisting
        anything -- when `find_redundant_decision()` finds a live decision
        for this exact `question_key` that already makes the ask redundant
        (see that function for exactly which decisions qualify, and why a
        Tier-2 auto-assumption does NOT suppress a genuinely Tier-3-
        triggering re-ask). Defaulting to False keeps every existing caller's
        behavior byte-identical: the ordinary path still files a fresh
        SELF_RESOLVED/ASSUMED/OPEN record every time (as `test_asking_the_
        same_question_twice_self_resolves_the_second_time` already proves),
        which is what `repeat_question_rate` and `build_digest()`'s batching
        are measured against. `enforce_do_not_ask=True` is for a caller that
        wants to stop growing questions.json with duplicates of an
        already-decided question altogether -- e.g. a repeatedly-re-run
        detector filing the SAME multi-option escalation every pass, the
        exact churn `build_multiple_choice_question()` is built to avoid.

        `grounding_evidence` (default None, disclosed-default like this
        module's other opt-in fields): an optional, additive
        `{"summary": str, "evidence_path": str}` dict answering "why is this
        question being asked" -- e.g. {"summary": "register X is present in
        the Excel register map but absent from the RTL port list",
        "evidence_path": "reg_map.xlsx#CTRL_REG / env.manifest.json#dut_facts.rtl"}
        -- distinct from `context_path` (WHERE the question concerns) and
        from `tier_reason` (WHICH classify_tier() rule fired). Only ever
        populated from what the caller actually passes here; see
        normalize_grounding_evidence()'s own docstring for why a partial
        dict (a summary with no citation, or vice versa) is refused rather
        than silently accepted.

        `suggested_answer` (default None, disclosed-default like this
        module's other opt-in fields): the suggest-then-confirm mode's own
        `{"value": str, "source_module": "env_manifest"|"design_source_
        inventory", "source_path": str, "rationale": str?}` dict -- see
        normalize_suggested_answer()'s own docstring, and derive_suggested_
        answer_from_env_manifest()/derive_suggested_answer_from_design_
        source_inventory() for how a caller derives one from real, already-
        computed evidence rather than authoring it by hand. When supplied,
        its `value` MUST equal `recommendation` (checked by validate_
        question() below, since a suggestion IS the recommendation, cited)
        -- the caller is expected to build `options`/`recommendation` around
        the suggested value (e.g. via build_suggest_then_confirm_options())
        rather than pass a `suggested_answer` that disagrees with them.

        `authority_role` (default None, disclosed-default like this module's
        other opt-in fields, added 2026-09-24 for CAP-M6-CLARSVC-001): one of
        "DESIGN"/"VERIFICATION"/"SHARED", per
        `dv_harness.clarification_service.classify_question_owner()` -- see
        `schemas/question.schema.json`'s own `authority_role` property for
        the full DE/DV Role-Based HITL rationale. HumanGate generalizes this
        module's own Tier-3 mechanism with this one new routing field rather
        than replacing it (HUMAN_GATE_CONTRACT.md)."""
        context = dict(context or {})
        options = normalize_options(options)
        grounding_evidence = normalize_grounding_evidence(grounding_evidence)
        suggested_answer = normalize_suggested_answer(suggested_answer)
        if authority_role is not None and authority_role not in ("DESIGN", "VERIFICATION", "SHARED"):
            raise QuestionValidationError(
                f"authority_role must be one of DESIGN/VERIFICATION/SHARED or None, got {authority_role!r}")
        question_key = question_key or make_question_key(domain, question, context_path)
        if enforce_do_not_ask:
            redundant = find_redundant_decision(self.find_decision(question_key), context)
            if redundant is not None:
                raise DoNotAskError(question_key, redundant)
        owner = route_owner(domain)
        qid = make_question_id(domain, question_key)

        # Part-A manifest/MCP consult, if a caller wired one in -- feeds
        # resolvable_from_manifest/manifest_value into classify_tier() the
        # same way an already-known context flag would.
        #
        # Skipped entirely when the question's own context trips a Tier-3
        # hard trigger (review defect F3-b): the lookup is keyed on
        # context_path alone and cannot tell whether the fact it returns
        # actually answers the question, so for a cannot-assume question it
        # must not even be CONSULTED, never mind allowed to resolve it. The
        # finish report's recommended next step -- wiring manifest_lookup
        # into every QuestionQueueStore caller -- is only safe with this
        # guard in place.
        if (self.manifest_lookup is not None
                and not is_cannot_assume(context)
                and not context.get("resolvable_from_manifest")):
            looked_up = self.manifest_lookup(context_path)
            if looked_up is not None:
                context["resolvable_from_manifest"] = True
                context["manifest_value"] = looked_up

        # Exemptions consult. A caller sets context["check_id"] to assert
        # "this question is about that exact check" -- the same honest-flag
        # discipline the 3 Tier-3 hard triggers already run on. No check_id,
        # no lookup: this must never guess which check a question concerns
        # from its free text. Always evaluated as of TODAY, with no as-of
        # override: "is this check exempt right now" is the only question
        # the ask path can be asking. find_exemption()'s own `as_of` exists
        # for tests and for reporting, not for backdating a live decision.
        exemption = self.find_exemption(context.get("check_id"))

        prior = self.find_decision(question_key)
        classification = classify_tier(context, prior_decision=prior, exemption=exemption)
        tier = classification["tier"]

        record: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "id": qid,
            "question_key": question_key,
            "blocking": tier == TIER3_CANNOT_ASSUME,
            "domain": domain.strip().lower(),
            "owner": owner,
            "question": question,
            "context_path": context_path,
            "options": options,
            "recommendation": recommendation,
            "assumption_if_unanswered": assumption_if_unanswered,
            "tier": tier,
            "tier_reason": classification["reason"],
            "status": "OPEN",
            "created_at": _now_iso(now),
            "answered_at": None, "answer": None, "basis": None, "decided_by": None,
            "overturned": False, "resolved_from_decision_id": None,
            "digest_batch_id": None, "digest_emitted_at": None,
            "grounding_evidence": grounding_evidence,
            "suggested_answer": suggested_answer,
            "authority_role": authority_role,
        }

        # Attached on EVERY tier when one exists, not only when it resolved
        # the ask: a Tier-3 escalation about an exempted check must reach
        # the human carrying the exemption an owner already cited, so
        # nobody re-derives it. See classify_tier()'s step 3.
        if exemption is not None:
            record["exemption"] = self._exemption_citation(exemption)

        if tier == TIER1_SELF_RESOLVE:
            # Which Tier-1 rule fired decides where the answer comes from --
            # never "prior is not None", which since the F3-a fix no longer
            # implies the prior decision is what resolved this ask (a
            # non-human prior can sit on file while the manifest resolves it).
            record["status"] = "SELF_RESOLVED"
            if classification["reason"] == "decisions_store_hit":
                cur = prior.get("current", {})
                record["answer"] = cur.get("answer")
                record["basis"] = cur.get("basis")
                record["decided_by"] = cur.get("decided_by")
                record["answered_at"] = cur.get("decided_at")
                record["resolved_from_decision_id"] = cur.get("question_id_of_answer")
            elif classification["reason"] == EXEMPTION_TIER1_REASON:
                record["answer"] = (
                    "Deliberately exempt (%s): %s"
                    % (exemption.get("id"), exemption.get("reason"))
                )
                record["basis"] = (
                    "exemption:%s basis_document=%s valid_until=%s"
                    % (exemption.get("id"), exemption.get("basis_document"),
                        exemption.get("valid_until"))
                )
                record["decided_by"] = str(exemption.get("owner"))
                record["answered_at"] = record["created_at"]
                # Deliberately NOT persisted into the decisions store. A
                # decision there is permanent until revoked; this exemption
                # expires on its own valid_until. Minting a decision from it
                # would outlive the exemption and go on suppressing this
                # question after the day the owner set for re-review --
                # converting the temporary workaround into the permanent,
                # never-revisited fact valid_until exists to prevent.
                # exemptions.yaml stays the single source for this answer.
            else:
                record["answer"] = str(context.get("manifest_value"))
                record["basis"] = f"resolved_from_manifest:{context_path}"
                record["decided_by"] = "env.manifest.json"
                record["answered_at"] = record["created_at"]
        elif tier == TIER2_SAFE_ASSUME:
            record["status"] = "ASSUMED"
            record["answer"] = assumption_if_unanswered
            record["basis"] = "tier2_safe_to_assume_default (worst case: one wasted, cheaply re-run regression)"
            record["decided_by"] = "dv_harness.question_queue(auto)"
            record["answered_at"] = record["created_at"]
            # Log-and-continue AND persist, with source="tier2_auto_assumption"
            # so it is permanently distinguishable from a human's answer.
            # That source is what stops this record from suppressing a later
            # Tier-3-triggering ask of the same question_key (classify_tier,
            # review defect F3-a); it also gives assumption_overturned_rate
            # something real to measure against once a human later answers,
            # and is what `revoke` withdraws if the guess turns out wrong.
            self._persist_decision(
                question_key=question_key, domain=record["domain"], owner=owner, question=question,
                answer=assumption_if_unanswered, basis=record["basis"], decided_by=record["decided_by"],
                source="tier2_auto_assumption", question_id_of_answer=qid, now=now,
            )
        # tier == TIER3_CANNOT_ASSUME: stays OPEN/blocking, no answer yet.

        validate_question(record)
        data = self._load_questions()
        data.setdefault("questions", []).append(record)
        self._save_questions(data)
        return record

    def get_question(self, question_id: str) -> Optional[dict]:
        for q in self._load_questions().get("questions", []):
            if q["id"] == question_id:
                return q
        return None

    def get_escalation_package(self, question_id: str) -> dict:
        """build_escalation_package() (see below) over a real persisted record,
        looked up by Q-ID through get_question() -- the store's own existing
        read path, never a second lookup mechanism. Raises KeyError (matching
        answer_question()'s own sibling raise) when no such question exists,
        rather than returning None and pushing the check onto every caller."""
        record = self.get_question(question_id)
        if record is None:
            raise KeyError(f"No question with id {question_id!r}")
        return build_escalation_package(record)

    def list_questions(self, *, status: Optional[str] = None, tier: Optional[int] = None,
                         blocking: Optional[bool] = None, domain: Optional[str] = None) -> List[dict]:
        qs = self._load_questions().get("questions", [])
        if status is not None:
            qs = [q for q in qs if q["status"] == status]
        if tier is not None:
            qs = [q for q in qs if q["tier"] == tier]
        if blocking is not None:
            qs = [q for q in qs if q["blocking"] == blocking]
        if domain is not None:
            qs = [q for q in qs if q["domain"] == domain.strip().lower()]
        return qs

    def answer_question(self, question_id: str, *, answer: str, basis: str,
                          decided_by: Optional[str] = None, now: Optional[datetime] = None) -> dict:
        """A human supplies a real answer to one question (by Q-ID). Works
        whether the question was OPEN (a Tier-3 escalation actually being
        answered) or ASSUMED (a Tier-2 default now being confirmed or
        overridden by a real human answer -- the overturn check runs either
        way). Persists the decision (so the same question_key never
        escalates again) and updates the question record itself."""
        data = self._load_questions()
        qs = data.get("questions", [])
        target = None
        for q in qs:
            if q["id"] == question_id:
                target = q
                break
        if target is None:
            raise KeyError(f"No question with id {question_id!r}")

        decided_by = decided_by or "unknown"
        entry = self._persist_decision(
            question_key=target["question_key"], domain=target["domain"], owner=target["owner"],
            question=target["question"], answer=answer, basis=basis, decided_by=decided_by,
            source="human_answer", question_id_of_answer=question_id, now=now,
        )
        overturned = bool(entry.get("_overturned_this_time"))

        target["status"] = "ANSWERED"
        target["answer"] = answer
        target["basis"] = basis
        target["decided_by"] = decided_by
        target["answered_at"] = _now_iso(now)
        target["overturned"] = overturned
        self._save_questions(data)

        # M8 Cohort 2 (CAP-M8-EXPLOOP-002 / GAP-M8-002): CLARIFICATION_
        # LEARNING's real producer. answer_question() is the one real
        # production point where a human resolves a Q-ID (dv-harness
        # question-queue answer, intake_resume.py's answer-by-Q-ID flow),
        # so this is the real "clarification learning" event -- not a
        # separate polling/inference mechanism. Best-effort, exactly like
        # every engine.py _promote_* call site's own try/except: a
        # promotion failure must never break the real answer-persistence
        # flow above, which has already succeeded by this point.
        try:
            from .experience_record import build_experience_record
            from .memory_router import route_and_store
            from .storage import StateStore
            from .config import load_config
            # M8 Cohort 4 (CAP-HITL-008): `authority_role` is a real,
            # already-classified field on `target` whenever this question
            # was filed through clarification_service.py's own real
            # resolve/file path (classify_question_owner() -> file_
            # clarification(authority_role=owner) -> add_question()) --
            # CAP-M6-CLARSVC-001's own existing production chain, reused
            # verbatim here rather than re-classified. None for a question
            # filed through an older/uninstrumented caller: build_
            # experience_record() turns that into the explicit
            # UNCLASSIFIED sentinel, never a silent omission (backward
            # compatibility -- see that function's own docstring). THE GAP
            # THIS CLOSES: DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md Section 24
            # names role information being "preserved through to the
            # learning loop, not discarded after the decision is made" as
            # the CONTINUOUS_EVOLUTION alignment target -- previously this
            # exact hook discarded it.
            role = target.get("authority_role")
            record = build_experience_record(
                experience_type="CLARIFICATION_LEARNING",
                title=f"Clarification answered: {target['domain']}",
                pattern=target["question"],
                lesson=f"Answer: {answer}",
                evidence=f"basis={basis}; decided_by={decided_by}; overturned={overturned}",
                applicability_constraints=target.get("context_path", ""),
                knowledge_domain=role,
                human_role=role,
            )
            promotion = route_and_store(self.root, record, cfg=load_config(self.root))
        except Exception as exc:
            promotion = {"destination": "PROMOTION_FAILED", "error": str(exc)}
        try:
            StateStore(self.root).event({
                "ts": _now_iso(now), "stage": "INTAKE", "event": "CLARIFICATION_LEARNING_PROMOTED",
                "question_id": question_id, "promotion": promotion,
            })
        except Exception:
            pass

        return target

    # -- expired exemptions -> real blocking questions -----------------------

    def escalate_expired_exemptions(self, *, as_of: Optional[date] = None,
                                      now: Optional[datetime] = None,
                                      write_review_queue: bool = True) -> List[dict]:
        """Turn every EXPIRED exemption into a real Tier-3 blocking question
        in this queue, and return the questions newly filed (empty when
        nothing expired, or when everything expired was already filed).

        This is the second half of the exemptions read path, and it closes
        the other end of the same gap find_exemption() closes. An expired
        exemption already produced a review-queue record
        (exemptions.build_review_queue()), and exemptions.py's own docstring
        named THIS module as the consumer that record was shaped for -- but
        the consumer never existed, so `review_queue.json` was a file with
        no reader and an expiry was a fact only a human running
        `dv-harness exemptions expire-report` by hand would ever see. An
        expired exemption is now a question with an owner, a Q-ID and a
        blocking tier, exactly like any other thing the harness cannot
        assume its way past.

        Tier 3 is not a choice made here: an expired exemption means a check
        is currently disabled with no live sanction, which is
        `affects_pass_fail_verdict` in the literal sense of that flag, so
        classify_tier() reaches Tier 3 on its own rules. The exemption is
        expired, so find_exemption() returns None for its check_id and
        nothing suppresses the escalation it just triggered.

        Idempotent: the question_key is derived from the exemption id, so a
        second run over an unchanged exemptions.yaml re-mints the same key,
        finds the existing question and files nothing. Renewing the
        exemption (a new valid_until) stops it being expired at all, which
        is the intended way for this question to stop recurring; answering
        the question does not by itself renew the exemption, and the answer
        text says so.

        Routed to domain "env" (owner DV-owner) because route_owner()'s
        table is a literal 3-domain routing rule, not a free-text owner
        field -- the exemption's own `owner` is carried in the question text
        and in the attached citation instead of being smuggled into a
        `owner` field the schema pins per domain."""
        as_of = as_of or date.today()
        queue = _exemptions.build_review_queue(self.exemptions_path, as_of=as_of)
        if write_review_queue:
            _exemptions.write_review_queue(
                queue, _exemptions.default_review_queue_path(self.root))

        existing_keys = {q["question_key"] for q in self._load_questions().get("questions", [])}
        filed: List[dict] = []
        for rec in queue:
            key = "%s:%s" % (EXEMPTION_EXPIRY_KEY_PREFIX, rec["exemption_id"])
            if key in existing_keys:
                continue
            filed.append(self.add_question(
                domain="env",
                question=(
                    "Exemption %s on check %r expired on %s (%s day(s) ago). Its owner is %s "
                    "and its stated reason is %r, grounded in %s. Is this check still "
                    "deliberately exempt?"
                    % (rec["exemption_id"], rec["check_id"], rec["valid_until"],
                        rec["days_expired"], rec["owner"], rec["reason"], rec["basis_document"])
                ),
                context_path="%s#%s" % (self.exemptions_path, rec["exemption_id"]),
                options=[
                    {"label": "renew",
                      "rationale": "The cited basis still holds; re-confirm with a new valid_until "
                                    "via `dv-harness exemptions add`. Answering here does not renew "
                                    "it -- the exemptions.yaml entry must actually be updated."},
                    {"label": "retire",
                      "rationale": "The restriction is gone or the check no longer exists; set "
                                    "status: retired so the entry survives as history without "
                                    "exempting anything."},
                    {"label": "re-enable-the-check",
                      "rationale": "The exemption was a temporary workaround that has outlived its "
                                    "reason; turn the check back on and delete nothing silently."},
                ],
                recommendation="renew",
                assumption_if_unanswered=(
                    "None -- an expired exemption is never auto-renewed. The check stays "
                    "unsanctioned until %s answers." % (rec["owner"],)
                ),
                question_key=key,
                context={
                    "check_id": rec["check_id"],
                    "affects_pass_fail_verdict": True,
                    "expired_exemption_id": rec["exemption_id"],
                },
                now=now,
            ))
        return filed

    # -- digest -------------------------------------------------------------

    def build_digest(self, *, trigger: str = "manual", stage: Optional[str] = None,
                       now: Optional[datetime] = None, min_hours_since_last: float = 24.0) -> dict:
        """Batch every never-yet-digested OPEN/ASSUMED question into one
        digest. Never called implicitly by add_question() -- Part B:
        "batched into a daily/end-of-run digest, never real-time pings".

        Three explicit trigger windows, reusing this harness's own existing
        regression-cycle boundary (dv_harness.models.Stage) rather than
        inventing a new timer mechanism:
          - trigger="manual": an explicit end-of-run call (a human, or a
            daily cron, running `dv-harness question-queue digest`) --
            always emits if there is anything pending.
          - trigger="stage_boundary": pass the stage that just completed;
            emits only when `stage` is one of DIGEST_BOUNDARY_STAGES (end of
            a regression run / coverage closure / re-audit cycle / signoff).
            WIRED on the real autonomous path since 2026-09-05:
            engine.DVHarness._emit_question_digest_at_stage_boundary() calls
            this (and compute_metrics()) from advance(), the single canonical
            "the current stage completed successfully, move on" transition --
            which loop() delegates to on every PASS and `dv-harness next`
            calls directly. Every boundary crossing lands as one
            QUESTION_QUEUE_DIGEST event in .dv-harness/events.jsonl, emitted
            or not. Any OTHER caller wires in the same way: call this right
            after its own stage-transition code runs, passing the stage that
            just completed.
          - trigger="scheduled": emits only once >= min_hours_since_last
            has elapsed since the last real emission -- the "daily" cadence
            for a caller that polls without knowing the exact stage.

        Returns {"emitted": bool, "batch_id": str|None, "questions": [...],
        "by_owner": {owner: [...]}}. emitted=False (empty batch_id/questions)
        whenever the trigger condition isn't met OR there is nothing pending
        -- safe to call this often without spamming empty digests.
        """
        now = now or datetime.now(timezone.utc)
        data = self._load_questions()
        qs = data.get("questions", [])
        pending = [q for q in qs if q["status"] in ("OPEN", "ASSUMED") and q.get("digest_batch_id") is None]

        if trigger == "stage_boundary":
            condition_met = stage in DIGEST_BOUNDARY_STAGES
        elif trigger == "scheduled":
            last = data.get("last_digest_emitted_at")
            condition_met = last is None or (now - _parse_iso(last)) >= timedelta(hours=min_hours_since_last)
        else:  # "manual" -- always eligible; an explicit end-of-run/daily call
            condition_met = True

        if not condition_met or not pending:
            return {"emitted": False, "batch_id": None, "questions": [], "by_owner": {}}

        batch_id = "DIGEST-" + now.strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(
            (":".join(q["id"] for q in pending)).encode("utf-8")).hexdigest()[:6]
        by_owner: Dict[str, List[dict]] = defaultdict(list)
        for q in pending:
            q["digest_batch_id"] = batch_id
            q["digest_emitted_at"] = _now_iso(now)
            by_owner[q["owner"]].append(q)

        data["last_digest_emitted_at"] = _now_iso(now)
        self._save_questions(data)
        return {"emitted": True, "batch_id": batch_id, "questions": pending, "by_owner": dict(by_owner)}

    # -- metrics --------------------------------------------------------------

    def compute_metrics(self, *, now: Optional[datetime] = None, window_days: int = 7) -> dict:
        """The 4 Part-B tracking metrics, each a real computation over the
        persisted questions/decisions records -- never a manually-maintained
        counter.

        - self_resolve_rate: percent of all asks classified Tier 1. Target
          >90%.
        - blocking_questions_per_week: Tier-3 (blocking) asks in the last
          `window_days`, normalized to a 7-day rate -- the direct human-cost
          proxy.
        - repeat_question_rate: percent of "re-asks of a question_key a
          HUMAN has already answered" that did NOT resolve at Tier 1.
          Provably 0 as long as classify_tier()'s human-answer override
          holds -- any nonzero value means persistence (find_decision/
          decisions.json) is broken. A Tier-2 auto-assumption is
          deliberately NOT counted as "already decided" here: since the
          F3-a fix it is only a provisional machine guess that a later
          Tier-3-triggering ask is SUPPOSED to escalate past, so counting a
          correct escalation as a persistence failure would make this
          metric fire on the fix rather than on a real bug. Keys whose
          decision was deliberately withdrawn via revoke_decision() are
          excluded for the same reason.
        - assumption_overturned_rate: percent of question_keys that were
          EVER given a Tier-2 auto-assumption whose value was later
          genuinely overturned by a real human answer. Too high means
          Tier-2's safe-to-assume admission bar (classify_tier's
          blast_radius check) is too loose.
        """
        now = now or datetime.now(timezone.utc)
        qs = self._load_questions().get("questions", [])
        total = len(qs)
        tier1 = sum(1 for q in qs if q["tier"] == TIER1_SELF_RESOLVE)
        self_resolve_rate = (tier1 / total * 100.0) if total else 0.0

        window_start = now - timedelta(days=window_days)
        blocking_recent = [q for q in qs if q.get("blocking") and _parse_iso(q["created_at"]) >= window_start]
        blocking_questions_per_week = len(blocking_recent) * (7.0 / window_days) if window_days else 0.0

        # repeat_question_rate: walk each question_key's asks in creation
        # order; once a HUMAN answer exists for that key, every SUBSEQUENT
        # ask is a "repeat opportunity" -- it should resolve at Tier 1. One
        # that doesn't is a persistence failure.
        decisions_data = self._load_decisions()
        revoked_keys = {r.get("question_key") for r in decisions_data.get("revoked", [])}
        by_key: Dict[str, List[dict]] = defaultdict(list)
        for q in sorted(qs, key=lambda q: q["created_at"]):
            by_key[q["question_key"]].append(q)
        repeat_opportunities = 0
        repeat_failures = 0
        for key, asks in by_key.items():
            if key in revoked_keys:
                continue
            human_answer_exists = False
            for q in asks:
                if human_answer_exists:
                    repeat_opportunities += 1
                    if q["tier"] != TIER1_SELF_RESOLVE:
                        repeat_failures += 1
                if q["status"] == "ANSWERED":
                    human_answer_exists = True
        repeat_question_rate = (repeat_failures / repeat_opportunities * 100.0) if repeat_opportunities else 0.0

        decisions = decisions_data.get("decisions", {})
        tier2_assumed = [d for d in decisions.values() if d.get("ever_tier2_assumed")]
        overturned = [d for d in tier2_assumed if d.get("overturned")]
        assumption_overturned_rate = (len(overturned) / len(tier2_assumed) * 100.0) if tier2_assumed else 0.0

        return {
            "self_resolve_rate_percent": round(self_resolve_rate, 2),
            "self_resolve_rate_target_percent": 90.0,
            "blocking_questions_per_week": round(blocking_questions_per_week, 2),
            "repeat_question_rate_percent": round(repeat_question_rate, 2),
            "assumption_overturned_rate_percent": round(assumption_overturned_rate, 2),
            "total_questions": total,
            "tier1_count": tier1,
            "tier2_count": sum(1 for q in qs if q["tier"] == TIER2_SAFE_ASSUME),
            "tier3_count": sum(1 for q in qs if q["tier"] == TIER3_CANNOT_ASSUME),
            "open_blocking_count": sum(1 for q in qs if q["status"] == "OPEN"),
        }


# ---- N-way question builder: the exactly-2-option shape, generalized -------

# `source_authority.escalate_conflict()` builds exactly ONE shape: two named
# sides of a source disagreement, each carrying its own evidence path as its
# option `rationale`, validated by `assert_both_evidence_paths_present()`
# before the record is persisted, then filed once (idempotent on
# question_key) as a Tier-3 blocking question. `build_multiple_choice_
# question()` below is that SAME shape with the "exactly 2" generalized to
# "N >= 2 named candidates" -- reusing this module's own machinery
# (`add_question`, `make_question_key`) exactly as `escalate_conflict`
# already does, so a caller with 3 plausible bind targets, 3 candidate root
# causes, or any other N-way pre-researched choice gets ONE well-formed
# question instead of hand-rolling the option-shape/evidence-citation/
# dedup discipline itself.
#
# Disclosed residual, stated rather than left to be discovered: this is a
# SEPARATE implementation from `source_authority.assert_both_evidence_paths_
# present()`, not a shared call into it -- this task's own scope is
# `dv_harness/question_queue.py` only, and `source_authority.py` (where
# `escalate_conflict`/`assert_both_evidence_paths_present` actually live) is
# outside it. Unifying the two for real means either making
# `source_authority.escalate_conflict()` call this module's generalized N=2
# case, or pointing both at one shared validator -- either edit touches
# `source_authority.py`, which this change does not. What IS true, and
# checked below rather than merely asserted, is that the two enforce the
# IDENTICAL rule (every named candidate's evidence path must appear verbatim
# in the question text or an option's label/rationale) -- see
# `test_assert_all_evidence_paths_present_matches_source_authority_rule` --
# so this is a deliberate, disclosed duplication of ONE rule, not an
# undisclosed drift into two diverging ones.

#: Same admission bar `source_authority.CONFLICT_QUESTION_CONTEXT` uses:
#: `affects_spec_intent` is the honest reason a caller choosing between N
#: pre-researched candidates cannot be resolved by the harness itself --
#: which of several plausible interpretations/targets/root-causes is
#: correct is exactly a spec-intent judgment call. A caller with a
#: genuinely different reason may override via `extra_context=`, the same
#: contract every other evidence dict in this codebase carries.
MULTIPLE_CHOICE_QUESTION_CONTEXT: dict = {"affects_spec_intent": True}

#: What a multi-candidate escalation says when nobody answers. Deliberately
#: NOT a value -- mirrors `source_authority.NO_SAFE_ASSUMPTION`: a Tier-3
#: question never silently uses its assumption, and naming one of the N
#: candidates here would be the one string a future tier relaxation could
#: pick up and act on as if it had been decided.
NO_SAFE_ASSUMPTION_MULTIPLE_CHOICE = (
    "NONE IS SAFE -- a choice among multiple pre-researched candidates with no "
    "single authority-derived winner is Tier-3 by construction; a human must pick "
    "which candidate is correct before anything proceeds on the strength of it."
)


def _schema_options_max_items() -> int:
    """The REAL current cap on `options` this module's own schema enforces --
    read from question.schema.json itself rather than a second hardcoded
    "3", so a future schema change is picked up automatically instead of
    requiring this function to be found and edited in step. Today that cap
    is 2-3 (see question.schema.json's own `options.maxItems`), the exact
    reason `source_authority.escalate_conflict()` already refuses (rather
    than truncates) a conflict with more than 3 sides."""
    return _load_schema()["properties"]["options"]["maxItems"]


def assert_all_evidence_paths_present(question_text: str, options: List[Dict[str, str]],
                                       evidence_paths: Sequence[str]) -> None:
    """The N-ary generalization of `source_authority.
    assert_both_evidence_paths_present()`'s rule (see this module's own
    disclosed-residual note above for why this is a second, deliberately
    identical implementation rather than a shared call): refuse a
    multi-candidate question that fails to carry EVERY named candidate's
    evidence path, verbatim, somewhere in the question text or an option's
    own label/rationale. An escalation naming N choices without saying
    where each one's evidence lives is worse than none filed at all -- it
    reads as researched work while leaving the human reader with nowhere to
    check N-1 of the N claims.

    Raises QuestionValidationError (never a bare assert) naming exactly
    which evidence path(s) are missing, and how many candidates that is out
    of the total -- so a caller can tell "forgot one citation" from "wrote
    the wrong candidate list entirely" without re-deriving it by hand."""
    blob = question_text + " " + " ".join(
        f"{o.get('label', '')} {o.get('rationale', '')}" for o in options
    )
    missing = [p for p in evidence_paths if p not in blob]
    if missing:
        raise QuestionValidationError(
            "multiple-choice question is missing the evidence path for %d of %d "
            "candidate(s): %r -- every candidate's evidence_path must appear in the "
            "question text or its own option rationale before this can be filed."
            % (len(missing), len(evidence_paths), missing)
        )


def build_multiple_choice_question(
    store: "QuestionQueueStore",
    *,
    domain: str,
    subject: str,
    candidates: Sequence[Dict[str, Any]],
    question_text: Optional[str] = None,
    recommendation_label: Optional[str] = None,
    context_path: Optional[str] = None,
    question_key: Optional[str] = None,
    extra_context: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    grounding_evidence: Optional[Dict[str, str]] = None,
) -> dict:
    """File ONE well-formed Tier-3 blocking question offering N >= 2 named
    candidates, each carrying its own evidence path -- the N-way
    generalization of `source_authority.escalate_conflict()`'s exactly-2-
    option shape (see the module-level comment above this function for the
    full relationship, including what is and is not shared with it).

    `candidates`: a sequence of >= 2 dicts, each REQUIRED to carry:
      - `label` (str): the candidate's name, becomes options[].label.
      - `evidence_path` (str): where THIS candidate's supporting evidence
        lives (a file:line, an env.manifest.json pointer, a register/port
        name, ...) -- folded into the option's `rationale` and asserted
        present by `assert_all_evidence_paths_present()` before anything is
        persisted, exactly the discipline `escalate_conflict` already
        enforces for its 2 sides, generalized to all N.
      - `rationale` (str, optional): additional pre-research reasoning
        beyond the bare evidence citation.
    Fewer than 2 candidates, or a candidate missing `label`/`evidence_path`,
    raises QuestionValidationError before anything is touched.

    More than `_schema_options_max_items()` candidates is REFUSED, not
    truncated -- silently dropping the (N-3)th candidate would drop that
    candidate's evidence path with it, exactly the failure
    `escalate_conflict`'s own "> 3 sides" refusal exists to prevent. Split a
    wider decision into pairwise/grouped questions instead.

    `question_text` defaults to a generated summary naming every candidate
    and its evidence path; a caller with a more precise question may pass
    its own (which must still satisfy `assert_all_evidence_paths_present()`).
    `recommendation_label` defaults to the first candidate when omitted --
    mirroring `escalate_conflict`'s own UNDECIDABLE-verdict behavior: with
    no authority-derived winner, recommending one anyway would be inventing
    the tie-break this function is explicitly declining to make; the
    highest-listed candidate is offered only as a starting point, never as
    a claimed answer.

    Idempotent on `question_key` (derived from domain/question_text/
    context_path when not supplied), the SAME discipline `escalate_conflict`
    already uses: an existing record for this exact key is returned as-is
    rather than duplicated, so a detector that reruns over unchanged sources
    never grows the queue. Files with `context={"affects_spec_intent": True,
    ...}` (see `MULTIPLE_CHOICE_QUESTION_CONTEXT`), so `classify_tier()`
    reaches Tier 3 (`CANNOT_ASSUME`, blocking) on its own ordinary rules --
    no tier is asserted directly by this function.

    `grounding_evidence` (default None): passed straight through to
    `add_question()` -- see that function's and normalize_grounding_
    evidence()'s own docstrings. Never synthesized from `candidates` here:
    each candidate's own `evidence_path` already answers WHERE its evidence
    lives (folded into that candidate's own option `rationale`), which is a
    different question from WHY a human is being asked to choose among
    them at all; a caller with a real answer to the latter supplies it
    explicitly rather than having one guessed on their behalf."""
    candidates = list(candidates)
    if len(candidates) < 2:
        raise QuestionValidationError(
            f"build_multiple_choice_question needs >= 2 named candidates, got "
            f"{len(candidates)}"
        )
    max_options = _schema_options_max_items()
    if len(candidates) > max_options:
        raise QuestionValidationError(
            f"build_multiple_choice_question got {len(candidates)} candidates, but "
            f"question.schema.json's options only allows up to {max_options} -- refused "
            f"rather than truncated (dropping a candidate would drop its evidence path "
            f"with it). Split a wider decision into pairwise/grouped multiple-choice "
            f"questions to keep every evidence path."
        )
    for i, c in enumerate(candidates):
        if not isinstance(c, dict) or not c.get("label") or not c.get("evidence_path"):
            raise QuestionValidationError(
                f"candidates[{i}] must be a dict carrying at least a non-empty 'label' "
                f"and 'evidence_path' (got {c!r})"
            )

    options: List[Dict[str, str]] = []
    for c in candidates:
        prefix = f"{c['rationale']} " if c.get("rationale") else ""
        options.append({
            "label": c["label"],
            "rationale": f"{prefix}evidence: {c['evidence_path']}",
        })

    if question_text is None:
        parts = [
            "%s: %s [evidence: %s]" % (c["label"], c.get("rationale") or "see cited evidence",
                                        c["evidence_path"])
            for c in candidates
        ]
        question_text = f"Multiple candidates for {subject}: " + "; ".join(parts)

    assert_all_evidence_paths_present(question_text, options,
                                       [c["evidence_path"] for c in candidates])

    labels = [o["label"] for o in options]
    if recommendation_label is not None and recommendation_label not in labels:
        raise QuestionValidationError(
            f"recommendation_label {recommendation_label!r} is not one of the offered "
            f"candidate labels {labels!r} -- a question must never recommend a candidate "
            f"it did not actually offer."
        )
    recommendation = recommendation_label or options[0]["label"]

    ctx = dict(MULTIPLE_CHOICE_QUESTION_CONTEXT)
    ctx.update(extra_context or {})

    key = question_key or make_question_key(
        domain, question_text, context_path or candidates[0]["evidence_path"])

    # Idempotent dedup BEFORE filing -- same reasoning escalate_conflict's own
    # comment gives: add_question() appends unconditionally, so a detector
    # that reruns over unchanged sources would otherwise mint a fresh
    # duplicate record (same Q-ID, same question_key) on every pass.
    for existing in store.list_questions():
        if existing.get("question_key") == key:
            return existing

    return store.add_question(
        domain=domain,
        question=question_text,
        context_path=context_path or candidates[0]["evidence_path"],
        options=options,
        recommendation=recommendation,
        assumption_if_unanswered=NO_SAFE_ASSUMPTION_MULTIPLE_CHOICE,
        question_key=key,
        context=ctx,
        now=now,
        grounding_evidence=grounding_evidence,
    )


# ---- Signoff-stage evidence-review questions (2026-09-07, additive) --------
#
# Gap: a human reviewing SIGNOFF-STAGE evidence (a signoff_export.py bundle
# manifest artifact, a signoff_blocker_list.py closure dimension, a
# functional_coverage_signoff.py closure finding, an evidence_provenance.py
# self-attested/derived caveat) had no reachable path to file a NEW
# clarifying question tied to one specific evidence item. Verified by direct
# grep before writing this: every real add_question()/build_multiple_choice_
# question() call site in this codebase is AI/gate-initiated (source_
# authority.escalate_conflict(), connectivity's T4 escalation, coverage_
# analysis's escalate_unreachable_stimulus/holes, the waveform-dump gate,
# gui_intake_wizard's answer flow, ...); request_clarification() (above)
# only RE-RENDERS a question that has ALREADY been filed by one of those.
# None of signoff_export.py/signoff_blocker_list.py/system_signoff_package.py/
# evidence_provenance.py has ever called add_question() at all.
#
# file_signoff_evidence_question() closes it by REUSE, not by a second
# filing mechanism: it is a thin, idempotent wrapper around this store's own
# add_question(), mirroring source_authority.escalate_conflict()'s and this
# module's own build_multiple_choice_question()'s pre-add_question() dedup-
# on-question_key discipline exactly, so a human re-reviewing the SAME
# evidence item (a dashboard re-render, a re-run signoff pass) gets back the
# ALREADY-FILED record rather than a duplicate that grows questions.json.

#: The four real signoff-stage evidence surfaces a human reviews before/at
#: signoff -- a closed vocabulary, never an open string a reader could not
#: go check (the same discipline normalize_suggested_answer()'s own
#: SUGGESTED_ANSWER_SOURCE_MODULES already applies one field over).
SIGNOFF_EVIDENCE_KIND_BUNDLE = "signoff_export_bundle"
SIGNOFF_EVIDENCE_KIND_BLOCKER_LIST = "signoff_blocker_list"
SIGNOFF_EVIDENCE_KIND_COVERAGE_CLOSURE = "functional_coverage_closure"
SIGNOFF_EVIDENCE_KIND_PROVENANCE_CAVEAT = "evidence_provenance_caveat"

SIGNOFF_EVIDENCE_KINDS = frozenset({
    SIGNOFF_EVIDENCE_KIND_BUNDLE, SIGNOFF_EVIDENCE_KIND_BLOCKER_LIST,
    SIGNOFF_EVIDENCE_KIND_COVERAGE_CLOSURE, SIGNOFF_EVIDENCE_KIND_PROVENANCE_CAVEAT,
})

#: Tier-3 by construction, the same posture CONFLICT_QUESTION_CONTEXT/
#: MULTIPLE_CHOICE_QUESTION_CONTEXT already take: a question raised against
#: one specific piece of SIGNOFF evidence is, by definition, a question about
#: whether a pass/fail-relevant artifact is trustworthy -- exactly
#: classify_tier()'s own "affects_pass_fail_verdict" hard trigger, never
#: asserted directly; always reached through classify_tier()'s ordinary
#: evaluation of this context dict.
SIGNOFF_EVIDENCE_QUESTION_CONTEXT: dict = {"affects_pass_fail_verdict": True}

#: What a signoff-evidence question says when nobody answers. Deliberately
#: NOT a value -- mirrors NO_SAFE_ASSUMPTION_MULTIPLE_CHOICE immediately
#: above: a Tier-3 question about signoff evidence must never silently use
#: an assumed answer, since that is precisely the "is this evidence
#: trustworthy" question a human flagged as unresolved.
NO_SAFE_ASSUMPTION_SIGNOFF_EVIDENCE = (
    "NONE IS SAFE -- signoff-stage evidence a human flagged as needing "
    "clarification must not be silently trusted or silently discarded; a "
    "human must resolve this before the affected signoff evidence is relied "
    "on further."
)


def file_signoff_evidence_question(
    store: "QuestionQueueStore",
    *,
    evidence_kind: str,
    evidence_path: str,
    evidence_summary: str,
    question: str,
    options: Any,
    recommendation: str,
    domain: str = "env",
    raised_by: Optional[str] = None,
    context_path: Optional[str] = None,
    question_key: Optional[str] = None,
    extra_context: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """File ONE new, real Tier-3 blocking question tied to ONE named piece of
    signoff-stage evidence (`evidence_kind` -- see SIGNOFF_EVIDENCE_KINDS).

    `evidence_path`/`evidence_summary` become the question's own
    `grounding_evidence` citation -- WHY this question exists, cited to WHERE
    in the real evidence it concerns (normalize_grounding_evidence()'s own
    existing "an uncited claim is refused outright" rule is reused
    unmodified: both are required and non-blank, or add_question() itself
    raises QuestionValidationError before anything is persisted).

    Idempotent on `question_key`, the SAME discipline source_authority.
    escalate_conflict() and build_multiple_choice_question() (above) already
    apply: a caller reviewing the SAME evidence item twice gets back the
    ALREADY-FILED record, never a duplicate -- add_question()'s own dedup is
    caller-supplied (see its docstring's `enforce_do_not_ask`), and this is
    what supplies it for this call site specifically.

    `raised_by` (optional): who RAISED the question, folded as an
    attribution prefix into the recorded `grounding_evidence["summary"]`.
    This is NOT the same fact as a recorded decision's own `decided_by` --
    who ANSWERS a question is, and stays, recorded only via the existing,
    sanctioned `answer_question()` path; `raised_by` here never writes a
    decision and is never treated as one.

    Files with `context={"affects_pass_fail_verdict": True, ...}` (see
    SIGNOFF_EVIDENCE_QUESTION_CONTEXT) so `classify_tier()` reaches Tier 3
    on its own ordinary rules -- no tier is asserted directly by this
    function. `extra_context` lets a caller with a genuinely different real
    reason override/extend that default, the same contract every other
    context dict in this module already carries."""
    if evidence_kind not in SIGNOFF_EVIDENCE_KINDS:
        raise QuestionValidationError(
            f"evidence_kind {evidence_kind!r} is not one of {sorted(SIGNOFF_EVIDENCE_KINDS)!r} -- "
            "a signoff-evidence question must cite one of this module's known signoff-stage "
            "evidence kinds, never an open string a reader could not go check."
        )

    summary = f"[raised by: {raised_by}] {evidence_summary}" if raised_by else evidence_summary
    grounding_evidence = {"summary": summary, "evidence_path": evidence_path}
    # Pre-validated here (raises with a signoff-specific call-site name)
    # rather than left to surface only once inside add_question() -- reuses
    # normalize_grounding_evidence() unmodified either way.
    normalize_grounding_evidence(grounding_evidence)

    ctx = dict(SIGNOFF_EVIDENCE_QUESTION_CONTEXT)
    ctx["signoff_evidence_kind"] = evidence_kind
    ctx.update(extra_context or {})

    key = question_key or make_question_key(domain, question, context_path or evidence_path)

    # Idempotent dedup BEFORE filing -- same reasoning escalate_conflict's
    # and build_multiple_choice_question's own comments give: add_question()
    # appends unconditionally, so a human re-reviewing the same evidence item
    # (a dashboard re-render, a re-run signoff pass) would otherwise mint a
    # fresh duplicate record (same Q-ID, same question_key) on every review.
    for existing in store.list_questions():
        if existing.get("question_key") == key:
            return existing

    return store.add_question(
        domain=domain,
        question=question,
        context_path=context_path or evidence_path,
        options=options,
        recommendation=recommendation,
        assumption_if_unanswered=NO_SAFE_ASSUMPTION_SIGNOFF_EVIDENCE,
        question_key=key,
        context=ctx,
        grounding_evidence=grounding_evidence,
        now=now,
    )


# ---- Question Escalation Package: the 9-field structured view (spec section 32) --
#
# question_queue.py's own persisted question record (question.schema.json) already
# carries every fact a human-facing escalation needs -- id, domain, question,
# context_path, options, recommendation, assumption_if_unanswered, owner, tier,
# blocking -- accumulated one Part-B mechanism at a time across this module's
# history. What never existed was a single, NAMED 9-field VIEW assembling exactly
# those facts into the shape a human reviewer (or a digest/GUI renderer) actually
# reads, so two renderers of "the same escalation" could each pick a different
# subset of the raw record and call it the package.
#
# Disclosed residual, stated rather than left to be discovered: this repository
# checkout does not carry the literal spec-section-32 document text (a repo-wide
# search found no file containing it), so the 9 field NAMES below are this
# module's own defensible synthesis -- built from established human-in-the-loop
# escalation practice and this module's own existing, already-tested vocabulary
# (domain/owner/tier routing, options-with-rationale, the Tier-2
# assumption-if-unanswered contract) -- rather than a verbatim transcription of a
# document this checkout does not have. What IS load-bearing regardless of the
# exact names, and enforced rather than merely claimed: every one of the 9 fields
# is a REAL, already-persisted fact from a record add_question() /
# build_multiple_choice_question() already produced -- never a fabricated value,
# and never a second, independently-filed record. build_escalation_package() is a
# pure, read-only PROJECTION of an existing record (the same "a generated view of
# a real store is never a second source of truth" discipline this module's own
# decisions.md already applies to decisions.json) -- it is never written back into
# questions.json, so question.schema.json's `additionalProperties: false` contract
# is untouched and no schema_version bump is required to add it.

#: The 9 named fields of a Question Escalation Package, in a fixed order --
#: build_escalation_package()'s only output shape.
ESCALATION_PACKAGE_FIELDS: tuple = (
    "question_id", "category", "context", "question_text", "options",
    "recommended_option", "default_if_unanswered", "owner", "urgency",
)

#: Field 9 (urgency), DERIVED from the tier classify_tier() already computed for
#: this record -- never an independently-declared value that could drift from the
#: tier a caller actually got escalated at. Tier 3 (blocking) is a live
#: awaiting-human-answer escalation; Tier 2 carries this module's own Tier-2
#: contract language ("logged and continues" -- see add_question()'s Tier-2
#: branch and TIER2_AUTO_ASSUMPTION_SOURCE); Tier 1 was never actually escalated
#: to a human at all, so its package is purely informational.
_URGENCY_BY_TIER: Dict[int, str] = {
    TIER3_CANNOT_ASSUME: "BLOCKING_AWAITING_HUMAN_ANSWER",
    TIER2_SAFE_ASSUME: "NON_BLOCKING_TIME_BOXED_ASSUMPTION_LOGGED",
    TIER1_SELF_RESOLVE: "INFORMATIONAL_ALREADY_SELF_RESOLVED",
}

#: The real record keys build_escalation_package() reads from -- every one
#: REQUIRED by question.schema.json's own `required` array, so a record that
#: cleared validate_question() always carries all of them. Listed here (not
#: re-derived from the schema) so a record that did NOT come through this
#: module's own filing mechanism -- a hand-built dict missing one -- is refused
#: with a specific, actionable message rather than a bare KeyError.
_ESCALATION_PACKAGE_REQUIRED_RECORD_KEYS: tuple = (
    "id", "domain", "context_path", "question", "options",
    "recommendation", "assumption_if_unanswered", "owner", "tier",
)


def build_escalation_package(record: Dict[str, Any]) -> Dict[str, Any]:
    """Project a persisted question RECORD (as returned by add_question() /
    build_multiple_choice_question() / QuestionQueueStore.get_question() /
    get_escalation_package()) into the 9 named ESCALATION_PACKAGE_FIELDS -- and
    only that: every value here is read straight off `record`, never
    re-derived from a second source, never independently computed, and never
    guessed when the record's own field is absent.

    Raises QuestionValidationError -- never a KeyError, and never a silently
    fabricated default -- when `record` is missing a field this projection
    needs (a malformed/incomplete dict, e.g. one built by hand rather than by
    this module's own filing mechanism, or carrying a `tier` outside the 3
    known values). This is the negative-control property this function
    exists to guarantee: an escalation package can never be assembled from
    evidence that is not really there."""
    if not isinstance(record, dict):
        raise QuestionValidationError(
            f"cannot build an escalation package: record must be a dict, got "
            f"{type(record).__name__}"
        )
    missing = [k for k in _ESCALATION_PACKAGE_REQUIRED_RECORD_KEYS if record.get(k) is None]
    if missing:
        raise QuestionValidationError(
            "cannot build an escalation package: the question record is missing "
            f"{missing!r} -- only a record produced by add_question() / "
            "build_multiple_choice_question() (never a hand-built dict) carries "
            "every fact this 9-field projection requires."
        )
    tier = record["tier"]
    urgency = _URGENCY_BY_TIER.get(tier)
    if urgency is None:
        raise QuestionValidationError(
            f"cannot build an escalation package: record['tier'] is {tier!r}, not "
            f"one of the 3 known tiers ({sorted(_URGENCY_BY_TIER)!r}) -- urgency "
            f"(field 9) has no honest value to report."
        )
    return {
        "question_id": record["id"],
        "category": record["domain"],
        "context": record["context_path"],
        "question_text": record["question"],
        "options": record["options"],
        "recommended_option": record["recommendation"],
        "default_if_unanswered": record["assumption_if_unanswered"],
        "owner": record["owner"],
        "urgency": urgency,
    }


def render_escalation_package_markdown(package: Dict[str, Any]) -> str:
    """Human-readable rendering of an escalation package, in
    ESCALATION_PACKAGE_FIELDS order -- for a digest/GUI renderer that wants
    ONE consistent block per escalated question rather than reformatting the
    raw record itself. No new table-rendering machinery: this is the same
    "one labeled field per line" shape this module's own
    QuestionQueueStore._render_decisions_md() already uses for a per-decision
    block, applied here to a package instead of a decision."""
    lines = [f"### {package['question_id']}", ""]
    lines.append(f"- **Category:** {package['category']}")
    lines.append(f"- **Context:** {package['context']}")
    lines.append(f"- **Question:** {package['question_text']}")
    lines.append("- **Options:**")
    for opt in package["options"]:
        rationale = f" -- {opt['rationale']}" if opt.get("rationale") else ""
        lines.append(f"  - {opt['label']}{rationale}")
    lines.append(f"- **Recommended option:** {package['recommended_option']}")
    lines.append(f"- **Default if unanswered:** {package['default_if_unanswered']}")
    lines.append(f"- **Owner:** {package['owner']}")
    lines.append(f"- **Urgency:** {package['urgency']}")
    return "\n".join(lines)


# ---- Question rephrasing / clarification loop (2026-09-07) ------------------
#
# question_queue.py files a question exactly once (add_question()), with a
# fixed question text and 2-3 pre-researched options. Nothing in this module
# -- or anywhere else in dv_harness, confirmed by a repo-wide search before
# writing this -- gave a human who does not understand an already-filed
# question any way to signal that and get back a clearer restatement,
# grounded in the SAME evidence that question already carries. Neither
# `reference_pattern_audit.classify_wait()`-style heuristics nor an LLM call
# is available or appropriate here: this module only ever has the literal
# fields a question record already carries to work with, and re-wording a
# question's own sentence with anything beyond those fields would risk
# silently changing what it actually asks -- exactly the fabrication the
# Evidence Truth Rule forbids.
#
# `request_clarification()` is deliberately NOT a second filing mechanism:
# it never calls add_question(), never mints a new Q-ID or question_key,
# and never changes a question's tier/status/blocking. It only
#   (a) re-renders an EXISTING record -- read via store.get_question(), the
#       store's own existing lookup, never a second one -- into a clearer,
#       more scannable structure built entirely from fields that record
#       already carries (options[].rationale, context_path, tier_reason,
#       exemption, assumption_if_unanswered/answer); and
#   (b) records, best-effort, that a human asked for one, in a small sibling
#       JSON file next to questions.json/decisions.json
#       (QuestionQueueStore.clarifications_path) -- reusing this module's own
#       _atomic_write_json()/_read_json() primitives rather than inventing a
#       second persistence mechanism, and NEVER touching questions.json
#       itself: question.schema.json's `additionalProperties: false` on the
#       persisted question record stays exactly as strict as before.
#
# "Simpler phrasing" is honestly bounded. This does not run any kind of
# paraphrase over the question's own free-text sentence -- there is no
# semantic-rewriting capability in this module to do that safely, and
# attempting one would be an unearned claim about what the question means.
# What it DOES do is translate classify_tier()'s own small, closed,
# machine-oriented tier_reason vocabulary (a raw
# "hard_trigger:affects_pass_fail_verdict") into a plain-English sentence via
# a fixed lookup table (_TIER_REASON_TRIGGER_EXPLANATIONS /
# _explain_tier_reason()) -- content that TODAY never reaches a human at all,
# since build_escalation_package()'s own 9-field view omits tier_reason and
# exemption entirely -- and lay every option's own already-researched
# rationale out explicitly under a fixed "evidence" heading instead of
# leaving it buried inside options[].rationale.

#: classify_tier()'s own 3 hard-trigger names (see hard_triggers()), each
#: translated into one plain-English clause. An unrecognized trigger name
#: (this table drifting out of sync with hard_triggers()) falls back to
#: printing the raw trigger name rather than guessing at a synonym for it --
#: see _explain_tier_reason().
_TIER_REASON_TRIGGER_EXPLANATIONS: Dict[str, str] = {
    "affects_pass_fail_verdict": "it could change whether a test is reported PASS or FAIL",
    "affects_spec_intent": "it is about what the spec actually intends, not just an implementation detail",
    "affects_read_only_file_change": "it would mean changing a file this harness normally treats as read-only",
}


def _explain_tier_reason(tier_reason: str) -> List[str]:
    """Translate one of classify_tier()'s own fixed, literal tier_reason
    strings (see that function's docstring for the full closed vocabulary it
    produces) into plain-English sentences -- a lookup over known literal
    forms, never a paraphrase of the question itself. An unrecognized head
    or suffix (this function's vocabulary drifting out of sync with
    classify_tier()'s) is surfaced verbatim rather than silently dropped or
    guessed at, so a reader still sees the real value instead of nothing."""
    if not tier_reason:
        return []
    notes: List[str] = []
    parts = tier_reason.split(";")
    head = parts[0]
    if head == "decisions_store_hit":
        notes.append("A human already answered this exact question before; this reuses that answer.")
    elif head == "active_exemption":
        notes.append("An on-file, currently-active exemption already covers this check.")
    elif head == "resolved_from_manifest":
        notes.append("The answer was already recorded in this project's own environment manifest.")
    elif head == "no_hard_trigger_low_blast_radius":
        notes.append("Nothing about this looked pass/fail-critical, so the worst case if the "
                      "assumption is wrong is one wasted, cheaply re-run regression.")
    elif head.startswith("hard_trigger:"):
        for t in head[len("hard_trigger:"):].split(","):
            explanation = _TIER_REASON_TRIGGER_EXPLANATIONS.get(t)
            notes.append(f"This needs a human decision because {explanation}." if explanation
                          else f"This needs a human decision (hard trigger on file: {t!r}).")
    elif head.startswith("blast_radius_exceeds_safe_assume_bound:"):
        radius = head.split(":", 1)[1]
        notes.append("The risk if the assumption is wrong is wider than one regression (recorded "
                      f"blast radius: {radius!r}), so this cannot be auto-assumed.")
    else:
        notes.append(f"Reason on file: {tier_reason!r}.")
    for suffix in parts[1:]:
        if suffix == "overrides_prior_non_human_decision":
            notes.append("This overrides an earlier machine guess (not a human answer) for the same "
                          "question -- the machine's own earlier guess is not treated as settled.")
        elif suffix.startswith("covered_by_active_exemption:"):
            exemption_id = suffix.split(":", 1)[1]
            notes.append(f"An active exemption ({exemption_id}) already covers the underlying check, "
                          "but it does not by itself answer this specific question.")
    return notes


def request_clarification(store: "QuestionQueueStore", question_id: str, *,
                            requested_by: Optional[str] = None,
                            reason: Optional[str] = None,
                            now: Optional[datetime] = None,
                            record: bool = True) -> Dict[str, Any]:
    """A human signals "I don't understand question `question_id`" and gets
    back a reworded rendering of that SAME question, grounded entirely in
    evidence the persisted record already carries -- see the module-level
    comment above for the full contract (never a second filing mechanism,
    never an NLP paraphrase of the question's own sentence).

    Raises KeyError when no such question exists -- the exact sibling raise
    get_escalation_package() already uses for the identical lookup failure,
    so both "read this question" entry points fail the same way.

    Returns:
      {"question_id", "package": <build_escalation_package()'s 9 fields>,
       "plain_summary": [str, ...],  # ordered, plain-English restatement,
                                      # grounded in tier_reason/exemption/
                                      # assumption_if_unanswered/answer
       "evidence": [str, ...],       # every option's own pre-researched
                                      # rationale, labeled and cited
       "clarification_id": str|None, # None only when record=False or the
                                      # best-effort write itself failed
       "requested_at": iso8601}

    `record=True` (default) additionally appends a real audit entry to
    `store.clarifications_path` (`.dv-harness/question_queue/
    clarifications.json`), written through this module's own
    _atomic_write_json() -- the SAME atomic-write primitive
    QuestionQueueStore's own _save_questions()/_save_decisions() already
    use, so this is one more sibling artifact in that store, never a new
    write mechanism. The write is best-effort: a failure degrades to
    `clarification_id=None` rather than losing the rendering the human
    actually asked for (the one part of this call that must never fail)."""
    target = store.get_question(question_id)
    if target is None:
        raise KeyError(f"No question with id {question_id!r}")

    package = build_escalation_package(target)

    plain_summary: List[str] = [
        f"Question: {target['question']}",
        f"Where this comes from: {target['context_path']}",
    ]
    plain_summary.extend(_explain_tier_reason(target.get("tier_reason", "")))
    exemption = target.get("exemption")
    if exemption:
        plain_summary.append(
            "On-file exemption %s (owner %s, valid until %s): %s"
            % (exemption["id"], exemption["owner"], exemption["valid_until"], exemption["reason"])
        )
    if target["tier"] == TIER3_CANNOT_ASSUME:
        plain_summary.append("If nobody answers: " + target["assumption_if_unanswered"])
    elif target["tier"] == TIER2_SAFE_ASSUME:
        plain_summary.append(
            "Already logged and continuing with (a machine guess, not a human answer): "
            + str(target.get("answer"))
        )
    elif target["tier"] == TIER1_SELF_RESOLVE:
        plain_summary.append(
            "Already resolved automatically -- answer: %s (basis: %s)"
            % (target.get("answer"), target.get("basis"))
        )

    evidence: List[str] = []
    for opt in target["options"]:
        rationale = opt.get("rationale")
        evidence.append(f"{opt['label']}: {rationale}" if rationale
                         else f"{opt['label']}: (no additional rationale on file)")

    now_iso = _now_iso(now)
    clarification_id: Optional[str] = None
    if record:
        try:
            data = _read_json(store.clarifications_path,
                                {"schema_version": SCHEMA_VERSION, "requests": []})
            requests = data.setdefault("requests", [])
            clarification_id = "CLARIFY-%s-%03d" % (question_id, len(requests) + 1)
            requests.append({
                "clarification_id": clarification_id,
                "question_id": question_id,
                "question_key": target["question_key"],
                "requested_by": requested_by or "unknown",
                "reason": reason,
                "requested_at": now_iso,
                "plain_summary": plain_summary,
            })
            _atomic_write_json(store.clarifications_path, data)
        except Exception:
            clarification_id = None

    return {
        "question_id": question_id,
        "package": package,
        "plain_summary": plain_summary,
        "evidence": evidence,
        "clarification_id": clarification_id,
        "requested_at": now_iso,
    }


def list_clarification_requests(store: "QuestionQueueStore", *,
                                  question_id: Optional[str] = None) -> List[dict]:
    """Every clarification request on file (see request_clarification()),
    optionally filtered to one `question_id`. Read-only; never mints
    `store.clarifications_path` (a missing file reads as an empty list,
    same as `_read_json()`'s own default-on-absence contract elsewhere in
    this module)."""
    data = _read_json(store.clarifications_path, {"schema_version": SCHEMA_VERSION, "requests": []})
    reqs = data.get("requests", [])
    if question_id is not None:
        reqs = [r for r in reqs if r.get("question_id") == question_id]
    return reqs


def render_clarification_markdown(clarification: Dict[str, Any]) -> str:
    """Human-readable rendering of a request_clarification() result -- the
    same "one labeled section per block" shape this module's own
    render_escalation_package_markdown()/_render_decisions_md() already use,
    applied here to a clarification instead of a package/decision."""
    lines = [f"### Clarification for {clarification['question_id']}", ""]
    lines.append("**In plain terms:**")
    for line in clarification["plain_summary"]:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("**Evidence already found, per option:**")
    for line in clarification["evidence"]:
        lines.append(f"- {line}")
    if clarification.get("clarification_id"):
        lines.append("")
        lines.append(f"- **Recorded as:** {clarification['clarification_id']}")
    return "\n".join(lines)
