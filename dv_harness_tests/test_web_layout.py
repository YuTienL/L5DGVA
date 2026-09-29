"""Tests for dv_harness/web_layout.py (item P1-1-web-layout-module).

`web_layout.py` is a pure, stdlib-only, dependency-free set of HTML-fragment
generation functions -- it starts no server and calls no other dv_harness
module, so these are real, direct calls into the functions under test rather
than an HTTP-driven harness (matching this file's own real scope: proving
this module is load-bearing over a live server is item P2-1's job, not
this one's -- see the module's own docstring).

Every test asserts on the REAL returned strings (structure, escaping,
required element ids/classes), never on a mock -- there is nothing in this
module to mock.
"""
from __future__ import annotations

import html as html_stdlib
import re

import pytest

from dv_harness.web_layout import (
    page_shell,
    render_card,
    render_nav,
    render_status_bar_partial,
)


# ---------------------------------------------------------------------------
# page_shell()
# ---------------------------------------------------------------------------


def test_page_shell_produces_a_complete_html_document():
    out = page_shell("My Title", "<p>hello</p>")
    assert out.startswith("<!doctype html>")
    assert out.rstrip().endswith("</html>")
    assert "<title>My Title</title>" in out
    assert "<p>hello</p>" in out
    # exactly one <style> block, and it is non-empty (real CSS, not a stub)
    style_matches = re.findall(r"<style>(.*?)</style>", out, re.S)
    assert len(style_matches) == 1
    assert len(style_matches[0]) > 100


def test_page_shell_escapes_the_title_but_never_the_body():
    # a title containing HTML-significant characters must be escaped --
    # this module must never let a caller-supplied title inject markup.
    out = page_shell("<script>evil()</script>", "<p>trusted body</p>")
    assert "<script>evil()</script>" not in out
    assert "&lt;script&gt;evil()&lt;/script&gt;" in out
    # body_html is trusted, pre-built markup and is embedded VERBATIM,
    # per this function's own documented contract -- a caller assembling a
    # page from render_nav()/render_card()/render_status_bar_partial()
    # output must see that real markup land in the page unescaped.
    assert "<p>trusted body</p>" in out


def test_page_shell_active_route_becomes_a_data_attribute():
    out = page_shell("T", "<div>x</div>", active_route="loops")
    assert 'data-active-route="loops"' in out
    assert "<body" in out


def test_page_shell_active_route_value_is_itself_escaped():
    out = page_shell("T", "<div>x</div>", active_route='"><script>x</script>')
    assert "<script>x</script>" not in out
    # the escaped attribute value must not break out of the attribute
    assert 'data-active-route="' in out


def test_page_shell_without_active_route_carries_no_data_attribute():
    out = page_shell("T", "<div>x</div>")
    assert "data-active-route" not in out


def test_page_shell_uses_no_third_party_template_syntax():
    # "no template engine" per this item's own scope: the output must never
    # contain an unresolved Jinja/Mustache-style placeholder, which would be
    # the tell-tale sign of a template engine having been used and having
    # failed to render.
    out = page_shell("Title {x}", "<p>{{ not_a_template_var }}</p>")
    assert "{{ not_a_template_var }}" in out  # passed through verbatim, not "rendered"


# ---------------------------------------------------------------------------
# render_status_bar_partial()
# ---------------------------------------------------------------------------


def test_status_bar_partial_reuses_dashboards_real_element_ids():
    out = render_status_bar_partial()
    # every id dashboard.py's own real Global Status Bar markup declares,
    # reused verbatim per this module's own REUSE OVER REINVENT contract.
    for real_id in (
        "globalStatusBar",
        "sbIdentityRegion",
        "sbHarnessRegion",
        "sbActivityRegion",
        "sbExecutionRegion",
        "sbClosureRegion",
        "sbBlockersRegion",
        "sbIdentity",
        "sbHarness",
        "sbActivity",
        "sbExecution",
        "sbClosure",
        "sbBlockers",
        "sbLayoutBtn",
        "sbDrawerBtn",
        "statusBarDrawer",
    ):
        assert f'id="{real_id}"' in out, f"missing real dashboard.py element id: {real_id}"


def test_status_bar_partial_wires_the_real_dashboard_js_hooks():
    out = render_status_bar_partial()
    # dashboard.py's own real JS function names -- reused as onclick targets
    # so a caller pairing this fragment with dashboard.py's existing JS gets
    # working buttons with no further edits.
    assert "onclick=\"cycleStatusBarLayout()\"" in out
    assert "onclick=\"toggleStatusBarDrawer()\"" in out


def test_status_bar_partial_drawer_starts_hidden():
    out = render_status_bar_partial()
    assert 'id="statusBarDrawer" style="display:none"' in out


def test_status_bar_partial_carries_no_script_tag_and_no_live_data():
    # a STATIC shell only -- structure, never runtime wiring or a script
    # block of its own, per this function's own documented contract.
    out = render_status_bar_partial()
    assert "<script" not in out
    assert "fetch(" not in out


def test_status_bar_partial_returns_a_stable_deterministic_string():
    # a pure function: identical output on every call, no hidden state.
    assert render_status_bar_partial() == render_status_bar_partial()


# ---------------------------------------------------------------------------
# render_nav()
# ---------------------------------------------------------------------------


def test_render_nav_renders_every_declared_route_as_a_link():
    out = render_nav([("home", "Home"), ("loops", "Loops"), ("agents", "Agents")])
    assert out.startswith('<nav class="webNav">')
    assert out.rstrip().endswith("</nav>")
    assert out.count("<a ") == 3
    assert ">Home</a>" in out
    assert ">Loops</a>" in out
    assert ">Agents</a>" in out
    # default href derived from the route id
    assert 'href="#home"' in out


def test_render_nav_accepts_explicit_href_via_three_tuple():
    out = render_nav([("home", "Home", "/home")])
    assert 'href="/home"' in out


def test_render_nav_accepts_a_mapping_entry():
    out = render_nav([{"route": "loops", "label": "Loops", "href": "/loops"}])
    assert 'href="/loops"' in out
    assert ">Loops</a>" in out


def test_render_nav_mapping_entry_accepts_id_key_as_alias_for_route():
    out = render_nav([{"id": "agents", "label": "Agents"}])
    assert 'href="#agents"' in out


def test_render_nav_marks_exactly_one_matching_link_active():
    out = render_nav([("home", "Home"), ("loops", "Loops")], active="loops")
    assert out.count('class="active"') == 1
    # the active link also carries aria-current="page"
    loops_link = re.search(r'<a [^>]*>Loops</a>', out).group(0)
    assert 'class="active"' in loops_link
    assert 'aria-current="page"' in loops_link
    home_link = re.search(r'<a [^>]*>Home</a>', out).group(0)
    assert 'class="active"' not in home_link


def test_render_nav_active_matching_no_real_route_highlights_nothing():
    # never a guessed match -- an active value naming no real route in the
    # supplied list simply highlights nothing; this is not an error.
    out = render_nav([("home", "Home")], active="not-a-real-route")
    assert 'class="active"' not in out
    assert ">Home</a>" in out


def test_render_nav_empty_routes_renders_an_empty_but_valid_nav():
    out = render_nav([])
    assert out == '<nav class="webNav"></nav>'


def test_render_nav_escapes_label_and_href():
    out = render_nav([("x", '<script>evil()</script>', '"><script>y</script>')])
    assert "<script>evil()</script>" not in out
    assert "&lt;script&gt;evil()&lt;/script&gt;" in out
    assert "<script>y</script>" not in out


def test_render_nav_rejects_a_malformed_route_entry():
    with pytest.raises(ValueError):
        render_nav([("only-one-element",)])


def test_render_nav_rejects_an_entry_with_no_real_id():
    with pytest.raises(ValueError):
        render_nav([("", "Label")])


def test_render_nav_rejects_an_entry_with_no_real_label():
    with pytest.raises(ValueError):
        render_nav([("route", "  ")])


def test_render_nav_rejects_a_non_sequence_routes_argument():
    with pytest.raises(ValueError):
        render_nav("not-a-list")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# render_card()
# ---------------------------------------------------------------------------


def test_render_card_wraps_body_with_id_and_title():
    out = render_card("myCard", "My Card Title", "<p>body content</p>")
    assert out.startswith('<div class="card" id="myCard">')
    assert out.rstrip().endswith("</div>")
    assert "<h3>My Card Title</h3>" in out
    assert "<p>body content</p>" in out


def test_render_card_embeds_body_html_verbatim_never_escaped():
    body = '<table><tr><td class="x">1</td></tr></table>'
    out = render_card("c1", "Title", body)
    assert body in out


def test_render_card_escapes_title_and_id():
    out = render_card(
        'a"onmouseover="evil()',
        "<b>bold</b> title",
        "<p>x</p>",
    )
    assert "onmouseover" not in out or "&quot;onmouseover=&quot;evil()" in out
    assert "<b>bold</b> title" not in out
    assert "&lt;b&gt;bold&lt;/b&gt; title" in out


def test_render_card_rejects_empty_card_id():
    with pytest.raises(ValueError):
        render_card("", "Title", "<p>x</p>")


def test_render_card_rejects_whitespace_only_card_id():
    with pytest.raises(ValueError):
        render_card("   ", "Title", "<p>x</p>")


def test_render_card_rejects_empty_title():
    with pytest.raises(ValueError):
        render_card("id1", "", "<p>x</p>")


def test_render_card_rejects_none_title():
    with pytest.raises(ValueError):
        render_card("id1", None, "<p>x</p>")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Composition: the four functions are designed to compose into one page,
# exactly the shape item P2-1 will need -- proven here as a real,
# end-to-end string-composition test (still no server, no I/O).
# ---------------------------------------------------------------------------


def test_functions_compose_into_one_well_formed_page():
    nav = render_nav([("home", "Home"), ("loops", "Loops")], active="loops")
    status_bar = render_status_bar_partial()
    card = render_card("loopsCard", "Loops", "<p>no loops yet</p>")
    page = page_shell("Loops", nav + status_bar + "<main>" + card + "</main>", active_route="loops")

    assert page.startswith("<!doctype html>")
    assert page.rstrip().endswith("</html>")
    assert 'data-active-route="loops"' in page
    assert '<nav class="webNav">' in page
    assert 'id="globalStatusBar"' in page
    assert 'id="loopsCard"' in page
    assert "<h3>Loops</h3>" in page
    # every element this composition introduces is present and balanced:
    # one nav open/close, one main open/close.
    assert page.count("<nav ") == 1 and page.count("</nav>") == 1
    assert page.count("<main>") == 1 and page.count("</main>") == 1

    # a real, independent HTML-ish sanity check: no unescaped '<script>'
    # anywhere in the composed page (this composition introduced no script).
    assert "<script" not in page


def test_module_imports_no_third_party_dependency():
    # "stdlib-only, dependency-free" is a structural property of the
    # module's own import statements, not merely a docstring claim --
    # checked directly against the real source.
    import ast
    import inspect

    import dv_harness.web_layout as wl

    source = inspect.getsource(wl)
    tree = ast.parse(source)
    allowed_top_level_modules = {"__future__", "html", "typing"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in allowed_top_level_modules, (
                    f"web_layout.py imports a non-stdlib/non-allowed module: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top = module.split(".")[0]
            assert top in allowed_top_level_modules, (
                f"web_layout.py imports from a non-stdlib/non-allowed module: {module}"
            )


def test_module_never_imports_dashboard_or_any_other_dv_harness_module():
    # this item's own scope: dashboard.py must not be touched, imported, or
    # executed by this module at all.
    import ast
    import inspect

    import dv_harness.web_layout as wl

    source = inspect.getsource(wl)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                assert "dashboard" not in name
                assert not name.startswith("dv_harness."), (
                    f"web_layout.py must import no other dv_harness module; found: {name}"
                )
