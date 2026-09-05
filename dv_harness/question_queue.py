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
from typing import Any, Callable, Dict, List, Optional

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
                       context: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None) -> dict:
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
        here, before anything is persisted."""
        context = dict(context or {})
        options = normalize_options(options)
        question_key = question_key or make_question_key(domain, question, context_path)
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
