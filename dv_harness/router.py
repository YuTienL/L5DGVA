# NOTICE (superseded 2026-08-28, 12-claim re-audit): the original industrial-
# grade-audit NOTICE below claimed this module was "NOT invoked by any
# executing code path" -- that is now FALSE, per CLAUDE.md's own Evidence
# Truth Rule ("current evidence wins and this file must be updated"). Real
# caller as of this audit: dv_harness/engine.py's run_stage() calls RouteResolver.resolve(node, protocol_decision=...) before every LLM call, feeding agent_profile.load_agent_profile(), SkillResolver.resolve(), MultiAgentOrchestrator.delegate() and the adapter's --agent flag.
# Original NOTICE text, now superseded: "this module is NOT invoked by any
# executing code path in dv_harness/ or .claude/agents/*.md as of this audit
# -- it is standalone/orphaned code."
#
# NOTICE (2026-09-04, AI-mechanism re-audit gap #4 "Route & Skill Resolver"):
# resolve() previously took only `node` and returned node.route/node.agent/
# node.skills verbatim, so a stage's skill set was 100% determined by the
# design-time table in .dv-harness/graph/main_graph.json -- byte-for-byte
# identical no matter what protocol/evidence THIS run carried. The real
# evidence-driven decision (protocol_router.resolve_protocol(), fed by
# engine._protocol_router_evidence()'s live user_goal/failing test/git-modified
# files/INTAKE subsystem boundary) already existed and already fired, but its
# result was stored beside the static answer as audit-only telemetry and never
# read back into it. resolve() now accepts that decision and folds the
# protocol's real skills into the returned `skills`, which run_stage() then
# resolves to paths and delegates -- i.e. the classification is now an INPUT
# to routing, the same "classify from real evidence, then look up" shape
# question_queue.route_owner() and connectivity.py's T1-T4 tiering use.
#
# NOTICE (2026-09-04, Research-Capability Evolution master prompt section 17
# "RESEARCH INTENT ROUTING"): a SECOND classify-then-look-up entry point now
# lives at the bottom of this module -- resolve_research_intent() /
# research_route_plan() / RouteResolver.resolve_intent(). It answers a
# different question than resolve() does (resolve() answers "this graph node
# is running, which agent/skills does it get"; resolve_intent() answers "the
# user typed this, is it a research request and what is the route"), and it
# deliberately shares this module's existing DEFAULT_ROUTES dispatch table
# rather than standing up a second router beside it. resolve() itself is
# UNCHANGED by that addition -- no existing DV/protocol/regression/signoff
# routing decision passes through any of the new code.
import itertools as _itertools
import json as _json

from .protocol_router import protocol_skill_routes

# 'research-route' -> 'research-architect' (2026-09-04) is a real entry, not a
# placeholder: research_route_plan() below resolves the architect's agent name
# THROUGH this table rather than hardcoding it, which is what keeps one
# dispatch table in this module instead of two. No graph node in
# .dv-harness/graph/main_graph.json declares `research-route`, so
# agent_dispatch.py (which reads the graph, never this dict) still reports
# research-architect as NOT_DISPATCHED, exactly as .claude/agents/ROSTER.md
# records it -- adding the route does not silently promote the profile to a
# stage-owning role.
DEFAULT_ROUTES={'analysis-route':'analysis-agent','implementation-route':'implementation-agent','build-route':'build-agent','debug-route':'debug-agent','regression-route':'regression-agent','review-route':'review-agent','lead-route':'dv-lead','research-route':'research-architect'}

# A graph node that declares the `protocol-router` skill has, by its own
# design-time declaration, said "which skills I actually need depends on which
# protocol this run is about" -- .claude/skills/CORE/protocol-router/SKILL.md
# is precisely the routing table resolve_protocol() executes, and its
# "Profile/VIP-Lookup Binding" section instructs that stage to go read the
# resolved protocol's profile/vip-lookup skills. Those are exactly the nodes
# whose skill list is widened here (DISCOVERY and PROTOCOL_CAPABILITY in the
# current main_graph.json; PROTOCOL_CAPABILITY is also where the real
# protocol_profile_binding_gate checks that those same skills were consulted).
# Deliberately NOT every node: appending `USB/usb-profile` to GIT_SYNC or
# SIGNOFF would be noise, not routing.
PROTOCOL_SENSITIVE_SKILLS=frozenset({'protocol-router'})

class RouteResolver:
 def __init__(self,root=None):
  # `root` is only needed to read .dv-harness/builder/protocol_builder_registry.json
  # for the resolved protocol's profile/vip-lookup skills; RouteResolver(None)
  # still resolves the static route/agent/skills exactly as before.
  self.root=root
 def _is_protocol_sensitive(self,node):
  return bool(PROTOCOL_SENSITIVE_SKILLS.intersection(node.skills or []))
 def resolve(self,node,protocol_decision=None):
  """Resolves route/agent/skills for one graph node.

  `protocol_decision` is protocol_router.resolve_protocol()'s real output for
  THIS run. When it resolved AND this node declared itself protocol-sensitive
  (see PROTOCOL_SENSITIVE_SKILLS), the protocol's real skills are appended to
  the node's static ones -- so two runs of the SAME node with different
  evidence genuinely get different skills. `route`/`agent` stay the static
  table's answer on purpose: resolve_protocol()'s `route` is a SKILL route
  (`USB/usb-profile`), not a graph route, and no evidence source anywhere in
  this harness maps a protocol onto a different agent -- inventing one would
  be fabrication, not routing.

  Static skills always come first and are never dropped; the returned
  `static_skills` preserves the pre-fold list so a caller can tell exactly
  what the dynamic decision added."""
  static_skills=list(node.skills or [])
  skills=list(static_skills)
  added_routes=[]
  if self._is_protocol_sensitive(node):
   for route in protocol_skill_routes(self.root,protocol_decision):
    name=route.rsplit('/',1)[-1]
    if name not in skills:
     skills.append(name);added_routes.append(route)
  return {'route':node.route,'agent':node.agent or DEFAULT_ROUTES.get(node.route),
          'skills':skills,'static_skills':static_skills,
          'protocol_skill_routes':added_routes}

 def resolve_intent(self, evidence, focus=None, documents=None):
  """The RUNTIME free-text front door: "the user asked for this -- is it a
  research request, and if so what is the route".

  Deliberately a separate method from resolve() rather than a parameter on
  it. resolve() is called once per graph node with a node in hand and must
  keep answering exactly what it answered before; this one is called with a
  user's words in hand and no node at all. Sharing a method would have meant
  giving resolve() a mode switch, which is how a router grows a second router
  inside itself.

  Returns {'research_decision': resolve_research_intent(...) output,
           'research_route_plan': research_route_plan(...) output or None}.
  A non-research request gets a resolved:False decision and a None plan --
  the caller then routes it exactly as it always did."""
  decision = resolve_research_intent(evidence)
  plan = (research_route_plan(decision, root=self.root, focus=focus,
                              documents=documents)
          if decision.get('resolved') else None)
  return {'research_decision': decision, 'research_route_plan': plan}


# --- Research intent routing (master prompt section 17) ----------------------
# Section 17 requires a permanent research intent path recognizing at minimum
# the five intents in RESEARCH_INTENTS below, with the default routing
#
#     Research Intent -> research-ingestion -> prior evidence lookup if
#     applicable -> research-architect -> Human Approval Gate
#
# and an explicit non-negotiable: "Do not interfere with existing DV/USB/PCIe/
# Ethernet/AMBA/MIPI/CAN-FD/regression/failure-triage/coverage/signoff
# workflows."
#
# Non-interference is STRUCTURAL here, not a matter of the classifier being
# careful. Nothing on the existing routing path calls any function in this
# section: engine.py's run_stage() calls resolve_protocol() then
# RouteResolver.resolve(), and neither of those is touched. A false positive
# in the vocabulary below can therefore misroute the NEW front door; it cannot
# reach, delay or alter a DV stage's route/agent/skills. The negative half of
# that claim is a real test, not an assertion -- test_research_intent_routing.py
# replays test_protocol_router.py's own evidence strings and asserts both that
# they classify as not-research AND that resolve_protocol()/resolve() return
# byte-identical results to before.
#
# WHICH EVIDENCE FIELDS ARE READ, and why not all five. protocol_router.py's
# FIELD_ORDER carries five fields; this classifier reads only the two that
# genuinely carry a statement of what the USER asked for:
#   * research_intent  -- set explicitly by the front door
#                         (commands.cmd_research), never guessed
#   * protocol_hint    -- engine._protocol_router_evidence() populates this
#                         with the live `user_goal` verbatim
# The other three (failing_test_name, active_config, modified_files,
# subsystem_boundary) are deliberately EXCLUDED. A git-modified file named
# `paper.pdf`, or a subsystem boundary containing the word "standard", is not
# a research request -- reading them here is precisely how a DV debug run
# would get hijacked into the research path, i.e. the interference section 17
# forbids. Narrowing the input is the mechanism, not an oversight.
import re as _re

RESEARCH_INTENTS = (
    'RESEARCH_ANALYSIS',
    'RESEARCH_COMPARE',
    'RESEARCH_ARCHITECTURE_IMPACT',
    'RESEARCH_DEEP_ANALYSIS',
    'RESEARCH_MULTI_DOCUMENT',
)

RESEARCH_INTENT_FIELDS = ('research_intent', 'protocol_hint')

# Section 53's four focus domains, verbatim. A focus narrows emphasis; it
# never changes the route (section 53: "must route into the same installed
# Skill/Agent logic and must not fork a second implementation").
RESEARCH_FOCUS_DOMAINS = ('regression', 'pss', 'debug', 'planning')

RESEARCH_ROUTE = 'research-route'
RESEARCH_INGESTION_SKILL = 'research-ingestion'
RESEARCH_INGESTION_SKILL_PATH = '.claude/skills/research-ingestion/SKILL.md'
RESEARCH_ARCHITECT_AGENT_PATH = '.claude/agents/research-architect.md'
RESEARCH_EVIDENCE_CARD_DIR = 'research/evidence_cards'

# Section 17's "prior evidence lookup IF APPLICABLE". Applicable when the
# request is about more than one document, or explicitly asks for comparison
# against what was already learned -- section 53 defines --compare as
# "standard analysis + stronger prior-evidence comparison" and --deep as
# "extended evidence + contradiction + benchmark analysis", both of which are
# meaningless without reading the prior cards.
PRIOR_EVIDENCE_LOOKUP_INTENTS = (
    'RESEARCH_COMPARE', 'RESEARCH_DEEP_ANALYSIS', 'RESEARCH_MULTI_DOCUMENT')

# --- Vocabulary, transcribed from the master prompt's own example requests ---
# Section 17's seven qualifying examples and section 52's four canonical
# prompts are the entire source of the phrases below; nothing here was
# invented to make a test pass. A request qualifies only when BOTH an action
# and a subject are present, which is what keeps ordinary DV phrasing out.
#
# STRONG actions are phrases whose object is always a body of knowledge, so
# they qualify against a METHOD subject too ("Study this regression-triage
# method." -- section 17). WEAK actions are ordinary DV verbs ("analyze",
# "compare", "review") that qualify ONLY against an unambiguous external
# DOCUMENT subject -- otherwise "compare the RTL implementation approach with
# the spec" would read as a research request.
_RESEARCH_STRONG_ACTIONS = (
    'study', 'learn from', 'adopt', 'deep research', 'research workflow',
    'research analysis', 'literature review',
)
_RESEARCH_WEAK_ACTIONS = (
    'analyze', 'analyse', 'analysis', 'compare', 'comparison', 'extract',
    'evaluate', 'assess', 'review', 'determine whether', 'decide whether',
    'ingest',
)
# Master prompt section 6's own source list: academic/arXiv/conference papers,
# standards, Accellera documents, vendor technical reports and application
# notes, architecture reports, engineering articles, benchmark reports,
# internal engineering and verification reports, technical design documents.
_RESEARCH_DOCUMENT_SUBJECTS = (
    'paper', 'papers', 'arxiv', 'preprint', 'preprints', 'publication',
    'publications', 'whitepaper', 'whitepapers', 'white paper', 'journal',
    'conference paper', 'literature', 'accellera', 'standard update',
    'standards update', 'standard revision', 'technical report',
    'technical reports', 'technical design document', 'application note',
    'application notes', 'benchmark report', 'benchmark reports',
    'architecture report', 'architecture reports', 'research report',
    'verification report', 'verification reports', 'engineering report',
    'engineering reports', 'engineering article', 'engineering articles',
)
_RESEARCH_METHOD_SUBJECTS = (
    'method', 'methods', 'methodology', 'methodologies', 'technique',
    'techniques', 'approach', 'approaches',
)

# Intent markers, checked in RESEARCH_INTENTS-independent precedence order
# (see _INTENT_PRECEDENCE). RESEARCH_ANALYSIS is the default -- section 53:
# "/research <file> = standard one-paper research analysis".
_MULTI_DOCUMENT_MARKERS = (
    'papers', 'publications', 'preprints', 'standards', 'documents',
    'technical reports', 'verification reports', 'multi-document',
    'multiple documents', 'each paper', 'per paper', 'all newly supplied',
)
_DEEP_MARKERS = (
    'deep research', 'deep analysis', 'deep-dive', 'deep dive', 'in-depth',
)
_ARCHITECTURE_IMPACT_MARKERS = (
    'architecture impact', 'architectural impact', 'impact on the architecture',
    'should change l5', 'should change the harness', 'architecture change',
    'changes the current dv agent harness', 'l5.x',
)
_COMPARE_MARKERS = (
    'compare', 'comparison', 'prior research', 'previous research',
    'prior evidence', 'previous papers', 'prior work', 'overlap',
    'contradiction', 'superseded',
)
_INTENT_PRECEDENCE = (
    ('RESEARCH_MULTI_DOCUMENT', _MULTI_DOCUMENT_MARKERS),
    ('RESEARCH_DEEP_ANALYSIS', _DEEP_MARKERS),
    ('RESEARCH_ARCHITECTURE_IMPACT', _ARCHITECTURE_IMPACT_MARKERS),
    ('RESEARCH_COMPARE', _COMPARE_MARKERS),
)


def _research_phrase_pattern(phrase):
    """One phrase -> one compiled pattern. Whitespace in a phrase matches any
    run of space/hyphen/underscore, so `standard update` also matches
    `standard-update`; the same not-adjacent-to-another-alnum boundary
    protocol_router._ALIAS_PATTERNS uses is applied on both ends, so `paper`
    does not fire inside `paperwork` and `ss` style accidents cannot happen."""
    body = r'[\s\-_]+'.join(_re.escape(tok) for tok in phrase.split())
    return _re.compile(r'(?<![A-Za-z0-9])' + body + r'(?![A-Za-z0-9])',
                       _re.IGNORECASE)


def _compile_all(phrases):
    return tuple((p, _research_phrase_pattern(p)) for p in phrases)


_STRONG_ACTION_PATTERNS = _compile_all(_RESEARCH_STRONG_ACTIONS)
_WEAK_ACTION_PATTERNS = _compile_all(_RESEARCH_WEAK_ACTIONS)
_DOCUMENT_SUBJECT_PATTERNS = _compile_all(_RESEARCH_DOCUMENT_SUBJECTS)
_METHOD_SUBJECT_PATTERNS = _compile_all(_RESEARCH_METHOD_SUBJECTS)
_INTENT_MARKER_PATTERNS = tuple(
    (intent, _compile_all(markers)) for intent, markers in _INTENT_PRECEDENCE)


def _matched(text, compiled):
    return [phrase for phrase, pat in compiled if pat.search(text)]


def _research_evidence_text(evidence):
    """The two user-intent-bearing fields, joined, in RESEARCH_INTENT_FIELDS
    order. A list/tuple value is joined the same way protocol_router.
    _field_text() joins one, so the two modules read a list identically."""
    parts = []
    for field in RESEARCH_INTENT_FIELDS:
        value = (evidence or {}).get(field)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(v) for v in value if v)
        else:
            parts.append(str(value))
    return ' '.join(p for p in parts if p.strip())


def resolve_research_intent(evidence):
    """Classifies a free-text request as one of RESEARCH_INTENTS, or as not a
    research request at all.

    Contract mirrors protocol_router.resolve_protocol() on purpose -- same
    `evidence` dict in, same never-raises rule, same structured
    {'resolved': False, ...} for "not recognized", and a mandatory non-empty
    `evidence` string on every return explaining what actually matched. A
    caller can hold both decisions side by side because they are the same
    shape.

    An explicit `evidence['research_intent']` naming one of RESEARCH_INTENTS
    is honored verbatim (that is the front door telling the router what the
    user chose, not the router guessing) -- see commands.cmd_research().

    Ambiguity resolves to NOT research. That direction is deliberate: a
    missed research request costs the user one explicit `dv-harness research`
    invocation, while a false positive is the interference section 17
    forbids."""
    text = _research_evidence_text(evidence)
    explicit = str(((evidence or {}).get('research_intent') or '')).strip().upper()
    if explicit in RESEARCH_INTENTS:
        return {
            'resolved': True,
            'intent': explicit,
            'route': RESEARCH_ROUTE,
            'agent': DEFAULT_ROUTES[RESEARCH_ROUTE],
            'matched_actions': [],
            'matched_subjects': [],
            'matched_intent_markers': [],
            'explicit': True,
            'evidence': (
                f"router.resolve_research_intent honored an explicit "
                f"research_intent field: '{explicit}' (no free-text "
                f"classification was performed)"),
        }
    if not text.strip():
        return _research_unresolved(
            'no populated research-intent evidence field '
            f'({", ".join(RESEARCH_INTENT_FIELDS)})')

    strong = _matched(text, _STRONG_ACTION_PATTERNS)
    weak = _matched(text, _WEAK_ACTION_PATTERNS)
    documents = _matched(text, _DOCUMENT_SUBJECT_PATTERNS)
    methods = _matched(text, _METHOD_SUBJECT_PATTERNS)

    if strong and (documents or methods):
        subjects = documents + methods
    elif weak and documents:
        subjects = list(documents)
    else:
        return _research_unresolved(
            'no research ACTION+SUBJECT pair found '
            f'(strong actions={strong or []}, weak actions={weak or []}, '
            f'document subjects={documents or []}, '
            f'method subjects={methods or []}); both halves are required')

    intent = 'RESEARCH_ANALYSIS'
    markers = []
    for candidate, compiled in _INTENT_MARKER_PATTERNS:
        hits = _matched(text, compiled)
        if hits:
            intent, markers = candidate, hits
            break

    actions = strong + weak
    marker_note = markers or ['(none -- RESEARCH_ANALYSIS default, master prompt section 53)']
    return {
        'resolved': True,
        'intent': intent,
        'route': RESEARCH_ROUTE,
        'agent': DEFAULT_ROUTES[RESEARCH_ROUTE],
        'matched_actions': actions,
        'matched_subjects': subjects,
        'matched_intent_markers': markers,
        'explicit': False,
        'evidence': (
            f"router.resolve_research_intent matched research action(s) "
            f"{actions} against subject(s) {subjects} in evidence field(s) "
            f"{list(RESEARCH_INTENT_FIELDS)}; intent '{intent}' selected by "
            f"marker(s) {marker_note}"),
    }


def _research_unresolved(reason):
    return {
        'resolved': False,
        'intent': None,
        'route': None,
        'agent': None,
        'matched_actions': [],
        'matched_subjects': [],
        'matched_intent_markers': [],
        'explicit': False,
        'reason': 'NOT_A_RESEARCH_REQUEST',
        'evidence': f'router.resolve_research_intent: {reason}',
    }


def _asset_exists(root, relpath):
    if root is None:
        return None
    try:
        from pathlib import Path as _Path
        return (_Path(root) / relpath).exists()
    except Exception:
        return None


def research_route_plan(decision, root=None, focus=None, documents=None):
    """Section 17's default routing, as an ordered list of REAL installed
    assets -- never a narrative.

        research-ingestion -> prior evidence lookup (if applicable)
        -> research-architect -> Human Approval Gate

    Every step names the file or function that actually performs it, and when
    `root` is supplied every step carries a real `exists` check against that
    tree, so a plan can be verified rather than believed. Returns None for an
    unresolved decision -- there is no research plan for a non-research
    request, and inventing one would be the interference section 17 forbids.

    This function ROUTES. It does not ingest a document, read a card, score a
    candidate or approve anything: section 19's "Do NOT place core logic in
    the command itself" applies to the routing layer for the same reason."""
    if not isinstance(decision, dict) or not decision.get('resolved'):
        return None
    intent = decision.get('intent')
    if focus is not None and focus not in RESEARCH_FOCUS_DOMAINS:
        raise ValueError(
            f'Unknown research focus: {focus!r} '
            f'(master prompt section 53 defines {list(RESEARCH_FOCUS_DOMAINS)})')

    docs = [str(d) for d in (documents or [])]
    prior_lookup_applicable = (
        intent in PRIOR_EVIDENCE_LOOKUP_INTENTS or len(docs) > 1)

    # The Human Approval Gate is the EXISTING ControlPlane, keyed on the stage
    # id capability_evolution.py already owns -- imported here rather than
    # re-typed so the two cannot drift. Lazy, to keep this module's import
    # cost unchanged for engine.py, which imports router on every start.
    from .capability_evolution import HUMAN_APPROVAL_STAGE

    steps = [{
        'step': RESEARCH_INGESTION_SKILL,
        'kind': 'skill',
        'asset': RESEARCH_INGESTION_SKILL_PATH,
        'mechanism': 'dv_harness.doc_extraction.build_research_evidence_card_skeleton',
        'produces': 'ResearchEvidenceCard (research/evidence_cards/<stem>.card.json)',
        'applicable': True,
        'applicability_reason': 'always -- section 17 routes every research intent through ingestion first',
    }]
    steps.append({
        'step': 'prior-evidence-lookup',
        'kind': 'evidence-lookup',
        'asset': RESEARCH_EVIDENCE_CARD_DIR,
        'mechanism': 'existing research/evidence_cards/ + dv_harness.memory.MemoryStore.find',
        'produces': 'prior ResearchEvidenceCard / Engineering Memory matches',
        'applicable': prior_lookup_applicable,
        'applicability_reason': (
            f'intent {intent} is in PRIOR_EVIDENCE_LOOKUP_INTENTS'
            if intent in PRIOR_EVIDENCE_LOOKUP_INTENTS else
            'more than one document supplied' if len(docs) > 1 else
            'section 17 "if applicable": a single-document standard analysis '
            'with no comparison asked for does not require it'),
    })
    steps.append({
        'step': DEFAULT_ROUTES[RESEARCH_ROUTE],
        'kind': 'agent',
        'asset': RESEARCH_ARCHITECT_AGENT_PATH,
        'mechanism': 'dv_harness.capability_evolution.decide_recommendation',
        'produces': 'CapabilityEvolutionCandidate (KEEP/ENHANCE/ADD/EXPERIMENT/REJECT)',
        'applicable': True,
        'applicability_reason': 'always -- section 17 routes every research intent to the architect',
    })
    steps.append({
        'step': 'human-approval-gate',
        'kind': 'gate',
        'asset': 'dv_harness/control_plane.py',
        'mechanism': (
            f'dv_harness.control_plane.ControlPlane.approve('
            f'stage="{HUMAN_APPROVAL_STAGE}") / '
            f'capability_evolution.assert_human_approval'),
        'produces': 'a recorded human decision -- the route STOPS here',
        'applicable': True,
        'applicability_reason': 'always -- master prompt section 43; research is not implementation (section 2.4)',
    })

    for step in steps:
        step['exists'] = _asset_exists(root, step['asset'])

    return {
        'intent': intent,
        'route': RESEARCH_ROUTE,
        'agent': DEFAULT_ROUTES[RESEARCH_ROUTE],
        'focus': focus,
        'documents': docs,
        'human_approval_stage': HUMAN_APPROVAL_STAGE,
        'stops_before_implementation': True,
        'steps': [s for s in steps if s['applicable']],
        'skipped_steps': [s for s in steps if not s['applicable']],
        'all_steps': steps,
        'decision': decision,
    }


# --- Skill-Routing Accuracy Tracking (2026-09-07, skill_routing_accuracy_tracking) ------
#
# GAP, confirmed by direct search before writing a line of this: neither RouteResolver.
# resolve() nor protocol_router.resolve_protocol() left any real, persisted record of the
# routing decision they made for a given stage/run -- each is a pure function computing an
# answer from its own inputs, and nothing downstream ever wrote that answer anywhere a later
# reader could join it against what actually happened next. So a question this project's own
# real evidence trail could answer in principle -- "when this stage's skill/agent routing
# resolved a particular way, did the stage then fail for a reason a missing or wrong-routed
# skill would explain" -- had no real data behind it at all.
#
# What follows is ADDITIVE ONLY. resolve()/resolve_protocol()/resolve_intent() above are
# completely untouched: their signatures, their return values, and their behavior for every
# existing caller (engine.run_stage(), the test suite pinned in
# test_route_resolver_protocol_fold_in.py, commands.cmd_research()) are unchanged by anything
# below. This section adds two new, OPTIONAL functions a caller invokes AFTER calling
# resolve()/resolve_protocol() with the real decision those functions already returned --
# never a replacement for either, and never a second place that decides a route.
#
# REUSE OVER REINVENT: the persistence mechanism is the SAME `storage.StateStore.event()`
# every other subsystem in this harness already writes `.dv-harness/events.jsonl` through
# (loop_telemetry.py, live_event_model.py, gui_audit_log.py, ...) -- there is no second event
# file and no second serializer here. The read-back half reuses
# `loop_telemetry.read_events()` (that module's own public, generic events.jsonl reader,
# already the reuse target `platform_health.py` and `live_event_model.py` both point at) --
# there is no third independent events.jsonl parser in this package either.
#
# The outcome-classification vocabulary is GROUNDED, never invented: every literal string it
# matches against a stage's own real `gates.evaluate_stage_evidence()` `reasons` list is a
# real, already-shipped sentinel this harness's own routing/dispatch machinery writes today --
# `protocol_router.resolve_protocol()`'s own `"UNRESOLVED_NEEDS_ROUTING_QUESTION"` reason
# string (this very module's sibling function, above), `tools/verification_flow/
# protocol_profile_binding_gate.py`'s own real `gate_id`
# ("protocol_profile_binding_gate", registered in `gates.STAGE_GATES["PROTOCOL_CAPABILITY"]`)
# and its own literal `"PROFILE_SKILL_NOT_CONSULTED"` FAIL reason (that gate exists precisely
# to check whether a protocol's resolved profile/vip-lookup skill was actually consulted --
# see this file's own NOTICE at the top), and `agent_dispatch.py`'s own real
# `NOT_DISPATCHED` status literal. A gate-reasons list matching none of these is honestly
# `OUTCOME_NOT_EXPLAINED_BY_ROUTING`, never silently folded into either "routing was fine" or
# "routing was the cause" -- and a caller that has not yet observed any outcome at all
# (`gate_reasons` empty/absent) is honestly `NO_OUTCOME_YET`, kept distinct from "checked and
# found nothing routing-related", per this project's own Evidence Truth Rule.
#
# Per rule 3 of this batch's own governing instructions, no scoring weight, threshold or
# routing DECISION is ever changed by anything below -- this section only RECORDS a decision
# that was already made (by the unmodified resolve()/resolve_protocol() above) and RECORDS a
# later observed outcome; `skill_routing_accuracy_report()` at the bottom only aggregates and
# reports those two real record streams. Applying a finding here to production routing
# behavior (e.g. auto-preferring one route over another) would itself be a production-behavior
# change and, like every other one in this project, would have to be proposed as data through
# `capability_evolution.py`'s existing controlled-experiment machinery for a human to approve
# -- nothing here does that, or could, since nothing here writes to `DEFAULT_ROUTES`,
# `PROTOCOL_SENSITIVE_SKILLS`, or any other value `resolve()`/`resolve_protocol()` actually
# reads.

#: The two real event names this section ever writes -- a fixed, closed vocabulary, the same
#: "an unrecognized name is worse than no event" discipline `loop_telemetry.emit()`/
#: `live_event_model.emit()` already enforce for their own vocabularies.
ROUTING_TELEMETRY_EVENTS = ('ROUTING_DECISION_RECORDED', 'ROUTING_OUTCOME_RECORDED')

#: `record_routing_decision()`'s own `kind` argument -- which of the two real router
#: functions above produced the `decision` dict being recorded. Never a third value: this
#: module has exactly two decision-producing functions, `resolve()` and `resolve_protocol()`.
ROUTING_DECISION_KIND_ROUTE = 'route_resolution'       # RouteResolver.resolve()'s own dict
ROUTING_DECISION_KIND_PROTOCOL = 'protocol_resolution'  # protocol_router.resolve_protocol()'s own dict
ROUTING_DECISION_KINDS = (ROUTING_DECISION_KIND_ROUTE, ROUTING_DECISION_KIND_PROTOCOL)

#: The grounded outcome-classification vocabulary `classify_routing_outcome()` returns.
#: `NO_OUTCOME_YET` and `OUTCOME_NOT_EXPLAINED_BY_ROUTING` are the two honest "we do not have
#: a routing explanation" answers, kept deliberately distinct (absent evidence vs. evidence
#: that was checked and found unrelated); the other three each cite the one real literal
#: sentinel that earned them, named beside each one below.
OUTCOME_NO_OUTCOME_YET = 'NO_OUTCOME_YET'
OUTCOME_UNRESOLVED_PROTOCOL = 'OUTCOME_EXPLAINED_UNRESOLVED_PROTOCOL'  # cites protocol_router.resolve_protocol()'s own reason
OUTCOME_MISSING_SKILL = 'OUTCOME_EXPLAINED_MISSING_SKILL'              # cites protocol_profile_binding_gate's own reason
OUTCOME_WRONG_AGENT = 'OUTCOME_EXPLAINED_WRONG_AGENT'                  # cites agent_dispatch.py's own NOT_DISPATCHED status
OUTCOME_NOT_EXPLAINED = 'OUTCOME_NOT_EXPLAINED_BY_ROUTING'
ROUTING_OUTCOME_STATUSES = (
    OUTCOME_NO_OUTCOME_YET, OUTCOME_UNRESOLVED_PROTOCOL, OUTCOME_MISSING_SKILL,
    OUTCOME_WRONG_AGENT, OUTCOME_NOT_EXPLAINED,
)

# The real, cited literal strings each OUTCOME_EXPLAINED_* status matches against a stage's
# own real `reasons` list (a list of plain strings; `gates._evaluate_stage_evidence_core()`
# builds each failing entry as `f"{gate_id}: {gr.detail}"`, so both a gate's own id and its
# own detail dict's string repr are present in the joined text this module scans).
_REASON_UNRESOLVED_PROTOCOL = 'UNRESOLVED_NEEDS_ROUTING_QUESTION'
_REASON_PROFILE_GATE_ID = 'protocol_profile_binding_gate'
_REASON_PROFILE_SKILL_NOT_CONSULTED = 'PROFILE_SKILL_NOT_CONSULTED'
_REASON_NOT_DISPATCHED = 'NOT_DISPATCHED'


class RoutingTelemetryError(ValueError):
    """Raised by record_routing_decision()/record_routing_outcome() for a kind/decision_id
    outside their own real closed contracts, or a payload that will not JSON-serialize."""


def assert_routing_telemetry_events_total():
    """ROUTING_TELEMETRY_EVENTS is exactly the two names this section's writers ever use, with
    no duplicate -- run at import so a future edit that silently widens or narrows it fails a
    test rather than drifting unnoticed, the same self-check convention
    `loop_telemetry.assert_events_match_section_108()` / `live_event_model.
    assert_gui_live_events_total()` already apply to their own vocabularies."""
    if len(ROUTING_TELEMETRY_EVENTS) != 2:
        raise AssertionError(
            f'ROUTING_TELEMETRY_EVENTS must carry exactly 2 names; found '
            f'{len(ROUTING_TELEMETRY_EVENTS)}: {list(ROUTING_TELEMETRY_EVENTS)}')
    if len(set(ROUTING_TELEMETRY_EVENTS)) != len(ROUTING_TELEMETRY_EVENTS):
        raise AssertionError(
            f'ROUTING_TELEMETRY_EVENTS carries a duplicate name: {list(ROUTING_TELEMETRY_EVENTS)}')


def assert_no_routing_telemetry_verdict_vocabulary_collision():
    """This section's own event names and outcome statuses share no token with
    `dv_harness.models.Status` -- the same guard several sibling modules in this codebase
    already run against their own domain vocabularies, so a routing-telemetry status can never
    be mistaken for (or silently collide with) a real stage verdict."""
    from .models import Status
    verdict_values = {s.value for s in Status}
    collisions = (set(ROUTING_TELEMETRY_EVENTS) | set(ROUTING_OUTCOME_STATUSES)) & verdict_values
    if collisions:
        raise AssertionError(
            f'skill-routing-accuracy-tracking vocabulary collides with '
            f'dv_harness.models.Status: {sorted(collisions)}')


assert_routing_telemetry_events_total()
assert_no_routing_telemetry_verdict_vocabulary_collision()


#: A real, monotonically-increasing per-process counter, so two `record_routing_decision()`
#: calls made back-to-back in the SAME process can never collide on `decision_id` even when
#: `engine.now()`'s own isoformat resolution happens to land on the identical microsecond
#: twice in a row (a real, documented edge case `loop_telemetry.new_run_id()`'s own docstring
#: already accepts for its coarser second-resolution stamp; this counter closes it here rather
#: than merely accepting it).
_ROUTING_DECISION_SEQ = _itertools.count(1)


def _routing_event_ts_and_pid():
    """The same real UTC-ISO timestamp format every event in this harness uses
    (`engine.now()`), imported lazily -- router.py is imported at module level by engine.py
    (see the NOTICE at the top of this file), so an eager `from .engine import now` here would
    be a real import cycle; every other module in this codebase with the identical constraint
    (loop_telemetry.emit(), live_event_model.emit()) defers this same import for the same
    reason."""
    from .engine import now
    import os
    return now(), os.getpid()


def classify_routing_outcome(gate_reasons):
    """Classify a stage's real, already-computed gate-failure reason strings for whether the
    failure is one a missing/wrong-routed skill would explain.

    `gate_reasons` is `gates.evaluate_stage_evidence()`'s own real `reasons` list for the
    stage this routing decision fed -- passed through verbatim by the caller, never
    re-derived or fabricated here. This is a LITERAL match against the small, closed, cited
    vocabulary named above `_REASON_*`, never a semantic reading of gate text: a real gate
    failure whose text matches none of those three real sentinels is honestly
    `OUTCOME_NOT_EXPLAINED_BY_ROUTING`, and an empty/absent `gate_reasons` (no outcome has
    been observed at all yet) is honestly `OUTCOME_NO_OUTCOME_YET` -- neither is ever guessed
    toward the other.

    Returns `{"status": <one of ROUTING_OUTCOME_STATUSES>, "matched_statuses": [...]}` --
    `matched_statuses` carries every one of the three OUTCOME_EXPLAINED_* signals that
    actually matched (a real stage can genuinely fail more than one of these at once), with
    `status` set to the first one found in the fixed order below; both fields are `[]`/one of
    the two non-explained values when nothing (or nothing at all) matched."""
    if not gate_reasons:
        return {'status': OUTCOME_NO_OUTCOME_YET, 'matched_statuses': []}
    text = '\n'.join(str(r) for r in gate_reasons)
    matched = []
    if _REASON_UNRESOLVED_PROTOCOL in text:
        matched.append(OUTCOME_UNRESOLVED_PROTOCOL)
    if _REASON_PROFILE_GATE_ID in text and _REASON_PROFILE_SKILL_NOT_CONSULTED in text:
        matched.append(OUTCOME_MISSING_SKILL)
    if _REASON_NOT_DISPATCHED in text:
        matched.append(OUTCOME_WRONG_AGENT)
    if not matched:
        return {'status': OUTCOME_NOT_EXPLAINED, 'matched_statuses': []}
    return {'status': matched[0], 'matched_statuses': matched}


def _assert_json_serializable(record, what):
    try:
        _json.dumps(record, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise RoutingTelemetryError(f'{what} is not JSON-serializable: {e}') from e


def record_routing_decision(store, decision, *, kind, stage=None, run_id=None, source=None):
    """Record ONE real routing decision -- the ALREADY-COMPUTED return value of
    `RouteResolver.resolve()` (`kind=ROUTING_DECISION_KIND_ROUTE`) or
    `protocol_router.resolve_protocol()` (`kind=ROUTING_DECISION_KIND_PROTOCOL`) -- through
    the real `storage.StateStore.event()` audit trail.

    `store` is a real `storage.StateStore` (or any object exposing an `.event(dict)` method of
    that identical shape). `decision` must be the real dict either function already returned
    -- this function never calls, re-derives, or second-guesses either one; it only persists
    the answer they already gave. Neither `resolve()` nor `resolve_protocol()`'s own
    signature, return value, or behavior is read, mutated, or in any way touched by this
    function's existence -- it is a NEW, OPTIONAL sibling a caller invokes strictly AFTER the
    real call it is recording.

    Returns the full record actually written, including its own `decision_id` -- the ONE
    thing a caller must hold onto to later join a real outcome via
    `record_routing_outcome()`."""
    if kind not in ROUTING_DECISION_KINDS:
        raise RoutingTelemetryError(
            f'kind={kind!r} is not one of {list(ROUTING_DECISION_KINDS)}')
    if not isinstance(decision, dict):
        raise RoutingTelemetryError(
            f'decision must be the real dict RouteResolver.resolve() or '
            f'protocol_router.resolve_protocol() already returned, got {type(decision)!r}')
    ts, pid = _routing_event_ts_and_pid()
    seq = next(_ROUTING_DECISION_SEQ)
    decision_id = f'{kind}:{stage or decision.get("route") or "unknown"}:{ts}:{pid}:{seq}'
    record = {
        'ts': ts,
        'event': 'ROUTING_DECISION_RECORDED',
        'decision_id': decision_id,
        'kind': kind,
        'decision': decision,
    }
    if stage is not None:
        record['stage'] = stage
    if run_id is not None:
        record['run_id'] = run_id
    if source is not None:
        record['source'] = str(source)
    _assert_json_serializable(record, 'decision')
    store.event(record)
    return record


def record_routing_outcome(store, decision_id, gate_reasons=None, *,
                           stage=None, run_id=None, source=None):
    """Record the real, later-observed outcome for a decision previously recorded by
    `record_routing_decision()`, joined by that call's own `decision_id`.

    `gate_reasons` is `gates.evaluate_stage_evidence()`'s own real `reasons` list for the
    stage this routing decision fed -- an absent/empty list is honestly classified
    `OUTCOME_NO_OUTCOME_YET` (see `classify_routing_outcome()`), never guessed. Like
    `record_routing_decision()`, this is a purely additive sibling: no existing function's
    signature or behavior is touched by this one's existence.

    Returns the full record actually written."""
    if not decision_id or not isinstance(decision_id, str):
        raise RoutingTelemetryError(
            'decision_id must be the real, non-empty decision_id record_routing_decision() '
            'returned for the decision this outcome is for')
    classification = classify_routing_outcome(gate_reasons or [])
    ts, _pid = _routing_event_ts_and_pid()
    record = {
        'ts': ts,
        'event': 'ROUTING_OUTCOME_RECORDED',
        'decision_id': decision_id,
        'status': classification['status'],
        'matched_statuses': classification['matched_statuses'],
        'gate_reasons': list(gate_reasons or []),
    }
    if stage is not None:
        record['stage'] = stage
    if run_id is not None:
        record['run_id'] = run_id
    if source is not None:
        record['source'] = str(source)
    _assert_json_serializable(record, 'gate_reasons')
    store.event(record)
    return record


#: The honest empty-state reason, naming the real writer this report reads.
NO_ROUTING_DECISIONS_RECORDED = 'NO_ROUTING_DECISIONS_RECORDED'


def skill_routing_accuracy_report(root, *, scan_lines=None):
    """Read back and join every real `record_routing_decision()`/`record_routing_outcome()`
    pair recorded so far in `.dv-harness/events.jsonl`, and report how often a routed
    decision's later observed outcome was one a missing/wrong-routed skill would explain.

    Reuses `loop_telemetry.read_events()` -- that module's own public, generic events.jsonl
    reader -- rather than a third independent parser beside it and `live_event_model.
    read_events()`'s own identical re-export. A project on which neither
    `record_routing_decision()` nor `record_routing_outcome()` has ever been called reports
    the honest `{"available": False, "reason": NO_ROUTING_DECISIONS_RECORDED, ...}` rather than
    a fabricated report -- this is a REACHED capability, not a WIRED one: nothing in
    `engine.run_stage()` calls either recording function today, so a bare project's own real
    events.jsonl genuinely carries none of these records yet, and this function must never
    present that absence as a clean 100%-accurate report.

    A decision recorded more than once with the SAME decision_id (should never happen in
    practice, since decision_id is minted fresh per `record_routing_decision()` call) is
    deduplicated to its first occurrence; a decision recorded with more than one outcome uses
    only the LATEST outcome (by scan order) for that decision_id, since a later real
    observation supersedes an earlier one.

    The `explains_failure_rate` is computed ONLY over decisions whose outcome resolved to one
    of `OUTCOME_EXPLAINED_*`/`OUTCOME_NOT_EXPLAINED_BY_ROUTING` (i.e. a real outcome WAS
    observed) -- a decision still sitting at `NO_OUTCOME_YET` never counts toward either side
    of that rate, and a zero denominator reports the rate as `None` with a real reason rather
    than a fabricated number."""
    from .loop_telemetry import read_events as _read_shared_events
    kwargs = {} if scan_lines is None else {'scan_lines': scan_lines}
    entries, scanned, truncated = _read_shared_events(root, **kwargs)

    decisions = {}
    for e in entries:
        if e.get('event') != 'ROUTING_DECISION_RECORDED':
            continue
        did = e.get('decision_id')
        if not did or did in decisions:
            continue
        decisions[did] = e

    outcomes = {}
    for e in entries:
        if e.get('event') != 'ROUTING_OUTCOME_RECORDED':
            continue
        did = e.get('decision_id')
        if not did:
            continue
        outcomes[did] = e  # later entries in scan order overwrite earlier ones

    if not decisions:
        return {
            'available': False,
            'reason': NO_ROUTING_DECISIONS_RECORDED,
            'events_scanned': scanned,
            'scan_truncated': truncated,
        }

    per_decision = []
    status_counts = {s: 0 for s in ROUTING_OUTCOME_STATUSES}
    for did, dec_event in decisions.items():
        outcome_event = outcomes.get(did)
        status = outcome_event['status'] if outcome_event else OUTCOME_NO_OUTCOME_YET
        status_counts[status] = status_counts.get(status, 0) + 1
        per_decision.append({
            'decision_id': did,
            'kind': dec_event.get('kind'),
            'stage': dec_event.get('stage'),
            'route': (dec_event.get('decision') or {}).get('route'),
            'status': status,
            'matched_statuses': (outcome_event or {}).get('matched_statuses', []),
        })

    explained = (status_counts[OUTCOME_UNRESOLVED_PROTOCOL]
                 + status_counts[OUTCOME_MISSING_SKILL]
                 + status_counts[OUTCOME_WRONG_AGENT])
    not_explained = status_counts[OUTCOME_NOT_EXPLAINED]
    observed_denominator = explained + not_explained
    explains_failure_rate = (explained / observed_denominator) if observed_denominator else None

    return {
        'available': True,
        'decisions_recorded': len(decisions),
        'decisions_with_outcome_recorded': sum(1 for d in per_decision
                                               if d['status'] != OUTCOME_NO_OUTCOME_YET),
        'status_counts': status_counts,
        'explains_failure_rate': explains_failure_rate,
        'explains_failure_rate_reason': (
            None if observed_denominator else
            'no decision with an observed outcome yet -- rate is not computable, never fabricated'),
        'decisions': per_decision,
        'events_scanned': scanned,
        'scan_truncated': truncated,
    }
