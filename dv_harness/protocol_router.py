"""Real, callable protocol/profile router -- closes the gap the 2026-09-01
AI-mechanism architecture audit flagged (also carried forward by
[[dv_harness_poster_gap_reaudit_2026_08_29]]): dv_harness/router.py's
RouteResolver.resolve() is a STATIC dict lookup keyed only on the graph
node's own pre-declared `route`/`agent`/`skills` fields in
.dv-harness/graph/main_graph.json (see that module's own NOTICE) -- the same
route/agent/skills come back every time a given Stage runs, regardless of
which protocol/failure/evidence THIS run actually has. The genuinely
input-driven rules for choosing a protocol/profile only ever existed as
prose in .claude/skills/CORE/protocol-router/SKILL.md; nothing executable
ever applied them. This module transcribes that prose into real code -- it
invents no new normalization rule or tie-break order. Every alias/route
entry below carries a comment pointing at the exact SKILL.md line it
encodes, so a future SKILL.md edit is easy to re-sync against.

Scope ruling (full write-up in
.work/route-skill-resolver-dynamic-implementation-report.md): SKILL.md's
tie-break order is "user intent -> failing test -> active config ->
modified files -> subsystem boundary". This module's FIELD_ORDER maps those
five documented sources onto five evidence-dict keys 1:1
(protocol_hint/failing_test_name/active_config/modified_files/
subsystem_boundary). `evidence` may supply any subset -- an absent, None, or
empty field is skipped, never treated as an error, because at least one of
those five fields (`active_config`, see dv_harness/engine.py's
_protocol_router_evidence()) has NO real per-run data source anywhere in
this engine today (no config.json/state.json field records a per-run
"active build config"). Per CLAUDE.md's Evidence Truth Rule / No
Golden-Reference Content Mining spirit ("never fabricate evidence you don't
have"), resolve_protocol() must work correctly with that field always
absent rather than force a caller to invent a plausible-looking value for
it.

RULING: like router.RouteResolver.resolve()/skill_resolver.SkillResolver.
resolve() (the two existing modules this one is designed to sit alongside
in engine.py's run_stage()), resolve_protocol() never raises -- an
unresolved input returns a structured {"resolved": False, ...} dict
(SKILL.md: "If unresolved after evidence inspection, ask one routing
question only" -- there is no interactive user to ask from inside a pure
resolver function, so the structured "needs a routing question" signal is
the code-level equivalent, left for the caller/agent to act on) rather than
a typed ValueError. A best-effort detector over uncertain free-text
evidence is a different kind of contract than uvm_generator.py's
manifest-schema validators (which DO use the typed-ValueError/
SCREAMING_SNAKE_CASE/detail-dict convention because a manifest is supposed
to already be well-formed) -- this module still carries a mandatory
non-empty "evidence" string on every return, matching that same discipline.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# --- Primary builder routes -------------------------------------------------
# SKILL.md "Primary routes:" list, verbatim.
PRIMARY_ROUTES: Dict[str, Dict[str, str]] = {
    "usb":       {"display": "USB",        "route": "USB/usb-profile"},
    "pcie":      {"display": "PCIe",       "route": "PCIe/pcie-profile"},
    "ethernet":  {"display": "Ethernet",   "route": "Ethernet/ethernet-profile"},
    "amba":      {"display": "AMBA",       "route": "AMBA/amba-profile"},
    "mipi_csi2": {"display": "MIPI CSI-2", "route": "MIPI/csi2-profile"},
    "mipi_dsi":  {"display": "MIPI DSI",   "route": "MIPI/dsi-profile"},
    "canfd":     {"display": "CAN-FD",     "route": "CAN/canfd-profile"},
    "emmc":      {"display": "eMMC/MMC",   "route": "PROTOCOL_BUILDERS/emmc-environment-builder"},
    "sdio":      {"display": "SD/SDIO",    "route": "PROTOCOL_BUILDERS/sd-environment-builder"},
}

# SKILL.md: "USB profile must further resolve Host vs Device." / "AMBA
# profile must further resolve: APB2/APB3/AHB/AHB-Lite/AXI3/AXI4/ACE-Lite/
# AXI-Stream." -- informational only. This router picks the PRIMARY route;
# the named further-resolution is a documented downstream concern of the
# profile skill itself (SKILL.md's "Profile/VIP-Lookup Binding" section),
# never invented here.
FURTHER_RESOLUTION: Dict[str, str] = {
    "usb": "Host vs Device",
    "amba": "APB2/APB3/AHB/AHB-Lite/AXI3/AXI4/ACE-Lite/AXI-Stream",
}

# SKILL.md "Normalize:" block, transcribed alias-by-alias. Every pattern is
# matched case-insensitively with a boundary of "not immediately adjacent to
# another letter/digit" on both sides -- deliberately NOT plain regex \b
# (which treats '_' as a word character, so \busb\b would never match inside
# a realistic snake_case failing_test_name like "test_pcie_link_train" or a
# modified_files path like "usb_host_controller.sv" -- exactly the two
# lower-priority tie-break evidence fields most likely to BE snake_case).
# This boundary still keeps "SS" from firing inside an unrelated word, and
# keeps bare "usb" from firing inside "usb2" (a digit is alnum-adjacent) --
# "usb2"/"usb3" are therefore their own explicit aliases below, matching the
# real registry's own "USB2/USB3 mode" discover-item wording
# (.dv-harness/builder/protocol_builder_registry.json, protocols.usb.discover).
_NOT_ALNUM = r"[A-Za-z0-9]"
_ALIASES: Tuple[Tuple[str, str], ...] = (
    (r"usb3", "usb"), (r"usb2", "usb"),                     # SKILL.md: "USB3 / SuperSpeed / SS"
    (r"superspeed", "usb"), (r"ss", "usb"), (r"usb", "usb"),
    (r"pci express", "pcie"), (r"pcie", "pcie"),             # SKILL.md: "PCI Express -> PCIe"
    (r"csi2", "mipi_csi2"), (r"csi-2", "mipi_csi2"),         # SKILL.md: "CSI2 / CSI-2"
    (r"mipi csi-2", "mipi_csi2"), (r"mipi csi2", "mipi_csi2"),
    (r"canfd", "canfd"), (r"can fd", "canfd"), (r"can-fd", "canfd"),  # SKILL.md: "CANFD / CAN FD"
    # SKILL.md: "AMAB4 -> AMBA when contextual" / "AIX4 -> AXI4 when
    # contextual" -- both typo-corrections into the AMBA bus family (AXI4 is
    # an AMBA protocol). "when contextual" is read here as "when the token
    # itself appears in evidence text" -- this module has no separate
    # out-of-band context signal to gate the correction on beyond that.
    (r"amab4", "amba"), (r"aix4", "amba"), (r"amba", "amba"),
    (r"axis", "amba"), (r"axi stream", "amba"), (r"axi-stream", "amba"),  # SKILL.md: "AXIS / AXI Stream -> AXI-Stream"
    (r"apb", "amba"), (r"ahb", "amba"), (r"axi", "amba"),
    # AMBA's own further-resolution vocabulary (SKILL.md: "AMBA profile must
    # further resolve: APB2/APB3/AHB/AHB-Lite/AXI3/AXI4/ACE-Lite/
    # AXI-Stream", and protocol_builder_registry.json's real amba4-soc
    # discover item "AXI3/AXI4/AXI4-Lite/AXI-Stream/AHB/AHB-Lite/APB3/APB4")
    # -- given their own explicit aliases (like usb2/usb3 above) since a bare
    # "axi"/"ahb"/"apb" alias never matches when immediately followed by a
    # version digit (digit is alnum-adjacent, no boundary).
    (r"axi3", "amba"), (r"axi4", "amba"), (r"axi4-lite", "amba"),
    (r"ahb-lite", "amba"), (r"apb2", "amba"), (r"apb3", "amba"), (r"apb4", "amba"),
    (r"ace-lite", "amba"),
    (r"mmc", "emmc"), (r"emmc", "emmc"),                     # SKILL.md: "MMC -> eMMC/MMC"
    (r"sdio", "sdio"), (r"sd/sdio", "sdio"),                 # SKILL.md: "SDIO -> SD/SDIO"
    (r"ethernet", "ethernet"),
    (r"mipi dsi", "mipi_dsi"), (r"mipi-dsi", "mipi_dsi"),
)
_ALIAS_PATTERNS: Tuple[Tuple["re.Pattern[str]", str], ...] = tuple(
    (re.compile(
        rf"(?<!{_NOT_ALNUM})" + re.escape(alias) + rf"(?!{_NOT_ALNUM})",
        re.IGNORECASE,
    ), canon)
    for alias, canon in _ALIASES
)

# SKILL.md tie-break order, verbatim: "For mixed-protocol SoCs, choose the
# protocol implicated by: user intent -> failing test -> active config ->
# modified files -> subsystem boundary." Keys below are this module's
# evidence-dict field names for each documented source, in that exact order.
FIELD_ORDER: Tuple[str, ...] = (
    "protocol_hint",       # "user intent"
    "failing_test_name",   # "failing test"
    "active_config",       # "active config"
    "modified_files",      # "modified files"
    "subsystem_boundary",  # "subsystem boundary"
)


def _field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(v) for v in value if v)
    return str(value)


def _detect(text: str) -> Optional[Tuple[str, str]]:
    """Returns (canonical_key, matched_alias_text) for the leftmost
    recognized alias in `text`, or None if nothing in text matches any
    known alias.

    SKILL.md: "Do not make AMBA the primary protocol merely because another
    DUT uses an AXI/APB backend." -- implemented by dropping 'amba' from the
    candidate set whenever at least one OTHER protocol also matched in the
    same field; 'amba' only wins when it is the ONLY protocol recognized in
    that field's text."""
    hits: List[Tuple[int, str, str]] = []  # (start_pos, canonical, matched_text)
    for pattern, canon in _ALIAS_PATTERNS:
        m = pattern.search(text)
        if m:
            hits.append((m.start(), canon, m.group(0)))
    if not hits:
        return None
    canons_present = {c for _, c, _ in hits}
    if "amba" in canons_present and len(canons_present) > 1:
        hits = [h for h in hits if h[1] != "amba"]
    hits.sort(key=lambda h: h[0])
    _, canon, matched = hits[0]
    return canon, matched


def resolve_protocol(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Resolves the primary DV protocol/profile route from structured
    evidence, applying protocol-router/SKILL.md's real normalization rules
    and tie-break order (module docstring above has the full scope ruling).
    `evidence` may supply any subset of FIELD_ORDER's keys -- an absent/
    empty/None field is simply skipped, never treated as an error.

    Two structurally different evidence dicts (e.g. one whose protocol_hint
    mentions USB, one whose mentions PCIe) are guaranteed to walk different
    branches here and land on a different PRIMARY_ROUTES entry -- this is
    what makes the routing genuinely input-driven, unlike the static
    per-Stage dict lookup RouteResolver.resolve() performs."""
    for field in FIELD_ORDER:
        raw = evidence.get(field)
        text = _field_text(raw)
        if not text.strip():
            continue
        found = _detect(text)
        if found is None:
            continue
        canon, matched_alias = found
        entry = PRIMARY_ROUTES[canon]
        return {
            "resolved": True,
            "protocol": canon,
            "display_name": entry["display"],
            "route": entry["route"],
            "matched_field": field,
            "matched_alias": matched_alias,
            "matched_value": raw,
            "further_resolution_required": FURTHER_RESOLUTION.get(canon),
            "evidence": (
                f"protocol_router.resolve_protocol matched alias "
                f"'{matched_alias}' -> protocol '{canon}' in evidence field "
                f"'{field}' (SKILL.md tie-break order: {', '.join(FIELD_ORDER)}); "
                f"raw field value: {raw!r}"
            ),
        }
    inspected = [f for f in FIELD_ORDER if _field_text(evidence.get(f)).strip()]
    return {
        "resolved": False,
        "protocol": None,
        "display_name": None,
        "route": None,
        "matched_field": None,
        "matched_alias": None,
        "matched_value": None,
        "further_resolution_required": None,
        "reason": "UNRESOLVED_NEEDS_ROUTING_QUESTION",
        "evidence": (
            "protocol_router.resolve_protocol found no recognized protocol "
            f"alias in any populated evidence field ({inspected or 'none populated'}); "
            "SKILL.md: 'If unresolved after evidence inspection, ask one "
            "routing question only.'"
        ),
    }
