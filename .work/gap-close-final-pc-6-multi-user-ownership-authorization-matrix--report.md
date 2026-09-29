# PC-6 — Multi-user ownership / authorization matrix

**Status: DONE**
**Commit: `ce382b7` — dashboard(PC-6): per-action per-role authorization matrix on the GUI-19 token**
**Test summary: 31 new tests in `dv_harness_tests/test_dashboard_authorization_matrix.py` pass; deleting the role comparison turns 13 of them red; 148 tests across every dashboard suite and 62 in `test_session_and_info.py` still pass unchanged.**

---

## 1. Independent re-verification (the gap was real)

Run before writing anything:

- `grep -rn "ownership_matrix|authorization_matrix|OWNERSHIP_MATRIX|AUTHORIZATION_MATRIX"` over `*.py`/`*.md` — **zero hits**.
- `grep -rn "VIEWER|APPROVER|OPERATOR"` over `dv_harness/` — **zero hits** other than unrelated AMBA `StructuralRole` / fabric-role text.
- `git show 08a61df` (GUI-19) read in full, plus the current `dv_harness/dashboard_auth.py` and `dashboard.py`'s `_authorized()` / `do_POST()` / `_dispatch_control()`.

Confirmed state before this change: `dashboard_auth.authorize()` was a pure **authentication** check — one token, `secrets.compare_digest`, applied to every POST identically. There was no permission concept anywhere. So whoever could watch a run could also:

- `POST /api/control {"command":"APPROVE"}` → a real `APPROVAL` in `control.json` and a real approve event in the audit trail,
- author a waiver (`/api/waiver`), which exempts a requirement from a real gate,
- flip `policy.require_dv_review_cosign` (`/api/config`),
- export the signoff bundle (`/api/signoff-export`),
- and the three `RESEARCH_*` capability-evolution approval verbs.

CLAUDE.md's own "Multi-User Coordination Conflict Detection (2026-09-06, section 239)" section states this in as many words: of section 239's nine concerns, "**ownership/authorized-role** … [is] NOT [implemented]".

`git status`/`git diff` on `dashboard.py`, `dashboard_auth.py`, `config.py`, `policy.py` showed **no uncommitted changes from other close-passes** before I started, and the final `git diff` hunk headers were all mine — so a scoped `git add` of my three paths was correct and `.dv-harness/events.jsonl` (dirty from other passes) was left alone.

## 2. What was built — extension, not a parallel mechanism

Everything is in the two GUI-19 files plus one new test file. No new module, no second auth store, no second audit trail.

### `dv_harness/dashboard_auth.py`

**Roles** `VIEWER < OPERATOR < APPROVER` (`ROLES`, `ROLE_RANK`). APPROVER is a strict superset of OPERATOR — there is no action an OPERATOR may take that an APPROVER may not.

**Tokens reuse the existing infrastructure.** `issue_session_token()` now mints one **independent** `secrets.token_urlsafe(32)` per role into the *same* `.dv-harness/dashboard_session.json` record, written through the *same* atomic tmpfile + `storage._atomic_replace()` path. The record's pre-existing `token` field **IS** the APPROVER token — so the startup-banner URL, `read_session_token()`, and every pre-PC-6 caller keep exactly the authority they had. `read_role_tokens()` is the operator's read-side for handing one out; a pre-PC-6 session file yields `{APPROVER: <token>}` only and never a fabricated VIEWER credential nobody minted.

**The matrix** — `ENDPOINT_REQUIRED_ROLE` + `CONTROL_COMMAND_REQUIRED_ROLE`. The split is exactly *"does this write a human DECISION into the audit trail"*:

| role | may |
|---|---|
| VIEWER | nothing mutating (read-only GET was never gated and still is not) |
| OPERATOR | `/api/setup`, `/api/start`, `/api/session/save`, `/api/session/restore`, `/api/upload`; control `PAUSE`, `RESUME`, `TAKEOVER`, `RELEASE_TAKEOVER`, `REDIRECT`, `CONSTRAINT_ADD`, `CONSTRAINT_REMOVE` |
| APPROVER | all of the above, plus `/api/config`, `/api/signoff-export`, `/api/waiver`; control `APPROVE`, `COSIGN`, `CORRECT`, `RESEARCH_APPROVE`, `RESEARCH_REJECT`, `RESEARCH_HOLD` |

`/api/control` is per-**COMMAND**, not per-endpoint, because one endpoint carries both "pause the run" and "approve SIGNOFF".

**Deny-by-default in both directions.** `UNMAPPED_ACTION_ROLE = APPROVER`: an unmapped endpoint, an unmapped control command, **and an unreadable control body** all require APPROVER. Not knowing which command a request carries is a reason to demand *more* authority, never less. So an action added later is gated at the **highest** level by existing, never at the lowest by omission — the same "gated by existing" property GUI-19's pre-dispatch placement gives.

**Drift guards.** `dispatched_post_endpoints()` / `dispatched_control_commands()` parse `dashboard.py`'s **real** `do_POST` and `_dispatch_control` source; `assert_endpoints_mapped()` / `assert_control_commands_mapped()` raise `DashboardRoleMatrixError` on either direction of drift (unmapped **or** stale). So the fallback is a safety net, not a place things quietly live.

**Decision function.** `authorize_detail()` does authentication first (unchanged reasons `NO_SESSION_TOKEN_ISSUED` / `MISSING_TOKEN` / `INVALID_TOKEN`), then `resolve_role()` (constant-time, most-privileged-first), then the matrix → `ROLE_NOT_PERMITTED`. `authorize()` is retained as the `(allowed, reason)` wrapper, and **with `role_tokens=None` behaves byte-identically to GUI-19** — the two existing unit tests of it pass untouched.

### `dv_harness/dashboard.py`

- `serve()` keeps the whole session record and passes `role_tokens` into the gate.
- `_authorized()` — still the single pre-dispatch choke point — reads `/api/control`'s `command` before dispatch and calls `authorize_detail()`.
- The request body is now read from the socket **at most once** per request and cached on the handler instance (`_consume_body()`), so the gate's peek cannot eat the payload the handler needs. `BaseHTTPRequestHandler` builds one instance per request, so the cache never outlives its request. This is asserted by a dedicated test.
- The denial lands as the **same** `DASHBOARD_AUTH_DENIED` event on the **same** `events.jsonl` trail `dv-harness audit` already reads, now carrying `role` / `required_role` / `action`.
- The 403 body for a role denial is `error: "ROLE_NOT_PERMITTED"` — deliberately *not* `AUTH_REQUIRED`, which would send an authenticated caller after the one credential that cannot help. The page's existing auth banner renders both, so a VIEWER's Approve click says which role the action needs instead of silently doing nothing.
- The startup banner additionally prints the VIEWER/OPERATOR URLs — the whole point of the split is that these can be handed out separately.

## 3. Human-approval gates: strictly tightened, never weakened

- This mechanism can **only ever refuse** an action the single token would have allowed. Nothing new is permitted to anyone.
- `HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError`, `ControlPlane.approve()`, `policy.can_signoff()` and the PR-only main/master governance are untouched and unreferenced by this change.
- `require_auth: false` remains GUI-19's explicit kiosk escape hatch, unchanged and deliberately not narrowed: with no credential there is no role to carry. Asserted by a test.
- No build, regression or LSF submission is triggered anywhere. Every test runs against a temp project on a free local port with an injected fake adapter (the pre-existing `adapter_factory` seam).

## 4. Tests — `dv_harness_tests/test_dashboard_authorization_matrix.py` (31 tests)

Real `dashboard.serve()` on a free local port, driven over real HTTP, reusing `test_dashboard_interactive.py`'s helpers (the same cross-test convention `test_dashboard_auth.py` follows). Tokens are read off `.dv-harness/dashboard_session.json`, never handed over from inside the server process.

The headline pair, which is exactly what the task asked for:

- `test_viewer_token_cannot_approve_and_mints_no_approval` — 403 `ROLE_NOT_PERMITTED`, `role: VIEWER`, `required_role: APPROVER`, and **`ControlPlane.get_approval("SIGNOFF") is None`** afterward.
- `test_the_same_approve_with_the_approver_token_really_lands` — the identical body at APPROVER returns 200 and a real approval record with the real `reviewer_id`/`note`.

Every other negative carries the same shape (side effect absent + a higher-role pairing that really lands): waivers (`waiver_store.read_waivers()` empty → 1), policy writes (`config.json` unchanged → `require_dv_review_cosign: true`), signoff export (no directory), setup (`project_meta.json` absent → present), OPERATOR refused on APPROVE, VIEWER refused even on PAUSE while OPERATOR's PAUSE really sets `ControlPlane.is_paused()`.

Deny-by-default proven both ways: an unknown POST endpoint and an unknown control command are **403 for OPERATOR** and reach their real 404/400 for APPROVER.

Guards and negative controls: the two drift guards are asserted **and proven to really trip** when the matrix is mutated; `VIEWER` is asserted absent from every required-role value (a VIEWER that could mutate would be a mutating role wearing a read-only name); a pre-PC-6 session record is asserted to keep full authority.

**Mutation check for detection power:** replacing the role comparison in `authorize_detail()` with `if False:` turns **13 of 31 red**; reverting returns all 31 green.

**Suite runs (all green, this machine, this commit):**

- `test_dashboard_authorization_matrix.py` — **31 passed**
- all seven pre-existing dashboard suites + the new one — **148 passed in 168s** (`test_dashboard_auth.py`, `test_dashboard_interactive.py`, `test_dashboard_amba_card.py`, `test_dashboard_loop_card.py`, `test_dashboard_memory_card.py`, `test_dashboard_research_card.py`, `test_dashboard_cli_checklist_rendering.py`)
- `test_session_and_info.py` + `test_stats_snapshot.py` (the other `read_session_token()` consumers) — **62 passed**

## 5. Built vs. deferred

**Built:** the role vocabulary, the per-action matrix over the complete real POST surface (9 endpoints + 13 control commands), per-role token issuance on the existing session record, the role check inside the existing single choke point, the distinct role-denial answer, the audit fields, the frontend banner, and two source-derived drift guards.

**Deliberately NOT built (and stated rather than implied closed):**

1. **Roles separate holders of different TOKENS, not identities.** A process that can read `dashboard_session.json` reads all three and can act as APPROVER. That is GUI-19's own disclosed residual 1, unchanged and not re-closed here — closing it needs OS-level peer credentials a TCP socket does not carry portably. Recorded as a third residual in `dashboard_auth.py`'s docstring.
2. **No user directory, no login, no per-person tokens.** There is one token per role per dashboard process, not one per human. `reviewer_id` remains a caller-supplied field on APPROVE/COSIGN, exactly as before — the matrix decides *whether* the action may happen, not *who* to name in it.
3. **CLI-side authorization is untouched.** `dv-harness approve` from a terminal is unaffected: a shell prompt on this machine is already the operator, and gating it would need a credential model this repo does not have. The gap the audit named, and the prior art it named to extend, are both the dashboard's.
4. **No role check on the six other waiver-consuming gates / no new stage gate.** This is an HTTP access-control layer; adding a stage gate that passed or failed on a role would be a different (and worse) mechanism.
5. **`multi_user_coordination.py` is not touched.** It is DETECTION across peer project roots and explicitly "not an auth layer"; wiring it into this would conflate two deliberately separate mechanisms.
