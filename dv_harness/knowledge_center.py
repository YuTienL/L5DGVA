from __future__ import annotations
import json, os, subprocess, sys, tempfile, time, uuid
from pathlib import Path
from typing import Any, Dict, Optional

# Marker line the server-side broker (tools/knowledge_center/broker.py) must
# print as its LAST stdout line, exactly once, so this client can find its
# JSON result inside remote_hop.py's own "=== cmd ===" banner/echo noise
# (remote_hop.py's main() prints a banner + the command's raw output + an
# "[exit N]" line for every trailing command it runs -- see
# PACKAGE/remote_hop.py). A distinctive prefix is more robust than assuming
# the broker's JSON is the only thing on stdout.
RESULT_MARKER = "DVHKC_RESULT:"


def _default_user() -> str:
    # Same fallback chain as control_plane.py's _default_user() -- reused
    # here (not imported, to keep this module import-light and because
    # control_plane's version is private) so a shared-knowledge-center write
    # is attributed the same way a human-control-plane action already is.
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def _default_host() -> str:
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown-host"


class KnowledgeCenterClient:
    """Local-side client for the shared, cross-user knowledge center that
    lives at a fixed path on a Linux server (dv_harness/config.py's
    `knowledge_center` block). Talks to it exclusively through
    tools/knowledge_center/broker.py running ON the server, invoked over the
    same short-lived telnet+ssh transport (remote_hop.py) already built for
    this project -- never a mounted network filesystem (see
    PACKAGE/REMOTE_LOGIN_GUIDE.md and the design discussion this module came
    out of: no file-locking exists anywhere in this codebase, and NFS-style
    cross-client locking is not something this project can rely on, so every
    concurrency-unsafe read-modify-write happens in ONE process on the
    Linux side instead).

    Every method here is best-effort and NEVER raises for a
    transport/configuration problem -- a user whose shared knowledge center
    is unreachable (offline, not yet configured, server down) must still be
    able to use their LOCAL harness normally. Callers should check the
    returned dict's "ok" key.
    """

    def __init__(self, cfg: Dict[str, Any], project_root: Optional[Path] = None):
        self.cfg = dict(cfg.get("knowledge_center") or {})
        self.project_root = Path(project_root) if project_root else None

    def configured(self) -> bool:
        return bool(self.cfg.get("enabled")) and bool(self.cfg.get("remote_root"))

    def _resolve_hop_script(self) -> Optional[Path]:
        explicit = self.cfg.get("hop_script")
        if explicit:
            p = Path(explicit)
            return p if p.is_file() else None
        # Fall back to searching next to the project root and one level up
        # (matches how remote_hop.py/remote_login.sh have been shipped this
        # session: alongside PACKAGE/, or copied into a project root).
        candidates = []
        if self.project_root:
            candidates += [self.project_root / "remote_hop.py",
                           self.project_root.parent / "remote_hop.py"]
        candidates.append(Path.cwd() / "remote_hop.py")
        for c in candidates:
            if c.is_file():
                return c
        return None

    def _invoke(self, verb: str, payload: Dict[str, Any], timeout: int = 90) -> Dict[str, Any]:
        if not self.configured():
            return {"ok": False, "error": "NOT_CONFIGURED"}
        hop = self._resolve_hop_script()
        if not hop:
            return {"ok": False, "error": "REMOTE_HOP_NOT_FOUND",
                     "detail": "set knowledge_center.hop_script or place remote_hop.py "
                               "next to the project root"}
        remote_root = str(self.cfg["remote_root"]).rstrip("/")
        fd, local_tmp = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            remote_tmp = f"/tmp/.dvhkc.{uuid.uuid4().hex[:12]}.json"
            remote_cmd = (
                f"python3 {remote_root}/broker.py {verb} --root {remote_root} "
                f"--payload-file {remote_tmp}; rm -f {remote_tmp}"
            )
            cmd = [sys.executable, str(hop), "--put", local_tmp, remote_tmp, remote_cmd]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                       timeout=timeout, encoding="utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "TIMEOUT"}
            except OSError as e:
                return {"ok": False, "error": "TRANSPORT_EXEC_FAILED", "detail": str(e)}
        finally:
            try:
                os.unlink(local_tmp)
            except OSError:
                pass

        stdout = proc.stdout or ""
        result_line = None
        for line in stdout.splitlines():
            if line.startswith(RESULT_MARKER):
                result_line = line[len(RESULT_MARKER):]
        if result_line is None:
            return {"ok": False, "error": "NO_RESULT_MARKER",
                     "detail": (stdout + (proc.stderr or ""))[-2000:]}
        try:
            result = json.loads(result_line)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": "MALFORMED_RESULT", "detail": str(e)}
        result.setdefault("ok", True)
        return result

    def _provenance(self, extra_kind: str = "") -> Dict[str, Any]:
        return {
            "origin_user": _default_user(),
            "origin_host": _default_host(),
            "origin_project": str(self.project_root) if self.project_root else "",
            "client_written_at": time.time(),
        }

    # --- public verbs -------------------------------------------------------

    def test_connection(self) -> Dict[str, Any]:
        return self._invoke("ping", {})

    def add(self, category: str, protocol: str, record: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "category": category,
            "protocol": protocol,
            "record": record,
            "provenance": self._provenance(),
            "max_age_days": self.cfg.get("max_age_days", 180),
        }
        return self._invoke("add", payload)

    def search(self, category: str = "", protocol: str = "", text: str = "",
               limit: int = 8) -> Dict[str, Any]:
        payload = {"category": category, "protocol": protocol, "text": text, "limit": limit}
        return self._invoke("search", payload)

    def deprecate(self, record_id: str, category: str, protocol: str,
                  reason: str, evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "record_id": record_id, "category": category, "protocol": protocol,
            "action": "retract", "reason": reason, "evidence": evidence or {},
            "provenance": self._provenance(),
        }
        return self._invoke("deprecate", payload)

    def confirm(self, record_id: str, category: str, protocol: str,
                evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "record_id": record_id, "category": category, "protocol": protocol,
            "evidence": evidence or {}, "provenance": self._provenance(),
            # BUG FIX (2026-08-28, audit-knowledge-center-reality): this
            # method never sent max_age_days at all, so broker.py's
            # cmd_confirm silently fell back to its own hardcoded
            # DEFAULT_MAX_AGE_DAYS (180) on every confirm -- a project
            # configured with a different max_age_days (e.g. 30 for
            # fast-moving corner cases) had its records' revalidate_by
            # window silently reset to 180 days on the very first confirm,
            # permanently diverging from the project's own policy. add()
            # already threaded this value through correctly; confirm() now
            # mirrors it.
            "max_age_days": self.cfg.get("max_age_days", 180),
        }
        return self._invoke("confirm", payload)

    def db_info(self, category: str = "", protocol: str = "", action: str = "",
                limit: int = 100) -> Dict[str, Any]:
        """Who added/updated/retracted what across the WHOLE shared
        knowledge center, and when -- the DB-wide activity log (broker.py's
        activity.jsonl), not any single record's own history."""
        payload = {"category": category, "protocol": protocol, "action": action, "limit": limit}
        return self._invoke("db_info", payload)


def maybe_push_to_shared(cfg: Dict[str, Any], project_root: Path, destination: str,
                          category: str, protocol: str, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Called from memory_router.route_and_store() after a LOCAL write has
    already succeeded. The local write is always authoritative and always
    happens first/regardless -- this is purely additive best-effort sharing,
    controlled by knowledge_center.enabled and .sync_on_promote. Returns
    None (not attempted) or the client's result dict; never raises."""
    kc_cfg = cfg.get("knowledge_center") or {}
    if not kc_cfg.get("enabled") or not kc_cfg.get("sync_on_promote"):
        return None
    if destination not in ("ENGINEERING_MEMORY", "ORGANIZATIONAL_MEMORY", "CORNER_CASE_LIBRARY"):
        return None
    try:
        client = KnowledgeCenterClient(cfg, project_root)
        return client.add(category or "_general", protocol or "_general", record)
    except Exception as exc:  # pragma: no cover - defensive, must never break a local write
        return {"ok": False, "error": "CLIENT_EXCEPTION", "detail": str(exc)}
