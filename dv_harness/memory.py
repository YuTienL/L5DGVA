from __future__ import annotations
import json, uuid, time
from pathlib import Path
from typing import Any, Dict, List, Optional

MEMORY_LEVELS=["working","job","project","engineering","organizational"]

class MemoryStore:
    def __init__(self, project_root: Path):
        self.root=project_root.resolve()
        self.dir=self.root/".dv-harness"/"memory"
        self.dir.mkdir(parents=True,exist_ok=True)
        for lv in MEMORY_LEVELS:
            (self.dir/lv).mkdir(parents=True,exist_ok=True)
        self.index_file=self.dir/"index.json"
        if not self.index_file.exists():
            self.index_file.write_text("[]",encoding="utf-8")

    def _index(self):
        return json.loads(self.index_file.read_text(encoding="utf-8"))

    def _save_index(self, rows):
        self.index_file.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")

    def add(self, level: str, memory: Dict[str,Any]):
        if level not in MEMORY_LEVELS:
            raise ValueError(level)
        mem=dict(memory)
        mid=mem.get("memory_id") or f"MEM-{uuid.uuid4().hex[:10].upper()}"
        mem["memory_id"]=mid
        mem["level"]=level
        mem.setdefault("created_at",time.time())
        mem.setdefault("last_used_at",None)
        mem.setdefault("reuse_count",0)
        mem.setdefault("confidence","UNKNOWN")
        mem.setdefault("status","ACTIVE")
        mem.setdefault("current_evidence_required",True)
        mem.setdefault("provenance",None)
        mem.setdefault("confirmation_count",0)
        mem.setdefault("last_confirmed_at",None)
        p=self.dir/level/f"{mid}.json"
        p.write_text(json.dumps(mem,ensure_ascii=False,indent=2),encoding="utf-8")
        rows=[x for x in self._index() if x.get("memory_id")!=mid]
        rows.append({
            "memory_id":mid,"level":level,"title":mem.get("title",""),
            "protocol":mem.get("protocol"),"scope":mem.get("scope"),
            "symptoms":mem.get("symptoms",[]),"root_cause":mem.get("root_cause"),
            "confidence":mem.get("confidence"),"status":mem.get("status","ACTIVE"),
            "path":str(p.relative_to(self.root)),
            "created_at":mem.get("created_at"),
            "last_used_at":mem.get("last_used_at"),"reuse_count":mem.get("reuse_count",0)
        })
        self._save_index(rows)
        return mem

    def get(self, memory_id: str) -> Optional[Dict[str,Any]]:
        for lv in MEMORY_LEVELS:
            p=self.dir/lv/f"{memory_id}.json"
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        return None

    def mark_used(self, memory_id: str):
        mem=self.get(memory_id)
        if not mem: return
        mem["last_used_at"]=time.time()
        mem["reuse_count"]=int(mem.get("reuse_count",0))+1
        self.add(mem["level"],mem)

def _tok(v):
    if v is None: return set()
    if isinstance(v,list): v=" ".join(map(str,v))
    return {x.lower() for x in str(v).replace("/"," ").replace("_"," ").replace("-"," ").split() if len(x)>1}

def _recency_score(row: Dict[str,Any], now: float) -> float:
    # Ranking factor named by the user's design ("Recency") but absent from
    # the original scoring function -- older memories should rank below
    # otherwise-equal fresher ones, decaying over ~90 days rather than a
    # hard cutoff (a 6-month-old confirmed fix is still worth surfacing,
    # just not ahead of an identical-strength recent one).
    ts = row.get("last_used_at") or row.get("created_at")
    if not ts: return 0.0
    age_days = max(0.0, (now - float(ts)) / 86400.0)
    return 1.0 * (0.5 ** (age_days / 90.0))

class MemoryRetriever:
    def __init__(self, store: MemoryStore): self.store=store
    def search(self, query: Dict[str,Any], limit: int=8, now: Optional[float]=None):
        q_protocol=str(query.get("protocol","")).lower()
        q_scope=str(query.get("scope","")).lower()
        q_sym=_tok(query.get("symptoms",[]))
        q_text=_tok(query.get("text",""))
        now = now if now is not None else time.time()
        scored=[]
        for row in self.store._index():
            if row.get("status")!="ACTIVE": continue
            score=0.0
            if q_protocol and str(row.get("protocol","")).lower()==q_protocol: score+=3
            if q_scope and str(row.get("scope","")).lower()==q_scope: score+=2
            score += len(q_sym & _tok(row.get("symptoms",[]))) * 1.5
            score += len(q_text & _tok([row.get("title",""),row.get("root_cause","")])) * 0.75
            score += {"CONFIRMED":2,"HIGH":1.5,"MEDIUM":.75,"LOW":.25}.get(row.get("confidence",""),0)
            score += _recency_score(row, now)
            if score>0: scored.append((score,row))
        scored.sort(key=lambda x:x[0],reverse=True)
        out=[]
        for score,row in scored[:limit]:
            mem=self.store.get(row["memory_id"])
            if mem: out.append({"score":score,"memory":mem})
        return out

class MemoryConsolidator:
    def __init__(self, store: MemoryStore): self.store=store
    def from_closed_finding(self, finding: Dict[str,Any], verification: Dict[str,Any]):
        if finding.get("status") not in ("CLOSED","VERIFIED"):
            raise ValueError("finding not closed")
        if verification.get("single_sim")!="PASS":
            raise ValueError("single_sim PASS required")
        if verification.get("regression") not in ("PASS","NOT_REQUIRED"):
            raise ValueError("regression PASS/NOT_REQUIRED required")
        if verification.get("reaudit")!="CLEAN":
            raise ValueError("reaudit CLEAN required")
        return self.store.add("engineering",{
            "title":finding.get("title") or finding.get("description","Verified finding"),
            "protocol":finding.get("protocol"),
            "scope":finding.get("scope"),
            "symptoms":finding.get("symptoms",[]),
            "root_cause":finding.get("root_cause"),
            "fix":finding.get("fix"),
            "evidence":finding.get("evidence",[]),
            "verification":verification,
            "confidence":"CONFIRMED",
            "reusable":True,
            "current_evidence_required":True,
            "source_finding_id":finding.get("finding_id")
        })

class MemoryGC:
    def __init__(self, store: MemoryStore): self.store=store
    def deprecate(self, memory_id: str, reason: str):
        mem=self.store.get(memory_id)
        if not mem: return False
        mem["status"]="DEPRECATED"
        mem["deprecation_reason"]=reason
        self.store.add(mem["level"],mem)
        return True

    # Staleness/correction lifecycle for a shared, cross-user knowledge base
    # (added for the Linux-server shared knowledge-center feature). None of
    # these statuses are new to the *reader* side: MemoryRetriever.search()
    # and gates._ccl_reuse_verified()'s CornerCaseLibrary counterpart already
    # filter/require `status == "ACTIVE"`, so simply moving a record OFF
    # "ACTIVE" here is sufficient to make every existing reuse/search path
    # stop trusting it -- no other code needed to change to enforce this.
    def supersede(self, memory_id: str, superseded_by: str, reason: str):
        """A newer, corrected record replaces this one (e.g. a different
        user's harness re-derived the same claim with better evidence)."""
        mem=self.store.get(memory_id)
        if not mem: return False
        mem["status"]="SUPERSEDED"
        mem["superseded_by"]=superseded_by
        mem["supersede_reason"]=reason
        self.store.add(mem["level"],mem)
        return True

    def retract(self, memory_id: str, reason: str, evidence: Optional[Dict[str,Any]]=None):
        """The record was found to be wrong outright (no replacement exists
        yet). Mirrors CLAUDE.md's Evidence Truth Rule: a retraction should
        itself cite the evidence that overturned the original claim, not
        just an opinion -- `evidence` is stored but not schema-enforced here
        (enforcement belongs to whichever gate consumes it)."""
        mem=self.store.get(memory_id)
        if not mem: return False
        mem["status"]="RETRACTED"
        mem["retraction_reason"]=reason
        mem["retraction_evidence"]=evidence or {}
        self.store.add(mem["level"],mem)
        return True

    def flag_stale(self, memory_id: str, reason: str=""):
        """Mark as needing revalidation before further reuse, without
        claiming it is actually wrong -- e.g. it has aged past
        knowledge_center.max_age_days, or a related-but-not-identical record
        now conflicts with it."""
        mem=self.store.get(memory_id)
        if not mem: return False
        mem["status"]="NEEDS_REVALIDATION"
        mem["stale_reason"]=reason
        self.store.add(mem["level"],mem)
        return True

    def confirm(self, memory_id: str, evidence: Optional[Dict[str,Any]]=None):
        """An independent, later run re-derived the SAME conclusion with
        fresh evidence: bump confirmation_count/last_confirmed_at, and if it
        had been flagged NEEDS_REVALIDATION, restore it to ACTIVE -- this is
        the accumulation mechanism that makes repeated independent agreement
        actually count for something, rather than every record being
        trusted equally forever regardless of how many times it has (or
        hasn't) been re-confirmed."""
        mem=self.store.get(memory_id)
        if not mem: return False
        mem["confirmation_count"]=int(mem.get("confirmation_count",0))+1
        mem["last_confirmed_at"]=time.time()
        if evidence:
            mem["last_confirmation_evidence"]=evidence
        if mem.get("status")=="NEEDS_REVALIDATION":
            mem["status"]="ACTIVE"
        self.store.add(mem["level"],mem)
        return True

# Corner-case Library: a cross-project persistent store distinct from
# MemoryStore's project/engineering levels above. MemoryStore rows are
# resolved findings tied to a single project's history; a corner case is a
# reusable STIMULUS/CONFIGURATION pattern (a way to hit a class of bug),
# indexed by protocol/category/risk rather than by a single root cause, and
# meant to be searched by future planning stages (SOC_SCENARIO_PLANNER,
# COVERAGE_CLOSURE) before those stages invent scenarios from scratch.
CORNER_CASE_CATEGORIES = [
    "reset_power", "concurrency", "ordering", "backpressure", "resource_limit",
    "cdc_timing", "error_fault", "recovery", "cross_feature", "cross_protocol",
    "traffic_pattern", "state_transition",
]
CORNER_CASE_RISK_TIERS = ["P0", "P1", "P2", "P3"]

class CornerCaseLibrary:
    def __init__(self, project_root: Path):
        self.root = project_root.resolve()
        self.dir = self.root/".dv-harness"/"memory"/"corner_case_library"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.dir/"index.json"
        if not self.index_file.exists():
            self.index_file.write_text("[]", encoding="utf-8")

    def _index(self):
        return json.loads(self.index_file.read_text(encoding="utf-8"))

    def _save_index(self, rows):
        self.index_file.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, record: Dict[str, Any]) -> Dict[str, Any]:
        rec = dict(record)
        if rec.get("category") not in CORNER_CASE_CATEGORIES:
            raise ValueError(f"category must be one of {CORNER_CASE_CATEGORIES}")
        if rec.get("risk_tier") not in CORNER_CASE_RISK_TIERS:
            raise ValueError(f"risk_tier must be one of {CORNER_CASE_RISK_TIERS}")
        ccid = rec.get("ccl_id") or f"CCL-{uuid.uuid4().hex[:10].upper()}"
        rec["ccl_id"] = ccid
        rec.setdefault("created_at", time.time())
        rec.setdefault("last_used_at", None)
        rec.setdefault("reuse_count", 0)
        rec.setdefault("confidence", "VALIDATED")
        rec.setdefault("status", "ACTIVE")
        rec.setdefault("current_evidence_required", True)
        rec.setdefault("applicability_conditions", [])
        rec.setdefault("resolution", {})
        rec.setdefault("evidence", {})
        # Staleness/provenance fields for the shared knowledge-center feature.
        # `revalidate_by` (epoch seconds, None = no auto-expiry) lets
        # gates._ccl_reuse_verified() reject a reuse claim once a record has
        # aged past knowledge_center.max_age_days without being re-confirmed,
        # even if nothing has explicitly proven it wrong yet -- CLAUDE.md's
        # "memory is prior knowledge, not current evidence" applies to age,
        # not just correctness. `provenance` records who/where a shared
        # record came from (absent for a purely local, non-shared record).
        rec.setdefault("revalidate_by", None)
        rec.setdefault("provenance", None)
        rec.setdefault("confirmation_count", 0)
        rec.setdefault("last_confirmed_at", None)
        p = self.dir/f"{ccid}.json"
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = [x for x in self._index() if x.get("ccl_id") != ccid]
        rows.append({
            "ccl_id": ccid, "corner_id": rec.get("corner_id"),
            "protocol": rec.get("protocol"), "category": rec.get("category"),
            "risk_tier": rec.get("risk_tier"), "description": rec.get("description", ""),
            "applicability_conditions": rec.get("applicability_conditions", []),
            "status": rec.get("status", "ACTIVE"), "path": str(p.relative_to(self.root)),
            "created_at": rec.get("created_at"), "last_used_at": rec.get("last_used_at"),
            "reuse_count": rec.get("reuse_count", 0),
        })
        self._save_index(rows)
        return rec

    def get(self, ccl_id: str) -> Optional[Dict[str, Any]]:
        p = self.dir/f"{ccl_id}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def mark_reused(self, ccl_id: str):
        rec = self.get(ccl_id)
        if not rec: return
        rec["last_used_at"] = time.time()
        rec["reuse_count"] = int(rec.get("reuse_count", 0)) + 1
        self.add(rec)

    def deprecate(self, ccl_id: str, reason: str) -> bool:
        rec = self.get(ccl_id)
        if not rec: return False
        rec["status"] = "DEPRECATED"
        rec["deprecation_reason"] = reason
        self.add(rec)
        return True

    def supersede(self, ccl_id: str, superseded_by: str, reason: str) -> bool:
        rec = self.get(ccl_id)
        if not rec: return False
        rec["status"] = "SUPERSEDED"
        rec["superseded_by"] = superseded_by
        rec["supersede_reason"] = reason
        self.add(rec)
        return True

    def retract(self, ccl_id: str, reason: str, evidence: Optional[Dict[str, Any]] = None) -> bool:
        rec = self.get(ccl_id)
        if not rec: return False
        rec["status"] = "RETRACTED"
        rec["retraction_reason"] = reason
        rec["retraction_evidence"] = evidence or {}
        self.add(rec)
        return True

    def flag_stale(self, ccl_id: str, reason: str = "") -> bool:
        rec = self.get(ccl_id)
        if not rec: return False
        rec["status"] = "NEEDS_REVALIDATION"
        rec["stale_reason"] = reason
        self.add(rec)
        return True

    def confirm(self, ccl_id: str, evidence: Optional[Dict[str, Any]] = None) -> bool:
        rec = self.get(ccl_id)
        if not rec: return False
        rec["confirmation_count"] = int(rec.get("confirmation_count", 0)) + 1
        rec["last_confirmed_at"] = time.time()
        if evidence:
            rec["last_confirmation_evidence"] = evidence
        if rec.get("status") == "NEEDS_REVALIDATION":
            rec["status"] = "ACTIVE"
        self.add(rec)
        return True

    def search(self, query: Dict[str, Any], limit: int = 8, now: Optional[float] = None):
        q_protocol = str(query.get("protocol", "")).lower()
        q_category = str(query.get("category", "")).lower()
        q_text = _tok(query.get("text", ""))
        now = now if now is not None else time.time()
        scored = []
        for row in self._index():
            if row.get("status") != "ACTIVE": continue
            score = 0.0
            if q_protocol and str(row.get("protocol", "")).lower() == q_protocol: score += 3
            if q_category and str(row.get("category", "")).lower() == q_category: score += 2
            score += len(q_text & _tok([row.get("description", ""), row.get("corner_id", "")])) * 1.0
            score += {"P0": 2, "P1": 1.5, "P2": .75, "P3": .25}.get(row.get("risk_tier", ""), 0)
            score += _recency_score(row, now)
            if score > 0 or (not q_protocol and not q_category and not q_text):
                scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, row in scored[:limit]:
            rec = self.get(row["ccl_id"])
            if rec: out.append({"score": score, "corner_case": rec})
        return out

# Per-tier convenience accessors for the MEMORY_LEVELS that -- unlike
# "engineering" (which gets a dedicated write-path via MemoryConsolidator)
# and the separate CornerCaseLibrary -- previously had no accessor of their
# own, only the generic MemoryStore.add()/get() with an explicit level
# argument. working/job/project each wrap the SAME backing store/file shape
# used by every MEMORY_LEVELS tier (.dv-harness/memory/<level>/<memory_id>.json
# plus the shared index.json) with a fixed level -- no new file format is
# introduced, this is a thin fixed-level wrapper around MemoryStore, which
# already creates and reads/writes all five tiers.
class _TierMemoryStore:
    level: str = ""
    def __init__(self, project_root: Path):
        self.store = MemoryStore(project_root)
    def add(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        return self.store.add(self.level, memory)
    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        mem = self.store.get(memory_id)
        return mem if mem and mem.get("level") == self.level else None
    def mark_used(self, memory_id: str):
        return self.store.mark_used(memory_id)

class WorkingMemoryStore(_TierMemoryStore):
    level = "working"

class JobMemoryStore(_TierMemoryStore):
    level = "job"

class ProjectMemoryStore(_TierMemoryStore):
    level = "project"

# organizational_memory is the top of the 5-layer pyramid -- durable,
# cross-project best-practices/lessons-learned meant to be read by every
# user's harness, not just this one. Unlike working/job/project above, its
# real backing store is the ALREADY-EXISTING shared, cross-user Knowledge
# Center (dv_harness/knowledge_center.py's KnowledgeCenterClient, talking to
# tools/knowledge_center/broker.py on the Linux server) -- not a new local
# `.dv-harness/memory/organizational/` file store, which would just be a
# second, disconnected copy of what memory_router.py's existing
# _SHAREABLE_DESTINATIONS best-effort push already treats as shareable.
# Constructed the same way every other KnowledgeCenterClient call site does
# (see cli.py's `knowledge` subcommands, dashboard.py's /api/knowledge/*):
# cfg from config.load_config(project_root), then KnowledgeCenterClient(cfg,
# project_root). Every method here is best-effort like the client itself --
# it delegates straight to KnowledgeCenterClient, which never raises on a
# transport/configuration problem and instead returns an honest
# {"ok": False, "error": ...} dict; callers should check "ok", not expect an
# exception.
class OrganizationalMemoryStore:
    def __init__(self, project_root: Path, cfg: Optional[Dict[str, Any]] = None):
        from .config import load_config
        from .knowledge_center import KnowledgeCenterClient
        self.project_root = Path(project_root)
        self.cfg = cfg if cfg is not None else load_config(self.project_root)
        self.client = KnowledgeCenterClient(self.cfg, self.project_root)

    def configured(self) -> bool:
        return self.client.configured()

    def add(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        # Mirrors memory_router._maybe_share's existing convention for this
        # same destination: category fixed to "_general" (organizational
        # lessons aren't protocol-family-scoped the way engineering/corner-case
        # records are), protocol taken from the record when present.
        protocol = memory.get("protocol") or "_general"
        return self.client.add("_general", protocol, memory)

    def search(self, query: Optional[Dict[str, Any]] = None, limit: int = 8) -> Dict[str, Any]:
        query = query or {}
        return self.client.search(query.get("category", ""), query.get("protocol", ""),
                                   query.get("text", ""), limit)

class CornerCaseLibraryConsolidator:
    # Mirrors MemoryConsolidator.from_closed_finding's validation-gate shape:
    # a corner case only gets persisted once it has actually been exercised
    # and semantically judged against real evidence, not merely proposed.
    def __init__(self, library: CornerCaseLibrary): self.library = library
    def from_resolved_corner_case(self, corner_case: Dict[str, Any], resolution: Dict[str, Any]):
        if not resolution.get("test_mapping"):
            raise ValueError("resolution.test_mapping required")
        if resolution.get("semantic_verdict") not in ("TRUE_PASS", "TRUE_FAIL"):
            raise ValueError("resolution.semantic_verdict must be TRUE_PASS or TRUE_FAIL")
        if not resolution.get("runtime_evidence_hash"):
            raise ValueError("resolution.runtime_evidence_hash required")
        record = dict(corner_case)
        record["resolution"] = resolution
        record["evidence"] = {
            "test_mapping": resolution["test_mapping"],
            "semantic_verdict": resolution["semantic_verdict"],
            "runtime_evidence_hash": resolution["runtime_evidence_hash"],
        }
        record["confidence"] = "VALIDATED"
        return self.library.add(record)
