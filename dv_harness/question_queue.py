"""dv_harness/question_queue.py -- the 3-tier ask-a-human protocol + question
queue mechanics (spec Part B: self-resolve / safe-to-assume / cannot-assume).

Scope note (this module implements Part B only): Part A's env.manifest.json
(VIP/DUT/env fact layers + a read-only MCP server) is a SEPARATE, not-yet-
built workstream. This module's Tier-1 self-resolve path is therefore
written against a `manifest_lookup` callable a caller may inject (e.g. once
Part A exists, `lambda path: mcp_client.get(...)`), defaulting to "nothing
resolvable" when omitted -- never a stub that pretends to read a manifest
that isn't there yet. What Part A does NOT need to exist for is this
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
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "question.schema.json"
SCHEMA_VERSION = "1.0"

# ---- Tiers ------------------------------------------------------------------

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


def classify_tier(context: Dict[str, Any], *, prior_decision: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
      3. The manifest shortcut is additionally gated on
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

    # 1. Hard triggers first -- before either Tier-1 shortcut.
    if triggers:
        if human_prior:
            return {"tier": TIER1_SELF_RESOLVE, "reason": "decisions_store_hit", "matched_triggers": []}
        reason = "hard_trigger:" + ",".join(triggers)
        if prior_decision is not None:
            # Audit signal: this ask escalates for real DESPITE an existing
            # machine-authored decision on file for the same question_key.
            reason += ";overrides_prior_non_human_decision"
        return {"tier": TIER3_CANNOT_ASSUME, "reason": reason, "matched_triggers": triggers}

    # 2. Prior-decision shortcut -- human answers only.
    if human_prior:
        return {"tier": TIER1_SELF_RESOLVE, "reason": "decisions_store_hit", "matched_triggers": []}

    # 3. Manifest shortcut -- never for a question whose own context is
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
                   blackboard: Optional[Any] = None):
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

        prior = self.find_decision(question_key)
        classification = classify_tier(context, prior_decision=prior)
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
            A caller wires this in by calling build_digest(store,
            trigger="stage_boundary", stage=new_stage) right after its own
            stage-transition code runs (not wired into engine.py itself in
            this change -- engine.py's stage-transition path is owned by a
            concurrent workstream this session; see this module's own
            report for the exact call site a future integration should use).
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
