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

# --- SYS-3 SUBSYSTEM RECORD SHAPE -------------------------------------------
# The System-Level Verification Integration workflow's SYS-3 ("KNOWLEDGE
# CENTER CHECK") names 21 fields to retrieve per subsystem, and its own rule
# is "Never create a parallel Knowledge Center". So this is a TYPED ACCESSOR
# over the existing add/search verbs -- same broker, same shards, same
# provenance/staleness lifecycle -- not a second store. All it adds is a
# fixed category and a fixed field vocabulary, so that "what does the shared
# KC know about subsystem X" is asked the same way by every caller instead of
# each one inventing its own `record` shape inside the client's otherwise
# opaque category/protocol/record envelope.
SUBSYSTEM_CATEGORY = "subsystem_environment"
SUBSYSTEM_RECORD_KIND = "subsystem_environment_record"

SUBSYSTEM_RECORD_FIELDS: tuple = (
    "SUBSYSTEM_ID", "PROTOCOL", "ROLE", "VERSION", "GIT_SHA",
    "ENVIRONMENT_PATH", "RTL_PATH", "VIP", "VIP_VERSION", "BUILD_STATUS",
    "LAST_KNOWN_PASS", "REGRESSION_STATUS", "COVERAGE_STATUS",
    "KNOWN_LIMITATIONS", "KNOWN_FAILURES", "COMMAND_TXT", "OWNER_AGENT",
    "OWNER_SKILL", "READINESS", "EVIDENCE", "CONFIDENCE",
)


# --- SYOSCB-3 THIRD-PARTY COMPONENT RECORD SHAPE ----------------------------
# SYOSCB-3 ("KNOWLEDGE CENTER REGISTRATION") names nine fields to register per
# reused third-party component, and closes with the same rule SYS-3 opens with:
# "Do not create a parallel knowledge store." So this is the SUBSYSTEM_*
# pattern above applied a second time -- another fixed category and field
# vocabulary over the SAME add/search verbs, the same broker, the same
# provenance/staleness lifecycle. It is deliberately a SEPARATE category from
# `subsystem_environment`: a vendored library is not a subsystem environment,
# has no COMMAND_TXT or REGRESSION_STATUS, and searching one shard for the
# other would return neither.
#
# Two fields go beyond SYOSCB-3's own list, because a record without them is
# not actionable: UPSTREAM_DEPENDENCIES (what the component itself needs in
# order to compile at all -- a UVM version, here) and EVIDENCE (the same
# citation field `SUBSYSTEM_RECORD_FIELDS` already carries, so a reader can
# check a claim instead of trusting it).
THIRD_PARTY_COMPONENT_CATEGORY = "third_party_component"
THIRD_PARTY_COMPONENT_KIND = "third_party_component_record"

THIRD_PARTY_COMPONENT_FIELDS: tuple = (
    "COMPONENT", "VERSION", "SOURCE_REFERENCE", "ROLE", "INTEGRATION_POLICY",
    "L5_DESTINATION", "BUILD_STATUS", "KNOWN_LIMITATIONS", "PROVENANCE",
    "UPSTREAM_DEPENDENCIES", "EVIDENCE",
)


def normalize_component_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Project an arbitrary stored KC record onto the SYOSCB-3 field names,
    case-insensitively, with the same present-and-null convention
    `normalize_subsystem_record()` uses -- "the KC has no L5_DESTINATION for
    this component" must be a readable fact, not a KeyError."""
    lowered = {str(k).lower(): v for k, v in (raw or {}).items()}
    out: Dict[str, Any] = {f: lowered.get(f.lower()) for f in THIRD_PARTY_COMPONENT_FIELDS}
    out["_kc"] = {
        k: (raw or {}).get(k)
        for k in ("memory_id", "status", "written_at", "revalidate_by",
                  "confirmation_count", "last_confirmed_at", "provenance")
        if k in (raw or {})
    }
    return out


def normalize_subsystem_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Project an arbitrary stored KC record onto the 21 SYS-3 field names,
    case-insensitively (a record written as `git_sha` and one written as
    `GIT_SHA` are the same fact). A field the record does not carry maps to
    None -- deliberately present-and-null rather than absent, so "the KC has
    no ROLE for this subsystem" is a readable fact instead of a KeyError at
    every call site. The broker's own lifecycle columns (memory_id/status/
    written_at/revalidate_by/confirmation_count/provenance) are carried
    through under `_kc` because SYS-3's staleness rule needs them."""
    lowered = {str(k).lower(): v for k, v in (raw or {}).items()}
    out: Dict[str, Any] = {f: lowered.get(f.lower()) for f in SUBSYSTEM_RECORD_FIELDS}
    out["_kc"] = {
        k: (raw or {}).get(k)
        for k in ("memory_id", "status", "written_at", "revalidate_by",
                  "confirmation_count", "last_confirmed_at", "provenance")
        if k in (raw or {})
    }
    return out


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

    def subsystem_record(self, subsystem_id: str, protocol: str = "",
                         limit: int = 16) -> Dict[str, Any]:
        """SYS-3: what does the shared Knowledge Center know about ONE
        subsystem environment. Routes through the existing `search` verb on
        the fixed SUBSYSTEM_CATEGORY shard -- no new transport, no new
        server-side command, no second store.

        Returns {"ok", "found", "record", "candidates"}. `found` is False
        (not an error) when the KC is reachable but holds no record for this
        subsystem: absence of a KC record is itself citable truth, and SYS-2
        treats it very differently from "the KC could not be reached".

        Matching is an exact, case-insensitive SUBSYSTEM_ID equality on the
        normalized record -- never a substring hit on the free-text search,
        which would happily return "USB3_DEVICE" for a query of "USB"."""
        res = self.search(category=SUBSYSTEM_CATEGORY, protocol=protocol,
                          text=str(subsystem_id), limit=limit)
        if not res.get("ok", True) or res.get("error"):
            return {"ok": False, "found": False, "record": None,
                    "error": res.get("error", "SEARCH_FAILED"),
                    "detail": res.get("detail", "")}
        wanted = str(subsystem_id).strip().lower()
        candidates = [normalize_subsystem_record(r) for r in (res.get("records") or [])]
        exact = [c for c in candidates if str(c.get("SUBSYSTEM_ID") or "").strip().lower() == wanted]
        return {
            "ok": True,
            "found": bool(exact),
            # search() already sorts newest-first, so the first exact hit is
            # the most recently written record for this subsystem.
            "record": exact[0] if exact else None,
            "candidates": [str(c.get("SUBSYSTEM_ID") or "") for c in candidates],
        }

    def record_subsystem(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """SYS-3 write half: publish/refresh one subsystem environment record
        on the same shard `subsystem_record()` reads. Uses the existing `add`
        verb, so the server stamps written_at/revalidate_by and the record
        joins the same staleness/confirm/deprecate lifecycle every other
        shared record has. Requires SUBSYSTEM_ID -- a record nobody can look
        up by subsystem is not a subsystem record."""
        subsystem_id = str((record or {}).get("SUBSYSTEM_ID") or "").strip()
        if not subsystem_id:
            return {"ok": False, "error": "SUBSYSTEM_ID_REQUIRED"}
        payload = {f: (record or {}).get(f) for f in SUBSYSTEM_RECORD_FIELDS}
        payload["SUBSYSTEM_ID"] = subsystem_id
        payload["kind"] = SUBSYSTEM_RECORD_KIND
        payload["title"] = f"{subsystem_id} subsystem environment"
        return self.add(SUBSYSTEM_CATEGORY, str(record.get("PROTOCOL") or "_general"), payload)

    def component_record(self, component: str, protocol: str = "",
                         limit: int = 16) -> Dict[str, Any]:
        """SYOSCB-3 read half: what does the shared Knowledge Center already
        know about ONE reused third-party component. Routes through the
        existing `search` verb on the fixed THIRD_PARTY_COMPONENT_CATEGORY
        shard -- no new transport, no new server-side command, no second store.

        Matching is exact, case-insensitive COMPONENT equality on the
        normalized record, for the same reason `subsystem_record()` refuses a
        substring hit: a free-text search for "uvm_syoscb" would happily return
        a record about an AMBA adapter that merely mentions it."""
        res = self.search(category=THIRD_PARTY_COMPONENT_CATEGORY, protocol=protocol,
                          text=str(component), limit=limit)
        if not res.get("ok", True) or res.get("error"):
            return {"ok": False, "found": False, "record": None,
                    "error": res.get("error", "SEARCH_FAILED"),
                    "detail": res.get("detail", "")}
        wanted = str(component).strip().lower()
        candidates = [normalize_component_record(r) for r in (res.get("records") or [])]
        exact = [c for c in candidates
                 if str(c.get("COMPONENT") or "").strip().lower() == wanted]
        return {
            "ok": True,
            "found": bool(exact),
            "record": exact[0] if exact else None,
            "candidates": [str(c.get("COMPONENT") or "") for c in candidates],
        }

    def record_component(self, record: Dict[str, Any],
                         protocol: str = "_general") -> Dict[str, Any]:
        """SYOSCB-3 write half: publish/refresh one third-party component
        record on the same shard `component_record()` reads, through the
        existing `add` verb, so the server stamps written_at/revalidate_by and
        it joins the same staleness/confirm/deprecate lifecycle. Requires
        COMPONENT -- a record nobody can look up by component name is not a
        component record.

        Build the record with
        `syoscb_source_audit.build_component_registration_payload()`; that
        function fills every field from a real read-only audit and never
        performs transport, so "the payload was built" and "the payload was
        published" stay two separately-visible events."""
        component = str((record or {}).get("COMPONENT") or "").strip()
        if not component:
            return {"ok": False, "error": "COMPONENT_REQUIRED"}
        payload = {f: (record or {}).get(f) for f in THIRD_PARTY_COMPONENT_FIELDS}
        payload["COMPONENT"] = component
        payload["kind"] = THIRD_PARTY_COMPONENT_KIND
        version = str((record or {}).get("VERSION") or "").strip()
        payload["title"] = f"{component} {version}".strip() + " third-party component"
        return self.add(THIRD_PARTY_COMPONENT_CATEGORY, protocol, payload)

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
