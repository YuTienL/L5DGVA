from __future__ import annotations
import json, os, socket, sys, tempfile, time, uuid
from pathlib import Path
from typing import Any, Dict, Optional

# Marker line the server-side broker (tools/knowledge_center/broker.py) must
# print as its LAST stdout line, exactly once, so this client can find its
# JSON result inside whatever else the remote command's real stdout happens
# to contain (the persistent relay's 'run' op returns raw remote stdout
# verbatim -- no banner/echo framing of its own, unlike the older
# remote_hop.py-subprocess transport this replaced on 2026-09-01, but a
# distinctive prefix is still more robust than assuming the broker's JSON
# is the only thing on stdout, e.g. if the shell prints its own noise).
RESULT_MARKER = "DVHKC_RESULT:"


def _default_user() -> str:
    # Same fallback chain as control_plane.py's _default_user() -- reused
    # here (not imported, to keep this module import-light and because
    # control_plane's version is private) so a shared-knowledge-center write
    # is attributed the same way a human-control-plane action already is.
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def _default_host() -> str:
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown-host"


def _remote_exec_module():
    """Import tools/remote/remote_exec.py's read_relay_info()/send_request()
    -- the same credential-free persistent-relay client every other
    real remote-execution call site in this project already uses. Not a
    package import: tools/remote/ has no __init__.py, so this sys.path-inserts
    its directory once (same convention dv_harness_tests/test_source_identity.py
    already establishes for this exact directory)."""
    remote_dir = str(Path(__file__).resolve().parents[1] / "tools" / "remote")
    if remote_dir not in sys.path:
        sys.path.insert(0, remote_dir)
    import remote_exec  # type: ignore
    return remote_exec


class KnowledgeCenterClient:
    """Local-side client for the shared, cross-user knowledge center that
    lives at a fixed path on a Linux server (dv_harness/config.py's
    `knowledge_center` block). Talks to it exclusively through
    tools/knowledge_center/broker.py running ON the server, invoked over the
    same credential-free persistent relay (tools/remote/remote_exec.py,
    talking to a remote_relay.py process a human already started) every
    other real remote command in this project uses -- never a mounted
    network filesystem (see
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

    def _vc_host_hop(self) -> tuple:
        vchost = self.cfg.get("vchost") or os.environ.get("VCHOST", "")
        vchop = self.cfg.get("vchop") or os.environ.get("VCHOP", "")
        return vchost, vchop

    def _invoke(self, verb: str, payload: Dict[str, Any], timeout: int = 90) -> Dict[str, Any]:
        """REAL INCIDENT FIX (2026-09-01): this method used to spawn its own
        tools/remote/remote_hop.py subprocess directly
        (`[sys.executable, str(hop), "--put", ...]`), reading credentials
        from ITS OWN process environment (remote_hop.py's own module-level
        `PW = os.environ.get(<the password's env var name>, '')`). That is exactly the exposure
        pattern CLAUDE.md's "Remote Linux Execution" section already forbids
        for remote_relay.py -- "a persistent OS-level environment variable
        can supply required credentials silently, defeating a 'missing env
        vars' safety check" -- confirmed as a real, live incident risk this
        session found while actually using this code path (see
        docs/superpowers/... session notes / Engineering Memory record
        MEM-78AD6C32EB for the full account, including the settings.local.json
        angle of the same underlying anti-pattern). remote_hop.py is the
        SAME risk category as remote_relay.py (it performs a real login with
        a real password from env), so it must never be invoked directly from
        a Claude-issued call either, even indirectly through this client.

        Fixed by routing exclusively through the already-sanctioned,
        credential-free persistent relay (tools/remote/remote_exec.py's
        read_relay_info()/send_request(), the exact mechanism CLAUDE.md's
        "Remote Linux Execution (Persistent Relay)" section already
        mandates for every other real remote command in this project) --
        this client now performs the identical two-step sequence
        (put the payload JSON, then run the broker command) as a real relay
        client, never spawning its own authenticated subprocess. If no
        relay is up for the configured vchost/vchop, this fails cleanly
        with RELAY_NOT_READY (mirroring remote_exec.py's own DOWN-state
        message) instead of silently trying to authenticate on its own.
        """
        if not self.configured():
            return {"ok": False, "error": "NOT_CONFIGURED"}

        vchost, vchop = self._vc_host_hop()
        if not vchost or not vchop:
            return {"ok": False, "error": "VC_HOST_HOP_NOT_CONFIGURED",
                     "detail": "set knowledge_center.vchost/vchop in config.json, or the "
                               "VCHOST/VCHOP env vars (the same values used to start "
                               "remote_relay.py)"}

        remote_exec = _remote_exec_module()
        info = remote_exec.read_relay_info(vchost, vchop)
        if info is None:
            return {"ok": False, "error": "RELAY_NOT_READY",
                     "detail": f"no persistent relay found for {vchost}-{vchop}. Ask the "
                               f"user to run, in their OWN terminal: VCUSER=... VCPW=... "
                               f"VCHOST={vchost} VCHOP={vchop} VCWORKDIR=... python "
                               f"tools/remote/remote_relay.py --start"}

        remote_root = str(self.cfg["remote_root"]).rstrip("/")
        remote_tmp = f"/tmp/.dvhkc.{uuid.uuid4().hex[:12]}.json"
        remote_cmd = (
            f"python3 {remote_root}/broker.py {verb} --root {remote_root} "
            f"--payload-file {remote_tmp}; rm -f {remote_tmp}"
        )

        fd, local_tmp = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            try:
                put_resp = remote_exec.send_request(
                    info["host"], info["port"],
                    {"token": info["token"], "op": "put", "local": local_tmp, "remote": remote_tmp},
                    timeout=timeout,
                )
            except (ConnectionRefusedError, OSError, socket.timeout) as e:
                return {"ok": False, "error": "RELAY_UNREACHABLE", "detail": str(e)}
        finally:
            try:
                os.unlink(local_tmp)
            except OSError:
                pass

        if not put_resp.get("ok"):
            return {"ok": False, "error": "TRANSPORT_PUT_FAILED", "detail": put_resp.get("error", "")}

        try:
            run_resp = remote_exec.send_request(
                info["host"], info["port"],
                {"token": info["token"], "op": "run", "cmd": remote_cmd, "timeout": timeout},
                timeout=timeout,
            )
        except (ConnectionRefusedError, OSError, socket.timeout) as e:
            return {"ok": False, "error": "RELAY_UNREACHABLE", "detail": str(e)}

        if not run_resp.get("ok"):
            return {"ok": False, "error": "TRANSPORT_RUN_FAILED", "detail": run_resp.get("error", "")}

        stdout = run_resp.get("stdout") or ""
        result_line = None
        for line in stdout.splitlines():
            if line.startswith(RESULT_MARKER):
                result_line = line[len(RESULT_MARKER):]
        if result_line is None:
            return {"ok": False, "error": "NO_RESULT_MARKER", "detail": stdout[-2000:]}
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
