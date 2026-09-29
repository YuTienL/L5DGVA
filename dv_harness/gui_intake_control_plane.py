"""dv_harness/gui_intake_control_plane.py -- GUI Intake Control Plane (2026-09-06)

CLAUDE_L5_INTAKE_MASTER.md section 33 asks for a dashboard control-plane
surface over the intake pipeline: view pending questions
(`dv_harness/question_queue.py`), view per-field intake statuses
(`dv_harness/intake_state.py`), and approve/answer from the UI -- wired to
real backend state, never a mocked/static page.

REUSE OVER REINVENT (checked before writing a line of this): `dashboard.py`
is this project's real, live web control plane (a genuine
`http.server.ThreadingHTTPServer`, GUI-19/PC-6 token+role auth via
`dashboard_auth.py`, a real `/api/control` dispatch). A repo-wide grep for
`question_queue`/`intake_state`/`QuestionQueueStore`/`IntakeState` inside
`dashboard.py` returns NOTHING -- neither module has ever been read by any
GUI surface in this codebase, so this is a genuine, previously-unclosed gap,
not a duplicate of an existing card. `dashboard.py` itself was NOT extended
here: it is 3600+ lines and, at the time of this change, was the single
most-recently-modified file in the entire repository (actively under
concurrent edit by other work in the same batch this task's own instructions
name as running alongside it) -- editing it risks a collision this batch's
own rule explicitly asks to avoid where a lower-risk path exists. Per the
same rule ("prefer a standalone `python -m dv_harness.<module>` front door
... matching several recent modules in this codebase that already made that
same disclosed choice"), this module is a SEPARATE, standalone control-plane
server rather than a `dashboard.py` card. Wiring it into `dashboard.py` as a
card once that file is no longer under concurrent pressure is a disclosed
residual, not a design choice made on the merits.

Backend, never mocked. Every read and write goes straight through the real,
already-shipped producer:
  - `list_pending_questions()` is `question_queue.QuestionQueueStore.
    list_questions()`, filtered to the same "not yet resolved" definition
    `QuestionQueueStore.build_digest()` already uses (`status in
    {"OPEN", "ASSUMED"}`) -- reused rather than a second definition of
    "pending" that could quietly drift from the one the digest mechanism
    already tracks metrics against.
  - `gather_intake_state()` builds a REAL `intake_state.IntakeState` via
    `intake_state.build_intake_state()`, fed the project's own real
    `env.manifest.json` (via `env_manifest.default_manifest_path()` /
    `load_env_manifest()` -- read only if one actually exists on disk;
    absent that, every general-category field honestly reads MISSING,
    exactly as `intake_state.py`'s own module contract requires, never a
    fabricated status) and the project's own real `QuestionQueueStore` (for
    `already_resolved()`'s do-not-ask read, never a write). The other
    `build_intake_state()` inputs this module has no real source for on its
    own (`bind_entries`, `dut_boundary`, `active_driver_conflicts`,
    `build_env_gate`, `known_pass_tests`) are left `None`, which
    `intake_state.py` already resolves to an honest MISSING per category --
    this module invents no stand-in evidence for any of them.
  - `answer_pending_question()` is `QuestionQueueStore.answer_question()`
    verbatim -- the ONE sanctioned "a human answered" write path in this
    codebase (source=`question_queue.HUMAN_DECISION_SOURCE`), the same write
    `dv-harness question-queue answer` already performs. This module adds no
    second decision-writing mechanism.
  - The readiness panel is `intake_state.evaluate_uvm_generation_ready()`
    verbatim -- the real, already-implemented worst-wins refusal gate (a
    single unresolved blocking category refuses regardless of how many
    others are clean); this module computes no readiness verdict of its
    own.

Auth. A mutating request (`POST /api/intake/answer`) is gated behind a
per-process session token, reusing `dashboard_auth.presented_token()`
(header / `Authorization: Bearer` / `?token=` parsing) and
`secrets.compare_digest` (the same constant-time comparison
`dashboard_auth.py` uses, so a wrong token cannot be recovered one character
at a time from response timing) directly rather than re-deriving either. It
deliberately does NOT reuse `dashboard_auth.authorize()`/`required_role()`:
that function's role matrix is dashboard.py's OWN 21-action table, keyed on
dashboard.py's own endpoint paths, and every endpoint this module serves is
a different path outside it -- reusing it would only ever resolve through
its `UNMAPPED_ACTION_ROLE` branch, requiring `dashboard.py`'s own APPROVER
credential for an endpoint that credential has nothing to do with, and
mixing this module's real session token (in its OWN session file, see
below) into that matrix's messaging would misattribute a denial to the
wrong dashboard's token. This surface exposes exactly one mutating action,
so a single token is the honest model -- not a 3-role matrix built to
imply a distinction (VIEWER/OPERATOR/APPROVER) this surface does not have.
The token is minted fresh per server start and written, with the same
`storage._atomic_replace()` atomic-write primitive `dashboard_auth.
issue_session_token()` itself uses, to `.dv-harness/
intake_control_plane_session.json` -- a DELIBERATELY DIFFERENT filename
from `dashboard.py`'s own `dashboard_session.json`, so the two processes'
credentials can never be confused with one another even when both run
against the same project root.

Deliberately bounded, and stated rather than implied closed: this module
files no question (only a human, via `answer_question()`, resolves one),
runs no gate script, and writes no state/blackboard/approval record beyond
the one sanctioned `question_queue` decision write. It is a REACHED
capability (import it, or run
`python -m dv_harness.gui_intake_control_plane serve --project-root <dir>`)
rather than a WIRED one: no `dashboard.py` card, no `dv-harness` CLI verb
(per this batch's own guidance to avoid `cli.py` while it is under heavy
concurrent edit pressure), and no graph node invokes it.

P1-3 (2026-09-07, additive-only, deferred item): `render_page()` now also
renders `web_layout.render_nav()` / `web_layout.render_status_bar_partial()`
-- imported, never re-implemented -- immediately inside `<body>`, before this
page's own existing heading/table markup, so this standalone server gains the
same status-bar/nav STRUCTURE `dashboard.py`'s real Global Status Bar already
uses. This is markup only: the status-bar partial is `web_layout.py`'s own
documented "STATIC shell, no live data, no `<script>` block" contract, and
nothing here wires it to a real `/api/status` poll or replaces this page's own
`/api/intake/*` endpoints/answer-form JS -- doing either would be exactly the
page-shell rewrite this item's own revision note says is out of scope. Every
existing route, endpoint, and rendering behavior of this server is unchanged.
"""
from __future__ import annotations

import html
import json
import os
import secrets
import tempfile
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import dashboard_auth
from . import env_manifest
from . import intake_state
from . import question_queue
from . import web_layout
from .storage import _atomic_replace

SESSION_FILENAME = "intake_control_plane_session.json"

#: The same "not yet resolved" definition `QuestionQueueStore.build_digest()`
#: already batches on -- reused, not re-derived, so this surface's notion of
#: "pending" can never quietly drift from the one the queue's own metrics
#: are measured against.
PENDING_QUESTION_STATUSES = frozenset({"OPEN", "ASSUMED"})


# ---------------------------------------------------------------------------
# backend reads/writes -- every one a real call into an existing producer
# ---------------------------------------------------------------------------

def list_pending_questions(project_root: Path) -> List[dict]:
    """Every question this project's real `QuestionQueueStore` has not yet
    been given a real answer for, most-recently-created first. `blocking`
    (Tier-3, status OPEN) and `assumed` (Tier-2, status ASSUMED, provisional
    until a human confirms or overturns it) are both included -- a human
    reviewing this surface needs to see a harness guess it is free to
    overturn just as much as a question it has not touched at all."""
    store = question_queue.QuestionQueueStore(Path(project_root))
    qs = [q for q in store.list_questions() if q.get("status") in PENDING_QUESTION_STATUSES]
    qs.sort(key=lambda q: q.get("created_at") or "", reverse=True)
    return qs


def gather_intake_state(project_root: Path) -> "intake_state.IntakeState":
    """A real `IntakeState`, built from whatever real evidence this project
    actually has on disk today -- never a fabricated stand-in for evidence
    that does not exist. See this module's own docstring for exactly which
    `build_intake_state()` inputs this surface can and cannot supply."""
    root = Path(project_root)
    manifest_path = env_manifest.default_manifest_path(root)
    manifest = env_manifest.load_env_manifest(str(manifest_path)) if manifest_path else None
    store = question_queue.QuestionQueueStore(root)
    return intake_state.build_intake_state(env_manifest=manifest, question_store=store)


def answer_pending_question(project_root: Path, question_id: str, *, answer: str,
                              basis: str, decided_by: str) -> dict:
    """The one sanctioned write this surface performs: a real human answer,
    through `QuestionQueueStore.answer_question()` verbatim. Raises
    `KeyError` for an unknown Q-ID, exactly as that method does -- this
    module adds no second error shape."""
    store = question_queue.QuestionQueueStore(Path(project_root))
    return store.answer_question(question_id, answer=answer, basis=basis, decided_by=decided_by)


def control_plane_snapshot(project_root: Path) -> Dict[str, Any]:
    """Everything one page render needs, assembled from the real backend in
    one call: the pending-question list, the real per-field IntakeState, and
    the real worst-wins UVM_GENERATION_READY verdict over it."""
    root = Path(project_root)
    pending = list_pending_questions(root)
    state = gather_intake_state(root)
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    return {
        "generated_at": state.generated_at,
        "pending_questions": pending,
        "fields": [r.to_dict() for r in state.records],
        "readiness": readiness.to_dict(),
    }


# ---------------------------------------------------------------------------
# session token -- own file, own process; never dashboard.py's
# ---------------------------------------------------------------------------

def session_file(project_root: Path) -> Path:
    return Path(project_root) / ".dv-harness" / SESSION_FILENAME


def issue_session_token(project_root: Path, *, port: Optional[int] = None,
                          host: str = "127.0.0.1") -> Dict[str, Any]:
    """Mint this server process's session token and persist it, using the
    same atomic-write primitive (`storage._atomic_replace`) `dashboard_auth.
    issue_session_token()` uses for its own, separate session file. A fresh
    token every start, same reasoning as that function's own docstring: a
    token left over from a server no longer running must not authorize
    anything against the next one."""
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
    fd, tmp = tempfile.mkstemp(prefix="intake_control_plane_session.", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        _atomic_replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return record


def read_session_token(project_root: Path) -> Optional[str]:
    p = session_file(project_root)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tok = rec.get("token") if isinstance(rec, dict) else None
    return tok if isinstance(tok, str) and tok else None


def _authorized(expected_token: str, headers: Any, path: str) -> bool:
    """Reuses `dashboard_auth.presented_token()` (header / `Authorization:
    Bearer` / `?token=` parsing) and `secrets.compare_digest` directly --
    see this module's own docstring for why `dashboard_auth.authorize()`
    itself is not reused here (its role matrix answers a different
    question, keyed on a different server's endpoints). Fails CLOSED: no
    token minted for this process authorizes nothing."""
    if not expected_token:
        return False
    given = dashboard_auth.presented_token(headers, path)
    return bool(given) and secrets.compare_digest(given, expected_token)


# ---------------------------------------------------------------------------
# HTML rendering -- real data in, real markup out; every value escaped
# ---------------------------------------------------------------------------

def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _render_questions_table(pending: List[dict]) -> str:
    if not pending:
        return "<p class=\"empty\">No pending questions -- the queue is empty.</p>"
    rows = []
    for q in pending:
        options = "; ".join(_e(o.get("label")) for o in (q.get("options") or []))
        rows.append(
            "<tr>"
            f"<td><code>{_e(q.get('id'))}</code></td>"
            f"<td>{_e(q.get('domain'))}</td>"
            f"<td>{_e(q.get('owner'))}</td>"
            f"<td>{_e(q.get('status'))}</td>"
            f"<td>{'yes' if q.get('blocking') else 'no'}</td>"
            f"<td>{_e(q.get('question'))}</td>"
            f"<td>{options}</td>"
            f"<td>{_e(q.get('recommendation'))}</td>"
            "<td>"
            "<form class=\"answer-form\" data-qid=\"" + _e(q.get('id')) + "\">"
            "<input type=\"text\" name=\"answer\" placeholder=\"answer\" required>"
            "<input type=\"text\" name=\"basis\" placeholder=\"basis\" required>"
            "<input type=\"text\" name=\"decided_by\" placeholder=\"decided by\" required>"
            "<button type=\"submit\">Answer</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Q-ID</th><th>Domain</th><th>Owner</th><th>Status</th>"
        "<th>Blocking</th><th>Question</th><th>Options</th><th>Recommendation</th>"
        "<th>Answer</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_fields_table(fields: List[dict]) -> str:
    if not fields:
        return "<p class=\"empty\">No intake fields recorded.</p>"
    rows = []
    for r in fields:
        rows.append(
            "<tr>"
            f"<td>{_e(r.get('field'))}</td>"
            f"<td>{_e(r.get('category'))}</td>"
            f"<td class=\"status-{_e(r.get('status')).lower()}\">{_e(r.get('status'))}</td>"
            f"<td>{_e(r.get('confidence'))}</td>"
            f"<td>{_e(r.get('source'))}</td>"
            f"<td>{_e(r.get('owner'))}</td>"
            f"<td>{_e(r.get('reason'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Field</th><th>Category</th><th>Status</th>"
        "<th>Confidence</th><th>Source</th><th>Owner</th><th>Reason</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def render_page(snapshot: Dict[str, Any]) -> str:
    readiness = snapshot.get("readiness") or {}
    ready = bool(readiness.get("ready"))
    blocking = readiness.get("blocking") or {}
    if ready:
        readiness_html = "<p class=\"ready\">UVM_GENERATION_READY: READY</p>"
    else:
        names = ", ".join(_e(k) for k in sorted(blocking))
        readiness_html = (
            f"<p class=\"blocked\">UVM_GENERATION_READY: BLOCKED "
            f"({len(blocking)} category(ies) unresolved: {names or 'none'})</p>"
        )
    # P1-3 (additive, deferred item): a shared status-bar/nav partial from
    # `web_layout.py`, inserted at a fixed point (immediately inside `<body>`,
    # before this page's own existing heading/table markup) -- structure
    # only, never a rewrite of this server's own already-working page shell.
    # The nav entries are this page's own two real sections (their `<h2 id=
    # ...>` anchors below), so the partial never invents a route this page
    # does not already have.
    layout_partial = web_layout.render_nav([
        ("questions", "Pending Questions", "#pending-questions"),
        ("fields", "Intake Field Statuses", "#intake-field-statuses"),
    ]) + web_layout.render_status_bar_partial()
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>GUI Intake Control Plane</title>
<style>
body {{ font-family: sans-serif; margin: 1.5em; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 2em; }}
th, td {{ border: 1px solid #ccc; padding: 0.4em 0.6em; text-align: left; vertical-align: top; }}
th {{ background: #eee; }}
.ready {{ color: green; font-weight: bold; }}
.blocked {{ color: #b00; font-weight: bold; }}
.status-blocked, .status-contradicted {{ color: #b00; }}
.status-auto_resolved, .status-user_confirmed {{ color: green; }}
.answer-form input {{ width: 8em; margin-right: 0.3em; }}
.empty {{ color: #666; font-style: italic; }}
#result {{ white-space: pre-wrap; font-family: monospace; }}
</style>
</head><body>
{layout_partial}
<h1>GUI Intake Control Plane</h1>
<p>Generated at {_e(snapshot.get('generated_at'))} from real backend state
(<code>question_queue.py</code> / <code>intake_state.py</code>) -- nothing on
this page is mocked.</p>
{readiness_html}
<h2 id="pending-questions">Pending Questions</h2>
{_render_questions_table(snapshot.get('pending_questions') or [])}
<h2 id="intake-field-statuses">Intake Field Statuses</h2>
{_render_fields_table(snapshot.get('fields') or [])}
<pre id="result"></pre>
<script>
document.querySelectorAll('.answer-form').forEach(function(form) {{
  form.addEventListener('submit', function(ev) {{
    ev.preventDefault();
    var qid = form.getAttribute('data-qid');
    var params = new URLSearchParams(window.location.search);
    var token = params.get('token') || '';
    var body = {{
      question_id: qid,
      answer: form.answer.value,
      basis: form.basis.value,
      decided_by: form.decided_by.value
    }};
    fetch('/api/intake/answer' + (token ? ('?token=' + encodeURIComponent(token)) : ''), {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(body)
    }}).then(function(r) {{ return r.text().then(function(t) {{ return {{status: r.status, text: t}}; }}); }})
      .then(function(res) {{
        document.getElementById('result').textContent = res.status + ': ' + res.text;
        if (res.status === 200) {{ window.location.reload(); }}
      }});
  }});
}});
</script>
</body></html>"""


# ---------------------------------------------------------------------------
# real HTTP server
# ---------------------------------------------------------------------------

def build_handler(project_root: Path, token_holder: Dict[str, Any]):
    """`token_holder` is a mutable dict (`{"token": ..., "require_auth":
    ...}`) rather than a plain string, so `serve()` can mint the real token
    AFTER the server has bound its port (needed to record the real port in
    the session file) without constructing a second handler class or
    reassigning `ThreadingHTTPServer.RequestHandlerClass` after
    construction. `require_auth=False` is the explicit, documented
    local-debugging opt-out -- checked here, never inferred from an absent
    token, so a caller who forgot to mint one gets a hard-denied 401 rather
    than an accidentally-open write endpoint."""
    root = Path(project_root)

    class Handler(BaseHTTPRequestHandler):
        server_version = "DVHarnessIntakeControlPlane/1.0"

        def log_message(self, fmt, *args):  # quiet unless explicitly asked for
            pass

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, status: int, body_text: str) -> None:
            body = body_text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler's own naming
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/":
                snap = control_plane_snapshot(root)
                self._send_html(200, render_page(snap))
            elif parsed.path == "/api/intake/questions":
                self._send_json(200, {"questions": list_pending_questions(root)})
            elif parsed.path == "/api/intake/state":
                state = gather_intake_state(root)
                self._send_json(200, state.to_dict())
            elif parsed.path == "/api/intake/snapshot":
                self._send_json(200, control_plane_snapshot(root))
            else:
                self._send_json(404, {"error": "NOT_FOUND", "path": parsed.path})

        def do_POST(self):  # noqa: N802
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != "/api/intake/answer":
                self._send_json(404, {"error": "NOT_FOUND", "path": parsed.path})
                return
            if token_holder.get("require_auth", True) and not _authorized(
                    token_holder.get("token") or "", self.headers, self.path):
                self._send_json(401, {
                    "error": "AUTH_REQUIRED",
                    "message": (
                        "This is a mutating request and requires this server's session "
                        f"token. Send it as an {dashboard_auth.TOKEN_HEADER} header, as "
                        "'Authorization: Bearer <token>', or as ?token=... on the URL. "
                        f"The token is also in .dv-harness/{SESSION_FILENAME}."
                    ),
                })
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._send_json(400, {"error": "MALFORMED_JSON_BODY"})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "BODY_MUST_BE_A_JSON_OBJECT"})
                return
            qid = payload.get("question_id")
            answer = payload.get("answer")
            basis = payload.get("basis")
            decided_by = payload.get("decided_by")
            if not qid or not answer or not basis or not decided_by:
                self._send_json(400, {
                    "error": "MISSING_REQUIRED_FIELD",
                    "required": ["question_id", "answer", "basis", "decided_by"],
                })
                return
            try:
                record = answer_pending_question(
                    root, str(qid), answer=str(answer), basis=str(basis),
                    decided_by=str(decided_by),
                )
            except KeyError as exc:
                self._send_json(404, {"error": "QUESTION_NOT_FOUND", "detail": str(exc)})
                return
            self._send_json(200, {"answered": record})

    return Handler


def build_server(project_root: Path, *, host: str = "127.0.0.1", port: int = 0,
                   require_auth: bool = True) -> "tuple[ThreadingHTTPServer, Optional[str]]":
    """Constructs (and binds) the real `ThreadingHTTPServer` without running
    it -- split out from `serve()` so a caller (a test, or an embedding
    process) can start it on its own thread and call `server.shutdown()` /
    `server.server_close()` for a clean stop, rather than being forced into
    `serve()`'s own blocking `serve_forever()`. Returns `(server, token)`;
    `token` is `None` when `require_auth=False`."""
    root = Path(project_root)
    token_holder: Dict[str, Any] = {"token": "", "require_auth": require_auth}
    server = ThreadingHTTPServer((host, port), build_handler(root, token_holder))
    actual_port = server.server_address[1]
    token: Optional[str] = None
    if require_auth:
        record = issue_session_token(root, port=actual_port, host=host)
        token_holder["token"] = record["token"]
        token = record["token"]
    return server, token


def serve(project_root: Path, *, host: str = "127.0.0.1", port: int = 0,
           require_auth: bool = True) -> None:
    """Starts the real `ThreadingHTTPServer` and blocks (`serve_forever`).
    `port=0` (the default) lets the OS choose a free port -- printed to
    stdout on start, the same "read the console output" model
    `dashboard_auth.py`'s own module docstring already documents for its
    session token."""
    root = Path(project_root)
    server, token = build_server(root, host=host, port=port, require_auth=require_auth)
    actual_port = server.server_address[1]
    if token:
        print(f"GUI Intake Control Plane: http://{host}:{actual_port}/?token={token}")
        print(f"Token also recorded at {session_file(root)}")
    else:
        print(f"GUI Intake Control Plane (auth disabled): http://{host}:{actual_port}/")
    try:
        server.serve_forever()
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# ad hoc front door
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m dv_harness.gui_intake_control_plane")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Start the GUI Intake Control Plane server.")
    p_serve.add_argument("--project-root", default=".")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--no-auth", action="store_true",
                          help="Disable the session-token gate (local debugging only).")

    p_snap = sub.add_parser("snapshot", help="Print the real control-plane snapshot as JSON.")
    p_snap.add_argument("--project-root", default=".")

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        serve(Path(args.project_root), host=args.host, port=args.port,
              require_auth=not args.no_auth)
        return 0
    if args.cmd == "snapshot":
        snap = control_plane_snapshot(Path(args.project_root))
        print(json.dumps(snap, ensure_ascii=False, default=str, indent=2))
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
