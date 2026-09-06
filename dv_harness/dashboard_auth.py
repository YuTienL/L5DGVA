"""Per-session token access control for the dashboard's MUTATING endpoints.

GUI-19 (2026-09-05 GUI completeness audit). `dashboard.serve()`'s
`do_GET`/`do_POST` had no authentication and no permission check anywhere,
while POST already exposed real, consequential actions: control-plane
APPROVE / COSIGN / TAKEOVER / constraint writes (`/api/control` ->
`_dispatch_control` -> `dv_harness.commands`), signoff-bundle export
(`/api/signoff-export`), waiver authoring (`/api/waiver`), policy writes
(`/api/config`), session save/restore, file upload and harness start.
The default bind is `127.0.0.1` (config.py's `dashboard.host`), which limits
NETWORK exposure -- it is not access control: any process or any other
logged-in user on the same machine could POST an APPROVE and mint a real
`APPROVAL` event in `.dv-harness/events.jsonl` under this project's audit
trail, with the harness recording it as a human decision.

The model is deliberately the one Jupyter uses for a localhost-only tool,
because it is the one that actually holds here:

  - `serve()` mints a fresh `secrets.token_urlsafe(32)` at startup, writes it
    to `.dv-harness/dashboard_session.json` (owner-only where the OS supports
    it) and PRINTS the URL carrying it. The token is never embedded in the
    HTML served at `GET /` -- a rogue local process that fetches the page
    learns nothing from it. To act, a caller must have read the console
    output or the session file.
  - Every POST endpoint is gated, deny-by-default: the check runs in
    `do_POST` BEFORE any path dispatch, so an endpoint added later is gated
    by existing without anyone remembering to opt it in.
  - Read-only GET endpoints stay open. They expose no action and gating them
    would break nothing but usability of a status page.

Comparison is `secrets.compare_digest`, so a wrong token cannot be recovered
one character at a time from response timing.

Two residuals, disclosed rather than implied closed (same convention as
`require_tier` / `require_phy_boundary` elsewhere in this codebase):

  1. A local process running AS THIS SAME USER can read
     `.dv-harness/dashboard_session.json` and is then indistinguishable from
     the human. Closing that needs OS-level peer-credential checks a TCP
     socket does not carry portably. What is closed is the case that
     actually existed: an unauthenticated caller acting with no credential
     at all.
  2. `os.chmod(0o600)` is real on POSIX; on Windows it only toggles the
     read-only bit and does NOT restrict other users via ACLs. The file's
     protection there is the containing user profile / project directory,
     not this call. `issue_session_token()` reports which of the two it got
     in the returned record's `permissions` field rather than claiming 0600
     everywhere.

PC-6 (2026-09-06): the ROLE half, on top of that same token.
----------------------------------------------------------

GUI-19 answered "is this caller the operator of this dashboard". It could not
answer "is this caller allowed to do THIS", because there was exactly one
token and it authorized every mutating endpoint equally: whoever could watch
the run could also mint a real `APPROVAL` in `control.json`, author a waiver,
flip a policy gate and export a signoff bundle. On a shared machine that is
the whole difference between an engineer watching a regression and the DV lead
signing it off.

Three roles, ordered, and a per-ACTION required role:

  - `VIEWER`    -- reads. Authorizes NO mutating action at all; read-only GET
                   was never gated and still is not, so a VIEWER token is only
                   ever needed to be told, explicitly, that an action is not
                   theirs.
  - `OPERATOR`  -- runs the harness: setup, start, pause/resume, takeover,
                   redirect, constraints, session save/restore, uploads.
  - `APPROVER`  -- everything an OPERATOR may do, plus the acts that write a
                   human DECISION into this project's audit trail: control
                   APPROVE / COSIGN / CORRECT and the three RESEARCH_* verbs,
                   waiver authoring, policy writes, signoff-bundle export.

This EXTENDS GUI-19 rather than standing beside it. `issue_session_token()`
mints one token per role into the same `.dv-harness/dashboard_session.json`
record, and the record's pre-existing `token` field IS the APPROVER token --
so the URL the startup banner prints, everything `read_session_token()`
returns, and every single-operator flow that existed before behave exactly as
they did. What is new is that an operator can now hand a colleague the VIEWER
or OPERATOR token instead of the one that can sign off.

`required_role()` is deny-by-default in both directions: a POST path this
module does not map, and an `/api/control` sub-command it does not map, both
require APPROVER. So an endpoint or a command added later is gated at the
HIGHEST level by existing, never at the lowest by omission -- the same
"gated by existing" property GUI-19's pre-dispatch placement gives.
`assert_endpoints_mapped()` / `assert_control_commands_mapped()` read
`dashboard.py`'s real dispatch and fail if either drifts, so the fallback is a
safety net rather than a place things quietly live.

Third disclosed residual, in the same spirit as the two above: the roles
separate HOLDERS OF DIFFERENT TOKENS. A process that can read
`dashboard_session.json` reads all three and can therefore act as APPROVER --
that is residual 1, unchanged and not re-closed here. What is closed is the
case that actually existed: a caller legitimately given access to the
dashboard being unable to be given anything less than full approval authority.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Header a programmatic caller (curl, the CLI, a test) sends the token in.
TOKEN_HEADER = "X-DV-Harness-Token"
# Query parameter the startup URL carries, so a human only has to click a
# link. The page moves it into sessionStorage and strips it from the address
# bar immediately (see dashboard.py's HTML), so it does not linger in browser
# history for every subsequent navigation.
TOKEN_QUERY_PARAM = "token"

SESSION_FILENAME = "dashboard_session.json"

# Every mutating action goes through POST in this dashboard; do_GET exposes
# no writer. So the gate is "POST requires a token", enforced once, before
# path dispatch -- never a per-endpoint allow-list that a new endpoint could
# be forgotten out of.
GATED_METHODS = ("POST", "PUT", "PATCH", "DELETE")

# ---- PC-6: roles and the per-action authorization matrix -------------------

VIEWER = "VIEWER"
OPERATOR = "OPERATOR"
APPROVER = "APPROVER"

#: Ordered least- to most-privileged. A role authorizes an action when its rank
#: is >= the action's required rank, so APPROVER can do everything OPERATOR can
#: -- there is no action an OPERATOR may take that an APPROVER may not.
ROLES = (VIEWER, OPERATOR, APPROVER)
ROLE_RANK = {role: rank for rank, role in enumerate(ROLES)}

#: Key under which the per-role tokens live in the session record.
ROLE_TOKENS_KEY = "role_tokens"

CONTROL_ENDPOINT = "/api/control"

#: Every real do_POST branch in dashboard.py, with the LOWEST role that may
#: reach it. `/api/control` is a floor only -- its sub-command decides the rest
#: (see CONTROL_COMMAND_REQUIRED_ROLE), because one endpoint carries both
#: "pause the run" and "approve SIGNOFF".
ENDPOINT_REQUIRED_ROLE = {
    "/api/setup": OPERATOR,
    "/api/start": OPERATOR,
    "/api/session/save": OPERATOR,
    "/api/session/restore": OPERATOR,
    "/api/upload": OPERATOR,
    CONTROL_ENDPOINT: OPERATOR,
    # Writes a real human DECISION or a governance artifact:
    "/api/config": APPROVER,          # flips policy.require_dv_review_cosign
    "/api/signoff-export": APPROVER,  # produces the bundle a signoff is read from
    "/api/waiver": APPROVER,          # exempts a requirement from a real gate
}

#: Every command `dashboard._dispatch_control()` really dispatches. The split
#: is exactly "does this write a human decision into the audit trail": PAUSE /
#: RESUME / TAKEOVER / RELEASE_TAKEOVER / REDIRECT / CONSTRAINT_* steer the
#: run and can be undone by steering it again; APPROVE / COSIGN / CORRECT and
#: the three RESEARCH_* verbs record a named human's judgment that other
#: mechanisms (policy.can_signoff(), capability_evolution's approval gate)
#: then rely on.
CONTROL_COMMAND_REQUIRED_ROLE = {
    "PAUSE": OPERATOR,
    "RESUME": OPERATOR,
    "TAKEOVER": OPERATOR,
    "RELEASE_TAKEOVER": OPERATOR,
    "REDIRECT": OPERATOR,
    "CONSTRAINT_ADD": OPERATOR,
    "CONSTRAINT_REMOVE": OPERATOR,
    "APPROVE": APPROVER,
    "COSIGN": APPROVER,
    "CORRECT": APPROVER,
    "RESEARCH_APPROVE": APPROVER,
    "RESEARCH_REJECT": APPROVER,
    "RESEARCH_HOLD": APPROVER,
}

#: An action neither table maps requires the HIGHEST role. Deny-by-default: a
#: POST endpoint or a control command added later must not become reachable by
#: a lower role merely because nobody remembered to classify it.
UNMAPPED_ACTION_ROLE = APPROVER

#: Stable machine reason for a caller who authenticated but whose role does not
#: reach the action. Distinct from MISSING_TOKEN/INVALID_TOKEN on purpose --
#: "you are not who you claim" and "you are who you claim and this is not
#: yours" need different answers from the operator reading the audit trail.
ROLE_DENIED_REASON = "ROLE_NOT_PERMITTED"


class DashboardAuthError(PermissionError):
    """A mutating request that presented no valid session token."""


class DashboardRoleMatrixError(AssertionError):
    """The role matrix no longer covers dashboard.py's real POST dispatch."""


def session_file(project_root: Path) -> Path:
    return Path(project_root) / ".dv-harness" / SESSION_FILENAME


def issue_session_token(project_root: Path, port: Optional[int] = None,
                        host: str = "127.0.0.1") -> Dict[str, Any]:
    """Mint this dashboard process's session token and persist it.

    Called once by `dashboard.serve()` at startup. A fresh token every start
    is deliberate: a token left over from a dashboard that is no longer
    running must not authorize anything against the next one.

    Written with the same atomic tmpfile + os.replace pattern as
    config.save_config()/storage.StateStore.save(), so a concurrent reader
    (the CLI, a test, a second dashboard checking for a stale file) never
    observes a half-written session record.

    PC-6: one INDEPENDENT token per role, all minted here so no role's
    credential can be derived from another's. `token` remains the APPROVER
    token -- it is what the startup banner prints and what the human who
    started the dashboard holds, so every pre-PC-6 caller keeps exactly the
    authority it had.
    """
    role_tokens: Dict[str, str] = {role: secrets.token_urlsafe(32) for role in ROLES}
    token = role_tokens[APPROVER]
    record: Dict[str, Any] = {
        "token": token,
        ROLE_TOKENS_KEY: role_tokens,
        "roles": list(ROLES),
        "issued_at": time.time(),
        "pid": os.getpid(),
        "user": os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
        "host": host,
        "port": port,
        "permissions": "owner-only(0600)" if os.name != "nt" else "windows-default-acl",
    }
    p = session_file(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    from .storage import _atomic_replace
    fd, tmp = tempfile.mkstemp(prefix="dashboard_session.", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            # Non-fatal: see residual 2 in this module's docstring. A
            # filesystem that cannot express the mode must not stop the
            # dashboard from starting with a token at all.
            pass
        _atomic_replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return record


def read_session_record(project_root: Path) -> Optional[Dict[str, Any]]:
    p = session_file(project_root)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def read_session_token(project_root: Path) -> Optional[str]:
    """The token a legitimate local caller (the CLI, curl, this test suite)
    reads to act on a running dashboard -- the same file the human is pointed
    at by the startup banner."""
    rec = read_session_record(project_root)
    tok = (rec or {}).get("token")
    return tok if isinstance(tok, str) and tok else None


def read_role_tokens(project_root: Path) -> Dict[str, str]:
    """The per-role tokens this dashboard process minted, for the operator who
    is handing one to a colleague. A session file written before PC-6 (or one
    carrying no role map) yields the APPROVER entry only, from its `token` --
    never a fabricated VIEWER/OPERATOR credential nobody minted."""
    rec = read_session_record(project_root) or {}
    raw = rec.get(ROLE_TOKENS_KEY)
    out: Dict[str, str] = {}
    if isinstance(raw, dict):
        for role in ROLES:
            tok = raw.get(role)
            if isinstance(tok, str) and tok:
                out[role] = tok
    if APPROVER not in out:
        tok = rec.get("token")
        if isinstance(tok, str) and tok:
            out[APPROVER] = tok
    return out


def resolve_role(presented: str, role_tokens: Optional[Dict[str, str]]) -> Optional[str]:
    """Which role the caller-presented token IS, or None if it is none of them.

    Compared most-privileged-first with secrets.compare_digest, the same
    constant-time comparison the single-token gate has always used, so a wrong
    token cannot be recovered one character at a time from response timing.
    Checking the highest rank first means a (never-issued) duplicate across two
    roles resolves to the stronger one rather than silently downgrading a
    legitimate approver.
    """
    if not presented or not role_tokens:
        return None
    for role in sorted(role_tokens, key=lambda r: ROLE_RANK.get(r, -1), reverse=True):
        expected = role_tokens.get(role)
        if isinstance(expected, str) and expected and secrets.compare_digest(presented, expected):
            return role
    return None


def required_role(path: str = "", control_command: Optional[str] = None) -> Tuple[str, str]:
    """(role, action) for a mutating request -- the matrix's single lookup.

    `action` is a stable machine label naming what was being attempted
    (`POST /api/waiver`, `POST /api/control APPROVE`), so the denial body, the
    audit event and this module's tests all quote the same string.
    """
    endpoint = (path or "").split("?", 1)[0]
    if endpoint not in ENDPOINT_REQUIRED_ROLE:
        return UNMAPPED_ACTION_ROLE, f"POST {endpoint} [UNMAPPED_ENDPOINT]"
    role = ENDPOINT_REQUIRED_ROLE[endpoint]
    if endpoint != CONTROL_ENDPOINT:
        return role, f"POST {endpoint}"
    command = (control_command or "").strip()
    if command not in CONTROL_COMMAND_REQUIRED_ROLE:
        # Includes the case where the body could not be read at all: which
        # command this is decides how privileged the request is, so not knowing
        # is a reason to require MORE, never less.
        label = command or "UNREADABLE"
        return UNMAPPED_ACTION_ROLE, f"POST {endpoint} {label} [UNMAPPED_CONTROL_COMMAND]"
    command_role = CONTROL_COMMAND_REQUIRED_ROLE[command]
    if ROLE_RANK[command_role] > ROLE_RANK[role]:
        role = command_role
    return role, f"POST {endpoint} {command}"


def presented_token(headers: Any, path: str = "") -> str:
    """Pull the caller-presented token out of a request.

    Accepts the dedicated header, an `Authorization: Bearer <token>` (so an
    ordinary HTTP client works without a custom header), or `?token=` on the
    request path (the startup URL's form). Returns "" when none was given --
    never None, so the caller compares strings only.
    """
    if headers is not None:
        raw = headers.get(TOKEN_HEADER)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        auth = headers.get("Authorization")
        if isinstance(auth, str) and auth.strip().lower().startswith("bearer "):
            return auth.strip()[7:].strip()
    if "?" in (path or ""):
        qs = urllib.parse.parse_qs(path.split("?", 1)[1])
        vals = qs.get(TOKEN_QUERY_PARAM) or []
        if vals and vals[0]:
            return vals[0]
    return ""


def authorize_detail(expected_token: str, headers: Any, path: str = "",
                     method: str = "POST", require_auth: bool = True,
                     role_tokens: Optional[Dict[str, str]] = None,
                     control_command: Optional[str] = None) -> Dict[str, Any]:
    """The single decision function. Authentication first, then the role.

    Returns `allowed`/`reason` plus the resolved `role`, the `required_role`
    the matrix demanded and the `action` label, because the HTTP layer has to
    tell the caller which of the two it failed and record the same on the
    audit trail.

    `role_tokens` absent (or missing an APPROVER entry) means "there is one
    token and it is the full-authority one" -- exactly GUI-19's pre-PC-6
    behaviour, so any caller that has not adopted roles is unchanged.
    """
    action = f"POST {(path or '').split('?', 1)[0]}"
    if not require_auth:
        return {"allowed": True, "reason": "AUTH_DISABLED_BY_CONFIG",
                "role": None, "required_role": None, "action": action}
    if (method or "").upper() not in GATED_METHODS:
        return {"allowed": True, "reason": "METHOD_NOT_GATED",
                "role": None, "required_role": None, "action": action}
    if not expected_token:
        # No token was ever minted for this server. Fail CLOSED: a mutating
        # endpoint whose credential does not exist must refuse, never fall
        # through to "nothing to check, so allow".
        return {"allowed": False, "reason": "NO_SESSION_TOKEN_ISSUED",
                "role": None, "required_role": None, "action": action}
    given = presented_token(headers, path)
    if not given:
        return {"allowed": False, "reason": "MISSING_TOKEN",
                "role": None, "required_role": None, "action": action}

    known = dict(role_tokens or {})
    known.setdefault(APPROVER, expected_token)
    role = resolve_role(given, known)
    if role is None:
        return {"allowed": False, "reason": "INVALID_TOKEN",
                "role": None, "required_role": None, "action": action}

    needed, action = required_role(path, control_command)
    if ROLE_RANK.get(role, -1) < ROLE_RANK[needed]:
        return {"allowed": False, "reason": ROLE_DENIED_REASON,
                "role": role, "required_role": needed, "action": action}
    return {"allowed": True, "reason": "OK",
            "role": role, "required_role": needed, "action": action}


def authorize(expected_token: str, headers: Any, path: str = "",
              method: str = "POST", require_auth: bool = True,
              role_tokens: Optional[Dict[str, str]] = None,
              control_command: Optional[str] = None) -> Tuple[bool, str]:
    """(allowed, reason) view of authorize_detail(), for callers that only
    need the verdict. `reason` is a stable machine token, not prose, so the
    HTTP layer and this module's tests assert the same value."""
    d = authorize_detail(expected_token, headers, path, method=method,
                         require_auth=require_auth, role_tokens=role_tokens,
                         control_command=control_command)
    return bool(d["allowed"]), str(d["reason"])


def denial_response(reason: str, role: Optional[str] = None,
                    required_role: Optional[str] = None,
                    action: Optional[str] = None) -> Dict[str, Any]:
    """The JSON body a refused mutating request gets back. It names the two
    real places the operator can get the token from -- a 403 that does not
    say how to proceed is how a security gate gets switched off."""
    if reason == ROLE_DENIED_REASON:
        # A ROLE denial is a different answer from an AUTH denial and says so:
        # this caller IS authenticated, and telling them to go find the token
        # again would send them to the one credential that cannot help.
        return {
            "error": ROLE_DENIED_REASON,
            "reason": reason,
            "role": role,
            "required_role": required_role,
            "action": action,
            "message": (
                f"Your session token has role {role}; {action} requires "
                f"{required_role}. Roles are ranked {' < '.join(ROLES)}. Ask "
                f"whoever started this dashboard for the {required_role} "
                f"token, or have them perform this action -- it records a "
                f"decision under the acting human's name."
            ),
        }
    return {
        "error": "AUTH_REQUIRED",
        "reason": reason,
        "message": (
            "This dashboard action is a mutating request and requires this "
            f"session's token. Send it as the {TOKEN_HEADER} header, as "
            f"'Authorization: Bearer <token>', or open the dashboard with the "
            f"?{TOKEN_QUERY_PARAM}=... URL printed when it started. The token "
            f"is also in .dv-harness/{SESSION_FILENAME}."
        ),
    }


def startup_banner(host: str, port: int, token: str, require_auth: bool,
                   role_tokens: Optional[Dict[str, str]] = None) -> str:
    url = f"http://{host}:{port}"
    if not require_auth:
        return (f"DV Harness Dashboard: {url}\n"
                "  WARNING: dashboard.require_auth is false -- every mutating "
                "POST (APPROVE / COSIGN / TAKEOVER / signoff-export / waiver) "
                "is open to any local process.")
    lines = [f"DV Harness Dashboard: {url}/?{TOKEN_QUERY_PARAM}={token}",
             f"  Mutating actions require this session token "
             f"(also written to .dv-harness/{SESSION_FILENAME})."]
    if role_tokens:
        # The whole point of the role split is that these can be handed out
        # SEPARATELY, so the banner has to show what there is to hand out.
        lines.append(f"  Roles ({' < '.join(ROLES)}) -- the URL above carries {APPROVER}:")
        for role in ROLES:
            tok = role_tokens.get(role)
            if not tok or role == APPROVER:
                continue
            lines.append(f"    {role}: {url}/?{TOKEN_QUERY_PARAM}={tok}")
    return "\n".join(lines)


# ---- drift guards: the matrix must cover dashboard.py's REAL dispatch -------

_ENDPOINT_DISPATCH_RE = re.compile(r'path\s*==\s*"(/api/[A-Za-z0-9_\-/]+)"')
_CONTROL_DISPATCH_RE = re.compile(r'cmd\s*==\s*"([A-Z_]+)"')


def _dashboard_source() -> str:
    return (Path(__file__).resolve().parent / "dashboard.py").read_text(encoding="utf-8")


def dispatched_post_endpoints() -> set:
    """The POST paths `dashboard.do_POST()` really dispatches, read off its
    own source rather than trusted from this module's table."""
    src = _dashboard_source()
    start = src.index("        def do_POST(self):")
    end = src.index("        def _handle_session_save(self):", start)
    return set(_ENDPOINT_DISPATCH_RE.findall(src[start:end]))


def dispatched_control_commands() -> set:
    """The commands `dashboard._dispatch_control()` really dispatches."""
    src = _dashboard_source()
    start = src.index("def _dispatch_control(")
    end = src.index("def serve(", start)
    return set(_CONTROL_DISPATCH_RE.findall(src[start:end]))


def assert_endpoints_mapped() -> None:
    """A POST endpoint dashboard.py dispatches but this matrix does not map
    still REFUSES anything below APPROVER (UNMAPPED_ACTION_ROLE), so the
    fallback is safe -- but an unclassified endpoint means nobody decided
    whether an OPERATOR should reach it, which is a decision, not a default."""
    real = dispatched_post_endpoints()
    unmapped = sorted(real - set(ENDPOINT_REQUIRED_ROLE))
    stale = sorted(set(ENDPOINT_REQUIRED_ROLE) - real)
    if unmapped or stale:
        raise DashboardRoleMatrixError(
            f"ENDPOINT_REQUIRED_ROLE drifted from dashboard.do_POST(): "
            f"unmapped={unmapped} stale={stale}")


def assert_control_commands_mapped() -> None:
    real = dispatched_control_commands()
    unmapped = sorted(real - set(CONTROL_COMMAND_REQUIRED_ROLE))
    stale = sorted(set(CONTROL_COMMAND_REQUIRED_ROLE) - real)
    if unmapped or stale:
        raise DashboardRoleMatrixError(
            f"CONTROL_COMMAND_REQUIRED_ROLE drifted from _dispatch_control(): "
            f"unmapped={unmapped} stale={stale}")
