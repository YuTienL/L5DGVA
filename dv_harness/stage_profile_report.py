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

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project-root',default='.'); a=ap.parse_args()
    print(render(a.project_root))
if __name__=='__main__': main()
