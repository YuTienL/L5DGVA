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
"""
from __future__ import annotations

import json
import os
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


class DashboardAuthError(PermissionError):
    """A mutating request that presented no valid session token."""


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
    """
    token = secrets.token_urlsafe(32)
    record: Dict[str, Any] = {
        "token": token,
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


def authorize(expected_token: str, headers: Any, path: str = "",
              method: str = "POST", require_auth: bool = True) -> Tuple[bool, str]:
    """The single decision function. Returns (allowed, reason).

    `reason` is a stable machine token, not prose, so the HTTP layer and this
    module's tests assert the same value.
    """
    if not require_auth:
        return True, "AUTH_DISABLED_BY_CONFIG"
    if (method or "").upper() not in GATED_METHODS:
        return True, "METHOD_NOT_GATED"
    if not expected_token:
        # No token was ever minted for this server. Fail CLOSED: a mutating
        # endpoint whose credential does not exist must refuse, never fall
        # through to "nothing to check, so allow".
        return False, "NO_SESSION_TOKEN_ISSUED"
    given = presented_token(headers, path)
    if not given:
        return False, "MISSING_TOKEN"
    if not secrets.compare_digest(given, expected_token):
        return False, "INVALID_TOKEN"
    return True, "OK"


def denial_response(reason: str) -> Dict[str, Any]:
    """The JSON body a refused mutating request gets back. It names the two
    real places the operator can get the token from -- a 403 that does not
    say how to proceed is how a security gate gets switched off."""
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


def startup_banner(host: str, port: int, token: str, require_auth: bool) -> str:
    url = f"http://{host}:{port}"
    if not require_auth:
        return (f"DV Harness Dashboard: {url}\n"
                "  WARNING: dashboard.require_auth is false -- every mutating "
                "POST (APPROVE / COSIGN / TAKEOVER / signoff-export / waiver) "
                "is open to any local process.")
    return (f"DV Harness Dashboard: {url}/?{TOKEN_QUERY_PARAM}={token}\n"
            f"  Mutating actions require this session token "
            f"(also written to .dv-harness/{SESSION_FILENAME}).")
