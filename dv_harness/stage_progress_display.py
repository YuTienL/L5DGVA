"""dv_harness/stage_progress_display.py -- the stage-boundary progress display
(banner + checklist + completeness % + "what still needs your detail" reminder
+ time/token summary) and its persisted markdown report.

WHAT THIS CLOSES (2026-09-04, stage-progress-display gap-close). The user's
own four-part spec asked for: (1) which stage is running, what is still
outstanding in it, and how close it is to done; (2) at every stage START a
clearly visible LOGO (clarified by the user as text/ASCII art, not an image
file) plus the checklist of required input documents/files/data with a
completeness %, plus an explicit reminder naming the items that still need
more detail from the user; (3) at every stage END the same visible logo plus
the output file/data checklist with completeness %, plus total execution time
including every sub-agent and the total tokens consumed; (4) both displays
persisted as reports.

What already existed and is REUSED here rather than rebuilt:
  - engine._emit_stage_start_marker()/_emit_stage_done_marker(): the real,
    already-wired stage-transition print points. This module supplies the
    body; those two functions keep emitting their one-line greppable marker
    exactly as before (engine.py calls the renderers here ALONGSIDE them, so
    a log scraper keying on STAGE_MARKER_PREFIX is unaffected).
  - gates.STAGE_GATES: the real per-stage gate registry. Every gate id in it
    is an evidence block the stage MUST carry, so it is the authoritative
    source for "what this stage requires" -- no parallel checklist source is
    invented here.
  - gates.INTAKE_FIELD_QUESTIONS: the real, already-written human-readable
    Traditional Chinese questions for intake fields, reused verbatim for the
    "please provide more detail on X" reminder instead of a second wording.
  - graph.Node.blackboard_read / blackboard_write / expected_evidence /
    expected_outputs: the real per-node declarations in main_graph.json.
  - engine._checklist_item_present(): the real presence checker (blackboard
    topic written? file on disk? evidence field truthy?), imported rather
    than reimplemented.
  - stage_profile_report.stage_time_and_token_summary(): the real per-stage
    wall-clock/agent-runtime/token numbers StageExecutionProfiler already
    records, including one row per sub-agent run (see that function).

DELIBERATE DESIGN CHOICES:
  - Pure 7-bit ASCII for the banner. Box-drawing characters render as
    mojibake or raise UnicodeEncodeError on a Windows cp950/cp437 console
    (this project's primary platform), which would turn an observability
    feature into a crash on the exact machine it is meant to help.
  - Every renderer is a pure string function taking already-computed data,
    so the persisted report file and the terminal output are the SAME text
    by construction -- they cannot drift, because there is only one render.
  - Informational only. Nothing here raises into run_stage(); engine.py
    wraps both call sites so a display/report failure can never turn a
    completed stage into a failed one.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

WIDTH = 80
BANNER_FILL = "#"

# --- the ASCII wordmark ------------------------------------------------------
# A 5-row block font, only the 4 glyphs the "DV L5" wordmark needs. Kept as
# data (not a pre-rendered blob) so the mark is assembled the same way every
# time and a glyph fix lands in one place.
_GLYPHS = {
    "D": ("####0#   #0#   #0#   #0#### "),
    "V": ("#   #0#   #0#   #0 # # 0  #  "),
    "L": ("#    0#    0#    0#    0#####"),
    "5": ("#####0#    0#### 0    #0#### "),
    " ": ("  0  0  0  0  "),
}
_WORDMARK = "DV L5"


def _wordmark_rows() -> List[str]:
    """The 5 rendered rows of the 'DV L5' block-letter wordmark.

    Each glyph's rows are padded to that glyph's own widest row before the
    columns are joined. Without this a glyph whose top row is narrower than
    its body (e.g. 'D': '####' over '#   #') shifts every glyph to its right
    by one column on that row only, which is exactly the kind of one-character
    skew that makes ASCII art look broken rather than deliberate."""
    columns = []
    for ch in _WORDMARK:
        rows = _GLYPHS[ch].split("0")
        w = max(len(r) for r in rows)
        columns.append([r.ljust(w) for r in rows])
    return ["  ".join(col[r] for col in columns) for r in range(5)]


def render_banner(stage: str, phase: str, info_lines: Optional[List[str]] = None,
                  timestamp: Optional[str] = None) -> str:
    """The stage-boundary LOGO: a framed ASCII-art 'DV L5' wordmark beside a
    short info column naming the phase (START/DONE) and this stage.

    `phase` is "START" or "DONE" (any other string is rendered verbatim, so a
    future third boundary needs no change here). `info_lines` are the caller's
    own extra right-column lines (verdict, position, completeness); they are
    truncated to fit the frame rather than wrapping, because a banner that
    reflows stops being scannable."""
    ts = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    left = _wordmark_rows()
    right = [
        "DV AGENT HARNESS L5",
        f">>>>>  STAGE {phase}  <<<<<",
        f"STAGE : {stage}",
    ]
    right.extend(info_lines or [])
    right.append(f"TIME  : {ts}")

    left_w = max(len(r) for r in left)
    rows = max(len(left), len(right))
    left += [""] * (rows - len(left))
    right += [""] * (rows - len(right))

    inner = WIDTH - 4  # "# " + content + " #"
    body = []
    for lrow, rrow in zip(left, right):
        cell = f"{lrow:<{left_w}}  |  {rrow}"
        body.append(f"{BANNER_FILL} {cell[:inner]:<{inner}} {BANNER_FILL}")

    bar = BANNER_FILL * WIDTH
    blank = f"{BANNER_FILL} {'':<{inner}} {BANNER_FILL}"
    return "\n".join([bar, blank] + body + [blank, bar])


# --- checklists --------------------------------------------------------------
# An item is {item_id, kind, source, description, present}. `source` names the
# REAL declaration this item came from, so a reader can always trace a
# checklist line back to the file that demanded it:
#   "graph.blackboard_read"    -- main_graph.json node.blackboard_read
#   "graph.expected_evidence"  -- main_graph.json node.expected_evidence
#   "graph.blackboard_write"   -- main_graph.json node.blackboard_write
#   "graph.expected_outputs"   -- main_graph.json node.expected_outputs
#   "gates.STAGE_GATES"        -- gates.py STAGE_GATES[stage] gate ids
SOURCE_BLACKBOARD_READ = "graph.blackboard_read"
SOURCE_EXPECTED_EVIDENCE = "graph.expected_evidence"
SOURCE_BLACKBOARD_WRITE = "graph.blackboard_write"
SOURCE_EXPECTED_OUTPUTS = "graph.expected_outputs"
SOURCE_STAGE_GATES = "gates.STAGE_GATES"

KIND_EVIDENCE_BLOCK = "evidence_block"


def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse items that name the SAME required thing, keeping the first
    (richest-described) occurrence and recording every declaration that asked
    for it in `sources`.

    This is not cosmetic. Two real declaration sources legitimately name the
    same artifact -- INTAKE's expected_evidence entry IS its blackboard_read
    topic 'environment' restated (its own description says so), and its
    expected_outputs entry 'intake_readiness' IS the STAGE_GATES gate id.
    Counting those twice inflates the denominator, so the completeness %
    would understate a stage that is genuinely complete, and the "please
    provide more detail" reminder would ask for the same thing twice.

    `present` is OR'd across the merged declarations: they are alternative
    routes to confirming one artifact is really there, so any one of them
    finding it means it is there."""
    order: List[str] = []
    merged: Dict[str, Dict[str, Any]] = {}
    for it in items:
        key = str(it["item_id"])
        if key not in merged:
            merged[key] = dict(it, sources=[it["source"]])
            order.append(key)
            continue
        prev = merged[key]
        prev["present"] = prev["present"] or it["present"]
        if it["source"] not in prev["sources"]:
            prev["sources"].append(it["source"])
    for entry in merged.values():
        entry["source"] = "+".join(entry["sources"])
    return [merged[k] for k in order]


def _summarize(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    items = _dedupe(items)
    total = len(items)
    present = sum(1 for it in items if it["present"])
    return {
        "items": items,
        "present_count": present,
        "total_count": total,
        # Same convention _run_checklist() in engine.py already established:
        # zero declared items means nothing is outstanding, so 100% -- not 0%,
        # which would read as "everything is missing" for a stage that in fact
        # requires nothing.
        "completeness_percent": (100.0 * present / total) if total else 100.0,
        "missing_item_ids": [it["item_id"] for it in items if not it["present"]],
    }


def _gate_ids_for_stage(root: Path, stage: str) -> List[str]:
    """The stage's REAL registered gate ids, through gates.effective_stage_gates()
    so the self-tuning overlay (.dv-harness/self_tuning/) is honored -- a gate
    the harness has really disabled for this stage must not appear on a
    checklist as still required."""
    from .gates import effective_stage_gates
    try:
        entries = effective_stage_gates(stage, root)
    except Exception:
        from .gates import STAGE_GATES
        entries = list(STAGE_GATES.get(stage, []))
    return [e[0] for e in entries]


def _evidence_block_present(blocks: Any, gate_id: str) -> bool:
    return isinstance(blocks, dict) and bool(blocks.get(gate_id))


def build_stage_input_checklist(root: Path, stage: str, node, blackboard,
                                 stage_history: Optional[Dict[str, Dict[str, Any]]] = None
                                 ) -> Dict[str, Any]:
    """The required-INPUT checklist shown at stage START: what documents,
    files and data this stage needs before it can be completed, each
    presence-checked for real.

    Three real declaration sources, never an invented parallel list:
      - node.blackboard_read: the upstream verification truth this node
        declares it reads. Present iff that Blackboard topic has been written.
      - node.expected_evidence: the node's own explicit entry checklist
        (file_path / blackboard_key / evidence_field items), resolved by the
        SAME engine._checklist_item_present() the pre-existing entry checklist
        uses.
      - gates.STAGE_GATES[stage]: every gate id registered for this stage is
        an evidence block the stage must carry to pass. Present iff this
        stage's most recent PRIOR attempt actually submitted that block
        (state.stages[stage]["last_evidence_blocks"], the same field
        build_stage_entry_checklist() reads) -- so a first attempt honestly
        reports 0/N required blocks supplied, and a retry shows exactly which
        ones already landed."""
    from .engine import _checklist_item_present

    history = stage_history or {}
    own_blocks = (history.get(stage) or {}).get("last_evidence_blocks")
    items: List[Dict[str, Any]] = []

    for topic in list(getattr(node, "blackboard_read", None) or []):
        items.append({
            "item_id": topic, "kind": "blackboard_key",
            "source": SOURCE_BLACKBOARD_READ,
            "description": f"upstream verification truth this stage reads: blackboard topic '{topic}'",
            "present": blackboard.read(topic) is not None,
        })

    for decl in list(getattr(node, "expected_evidence", None) or []):
        def _evidence_for(stage_ref, _h=history, _own=stage):
            entry = _h.get(stage_ref or _own) or {}
            blocks = entry.get("last_evidence_blocks")
            return blocks if isinstance(blocks, dict) else {}
        items.append({
            "item_id": decl.get("item_id"), "kind": decl.get("kind"),
            "source": SOURCE_EXPECTED_EVIDENCE,
            "description": decl.get("description", ""),
            "present": _checklist_item_present(decl, Path(root), blackboard, _evidence_for),
        })

    for gate_id in _gate_ids_for_stage(Path(root), stage):
        items.append({
            "item_id": gate_id, "kind": KIND_EVIDENCE_BLOCK,
            "source": SOURCE_STAGE_GATES,
            "description": f"required evidence block ```dv-harness-evidence:{gate_id}```",
            "present": _evidence_block_present(own_blocks, gate_id),
        })

    return _summarize(items)


def build_stage_output_checklist(root: Path, stage: str, node, blackboard,
                                  evidence_blocks: Optional[Dict[str, Any]] = None
                                  ) -> Dict[str, Any]:
    """The OUTPUT checklist shown at stage DONE: the files and data this stage
    was supposed to produce, each presence-checked for real.

    Same "real declarations only" rule as the input checklist, mirrored:
      - node.blackboard_write: the topics this node is declared to write.
        Present iff the topic now holds a value (engine.py's PASS branch
        writes these via _write_blackboard_from_evidence()).
      - node.expected_outputs: the node's own explicit exit checklist.
      - gates.STAGE_GATES[stage]: present iff THIS attempt's own freshly
        extracted evidence carried that block (not the persisted
        last_evidence_blocks -- "what did this attempt just produce" is
        exactly what an exit check means, the same reasoning
        build_stage_exit_checklist()'s docstring already gives)."""
    from .engine import _checklist_item_present

    blocks = evidence_blocks if isinstance(evidence_blocks, dict) else {}
    items: List[Dict[str, Any]] = []

    for topic in list(getattr(node, "blackboard_write", None) or []):
        items.append({
            "item_id": topic, "kind": "blackboard_key",
            "source": SOURCE_BLACKBOARD_WRITE,
            "description": f"verification truth this stage writes: blackboard topic '{topic}'",
            "present": blackboard.read(topic) is not None,
        })

    for decl in list(getattr(node, "expected_outputs", None) or []):
        items.append({
            "item_id": decl.get("item_id"), "kind": decl.get("kind"),
            "source": SOURCE_EXPECTED_OUTPUTS,
            "description": decl.get("description", ""),
            "present": _checklist_item_present(decl, Path(root), blackboard, lambda _s: blocks),
        })

    for gate_id in _gate_ids_for_stage(Path(root), stage):
        items.append({
            "item_id": gate_id, "kind": KIND_EVIDENCE_BLOCK,
            "source": SOURCE_STAGE_GATES,
            "description": f"evidence block ```dv-harness-evidence:{gate_id}``` produced by this attempt",
            "present": _evidence_block_present(blocks, gate_id),
        })

    return _summarize(items)


# --- "please provide more detail on X" ---------------------------------------
def _topic_writers(graph, topic: str) -> List[str]:
    """Which graph node(s) really declare `topic` in their blackboard_write --
    so a missing input names the upstream stage that produces it, instead of
    telling a human to conjure a blackboard topic from nowhere."""
    if graph is None:
        return []
    return sorted(n.id for n in graph.nodes.values()
                  if topic in (getattr(n, "blackboard_write", None) or []))


def build_detail_requests(root: Path, stage: str, checklist: Dict[str, Any],
                          graph=None, gate_reasons: Optional[List[str]] = None
                          ) -> List[str]:
    """The explicit "please provide more detail on: X, Y, Z" reminder --
    one line per genuinely missing/incomplete required item, each saying what
    is missing AND how it is supplied.

    Reuses gates.INTAKE_FIELD_QUESTIONS verbatim wherever a missing item id
    (or a gate reason's named field) has a real question already written for
    it, rather than inventing a second wording for the same ask."""
    from .gates import INTAKE_FIELD_QUESTIONS

    lines: List[str] = []
    by_id = {it["item_id"]: it for it in checklist.get("items", [])}
    for item_id in checklist.get("missing_item_ids", []):
        item = by_id.get(item_id, {})
        source, kind = item.get("source"), item.get("kind")
        question = INTAKE_FIELD_QUESTIONS.get(str(item_id))
        if question:
            lines.append(f"{item_id}: {question}")
        elif source == SOURCE_BLACKBOARD_READ or kind == "blackboard_key":
            writers = _topic_writers(graph, str(item_id))
            produced_by = (f" (produced by stage {', '.join(writers)})" if writers
                           else " (no stage in the graph declares it as an output -- "
                                "it must be supplied by hand)")
            lines.append(f"{item_id}: required input data '{item_id}' has never been "
                         f"written to the blackboard{produced_by}.")
        elif kind == "file_path":
            lines.append(f"{item_id}: required file is not on disk at "
                         f"'{Path(root) / str(item_id)}' -- provide the real path or the file.")
        elif kind == KIND_EVIDENCE_BLOCK:
            lines.append(f"{item_id}: no ```dv-harness-evidence:{item_id}``` block has been "
                         f"supplied for stage {stage} yet -- the gate cannot run without it.")
        else:
            desc = item.get("description") or "required item"
            lines.append(f"{item_id}: {desc} -- still missing.")

    # A gate that RAN and failed on a named missing field is a second, real
    # source of "this specific thing needs more detail" -- intake_readiness.py
    # reports those as bare field names, which INTAKE_FIELD_QUESTIONS turns
    # into an actual question. Only fields with a real registered question are
    # promoted here; a raw gate reason string is not paraphrased into one.
    for reason in gate_reasons or []:
        for field, question in INTAKE_FIELD_QUESTIONS.items():
            if re.search(rf"\b{re.escape(field)}\b", str(reason)) and \
                    not any(ln.startswith(f"{field}:") for ln in lines):
                lines.append(f"{field}: {question}")
    return lines


# --- rendering ---------------------------------------------------------------
def section_rule(title: str) -> str:
    """A section rule padded to exactly WIDTH from the title's REAL length.

    Public, and imported by stage_profile_report.render_stage_time_and_tokens()
    rather than copied, because every caller used to hardcode its own
    subtraction constant and they did not agree: the time/token block's
    '-- EXECUTION TIME AND TOKENS ' + '-' * 50 came to 79 characters while
    every checklist rule came to 80, so the one section rendered from the
    other module sat a character short of the banner above it. Sharing the
    helper is what makes that un-driftable; a corrected constant would only
    have been correct until the next title changed length."""
    head = f"-- {title} "
    return head + "-" * max(0, WIDTH - len(head))


def _render_checklist(title: str, checklist: Dict[str, Any]) -> List[str]:
    out = [section_rule(title)]
    if not checklist.get("items"):
        out.append("  (this stage declares no items of this kind)")
    for it in checklist.get("items", []):
        mark = "x" if it["present"] else " "
        out.append(f"  [{mark}] {it['item_id']}  <{it.get('source')}/{it.get('kind')}>")
        if it.get("description"):
            out.append(f"        {it['description']}")
    out.append(f"  COMPLETENESS: {checklist['completeness_percent']:.1f}%  "
               f"({checklist['present_count']}/{checklist['total_count']} present)")
    return out


def _stage_position(stage: str) -> str:
    from .policy import ORDER
    order = list(ORDER)
    if stage in order:
        return f"STEP  : {order.index(stage) + 1} / {len(order)} (workflow order)"
    return f"STEP  : {stage} (not in the linear workflow order)"


def render_stage_start_display(stage: str, input_checklist: Dict[str, Any],
                               detail_requests: List[str],
                               timestamp: Optional[str] = None,
                               attempt: Optional[int] = None) -> str:
    """Requirement #2's screen: banner + required-input checklist + completeness
    % + the explicit "needs your detail" reminder. Also carries requirement
    #1's outstanding-items view for the stage that is starting."""
    info = [
        f"INPUTS: {input_checklist['present_count']}/{input_checklist['total_count']} ready "
        f"({input_checklist['completeness_percent']:.0f}%)",
        _stage_position(stage),
    ]
    if attempt is not None:
        info.append(f"ATTEMPT: {attempt}")
    parts = [render_banner(stage, "START", info_lines=info, timestamp=timestamp), ""]
    parts += _render_checklist("REQUIRED INPUTS (documents / files / data)", input_checklist)
    parts.append("")
    parts.append(section_rule("ACTION REQUIRED: please provide more detail on"))
    if detail_requests:
        for line in detail_requests:
            parts.append(f"  * {line}")
    else:
        parts.append("  (nothing outstanding -- every required input for this stage is present)")
    return "\n".join(parts)


def render_stage_done_display(stage: str, gate_verdict: Any, stage_completion_percent: Any,
                              output_checklist: Dict[str, Any],
                              time_token_summary: Dict[str, Any],
                              outstanding: Optional[List[str]] = None,
                              timestamp: Optional[str] = None) -> str:
    """Requirement #3's screen: banner + output checklist + completeness % +
    the total execution time (including every sub-agent run) and total tokens
    consumed."""
    from .stage_profile_report import render_stage_time_and_tokens
    pct = (f"{stage_completion_percent:.0f}" if isinstance(stage_completion_percent, (int, float))
           else "-")
    info = [
        f"VERDICT: {gate_verdict}  ({pct}% gates satisfied)",
        f"OUTPUTS: {output_checklist['present_count']}/{output_checklist['total_count']} present "
        f"({output_checklist['completeness_percent']:.0f}%)",
    ]
    parts = [render_banner(stage, "DONE", info_lines=info, timestamp=timestamp), ""]
    parts += _render_checklist("OUTPUT FILES / DATA PRODUCED", output_checklist)
    parts.append("")
    parts.append(section_rule("STILL OUTSTANDING IN THIS STAGE"))
    if outstanding:
        for line in outstanding:
            parts.append(f"  * {line}")
    else:
        parts.append("  (nothing outstanding for this stage)")
    parts.append("")
    parts.append(render_stage_time_and_tokens(time_token_summary))
    return "\n".join(parts)


# --- persisted reports -------------------------------------------------------
STAGE_REPORT_SUBDIR = Path(".dv-harness") / "stage_reports"
_TS_SAFE = re.compile(r"[^0-9A-Za-z]+")


def stage_report_dir(root: Path) -> Path:
    return Path(root) / STAGE_REPORT_SUBDIR


def save_stage_report(root: Path, stage: str, phase: str, display_text: str,
                      payload: Optional[Dict[str, Any]] = None,
                      timestamp: Optional[str] = None) -> Path:
    """Requirement #4: persist the display as a real, human-readable markdown
    report at .dv-harness/stage_reports/<stage>_<phase>_<timestamp>.md.

    The report EMBEDS the exact display text that was printed (inside a fenced
    block, so the ASCII banner survives markdown rendering verbatim) -- the
    file and the terminal can never disagree, because there is only one
    rendered string and both consume it. `payload` is the structured data
    behind the display, appended as JSON so a later tool can read the numbers
    back without re-parsing the ASCII.

    Both fences are FOUR backticks, not three, and that is load-bearing: the
    checklist text this report embeds names the evidence fences it is asking
    for (```dv-harness-evidence:<gate_id>```), so a three-backtick wrapper
    would be closed early by its own content -- the report would render as
    broken markdown and its JSON block would be unparseable. Found by a real
    test, not predicted."""
    ts = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_dir = stage_report_dir(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stage}_{phase.lower()}_{_TS_SAFE.sub('', ts)}.md"
    body = [
        f"# DV Agent Harness L5 -- stage {phase.upper()} report: {stage}",
        "",
        f"- stage: `{stage}`",
        f"- phase: `{phase.upper()}`",
        f"- generated_at: `{ts}`",
        "",
        "## Display (verbatim, exactly as printed to the terminal)",
        "",
        "````text",
        display_text,
        "````",
        "",
    ]
    if payload is not None:
        body += ["## Structured data", "", "````json",
                 json.dumps(payload, ensure_ascii=False, indent=2, default=str), "````", ""]
    path.write_text("\n".join(body), encoding="utf-8")
    return path


_REPORT_PHASES = ("start", "done")


def _parse_report_name(stem: str) -> Optional[Dict[str, str]]:
    """Split a report filename back into (stage, phase, timestamp).

    Parsed from the RIGHT, because a stage name legitimately contains
    underscores and the phase/timestamp fields never do: save_stage_report()
    lowercases the phase and strips every non-alphanumeric character out of
    the timestamp. So the last two "_"-separated fields are always exactly
    phase and timestamp, and everything before them is the stage -- which
    `ARCH_CALIBRATION_start_2026...` would otherwise split wrongly.

    Returns None for any file that does not match the shape this module
    writes, so a stray .md dropped in the directory by hand is skipped
    rather than being reported as a stage report with a garbage stage."""
    parts = stem.rsplit("_", 2)
    if len(parts) != 3:
        return None
    stage, phase, ts = parts
    if not stage or phase not in _REPORT_PHASES or not ts.isalnum():
        return None
    return {"stage": stage, "phase": phase, "timestamp": ts}


def list_stage_reports(root: Path, stage: Optional[str] = None,
                       phase: Optional[str] = None) -> List[Path]:
    """Saved reports, genuinely oldest first.

    Ordered by the report's own embedded TIMESTAMP, not by filename. Sorting
    the raw names instead put every `_done_` report ahead of every `_start_`
    one regardless of when either was written ("done" < "start"), so the
    "oldest first" contract was false across a mixed-phase listing and
    latest_stage_report() returned a stage's START report while a newer DONE
    report sat right beside it. The timestamps are fixed-width and
    digit-normalized by save_stage_report(), so a lexical sort of them IS a
    chronological sort; the tiebreak keeps a start/done pair written in the
    same second in the order they really happened.

    The `stage` filter matches the parsed stage EXACTLY rather than by name
    prefix. This is not hypothetical tidiness: the real workflow order
    contains BUILD alongside BUILD_DEBUG, and REGRESSION alongside
    REGRESSION_SELECT and REGRESSION_MONITOR, so a prefix match returned
    another stage's reports under the name of the one that was asked for."""
    d = stage_report_dir(root)
    if not d.is_dir():
        return []
    rows = []
    for p in d.glob("*.md"):
        meta = _parse_report_name(p.stem)
        if meta is None:
            continue
        if stage and meta["stage"] != stage:
            continue
        if phase and meta["phase"] != phase.lower():
            continue
        rows.append((meta["timestamp"], _REPORT_PHASES.index(meta["phase"]), p.name, p))
    return [r[-1] for r in sorted(rows)]


def latest_stage_report(root: Path, stage: Optional[str] = None,
                        phase: Optional[str] = None) -> Optional[Path]:
    reports = list_stage_reports(root, stage=stage, phase=phase)
    return reports[-1] if reports else None
