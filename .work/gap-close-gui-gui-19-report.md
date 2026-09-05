# GUI-19 gap close -- real permission/token check on every mutating POST

(Requested path was `.work/gap-close-gui-gui-19:-report.md`; `:` is not a legal
Windows filename character, so the colon is dropped.)

**Status: DONE**

**Test summary**: 166 passed -- the full `dv_harness_tests/test_dashboard*.py`
suite (109, including 15 new `test_dashboard_auth.py` tests) plus
`test_session_and_info.py` (57, whose own dashboard POST helper was updated to
present a real token). A mutation check that deletes the gate call turns 6 of
the 15 new tests red, so they have real detection power rather than only
observing that a code path exists.

## The gap, as it really was

`dashboard.serve()`'s `do_GET`/`do_POST` had no authentication and no permission
check anywhere, while POST already exposed real, consequential actions:
control-plane `APPROVE` / `COSIGN` / `TAKEOVER` / constraint writes
(`/api/control` -> `_dispatch_control` -> `dv_harness.commands`), signoff-bundle
export, waiver authoring, policy writes, session save/restore, upload and
harness start. The default `127.0.0.1` bind (`config.py`'s `dashboard.host`)
limits NETWORK reach; it is not access control. Confirmed empirically during
this pass by removing the new gate: an unauthenticated `POST /api/control`
`{"command":"APPROVE","stage":"SIGNOFF"}` returns 200 and mints a real approval
in `.dv-harness/control.json` plus a real `approve` event in the project's audit
trail, attributed to whatever `reviewer_id` the caller typed.

## What was built

**`dv_harness/dashboard_auth.py`** (new) -- the whole mechanism, kept out of
`dashboard.py` so it is unit-testable without an HTTP server:

- `issue_session_token()` mints a fresh `secrets.token_urlsafe(32)` per dashboard
  process and persists it to `.dv-harness/dashboard_session.json` through the
  existing `storage._atomic_replace()` tmpfile pattern (reused, not
  re-implemented), `chmod 0o600` where the OS supports it. A fresh token per
  start is deliberate: a token left over from a dashboard that is no longer
  running must not authorize anything against the next one.
- `authorize(expected, headers, path, method, require_auth) -> (allowed, reason)`
  is the single decision function. `secrets.compare_digest` comparison, so a
  wrong token is not recoverable a character at a time from response timing.
  **Fails closed**: an expected token that does not exist yields
  `NO_SESSION_TOKEN_ISSUED` (deny), never "nothing to compare, so allow".
- `presented_token()` accepts `X-DV-Harness-Token`, `Authorization: Bearer ...`,
  or `?token=` on the path.
- `denial_response()` / `startup_banner()` -- a 403 that names the two real
  places the operator can get the token from, and a startup line printing the
  ready-to-click URL. A gate that does not say how to proceed is how a gate gets
  switched off.

**`dv_harness/dashboard.py`**:

- `serve()` mints the token BEFORE the server can accept a request, so no window
  exists in which a mutating POST is reachable with no credential in existence.
- `Handler._authorized()` runs in `do_POST` **before path dispatch** -- so a POST
  endpoint added later is gated by existing, not by whoever adds it remembering
  to opt it in. An unknown POST path is refused 403, not 404.
- Every denial is recorded as a real `DASHBOARD_AUTH_DENIED` event on the same
  `.dv-harness/events.jsonl` trail `dv-harness audit` already reads (best-effort:
  an audit-write failure never turns a denial into a 500).
- `do_POST` now dispatches on the path with its query string stripped, so the
  `?token=` form works; every branch still takes its real arguments from the JSON
  body only.
- Frontend: `postJSON()` (the one central POST helper the whole page already went
  through) attaches the token header. The token is **never embedded in the served
  HTML** -- it arrives once as `?token=` on the startup URL, is moved into
  `sessionStorage` and stripped from the address bar via `history.replaceState`.
  A 403 raises a real `#authBanner` telling the operator where the token is.

**`dv_harness/config.py`**: `dashboard.require_auth`, default `True`. Because
`load_config()` deep-merges `DEFAULT_CONFIG`, every existing project's
`config.json` gets it on next load without migration. Setting it false prints a
startup WARNING naming exactly what that opens.

## Tests (`dv_harness_tests/test_dashboard_auth.py`, 15 tests)

Written for detection power, not coverage theatre. Every negative case asserts
the real **side effect is absent** afterward, read off disk through the real
modules (`ControlPlane.get_approval()` is still `None`,
`waiver_store.read_waivers()` still empty, no `project_meta.json` / `uploads/` /
`signoff-export/` / policy write), and each is paired with the same request
carrying the real token to prove the action is genuinely reachable:

- unauthenticated `APPROVE` -> 403 `MISSING_TOKEN`, **no approval written**;
  same request with the real token -> 200 and the approval really lands
- wrong token -> 403 `INVALID_TOKEN` (an implementation that only checked the
  header was PRESENT would pass the first test and fail this one)
- one dashboard's token does not authorize another dashboard
- all 9 real POST endpoints plus an unknown POST path refused unauthenticated
- token accepted via `Authorization: Bearer` and via `?token=`
- read-only GETs stay open; **the served HTML does not contain the token**
- the denial reaches the real audit trail
- `require_auth: false` opt-in really opens POSTs; the shipped default is `True`
- `authorize()` fails closed with no issued token; GET is not gated

The token these tests present is read out of `.dv-harness/dashboard_session.json`
-- the same file the startup banner points a human at -- never handed over from
inside the server process.

`test_dashboard_interactive.py`'s and `test_session_and_info.py`'s shared
`_post()` helpers now present that real token too (keyed by port, since both
modules leave several dashboards running at once), so the **entire pre-existing
dashboard HTTP suite now runs through the real gate** rather than around it.

## Mutation check (evidence the tests bite)

Temporarily replacing `if not self._authorized(): return` with `pass` in
`do_POST`:

```
6 failed, 9 passed
FAILED test_unauthenticated_approve_is_rejected_and_writes_no_approval
   - AssertionError: (200, {'result': {'approved_at': ...}})
FAILED test_wrong_token_is_rejected_not_merely_a_present_header
FAILED test_one_dashboards_token_does_not_authorize_another
FAILED test_every_mutating_post_endpoint_refuses_an_unauthenticated_caller
   - /api/setup was not refused: 200 {'saved': True, ...}
FAILED test_unauthenticated_waiver_and_signoff_export_write_nothing
FAILED test_denial_is_recorded_on_the_real_audit_trail
```

The gate was restored immediately afterward.

## Disclosed residuals (not implied closed)

1. A local process running **as this same user** can read
   `.dv-harness/dashboard_session.json` and is then indistinguishable from the
   human. Closing that needs OS-level peer-credential checks a TCP socket does
   not carry portably. What is closed is the case that actually existed: a caller
   acting with no credential at all.
2. `os.chmod(0o600)` is real on POSIX; on Windows it only toggles the read-only
   bit and does not restrict other users via ACLs. `issue_session_token()`
   records which of the two it actually got in the session record's
   `permissions` field rather than claiming 0600 everywhere.
3. GET endpoints are deliberately ungated (per the task's own scoping). They
   expose no writer.

## Deferred

Nothing from GUI-19. No RBAC *role* model was built: the gap as audited is "no
authentication or permission check anywhere in front of mutating actions", and
for a single-operator localhost tool a per-session capability token is the real
answer -- a role table with one role would have been the decorative version this
task explicitly warned against.

## Files

- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\dashboard_auth.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\dashboard.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\config.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_dashboard_auth.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_dashboard_interactive.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_session_and_info.py`
