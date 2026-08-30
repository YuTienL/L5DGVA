# NOTICE (added during industrial-grade audit, 2026-08-28): this module is
# NOT invoked by any executing code path in dv_harness/ or .claude/agents/*.md
# as of this audit -- it is standalone/orphaned code. Any WORKFLOW_MANIFEST.json
# capability flag referencing this file's feature is aspirational, not a
# statement that this code actually runs in the pipeline. See
# CHANGELOG_v0_to_v50.md and the industrial-grade-deep-audit findings for detail.
from __future__ import annotations
from pathlib import Path
import hashlib, json, time, re
from typing import Dict, Any, List

SUPPORTED = {".pdf",".docx",".txt",".md",".html",".htm",".csv",".xlsx",".xls",".sv",".v",".vh",".svh"}

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

class DocumentIndex:
    def __init__(self, project_root: Path):
        self.root=project_root.resolve()
        self.dir=self.root/".dv-harness"/"documents"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_file=self.dir/"document_index.json"
        if not self.index_file.exists():
            self.index_file.write_text("[]", encoding="utf-8")

    def load(self):
        return json.loads(self.index_file.read_text(encoding="utf-8"))

    def save(self, rows):
        self.index_file.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")

    def needs_extract(self, path: Path) -> bool:
        digest=sha256_file(path)
        for row in self.load():
            if row.get("path")==str(path.resolve()) and row.get("sha256")==digest:
                return False
        return True

    def register(self, path: Path, kind: str="generic", metadata: Dict[str,Any]|None=None):
        digest=sha256_file(path)
        rows=[r for r in self.load() if r.get("path")!=str(path.resolve())]
        rows.append({
            "path":str(path.resolve()),
            "name":path.name,
            "suffix":path.suffix.lower(),
            "sha256":digest,
            "kind":kind,
            "mtime":path.stat().st_mtime,
            "indexed_at":time.time(),
            "metadata":metadata or {}
        })
        self.save(rows)
        return rows[-1]

def normalize_register_record(record: Dict[str,Any]) -> Dict[str,Any]:
    keys=["document","version","page","section","register_name","address","bit_range",
          "field_name","access","reset_value","description","source_location"]
    return {k:record.get(k) for k in keys}

def evidence_ref(document: str, version: str, page: str, section: str, location: str=""):
    return {
        "document":document,
        "version":version,
        "page":page,
        "section":section,
        "source_location":location
    }
