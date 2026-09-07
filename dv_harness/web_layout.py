"""dv_harness/web_layout.py -- pure HTML-fragment layout functions (P1-1).

Scope, stated precisely per this item's own revision note: this module is a
PURE, stdlib-only, dependency-free set of functions that produce HTML
fragments/strings. No template engine, no build step, no new dependency of
any kind -- the only import beyond the stdlib `typing` module is `html`
(stdlib), used for attribute/text escaping.

This module does NOT require, and does NOT perform, any edit to
dashboard.py's existing `/` route to be considered load-bearing. That
refactor was the ORIGINAL P1-2 item and was explicitly dropped as unsafe:
dashboard.py is an 8500+-line file depended on by ~250 real, currently
passing tests (`dv_harness_tests/test_dashboard_*.py`), and rewriting its
existing inline HTML-generation code in place is exactly the kind of
destructive, high-blast-radius change this project's own governance (see
CLAUDE.md's "gh CLI + PR-Only Governance Policy" / "Change-Budget /
Blast-Radius Gate" sections) treats as requiring a pinned human approval
rather than an unreviewed drive-by edit. The proof that this module is real
and load-bearing rather than dead code is therefore DEFERRED to item P2-1,
which is the item that actually calls these functions from a NEW, ADDITIVE
route (never an edit to dashboard.py's existing `/` route's own HTML
generation).

REUSE OVER REINVENT: `render_status_bar_partial()` below was built by
READING dashboard.py's existing inline Global Status Bar markup/CSS/JS (its
`.statusBar` HTML block, its `.statusBar`/`.sbPill`/`.statusBarDrawer`
CSS rules, and its `loadGlobalStatusBar()` / `renderGlobalStatusBar()` /
`cycleStatusBarLayout()` / `toggleStatusBarDrawer()` JS functions -- all
read fresh from the live file before writing a line of this module) as a
REFERENCE, never by importing, executing, or refactoring dashboard.py
itself -- dashboard.py is completely untouched by this item, and this
module imports nothing from it. The markup this function emits deliberately
reuses the SAME element ids/classes dashboard.py's own status bar already
uses (`globalStatusBar`, `sbIdentityRegion`/`sbHarnessRegion`/
`sbActivityRegion`/`sbExecutionRegion`/`sbClosureRegion`/`sbBlockersRegion`,
`sbPill`, `statusBarDrawer`, `sbLayoutBtn`, `sbDrawerBtn`) and the SAME
`/api/status` polling contract dashboard.py's own status bar already relies
on (`harness_status.HarnessStatusService.serve()`'s flat
`{available, status, error}` shape -- see dashboard.py's own "NOTE ON SHAPE"
comment on `renderGlobalStatusBar()`), so a future caller adopting this
module's output can reuse dashboard.py's existing `.statusBar` CSS/JS
verbatim rather than a second, incompatible implementation of the same
widget.
"""
from __future__ import annotations

import html
from typing import Iterable, Mapping, Optional, Sequence, Tuple, Union

__all__ = [
    "page_shell",
    "render_status_bar_partial",
    "render_nav",
    "render_card",
]

# One route entry accepted by render_nav(): either a (route_id, label) /
# (route_id, label, href) tuple, or a dict carrying the equivalent keys
# (`route`/`id`, `label`, optional `href`). Duck-typed rather than a single
# rigid shape, matching this project's own established convention elsewhere
# in dv_harness for a caller-declared list of small records.
RouteEntry = Union[Tuple[str, str], Tuple[str, str, str], Mapping[str, str]]


def _esc(text: object) -> str:
    """Escape arbitrary text for safe inclusion in HTML content.

    A thin, always-applied wrapper around stdlib `html.escape()` -- every
    function in this module runs every piece of caller-supplied text (a
    title, a label, an id used as a rendered attribute value) through this
    before it reaches the returned string, so a caller can never
    accidentally inject markup into a page built from this module's output
    merely by supplying a status string, a project name, or a card title
    that happens to contain `<`/`>`/`&`/quote characters.
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def _esc_attr(text: object) -> str:
    """Escape text for safe inclusion inside a double-quoted HTML attribute.

    Distinct from `_esc()` in name only (both call `html.escape(...,
    quote=True)`, which already escapes `"` and `'` as well as `<`/`>`/`&`)
    -- kept as a separate, explicitly-named function so a reader of a call
    site can see at a glance whether a value is landing in element CONTENT
    or in an attribute VALUE, without having to re-derive that both are
    safe under the same stdlib call.
    """
    return _esc(text)


# ---------------------------------------------------------------------------
# Minimal, self-contained CSS. Deliberately NOT a copy-paste of dashboard.py's
# own CSS block (that would be duplication of a file this item must not
# import or edit) -- these are freshly written, small rule sets covering
# exactly the elements this module's own four functions emit, using the SAME
# class/id names dashboard.py's own status bar already uses (see the module
# docstring) so the two are visually/structurally compatible without either
# file depending on the other.
# ---------------------------------------------------------------------------

_BASE_CSS = (
    "body{font-family:Arial,sans-serif;background:#f4f7fb;color:#18233f;margin:0}"
    "main{padding:24px;max-width:1200px;margin:auto}"
    "a{color:#2457a6}"
)

_NAV_CSS = (
    ".webNav{background:#18233f;padding:0 16px;display:flex;gap:2px;flex-wrap:wrap}"
    ".webNav a{display:inline-block;padding:12px 14px;color:#c9d6ea;text-decoration:none;"
    "font-size:13px;border-bottom:3px solid transparent}"
    ".webNav a:hover{color:#fff}"
    ".webNav a.active{color:#fff;border-bottom-color:#2457a6;font-weight:bold}"
)

_CARD_CSS = (
    ".card{background:white;border:1px solid #d9e1ec;border-radius:10px;padding:16px;"
    "margin-bottom:16px}"
    ".card h3{margin:0 0 10px 0;font-size:15px}"
)

# Mirrors dashboard.py's own `.statusBar`/`.sbPill`/`.statusBarDrawer` rule
# shapes (read as reference, not copied verbatim) -- see the module
# docstring's REUSE OVER REINVENT note.
_STATUS_BAR_CSS = (
    ".statusBar{position:sticky;top:0;z-index:50;background:#12203a;color:#eaf1fb;"
    "padding:8px 16px;font-size:12px;box-shadow:0 2px 6px rgba(0,0,0,.15)}"
    ".statusBar .statusBarRow{display:flex;align-items:center;gap:14px;flex-wrap:wrap}"
    ".statusBar .sbRegion{display:flex;align-items:center;gap:6px}"
    ".statusBar .sbLabel{color:#9fb4d6;font-size:10px;text-transform:uppercase;"
    "letter-spacing:.03em}"
    ".statusBar button{background:#1b3a63;color:#eaf1fb;border:1px solid #2c5490;"
    "border-radius:4px;padding:3px 8px;font-size:11px;cursor:pointer}"
    ".statusBar .sbSpacer{flex:1 1 auto}"
    ".sbPill{border-radius:10px;padding:2px 9px;font-weight:bold;font-size:11px;"
    "white-space:nowrap;background:#5a6b8c;color:#fff}"
    ".statusBarDrawer{margin-top:8px;background:#0e1a30;border-top:1px solid #2c5490;"
    "padding:8px 4px;display:none;flex-wrap:wrap;gap:16px;max-height:320px;overflow:auto}"
)

_ALL_CSS = _BASE_CSS + _NAV_CSS + _CARD_CSS + _STATUS_BAR_CSS


def page_shell(title: str, body_html: str, active_route: Optional[str] = None) -> str:
    """Wrap `body_html` in a complete, standalone HTML document.

    `title` is escaped and placed in a real `<title>` element. `body_html`
    is trusted, pre-built markup (typically the concatenation of this
    module's own `render_nav()`/`render_status_bar_partial()`/
    `render_card()` output) and is embedded VERBATIM -- this function does
    not escape it, the same "caller-assembled trusted markup" contract every
    other HTML-fragment function in this codebase (e.g.
    `connectivity.render_markdown_table()`'s Markdown-table callers) already
    follows.

    `active_route`, when supplied, is recorded as a `data-active-route`
    attribute on `<body>` -- a plain, inert data attribute a caller's own
    client-side JS may read; this function does not itself decide nav
    highlighting (that is `render_nav()`'s own job).

    Returns a complete document string: `<!doctype html>` through the
    closing `</html>` tag. No template engine and no build step are used --
    this is plain Python string formatting over stdlib-escaped inputs only.
    """
    title_html = _esc(title)
    body_attr = f' data-active-route="{_esc_attr(active_route)}"' if active_route else ""
    return (
        "<!doctype html>\n"
        "<html><head><meta charset=\"utf-8\">"
        f"<title>{title_html}</title>"
        f"<style>{_ALL_CSS}</style>"
        "</head>"
        f"<body{body_attr}>"
        f"{body_html}"
        "</body></html>"
    )


def render_status_bar_partial() -> str:
    """Render the Global Status Bar HTML fragment (structure only).

    Reuses dashboard.py's own real, already-shipped Global Status Bar
    element ids/classes (see the module docstring's REUSE OVER REINVENT
    note) so a caller may pair this fragment's markup with dashboard.py's
    existing `.statusBar` CSS and `loadGlobalStatusBar()`/
    `renderGlobalStatusBar()`/`cycleStatusBarLayout()`/
    `toggleStatusBarDrawer()` JS functions unmodified, or with this module's
    own `_STATUS_BAR_CSS`.

    This is a STATIC shell only -- five summary regions (identity/harness/
    activity/execution/closure) plus a blockers region, a layout-cycle
    button, a details-drawer toggle button, and the (initially hidden)
    drawer container itself -- carrying no live data and no `<script>`
    block of its own. Populating it from a real `/api/status` response, and
    supplying the JS that drives `cycleStatusBarLayout()`/
    `toggleStatusBarDrawer()`, is the calling page's own job (deferred to
    item P2-1's live server route) -- this function's whole contract is
    producing the STRUCTURE, never the runtime wiring, matching this
    module's own "pure HTML-fragment functions, no build step" scope.
    """
    return (
        '<div class="statusBar mode-standard" id="globalStatusBar">'
        '<div class="statusBarRow">'
        '<div class="sbRegion" id="sbIdentityRegion">'
        '<span class="sbLabel">Project</span><span id="sbIdentity">-</span></div>'
        '<div class="sbRegion" id="sbHarnessRegion">'
        '<span class="sbLabel">Harness</span>'
        '<span id="sbHarness" class="sbPill status-UNKNOWN">UNKNOWN</span></div>'
        '<div class="sbRegion" id="sbActivityRegion">'
        '<span class="sbLabel">Activity</span><span id="sbActivity">-</span></div>'
        '<div class="sbRegion" id="sbExecutionRegion">'
        '<span class="sbLabel">Execution</span><span id="sbExecution">-</span></div>'
        '<div class="sbRegion" id="sbClosureRegion">'
        '<span class="sbLabel">Closure</span>'
        '<span id="sbClosure" class="sbPill status-UNKNOWN">UNKNOWN</span></div>'
        '<div class="sbRegion" id="sbBlockersRegion">'
        '<span class="sbLabel">Blockers</span><span id="sbBlockers">-</span></div>'
        '<div class="sbSpacer"></div>'
        '<button onclick="cycleStatusBarLayout()" id="sbLayoutBtn" '
        'title="Cycle compact/standard/expanded layout">Standard</button>'
        '<button onclick="toggleStatusBarDrawer()" id="sbDrawerBtn" '
        'title="Show every HarnessStatusIR field">Details &#9662;</button>'
        "</div>"
        '<div class="statusBarDrawer" id="statusBarDrawer" style="display:none"></div>'
        "</div>"
    )


def _normalize_route_entry(entry: RouteEntry) -> Tuple[str, str, str]:
    """Reduce one caller-supplied route entry to (route_id, label, href).

    Accepts a 2-tuple `(route_id, label)` (href defaults to `#<route_id>`),
    a 3-tuple `(route_id, label, href)`, or a mapping carrying `route` (or
    `id`) and `label` keys plus an optional `href` key -- duck-typed rather
    than one rigid shape, matching this project's own established
    convention (see e.g. `intake_question_priority.py`'s own tolerant
    per-record field access) for a caller-declared list of small records.
    Raises `ValueError` naming the malformed entry rather than silently
    skipping or guessing at it.
    """
    if isinstance(entry, Mapping):
        route_id = entry.get("route", entry.get("id"))
        label = entry.get("label")
        href = entry.get("href")
    elif isinstance(entry, tuple) and len(entry) == 2:
        route_id, label = entry
        href = None
    elif isinstance(entry, tuple) and len(entry) == 3:
        route_id, label, href = entry
    else:
        raise ValueError(
            f"render_nav(): each route entry must be a (route_id, label) or "
            f"(route_id, label, href) tuple, or a mapping carrying "
            f"'route'/'id' and 'label' keys; got: {entry!r}"
        )
    if not route_id or not str(route_id).strip():
        raise ValueError(f"render_nav(): route entry has no real route id: {entry!r}")
    if label is None or not str(label).strip():
        raise ValueError(f"render_nav(): route entry has no real label: {entry!r}")
    if not href:
        href = f"#{route_id}"
    return str(route_id), str(label), str(href)


def render_nav(routes: Sequence[RouteEntry], active: Optional[str] = None) -> str:
    """Render a horizontal navigation bar over a caller-declared route list.

    `routes` is a real, caller-supplied list -- this function discovers no
    route of its own and invents no page hierarchy; each entry names one
    real navigable destination (see `_normalize_route_entry()` for the
    accepted shapes). `active`, when it matches an entry's own route id
    (compared as a plain string, never fuzzy), marks that one link with the
    `active` CSS class and `aria-current="page"` -- never more than one
    entry, and never a guessed match when `active` names no real entry in
    `routes` at all (the link list is rendered exactly as declared either
    way; an unmatched `active` value simply highlights nothing, it is not
    an error, since a caller mid-navigation to a route not yet present in
    its own static route list is a legitimate, non-exceptional state).

    An empty `routes` sequence renders an empty (but structurally valid)
    `<nav class="webNav"></nav>` element, never a fabricated placeholder
    link.
    """
    if not isinstance(routes, (list, tuple)):
        raise ValueError(
            f"render_nav(): routes must be a list/tuple of route entries; got: {type(routes)!r}"
        )
    links = []
    for entry in routes:
        route_id, label, href = _normalize_route_entry(entry)
        is_active = active is not None and route_id == str(active)
        cls = ' class="active"' if is_active else ""
        aria = ' aria-current="page"' if is_active else ""
        links.append(f'<a href="{_esc_attr(href)}"{cls}{aria}>{_esc(label)}</a>')
    return '<nav class="webNav">' + "".join(links) + "</nav>"


def render_card(card_id: str, title: str, body_html: str) -> str:
    """Render one card container: an id'd `<div class="card">` with a title.

    `card_id` and `title` are both required, real, non-empty strings --
    `ValueError` is raised rather than silently rendering an unidentifiable
    or untitled card, mirroring this project's own established discipline
    (e.g. `verification_boundary_ir.py`'s construction-time refusals) of
    refusing to build a record missing an identifying field rather than
    guessing one. `body_html` is trusted, pre-built markup and is embedded
    verbatim (the same "caller-assembled trusted markup" contract
    `page_shell()` already documents) -- this function's own job is only the
    card chrome (the `id`, the `class="card"` wrapper, and the `<h3>`
    title), matching dashboard.py's own real `<div class="card">...<h3>...`
    convention read as reference (see the module docstring).
    """
    if not card_id or not str(card_id).strip():
        raise ValueError("render_card(): card_id must be a real, non-empty string")
    if not title or not str(title).strip():
        raise ValueError("render_card(): title must be a real, non-empty string")
    return (
        f'<div class="card" id="{_esc_attr(card_id)}">'
        f"<h3>{_esc(title)}</h3>"
        f"{body_html}"
        "</div>"
    )
