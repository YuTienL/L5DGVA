from __future__ import annotations
import json, os, tempfile, time, uuid
from pathlib import Path
from typing import Dict, Any, Optional
from .storage import _atomic_replace

def extract_provider_usage(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Pulls token usage out of an adapter's raw response. The CLI adapter
    nests it at raw['response']['usage'] (from `claude -p --output-format
    json`); the SDK adapter does not currently surface usage, so this
    returns an all-None dict for it rather than raising."""
    usage = ((raw or {}).get("response") or {}).get("usage") or {}
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_write_tokens": usage.get("cache_creation_input_tokens"),
    }

class StageExecutionProfiler:
    def __init__(self, project_root: Path):
        self.root=project_root.resolve()
        self.dir=self.root/".dv-harness"/"telemetry"
        self.stage_dir=self.dir/"stages"
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        self.workflow_file=self.dir/"workflow_profile.json"

    def begin_stage(self, stage_id, stage_name, graph_node="", metadata=None):
        pid=f"STAGE-{uuid.uuid4().hex[:8].upper()}"
        rec={
            "profile_id":pid,"stage_id":stage_id,"stage_name":stage_name,
            "graph_node":graph_node or stage_id,
            "start_time_epoch":time.time(),"end_time_epoch":None,
            "stage_wall_clock_sec":0.0,"aggregate_agent_runtime_sec":0.0,
            "parallel_saving_sec":0.0,"parallelism_efficiency":0.0,
            "input_tokens":None,"output_tokens":None,
            "cache_read_tokens":None,"cache_write_tokens":None,"total_tokens":None,
            "tool_calls":0,"retries":0,"finding_count":0,"closed_finding_count":0,
            "status":"RUNNING","agents":[],"metadata":metadata or {}
        }
        self._save(rec)
        return rec

    def add_agent_run(self, profile_id, agent, runtime_sec, usage=None, tool_calls=0, retries=0,
                      model="", job_id="", status="PASS"):
        rec=self._load(profile_id)
        usage=usage or {}
        a={
            "agent":agent,"runtime_sec":float(runtime_sec),"model":model,"job_id":job_id,
            "input_tokens":usage.get("input_tokens"),
            "output_tokens":usage.get("output_tokens"),
            "cache_read_tokens":usage.get("cache_read_tokens"),
            "cache_write_tokens":usage.get("cache_write_tokens"),
            "tool_calls":int(tool_calls),"retries":int(retries),"status":status
        }
        vals=[a.get("input_tokens"),a.get("output_tokens")]
        a["total_tokens"]=sum(v for v in vals if isinstance(v,(int,float))) if any(isinstance(v,(int,float)) for v in vals) else None
        rec["agents"].append(a)
        rec["aggregate_agent_runtime_sec"] += a["runtime_sec"]
        rec["tool_calls"] += a["tool_calls"]
        rec["retries"] += a["retries"]

        def sum_usage(key):
            vals=[x.get(key) for x in rec["agents"] if isinstance(x.get(key),(int,float))]
            return sum(vals) if vals else None

        rec["input_tokens"]=sum_usage("input_tokens")
        rec["output_tokens"]=sum_usage("output_tokens")
        rec["cache_read_tokens"]=sum_usage("cache_read_tokens")
        rec["cache_write_tokens"]=sum_usage("cache_write_tokens")
        rec["total_tokens"]=sum_usage("total_tokens")
        self._save(rec)
        return rec

    def end_stage(self, profile_id, status="PASS", finding_count=0, closed_finding_count=0):
        rec=self._load(profile_id)
        rec["end_time_epoch"]=time.time()
        rec["stage_wall_clock_sec"]=max(0.0,rec["end_time_epoch"]-rec["start_time_epoch"])
        rec["status"]=status
        rec["finding_count"]=int(finding_count)
        rec["closed_finding_count"]=int(closed_finding_count)
        rec["parallel_saving_sec"]=max(0.0,rec["aggregate_agent_runtime_sec"]-rec["stage_wall_clock_sec"])
        rec["parallelism_efficiency"]=(rec["parallel_saving_sec"]/rec["aggregate_agent_runtime_sec"]
                                      if rec["aggregate_agent_runtime_sec"] else 0.0)
        rec["tokens_per_finding"]=(rec["total_tokens"]/rec["finding_count"]
                                   if isinstance(rec["total_tokens"],(int,float)) and rec["finding_count"] else None)
        rec["tokens_per_closed_finding"]=(rec["total_tokens"]/rec["closed_finding_count"]
                                          if isinstance(rec["total_tokens"],(int,float)) and rec["closed_finding_count"] else None)
        self._save(rec)
        self._update_workflow()
        return rec

    def _path(self,pid): return self.stage_dir/f"{pid}.json"

    def _write_json_atomic(self, path: Path, data) -> None:
        # Graph-level parallel fan-out (2026-08-29): run_stage() (and hence
        # begin_stage/add_agent_run/end_stage) can now execute concurrently
        # across ThreadPoolExecutor-dispatched branches -- a plain
        # write_text() here let a concurrent all_stages()/_load() reader
        # observe a truncated/empty file mid-write (confirmed by a real
        # JSONDecodeError under the new fan-out test). Same atomic
        # tempfile+os.replace idiom storage.StateStore.save()/
        # config.save_config() already use for exactly this reason. suffix is
        # deliberately ".tmp", NOT ".json" -- all_stages() globs "STAGE-*.json"
        # in this same directory, and a mid-write tempfile ending in .json
        # would itself match that glob and could be read (or vanish under a
        # concurrent reader) before it's renamed into place.
        fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _atomic_replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _save(self,rec): self._write_json_atomic(self._path(rec["profile_id"]), rec)
    def _load(self,pid): return json.loads(self._path(pid).read_text(encoding="utf-8"))
    def all_stages(self):
        recs = [json.loads(p.read_text(encoding="utf-8")) for p in self.stage_dir.glob("STAGE-*.json")]
        return sorted(recs, key=lambda r: r.get("start_time_epoch") or 0)

    def _update_workflow(self):
        stages=[s for s in self.all_stages() if s.get("status")!="RUNNING"]
        total_wall=sum(s.get("stage_wall_clock_sec",0) for s in stages)
        total_agent=sum(s.get("aggregate_agent_runtime_sec",0) for s in stages)
        token_values=[s.get("total_tokens") for s in stages if isinstance(s.get("total_tokens"),(int,float))]
        data={
            "stage_count":len(stages),
            "total_stage_wall_clock_sec":total_wall,
            "total_aggregate_agent_runtime_sec":total_agent,
            "total_parallel_saving_sec":max(0,total_agent-total_wall),
            "overall_parallelism_efficiency":((total_agent-total_wall)/total_agent if total_agent else 0),
            "total_tokens":sum(token_values) if token_values else None,
            "tool_calls":sum(s.get("tool_calls",0) for s in stages),
            "retries":sum(s.get("retries",0) for s in stages),
            "finding_count":sum(s.get("finding_count",0) for s in stages),
            "closed_finding_count":sum(s.get("closed_finding_count",0) for s in stages)
        }
        self._write_json_atomic(self.workflow_file, data)
