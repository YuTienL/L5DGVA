from __future__ import annotations
import json, os, uuid, time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from .memory_artifact_policy import enforce_record_artifact_policy
from .memory_security import redact_record

MEMORY_LEVELS=["working","job","project","engineering","organizational"]


def _guard_record_before_write(mem: Dict[str,Any]) -> Dict[str,Any]:
    """The one write-time guard every record in this module passes through
    before it reaches disk (2026-09-04, gap-close-obsidian-memory phases
    12+19).

    THE GAP THIS CLOSES, confirmed by full-repo grep before it was written:
    `memory_security.py`'s real secret detector/redactor was wired ONLY into
    `memory_vault.FileSystemMarkdownAdapter.create()`/`update()` -- the
    Markdown MIRROR. This module, which `memory_router.py` itself documents
    as "the durable JSON record (the system of record)", never referenced it.
    Every record write lands here FIRST and unredacted; the mirror, if any,
    is written seconds later, only for JOB/PROJECT/ENGINEERING/
    ORGANIZATIONAL destinations, and only when a truthy `cfg` was passed --
    while WORKING_MEMORY (every react-loop reasoning step) is excluded from
    the mirror by design and so was never scanned by anything at all. A
    secret-shaped string embedded in a legitimate record's free-text field
    (symptom/evidence/terminal_signature/hypothesis) passed
    `route_memory()`'s kind-only REJECT untouched and was written verbatim,
    permanently. The same hole existed for CLAUDE.md's "never store giant
    logs or raw FSDB content" rule: `memory_doctor.check_large_files()` only
    ever walked the Markdown vault tree, never `.dv-harness/memory/**`.

    Ordering is deliberate: REDACT FIRST, then bound size. Truncating first
    can split a multi-line secret (an SSH PEM block) so that its
    BEGIN/END-anchored pattern no longer matches, leaving real key material
    in the surviving text unredacted.
    """
    mem, secret_findings = redact_record(mem)
    if secret_findings:
        mem["secrets_redacted"] = True
        mem["secrets_redacted_types"] = sorted({f["type"] for f in secret_findings})
    mem, artifact_report = enforce_record_artifact_policy(mem)
    if artifact_report["truncated_fields"]:
        mem["large_artifact_truncated"] = artifact_report["truncated_fields"]
    return mem


class PropertyFilterError(ValueError):
    """A `--property` CLI argument that is not `KEY=VALUE`."""


def parse_property_filters(items) -> Dict[str,str]:
    """Turn repeated `--property KEY=VALUE` CLI arguments into the
    `query["property"]` dict both MemoryRetriever.search() (JSON MemoryStore)
    and memory_vault.FileSystemMarkdownAdapter.search() (Markdown vault
    mirror) already accept. Shared by `dv-harness memory search` and
    `python -m dv_harness.memory_cli search` so the two CLIs cannot drift on
    how a property filter is spelled. Only the FIRST `=` splits, so a value
    may itself contain `=`."""
    out: Dict[str,str]={}
    for item in items or []:
        key,sep,value=str(item).partition("=")
        if not sep or not key.strip():
            raise PropertyFilterError(f"expected KEY=VALUE, got {item!r}")
        out[key.strip()]=value.strip()
    return out

# REMOVED (2026-09-03, gap-close-engine cleanup): a `current_evidence_required`
# field used to be set to `True` on every MemoryStore record (all 5 tiers)
# via `add()`'s setdefault below, and again explicitly `True` in
# MemoryConsolidator.from_closed_finding()'s "engineering"-tier write. Full-
# repo audit found zero read sites anywhere -- no gate, engine code, CLI, or
# dashboard ever consulted it -- and no write path ever set it to anything
# but `True`, so it could never have discriminated one record from another
# even if something had read it. The real, actually-wired "revalidate before
# trusting" mechanism for reused knowledge in this codebase is
# gates._ccl_reuse_verified() (status=="ACTIVE" + unexpired revalidate_by +
# real evidence.runtime_evidence_hash/semantic_verdict) -- built independently
# using different fields, for CornerCaseLibrary records specifically (see
# CornerCaseLibrary.add()/CornerCaseLibraryConsolidator below, which keep
# their OWN current_evidence_required field, now with real read-side
# enforcement in gates.py). Plain MemoryStore records (this class) have no
# citation/skip-gate consumer at all -- they only ever reach a stage prompt
# as informational relevant_memory context, already uniformly disclaimed by
# prompts.py regardless of any per-record flag -- so this field was dead
# weight here specifically, not a smaller version of the CCL mechanism.
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
        # Atomic replace rather than a truncate-then-write (2026-09-03,
        # gap-close-obsidian-memory phase 4+5): index.json is read by every
        # MemoryRetriever.search() call, and a plain write_text() leaves a
        # real window in which a concurrent reader sees a truncated/partial
        # JSON document and raises JSONDecodeError. os.replace() is atomic on
        # both POSIX and Windows, so a reader always sees either the whole
        # previous index or the whole new one.
        tmp=self.index_file.with_name(f"index.json.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(str(tmp),str(self.index_file))

    # Cross-process lock guarding index.json's read-modify-write (2026-09-03,
    # gap-close-obsidian-memory phase 4+5). REAL, MEASURED DEFECT this closes:
    # this project's own live store had 18 of 31 engineering-tier and 13 of 14
    # working-tier record FILES on disk with no corresponding index.json row,
    # making them invisible to MemoryRetriever.search() (which iterates
    # _index(), memory.py's search() below) while still reachable by exact id
    # via get() (which reads the file directly). The signature -- every record
    # file intact, only index rows missing -- is a classic lost update: two
    # processes (this session runs several concurrent agents, each calling
    # route_and_store()) both _index(), both append their own row, and the
    # second _save_index() overwrites the first's row. A lock directory is
    # used because os.mkdir() is atomic on both POSIX and Windows with no
    # extra dependency (fcntl/msvcrt differ per platform; this module must
    # work on both this project's Windows dev end and its Linux server).
    #
    # AVAILABILITY over strictness, deliberately: if the lock cannot be
    # acquired within _INDEX_LOCK_TIMEOUT_S even after breaking a stale one,
    # add() proceeds WITHOUT the lock rather than raising -- a memory write
    # must never break the engine stage/reconcile that triggered it (the same
    # best-effort discipline every route_and_store() call site already
    # applies). reindex() below exists to repair whatever such a window loses.
    _INDEX_LOCK_TIMEOUT_S = 10.0
    _INDEX_LOCK_STALE_S = 60.0

    @contextmanager
    def _index_lock(self):
        lock_dir=self.dir/".index.lock"
        acquired=False
        deadline=time.monotonic()+self._INDEX_LOCK_TIMEOUT_S
        while True:
            try:
                os.mkdir(str(lock_dir))
                acquired=True
                break
            except FileExistsError:
                try:
                    age=time.time()-lock_dir.stat().st_mtime
                except OSError:
                    age=0.0
                if age>self._INDEX_LOCK_STALE_S:
                    try:
                        os.rmdir(str(lock_dir))
                    except OSError:
                        pass
                    continue
                if time.monotonic()>=deadline:
                    break
                time.sleep(0.02)
            except OSError:
                break
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    os.rmdir(str(lock_dir))
                except OSError:
                    pass

    def _index_row(self, level: str, mem: Dict[str,Any], path: Path) -> Dict[str,Any]:
        return {
            "memory_id":mem.get("memory_id"),"level":level,"title":mem.get("title",""),
            "protocol":mem.get("protocol"),"scope":mem.get("scope"),
            "symptoms":mem.get("symptoms",[]),"root_cause":mem.get("root_cause"),
            "confidence":mem.get("confidence"),"status":mem.get("status","ACTIVE"),
            "path":str(path.relative_to(self.root)),
            "created_at":mem.get("created_at"),
            "last_used_at":mem.get("last_used_at"),"reuse_count":mem.get("reuse_count",0)
        }

    # Fields that record INDEPENDENT RE-CONFIRMATION of a record, and which
    # therefore may never be set by whoever supplies the record body. They are
    # the direct input to memory_router.promote_to_organizational()'s third
    # gate (confirmation_count >= ORGANIZATIONAL_MIN_CONFIRMATIONS), i.e. to
    # CLAUDE.md's "a second independent run re-deriving the same
    # root_cause/protocol -- not the same run reported twice".
    # `last_confirmation_evidence` deliberately has no entry: it is simply
    # ABSENT until a confirm() supplies one, which is distinct from present-
    # and-empty and must stay that way on a record that was never confirmed.
    _CONFIRMATION_OWNED_DEFAULTS = {"confirmation_count": 0, "last_confirmed_at": None}
    _CONFIRMATION_OWNED_FIELDS = ("confirmation_count", "last_confirmed_at",
                                  "last_confirmation_evidence")

    def _apply_confirmation_integrity(self, mid: str, mem: Dict[str,Any]):
        """Force the confirmation fields to their real on-disk values,
        discarding whatever the caller put there (2026-09-04, gap-close-
        obsidian-memory phase 4+5).

        THE GAP THIS CLOSES, reproduced live before it was written: these
        were plain `setdefault`s, so a caller-supplied value passed through
        verbatim. A SINGLE route_and_store() creation event carrying
        {"confirmation_count": 7} was written to the engineering tier with
        confirmation_count=7 and then promoted straight to ORGANIZATIONAL
        by promote_to_organizational() -- clearing a gate whose entire
        purpose is to require a second, independently-derived run. The
        qualitative and quantitative gates are unforgeable in the same way
        (one re-derives a verification block's shape, the other is computed
        from caller inputs at promotion time), but the counter was simply
        read back from the record body, so the record could assert its own
        eligibility.

        MemoryGC.confirm() -- the one authorized writer, which increments
        from the stored value under the caller's own read-modify-write --
        passes _confirmation_write=True to bypass this. Every other writer
        (route_and_store()/_add_or_confirm_engineering() creating a record,
        mark_used()/_write_back_knowledge_commit_sha() round-tripping one,
        MemoryGC's revalidation paths) keeps whatever is already on disk,
        so a re-add can neither invent nor silently drop confirmations.
        """
        prior=self.get(mid) or {}
        for field in self._CONFIRMATION_OWNED_FIELDS:
            if field in prior:
                mem[field]=prior[field]
            elif field in self._CONFIRMATION_OWNED_DEFAULTS:
                mem[field]=self._CONFIRMATION_OWNED_DEFAULTS[field]
            else:
                mem.pop(field,None)

    def add(self, level: str, memory: Dict[str,Any], *, _confirmation_write: bool=False):
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
        mem.setdefault("provenance",None)
        if _confirmation_write:
            for field,default in self._CONFIRMATION_OWNED_DEFAULTS.items():
                mem.setdefault(field,default)
        else:
            self._apply_confirmation_integrity(mid,mem)
        mem=_guard_record_before_write(mem)
        p=self.dir/level/f"{mid}.json"
        p.write_text(json.dumps(mem,ensure_ascii=False,indent=2),encoding="utf-8")
        with self._index_lock():
            rows=[x for x in self._index() if x.get("memory_id")!=mid]
            rows.append(self._index_row(level,mem,p))
            self._save_index(rows)
        return mem

    def index_integrity(self) -> Dict[str,Any]:
        """Read-only drift report between the real per-tier record FILES on
        disk and index.json's rows -- the two halves MemoryRetriever.search()
        (index-driven) and get() (file-driven) each read. Never repairs
        anything; reindex() below does that. Backs memory_doctor's
        `memory_store_index` check."""
        rows=self._index()
        indexed={str(r.get("memory_id")) for r in rows if r.get("memory_id")}
        files_missing_from_index: List[Dict[str,Any]] = []
        per_level: Dict[str,Dict[str,int]] = {}
        on_disk=set()
        for lv in MEMORY_LEVELS:
            level_files=sorted(p for p in (self.dir/lv).glob("*.json"))
            level_rows=[r for r in rows if r.get("level")==lv]
            per_level[lv]={"files":len(level_files),"index_rows":len(level_rows)}
            for p in level_files:
                on_disk.add(p.stem)
                if p.stem not in indexed:
                    files_missing_from_index.append({"memory_id":p.stem,"level":lv,
                                                      "path":str(p.relative_to(self.root))})
        index_rows_without_file=[
            {"memory_id":r.get("memory_id"),"level":r.get("level"),"path":r.get("path")}
            for r in rows if str(r.get("memory_id")) not in on_disk
        ]
        return {
            "ok":not files_missing_from_index and not index_rows_without_file,
            "index_row_count":len(rows),
            "record_file_count":len(on_disk),
            "per_level":per_level,
            "files_missing_from_index":files_missing_from_index,
            "index_rows_without_file":index_rows_without_file,
        }

    def reindex(self, prune_missing: bool=False) -> Dict[str,Any]:
        """Repair index.json from the real record files on disk -- the one
        source of truth for what this store actually holds (each tier file IS
        the record; the index is a derived search projection of it, see
        _index_row()).

        Adds a row for every record file that has none (making it visible to
        MemoryRetriever.search() again) and refreshes the row of every file
        whose stored row has drifted from the file's own current content.
        Rows whose record file no longer exists are only REPORTED by default,
        never dropped -- dropping is destructive and such a row is already
        inert for search purposes (search() calls get(), which returns None,
        and the hit is skipped); pass prune_missing=True to remove them
        deliberately. An unreadable/unparseable record file is reported and
        skipped, never guessed at."""
        with self._index_lock():
            rows=self._index()
            by_id={str(r.get("memory_id")):r for r in rows if r.get("memory_id")}
            added: List[str] = []
            refreshed: List[str] = []
            unreadable: List[Dict[str,str]] = []
            on_disk=set()
            for lv in MEMORY_LEVELS:
                for p in sorted((self.dir/lv).glob("*.json")):
                    on_disk.add(p.stem)
                    try:
                        mem=json.loads(p.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError) as exc:
                        unreadable.append({"memory_id":p.stem,"level":lv,"error":str(exc)})
                        continue
                    mem.setdefault("memory_id",p.stem)
                    row=self._index_row(lv,mem,p)
                    prior=by_id.get(p.stem)
                    if prior is None:
                        by_id[p.stem]=row
                        added.append(p.stem)
                    elif prior!=row:
                        by_id[p.stem]=row
                        refreshed.append(p.stem)
            pruned: List[str] = []
            for mid in [m for m in by_id if m not in on_disk]:
                if prune_missing:
                    by_id.pop(mid)
                pruned.append(mid)
            self._save_index(sorted(by_id.values(), key=lambda r: (r.get("level") or "",
                                                                    str(r.get("memory_id")))))
        return {
            "added":added,"refreshed":refreshed,
            "rows_without_file":pruned,"pruned":prune_missing,
            "unreadable_record_files":unreadable,
            "index_row_count":len(by_id),
        }

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

# Common English function words excluded from _tok so a shared preposition/
# article/pronoun (e.g. both an unrelated LSF record's title and an
# unrelated coverage query happening to each contain the word "in") can
# never by itself manufacture a text-overlap match -- see finding I2's
# relevance-floor fix in MemoryRetriever.search(), which now depends on
# text-overlap tokens actually meaning something.
_STOPWORDS = {
    "a","an","the","in","on","of","to","is","are","was","were","be","been",
    "and","or","for","with","this","that","it","its","as","at","by","from",
    "into","onto","over","under","up","down","not","no","so","if","then",
    "than","too","also","do","does","did","has","have","had","can","will",
    "due","during",
}

def _tok(v):
    if v is None: return set()
    if isinstance(v,list): v=" ".join(map(str,v))
    return {
        x.lower() for x in str(v).replace("/"," ").replace("_"," ").replace("-"," ").split()
        if len(x)>1 and x.lower() not in _STOPWORDS
    }

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
    # Sentinel accepted by search()'s `status` key to mean "any status at all"
    # (including DEPRECATED/SUPERSEDED records MemoryGC.deprecate() wrote) --
    # search() otherwise defaults to ACTIVE-only, which is what every existing
    # caller relies on.
    STATUS_ANY = ("ANY", "*")

    def __init__(self, store: MemoryStore): self.store=store

    def _record_field(self, row: Dict[str,Any], key: str, record_cache: Dict[str,Any]):
        """Value of `key` for an index row, reading the full record file only
        when the index row does not carry that key. _index_row() persists a
        fixed subset (protocol/scope/symptoms/root_cause/confidence/status/
        level/title/...); an arbitrary property filter must still be able to
        reach a field that lives only in the record itself (e.g. `subsystem`,
        `kind`, `project`, `verified`). The cache keeps that to at most one
        file read per candidate row, not one per filter key."""
        if key in row:
            return row.get(key)
        mid=str(row.get("memory_id"))
        if mid not in record_cache:
            record_cache[mid]=self.store.get(mid) or {}
        return record_cache[mid].get(key)

    @staticmethod
    def _property_matches(actual: Any, wanted: Any) -> bool:
        if isinstance(actual, (list, tuple, set)):
            return str(wanted) in {str(x) for x in actual}
        return str(actual)==str(wanted)

    def search(self, query: Dict[str,Any], limit: int=8, now: Optional[float]=None):
        q_protocol=str(query.get("protocol","")).lower()
        q_scope=str(query.get("scope","")).lower()
        q_sym=_tok(query.get("symptoms",[]))
        q_text=_tok(query.get("text",""))
        # Structural filters (2026-09-04, gap-close-obsidian-memory phase 9):
        # level/confidence/status/arbitrary-property, so the JSON MemoryStore's
        # own retrieval reaches the same filter classes the Vault mirror's
        # FileSystemMarkdownAdapter.search() already offered. Tag and wiki-link
        # filters are deliberately NOT added here: MemoryStore records carry
        # neither field (they are Markdown-note concepts owned by
        # memory_vault.py), so a filter for them would match nothing by
        # construction.
        q_levels=query.get("level") or query.get("memory_level")
        if isinstance(q_levels,str): q_levels=[q_levels]
        q_levels={str(x) for x in (q_levels or [])}
        q_confidence=str(query.get("confidence","")).upper()
        status_raw=query.get("status")
        status_explicit=bool(status_raw)
        q_status=str(status_raw or "ACTIVE").upper()
        status_any=status_explicit and q_status in self.STATUS_ANY
        property_filters=dict(query.get("property") or {})
        record_cache: Dict[str,Any]={}
        now = now if now is not None else time.time()
        scored=[]
        for row in self.store._index():
            if not status_any and str(row.get("status","")).upper()!=q_status: continue
            if q_levels and str(row.get("level")) not in q_levels: continue
            if q_confidence and str(row.get("confidence","")).upper()!=q_confidence: continue
            if property_filters and not all(
                self._property_matches(self._record_field(row,k,record_cache),v)
                for k,v in property_filters.items()
            ): continue
            # Relevance floor (2026-08-31 fix wave, finding I2): _recency_score
            # is ALWAYS positive for any record with a timestamp (up to 1.0,
            # decaying), and confidence contributes independently of the
            # query too -- so before this floor, a record with genuinely ZERO
            # overlap with the query (no protocol/scope/symptom/text match at
            # all) still scored >0 and was returned as "relevant" purely from
            # age/confidence. Confirmed empirically: an unrelated
            # ethernet/LSF record was returned for an unrelated USB coverage
            # query at score 1.0 (pure recency). `relevance` below sums ONLY
            # the query-overlap components; a record must clear a positive
            # relevance floor to be considered at all, no matter how fresh or
            # how confident it is -- recency/confidence still shape ranking
            # AMONG genuinely relevant hits, they just can't manufacture
            # relevance on their own.
            #
            # A structural filter the caller EXPLICITLY passed (level/
            # confidence/status/property) does count toward relevance: unlike
            # recency/confidence-as-ranking-bonus, a record that survives an
            # explicit filter genuinely matched a stated part of the query, so
            # "list every ACTIVE engineering-tier record" must not be emptied
            # out by the floor. Queries that pass no structural filter are
            # unaffected -- their relevance is still text/protocol/scope/
            # symptom overlap only, exactly as finding I2 required.
            relevance=0.0
            if q_levels: relevance+=1
            if q_confidence: relevance+=1
            if status_explicit: relevance+=1
            relevance += len(property_filters) * 1.0
            if q_protocol and str(row.get("protocol","")).lower()==q_protocol: relevance+=3
            if q_scope and str(row.get("scope","")).lower()==q_scope: relevance+=2
            relevance += len(q_sym & _tok(row.get("symptoms",[]))) * 1.5
            relevance += len(q_text & _tok([row.get("title",""),row.get("root_cause","")])) * 0.75
            if relevance<=0: continue
            score = relevance
            score += {"CONFIRMED":2,"HIGH":1.5,"MEDIUM":.75,"LOW":.25}.get(row.get("confidence",""),0)
            score += _recency_score(row, now)
            scored.append((score,row))
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
        hasn't) been re-confirmed.

        This is the ONLY authorized writer of the confirmation fields
        (MemoryStore._CONFIRMATION_OWNED_FIELDS) -- it increments from the
        value already on disk and passes _confirmation_write=True, which is
        what MemoryStore.add() requires before it will accept them from a
        record body at all. See _apply_confirmation_integrity()."""
        mem=self.store.get(memory_id)
        if not mem: return False
        mem["confirmation_count"]=int(mem.get("confirmation_count",0))+1
        mem["last_confirmed_at"]=time.time()
        if evidence:
            mem["last_confirmation_evidence"]=evidence
        if mem.get("status")=="NEEDS_REVALIDATION":
            mem["status"]="ACTIVE"
        self.store.add(mem["level"],mem,_confirmation_write=True)
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
        # current_evidence_required (2026-09-03, gap-close-engine cleanup:
        # gave this field a real False-setter and a real read site, see
        # CornerCaseLibraryConsolidator.from_resolved_corner_case() below and
        # gates._ccl_reuse_verified()): defaults True on this bare add() path
        # -- a record hand-added here (not through the validated
        # from_resolved_corner_case() write path below) is NOT reuse-eligible
        # via REUSED_CCL:<id> even though status defaults to ACTIVE; only a
        # record actually created FROM genuine current evidence gets False.
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
        # Same write-time secret/large-artifact guard MemoryStore.add() runs
        # (see _guard_record_before_write above). The corner-case library is a
        # separate file store that never passes through MemoryStore, and its
        # records ARE pushed to the shared cross-user Knowledge Center
        # (memory_router._SHAREABLE_DESTINATIONS), so leaving it unguarded
        # would keep exactly the leak path this guard exists to close.
        rec = _guard_record_before_write(rec)
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
    # CROSS-REFERENCE (memory-engine-schema-completion audit, 2026-09-01):
    # this tier's real hypothesis/evidence/next-action content is produced by
    # dv_harness.react.ReactRecorder.record() (once per outer stage attempt)
    # and pushed HERE at write time via memory_router.route_and_store()
    # (kind="react_reasoning_step" -> WORKING_MEMORY) -- see ReactRecorder's
    # module-header RULING comment for why this is a write-time push rather
    # than MemoryRetriever.search() reaching into react.py's own
    # `.dv-harness/react/` file layout at read time. Every reader of this
    # class (MemoryRetriever.search(), CLI/dashboard listings) therefore sees
    # real live reasoning state with no read-side changes needed.
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
        # (2026-09-03, gap-close-engine cleanup) this is the one write path
        # that already requires real test_mapping/semantic_verdict/
        # runtime_evidence_hash before creating the record -- i.e. the record
        # is created FROM genuine current evidence at write time -- so it is
        # reuse-eligible without further revalidation, unlike a bare
        # CornerCaseLibrary.add() record (whose current_evidence_required
        # setdefault above stays True). Enforced by gates._ccl_reuse_verified().
        record["current_evidence_required"] = False
        return self.library.add(record)
