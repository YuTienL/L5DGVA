from pathlib import Path
import argparse, json
from .stage_profile import StageExecutionProfiler

def sec(v):
    v=float(v or 0); h=int(v//3600); m=int((v%3600)//60); s=int(v%60)
    return f'{h}h{m:02d}m{s:02d}s' if h else f'{m}m{s:02d}s'
def tok(v,available=True):
    if not available: return 'N/A'
    v=int(v or 0); return f'{v/1000:.1f}K' if v>=1000 else str(v)

# 2026-09-01, cross-adapter-token-tracking pass: this table's Input/Output/
# Total columns already rendered 'N/A' (via tok()'s `available` arg) for a
# stage whose add_agent_run() usage came back all-None -- but a bare 'N/A'
# with no context reads identically whether the cause is "this stage just
# hasn't run an agent yet" or "the configured adapter genuinely never
# surfaces token usage at all" (the SDK adapter, per stage_profile.
# extract_provider_usage()'s own docstring and dv_harness/adapters/sdk.py --
# ClaudeCodeSDKAdapter.run()'s raw response never carries a `response.usage`
# block, so extract_provider_usage() always returns all-None for it, by
# design, not as a bug). A viewer of this exact table (`dv-harness
# stage-profile` and dashboard.py's "Stage Execution Profile" card both
# render this string verbatim -- see stage_profile_report.render()'s own
# docstring) could otherwise mistake silent SDK-adapter N/As for a broken
# measurement. RULING: read the project's OWN currently-configured adapter
# (".dv-harness/config.json"'s top-level "adapter" field, the same field
# DVHarness._adapter() in engine.py switches on) and, only when it is
# genuinely "sdk", append one explicit note naming the real reason -- never
# inferred from the N/A values themselves (a CLI-adapter stage that simply
# has not run any agent yet also shows N/A, and must NOT be mislabeled as an
# SDK limitation). A config read failure (no project root, unreadable/absent
# config.json) degrades to "cli" -- the documented default adapter -- so a
# read error can only ever suppress this note, never fabricate one.
def _configured_adapter_name(project_root) -> str:
    try:
        from .config import load_config
        return str(load_config(Path(project_root)).get('adapter', 'cli'))
    except Exception:
        return 'cli'

SDK_ADAPTER_TOKEN_NOTE = (
    'NOTE: token counts show N/A for every stage above because this project is '
    'configured to use the SDK adapter ("adapter": "sdk" in .dv-harness/config.json). '
    'The SDK adapter does not currently surface token usage data upstream '
    '(see dv_harness/adapters/sdk.py and stage_profile.extract_provider_usage()\'s '
    'docstring) -- this is a documented, known limitation of that adapter, not a '
    'zero-token run or a broken measurement. Switch to the CLI adapter '
    '("adapter": "cli") for real per-stage token accounting.'
)

def render(project_root='.') -> str:
    # BUG FIX (2026-08-28, gui-cli-completeness-audit): the wall-clock/token/
    # tool-call/retry data this renders was already being collected live by
    # engine.py on every real stage run (StageExecutionProfiler.begin_stage/
    # add_agent_run/end_stage), but this module had NO CLI or GUI entry
    # point -- `python -m dv_harness.stage_profile_report` run manually,
    # outside the `dv-harness` command, was the only way to see it. Extracted
    # from main() into a plain string-returning function so `dv-harness
    # stage-profile` (dv_harness/cli.py) can call it directly; main() below
    # is unchanged for anyone still invoking the module as a standalone script.
    p=StageExecutionProfiler(Path(project_root)); rows=p.all_stages()
    lines=['DV Agent Harness L5 - Stage Execution Profile']
    lines.append(f"{'Stage':<26} {'Wall':>8} {'Input':>8} {'Output':>8} {'Total':>8} {'Tools':>6} {'Retry':>6} {'Status':>8}")
    lines.append('-'*86)
    total_wall=total_in=total_out=total_tok=0.0; any_tok=False
    for r in rows:
        it,ot,tt=r.get('input_tokens'),r.get('output_tokens'),r.get('total_tokens')
        if tt is not None: any_tok=True
        total_wall+=r.get('stage_wall_clock_sec') or 0
        total_in+=it or 0; total_out+=ot or 0; total_tok+=tt or 0
        lines.append(f"{r.get('stage_name','')[:26]:<26} {sec(r.get('stage_wall_clock_sec')):>8} "
              f"{tok(it,it is not None):>8} {tok(ot,ot is not None):>8} {tok(tt,tt is not None):>8} "
              f"{r.get('tool_calls',0):>6} {r.get('retries',0):>6} {r.get('status',''):>8}")
    lines.append('-'*86)
    lines.append(f"{'TOTAL WORKFLOW':<26} {sec(total_wall):>8} "
          f"{tok(total_in,any_tok):>8} {tok(total_out,any_tok):>8} {tok(total_tok,any_tok):>8}")
    if p.workflow_file.exists():
        w=json.loads(p.workflow_file.read_text(encoding='utf-8')); lines.append('-'*86)
        lines.append('AGGREGATE AGENT TIME   : '+sec(w.get('total_aggregate_agent_runtime_sec')))
        lines.append('PARALLEL SAVING        : '+sec(w.get('total_parallel_saving_sec')))
        lines.append('PARALLEL EFFICIENCY    : '+f"{w.get('overall_parallelism_efficiency',0)*100:.1f}%")
        lines.append('TOOL CALLS / RETRIES   : '+f"{w.get('tool_calls',0)} / {w.get('retries',0)}")
    if _configured_adapter_name(project_root) == 'sdk':
        lines.append('')
        lines.append(SDK_ADAPTER_TOKEN_NOTE)
    return '\n'.join(lines)


# --- per-stage time/token summary, INCLUDING every sub-agent run -------------
# (2026-09-04, stage-progress-display gap-close.) render() above is a
# whole-workflow table with one row per stage; the stage-DONE display needs
# the opposite cut -- ONE stage, broken down by the individual agent runs
# inside it, because the user's requirement is "總執行時間（含各個 Agents）"
# and a single collapsed per-stage row cannot answer "including each agent".
#
# The data was already being collected and is NOT re-collected here:
# StageExecutionProfiler.add_agent_run() appends one entry to the stage
# record's `agents` list per REAL adapter.run() invocation, and there are two
# real call sites -- engine.run_stage()'s own main stage dispatch, and
# react_loop._record_agent_run() for every sub-agent dispatch the inner ReAct
# loop makes (a reflection call, its hallucination re-ask, a
# RETRY_TARGETED/REQUEST_EVIDENCE targeted retry). rec['input_tokens'] /
# ['output_tokens'] / ['total_tokens'] / ['aggregate_agent_runtime_sec'] are
# already sums across that whole list, so the stage totals below DO include
# sub-agents. What was genuinely missing is any way to SEE that: nothing
# anywhere rendered the per-agent rows, so "does this number include the
# sub-agents" was unanswerable without opening the raw telemetry JSON. These
# two functions are that missing surface, plus cache-token columns render()
# never showed (cache_read/cache_write are real recorded fields and are real
# tokens consumed).
def stage_time_and_token_summary(project_root, stage_name) -> dict:
    """Real wall-clock/runtime/token numbers for ONE stage, read back from the
    StageExecutionProfiler records that stage's own runs wrote.

    Returns `attempts` (every STAGE-*.json record for this stage), `latest`
    (the most recent attempt, with one `agents` row per real agent/sub-agent
    dispatch), `stage_totals` (summed across every attempt of this stage), and
    `workflow_totals` (the whole run, straight out of workflow_profile.json).

    `token_data_available` is False when NO agent run anywhere in this stage
    reported usage -- kept as an explicit flag rather than inferred from a
    zero, because zero tokens and "this adapter never reports tokens" are
    different facts (see SDK_ADAPTER_TOKEN_NOTE above)."""
    root = Path(project_root)
    p = StageExecutionProfiler(root)
    try:
        records = [r for r in p.all_stages()
                   if r.get('stage_id') == stage_name or r.get('stage_name') == stage_name]
    except Exception:
        records = []

    def _sum(key, recs):
        vals = [r.get(key) for r in recs if isinstance(r.get(key), (int, float))]
        return sum(vals) if vals else None

    agents = list((records[-1].get('agents') or [])) if records else []
    all_agents = [a for r in records for a in (r.get('agents') or [])]
    latest = records[-1] if records else None
    workflow = {}
    if p.workflow_file.exists():
        try:
            workflow = json.loads(p.workflow_file.read_text(encoding='utf-8'))
        except Exception:
            workflow = {}
    return {
        'stage_name': stage_name,
        'attempts': len(records),
        'latest': None if latest is None else {
            'profile_id': latest.get('profile_id'),
            'status': latest.get('status'),
            'stage_wall_clock_sec': latest.get('stage_wall_clock_sec'),
            'aggregate_agent_runtime_sec': latest.get('aggregate_agent_runtime_sec'),
            'parallel_saving_sec': latest.get('parallel_saving_sec'),
            'input_tokens': latest.get('input_tokens'),
            'output_tokens': latest.get('output_tokens'),
            'cache_read_tokens': latest.get('cache_read_tokens'),
            'cache_write_tokens': latest.get('cache_write_tokens'),
            'total_tokens': latest.get('total_tokens'),
            'tool_calls': latest.get('tool_calls'),
            'retries': latest.get('retries'),
            'agents': agents,
            'agent_run_count': len(agents),
        },
        'stage_totals': {
            'stage_wall_clock_sec': _sum('stage_wall_clock_sec', records) or 0.0,
            'aggregate_agent_runtime_sec': _sum('aggregate_agent_runtime_sec', records) or 0.0,
            'input_tokens': _sum('input_tokens', records),
            'output_tokens': _sum('output_tokens', records),
            'cache_read_tokens': _sum('cache_read_tokens', records),
            'cache_write_tokens': _sum('cache_write_tokens', records),
            'total_tokens': _sum('total_tokens', records),
            'agent_run_count': len(all_agents),
            'tool_calls': sum(r.get('tool_calls') or 0 for r in records),
            'retries': sum(r.get('retries') or 0 for r in records),
        },
        'workflow_totals': {
            'stage_count': workflow.get('stage_count'),
            'total_stage_wall_clock_sec': workflow.get('total_stage_wall_clock_sec'),
            'total_aggregate_agent_runtime_sec': workflow.get('total_aggregate_agent_runtime_sec'),
            'total_tokens': workflow.get('total_tokens'),
            'tool_calls': workflow.get('tool_calls'),
            'retries': workflow.get('retries'),
        },
        'token_data_available': any(
            isinstance(a.get('total_tokens'), (int, float)) for a in all_agents),
        'adapter_note': (SDK_ADAPTER_TOKEN_NOTE
                         if _configured_adapter_name(project_root) == 'sdk' else None),
    }


def render_stage_time_and_tokens(summary: dict) -> str:
    """The stage-DONE time/token block, rendered from stage_time_and_token_summary()
    output. Takes the already-computed dict (not a project root) so the
    persisted stage report and the terminal render the SAME numbers from the
    SAME single read -- re-reading telemetry for the report could otherwise
    pick up a concurrent branch's write and disagree with what was printed."""
    # Imported lazily and by name from the display module so this block's rule
    # is the SAME width as the checklist rules it is printed beneath. The
    # import is function-local because stage_progress_display imports this
    # module (also lazily) for exactly this renderer -- keeping both sides
    # lazy means neither module can be made unimportable by the other.
    from .stage_progress_display import section_rule
    avail = bool(summary.get('token_data_available'))
    lines = [section_rule('EXECUTION TIME AND TOKENS')]
    latest = summary.get('latest')
    if latest is None:
        lines.append(f"  no telemetry record for stage {summary.get('stage_name')} yet")
        return '\n'.join(lines)
    lines.append(f"  {'AGENT (this attempt)':<38} {'Runtime':>9} {'Input':>8} "
                 f"{'Output':>8} {'Total':>8} {'Status':>7}")
    for a in latest.get('agents') or []:
        it, ot, tt = a.get('input_tokens'), a.get('output_tokens'), a.get('total_tokens')
        lines.append(f"  {str(a.get('agent', ''))[:38]:<38} {sec(a.get('runtime_sec')):>9} "
                     f"{tok(it, it is not None):>8} {tok(ot, ot is not None):>8} "
                     f"{tok(tt, tt is not None):>8} {str(a.get('status', '')):>7}")
    if not (latest.get('agents') or []):
        lines.append('  (no agent run recorded for this attempt)')
    lines.append('  ' + '-' * 78)
    lines.append(f"  {'STAGE WALL CLOCK':<38} {sec(latest.get('stage_wall_clock_sec')):>9}")
    lines.append(f"  {'ALL AGENTS RUNTIME (incl. sub-agents)':<38} "
                 f"{sec(latest.get('aggregate_agent_runtime_sec')):>9}   "
                 f"across {latest.get('agent_run_count', 0)} agent run(s)")
    st = summary.get('stage_totals') or {}
    lines.append(f"  {'STAGE TOTAL (all ' + str(summary.get('attempts', 0)) + ' attempt(s))':<38} "
                 f"{sec(st.get('stage_wall_clock_sec')):>9}   "
                 f"agent runtime {sec(st.get('aggregate_agent_runtime_sec'))}, "
                 f"{st.get('agent_run_count', 0)} agent run(s)")
    lines.append(f"  {'STAGE TOKENS (in/out/cache/total)':<38} "
                 f"{tok(st.get('input_tokens'), avail)} / {tok(st.get('output_tokens'), avail)} / "
                 f"{tok((st.get('cache_read_tokens') or 0) + (st.get('cache_write_tokens') or 0), avail)} / "
                 f"{tok(st.get('total_tokens'), avail)}")
    wf = summary.get('workflow_totals') or {}
    lines.append(f"  {'WORKFLOW TOTAL SO FAR':<38} "
                 f"{sec(wf.get('total_stage_wall_clock_sec')):>9}   "
                 f"agent runtime {sec(wf.get('total_aggregate_agent_runtime_sec'))}, "
                 f"tokens {tok(wf.get('total_tokens'), wf.get('total_tokens') is not None)}, "
                 f"tool calls {wf.get('tool_calls') or 0}, retries {wf.get('retries') or 0}")
    if summary.get('adapter_note'):
        lines.append('')
        lines.append('  ' + summary['adapter_note'])
    return '\n'.join(lines)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project-root',default='.'); a=ap.parse_args()
    print(render(a.project_root))
if __name__=='__main__': main()
