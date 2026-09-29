"""Tests for dv_harness/connectivity.py -- bind-location / VIP-connectivity /
checker-scoreboard planning system (2026-09-03, "mcp-bind-connectivity"
workstream, Part C of the user's env.manifest.json spec).

Covers: the 4-tier bind classifier (all 4 tiers, plus a genuine
T3-must-never-auto-accept regression test), the count-check equations (a
passing case and a deliberately-broken case per interface), the per-row
lock/diff mechanism, the checker/scoreboard planning-table generator's
ORDERING/LEGAL-DROP-never-auto-filled guarantee, the 3 machine gates
(synthetic fixtures + a live-environment honesty check for Gate 1), the
existing-bind grep/parse, the interface-fingerprint protocol matcher, and
the topology/config_db-trace parsers against documented-shape synthetic
fixtures.
"""
from __future__ import annotations

import inspect
import json

import pytest

from dv_harness import connectivity as conn


# ===========================================================================
# 4-tier confidence classifier
# ===========================================================================

def test_tier1_already_decided_from_existing_bind():
    r = conn.classify_bind_tier(existing_bind={"target": "chip.core.usb0"})
    assert r.tier == conn.BindTier.T1_ALREADY_DECIDED
    assert r.auto_acceptable is True
    assert r.requires_human_confirmation is False
    assert r.requires_question_queue_entry is False


def test_tier2_structural_match_auto_acceptable_but_listed():
    match = conn.match_protocol_fingerprint(
        {"AWVALID", "AWREADY", "WLAST", "BRESP", "SOMETHING_ELSE"}, "AXI")
    assert match["matched"] is True
    r = conn.classify_bind_tier(structural_match=match)
    assert r.tier == conn.BindTier.T2_STRUCTURAL_MATCH
    assert r.auto_acceptable is True
    assert r.requires_human_confirmation is False
    # "still LISTED in the report for visibility" -- rationale must name the protocol.
    assert "AXI" in r.rationale


def test_tier3_naming_heuristic_always_requires_human_confirmation():
    r = conn.classify_bind_tier(naming_match="u_usb3_top")
    assert r.tier == conn.BindTier.T3_NAMING_HEURISTIC
    assert r.auto_acceptable is False
    assert r.requires_human_confirmation is True
    assert r.requires_question_queue_entry is False


def test_tier3_never_auto_accepted_even_with_partial_structural_hint():
    """Regression guard: a naming match alone (no FULL structural fingerprint
    match) must classify as T3 and never be nudged to auto-acceptable, even
    when some -- not all -- required structural signals happen to be present."""
    partial = conn.match_protocol_fingerprint({"AWVALID"}, "AXI")  # missing AWREADY/WLAST/BRESP
    assert partial["matched"] is False
    r = conn.classify_bind_tier(naming_match="u_axi_bridge", structural_match=partial)
    assert r.tier == conn.BindTier.T3_NAMING_HEURISTIC
    assert r.auto_acceptable is False
    assert r.requires_human_confirmation is True
    conn.assert_t3_never_auto_accepted(r)  # must not raise


def test_assert_t3_never_auto_accepted_catches_a_corrupted_result():
    bad = conn.BindTierResult(
        tier=conn.BindTier.T3_NAMING_HEURISTIC, rationale="x",
        auto_acceptable=True, requires_human_confirmation=False,
        requires_question_queue_entry=False,
    )
    with pytest.raises(conn.BindTierError) as exc:
        conn.assert_t3_never_auto_accepted(bad)
    assert exc.value.reason == "T3_MUST_NEVER_AUTO_ACCEPT"


def test_tier4_undecidable_routes_to_question_queue():
    r = conn.classify_bind_tier()
    assert r.tier == conn.BindTier.T4_UNDECIDABLE
    assert r.auto_acceptable is False
    assert r.requires_human_confirmation is False
    assert r.requires_question_queue_entry is True


def test_tier_priority_t1_outranks_everything_else():
    match = conn.match_protocol_fingerprint({"AWVALID", "AWREADY", "WLAST", "BRESP"}, "AXI")
    r = conn.classify_bind_tier(existing_bind={"target": "chip.core.axi0"},
                                 structural_match=match, naming_match="u_axi_bridge")
    assert r.tier == conn.BindTier.T1_ALREADY_DECIDED


# ===========================================================================
# Interface fingerprints (extends verible_parser, real port extraction)
# ===========================================================================

def test_build_interface_fingerprints_from_verible_module_info():
    mod = conn.verible_parser.ModuleInfo(
        name="axi_slave_wrap",
        ports=[
            conn.verible_parser.PortInfo(name="awvalid", direction="input", data_type="logic"),
            conn.verible_parser.PortInfo(name="awready", direction="output", data_type="logic"),
            conn.verible_parser.PortInfo(name="wlast", direction="input", data_type="logic"),
            conn.verible_parser.PortInfo(name="bresp", direction="output", data_type="logic [1:0]"),
        ],
    )
    fps = conn.build_interface_fingerprints([mod])
    assert fps["axi_slave_wrap"] == {"AWVALID", "AWREADY", "WLAST", "BRESP"}


def test_match_protocol_fingerprint_partial_never_rounds_up():
    result = conn.match_protocol_fingerprint({"AWVALID", "AWREADY"}, "AXI")
    assert result["matched"] is False
    assert result["missing_signals"] == ["BRESP", "WLAST"]


def test_match_protocol_fingerprint_unknown_protocol_is_honest():
    result = conn.match_protocol_fingerprint({"AWVALID"}, "NOT_A_REAL_PROTOCOL")
    assert result["matched"] is False
    assert result["reason"] == "UNKNOWN_PROTOCOL_FINGERPRINT"


# ===========================================================================
# AMBA-4: protocol classification from RTL evidence
#
# Synthetic fixtures only -- these build port-name sets in the shape
# verible_parser really produces for a fabric wrapper, so the classifier is
# exercised through its real inputs. Nothing here writes, emits, or plans a
# `bind` statement: AMBA-30/AMBA-31 keep implementation behind a human review
# gate, and this step is discovery machinery only.
# ===========================================================================

def _axi_mm_ports(prefix="s00_axi", *, burst=True, ids=True, wid=False,
                  coherency=False, lite=False, qos=False, omit=()):
    """Port names for one AXI memory-mapped interface, spelled the way a real
    fabric wrapper spells them (`s00_axi_awvalid`), so the classifier is
    tested against prefixed names rather than bare spec tokens."""
    sigs = ["awvalid", "awready", "awaddr", "wvalid", "wready", "wdata",
            "bvalid", "bready", "bresp", "arvalid", "arready", "araddr",
            "rvalid", "rready", "rdata", "rresp"]
    if burst:
        sigs += ["awlen", "awsize", "awburst", "arlen", "arsize", "arburst", "wlast", "rlast"]
    if ids:
        sigs += ["awid", "arid", "bid", "rid"]
    if wid:
        sigs += ["wid"]
    if coherency:
        sigs += ["awsnoop", "arsnoop", "awdomain", "ardomain", "awbar", "arbar"]
    if lite:
        sigs += ["awprot", "arprot", "wstrb"]
    if qos:
        sigs += ["awqos", "arqos", "awregion", "arregion"]
    return {f"{prefix}_{s}".upper() for s in sigs if s not in omit}


def _ahb_ports(prefix="m02_ahb", *, multi_master=False, mastlock=False, omit=()):
    sigs = ["haddr", "htrans", "hwrite", "hwdata", "hrdata", "hready",
            "hsize", "hburst", "hprot", "hresp"]
    if multi_master:
        sigs += ["hmaster", "hsplit", "hbusreq", "hgrant", "hlock"]
    if mastlock:
        sigs += ["hmastlock"]
    return {f"{prefix}_{s}".upper() for s in sigs if s not in omit}


def _apb_ports(prefix="m01_apb", *, apb3=False, apb4=False):
    sigs = ["paddr", "psel", "penable", "pwrite", "pwdata", "prdata"]
    if apb3 or apb4:
        sigs += ["pready", "pslverr"]
    if apb4:
        sigs += ["pstrb", "pprot"]
    return {f"{prefix}_{s}".upper() for s in sigs}


def _axis_ports(prefix="m_axis"):
    sigs = ["tvalid", "tready", "tdata", "tstrb", "tkeep", "tlast", "tid", "tdest", "tuser"]
    return {f"{prefix}_{s}".upper() for s in sigs}


def test_all_ten_amba4_classifications_have_a_real_fingerprint_and_display_name():
    """AMBA-3 mandates exactly these ten classifications."""
    assert set(conn.AMBA4_PROTOCOLS) == {
        "AHB", "AHB_LITE", "APB", "APB3", "APB4",
        "AXI3", "AXI4", "AXI4_LITE", "ACE_LITE", "AXI4_STREAM"}
    for proto in conn.AMBA4_PROTOCOLS:
        assert proto in conn.PROTOCOL_FINGERPRINTS, proto
        assert conn.PROTOCOL_FINGERPRINTS[proto], proto
        assert proto in conn.AMBA4_DISPLAY_NAMES, proto
    # The doc's own spellings, so a report never invents one.
    assert conn.AMBA4_DISPLAY_NAMES["AXI4_LITE"] == "AXI4-Lite"
    assert conn.AMBA4_DISPLAY_NAMES["ACE_LITE"] == "ACE-Lite"
    assert conn.AMBA4_DISPLAY_NAMES["AHB_LITE"] == "AHB-Lite"
    assert conn.AMBA4_DISPLAY_NAMES["AXI4_STREAM"] == "AXI4-Stream"


@pytest.mark.parametrize("proto", conn.AMBA4_PROTOCOLS)
def test_fingerprint_table_and_classifier_never_disagree(proto):
    """A port set that IS a table entry must classify to that same protocol.
    The table answers "does this fully exhibit X's signature", the classifier
    answers "which ONE protocol is this" -- they may not contradict."""
    ports = set(conn.PROTOCOL_FINGERPRINTS[proto])
    assert conn.match_protocol_fingerprint(ports, proto)["matched"] is True
    result = conn.classify_amba_protocol(ports)
    assert result.status == conn.AmbaClassificationStatus.RESOLVED.value, result.discriminators
    assert result.protocol == proto, result.discriminators


def test_axi4_is_not_misread_as_axi3_because_awid_contains_wid():
    """The core AMBA-4 discriminator, and the exact reason token matching
    replaced substring matching: `"WID" in "AWID"` is True."""
    axi4 = _axi_mm_ports("s00_axi")           # has AWID/ARID/BID/RID, no WID
    assert any("AWID" in p for p in axi4)
    result = conn.classify_amba_protocol(axi4)
    assert result.status == conn.AmbaClassificationStatus.RESOLVED.value
    assert result.protocol == "AXI4"
    # ...and a real AXI3 port list, which additionally carries WID, resolves to AXI3.
    axi3 = _axi_mm_ports("s00_axi", wid=True)
    assert conn.classify_amba_protocol(axi3).protocol == "AXI3"
    # The token set proves the mechanism, not just the verdict.
    assert "AWID" in conn.amba_signal_tokens(axi4)
    assert "WID" not in conn.amba_signal_tokens(axi4)
    assert "WID" in conn.amba_signal_tokens(axi3)


def test_hreadyout_does_not_satisfy_hready_under_token_matching():
    """"HREADY" is a substring of "HREADYOUT". An AHB slave port list that
    exposes only HREADYOUT is genuinely missing HREADY and must be reported
    incomplete, not silently completed by a substring hit."""
    ports = _ahb_ports(omit=("hready",)) | {"M02_AHB_HREADYOUT"}
    result = conn.classify_amba_protocol(ports)
    assert result.status == conn.AmbaClassificationStatus.UNRESOLVED_PARTIAL_EVIDENCE.value
    assert result.family == "AHB"
    assert "HREADY" in result.missing_signals


def test_ahb_lite_vs_full_ahb_uses_arbitration_signals_not_hmastlock():
    """AHB-Lite carries HMASTLOCK too, so HMASTLOCK must never promote an
    interface to full multi-master AHB."""
    lite = conn.classify_amba_protocol(_ahb_ports(mastlock=True))
    assert lite.status == conn.AmbaClassificationStatus.RESOLVED.value
    assert lite.protocol == "AHB_LITE", lite.discriminators
    full = conn.classify_amba_protocol(_ahb_ports(multi_master=True, mastlock=True))
    assert full.protocol == "AHB"
    assert "HMASTER" in full.evidence_signals


def test_apb_tiers_base_vs_apb3_vs_apb4():
    assert conn.classify_amba_protocol(_apb_ports()).protocol == "APB"
    assert conn.classify_amba_protocol(_apb_ports(apb3=True)).protocol == "APB3"
    assert conn.classify_amba_protocol(_apb_ports(apb4=True)).protocol == "APB4"
    # The corrected base-APB entry: it must no longer REQUIRE PREADY (APB3
    # evidence) and must include the address/data signals it used to omit.
    assert "PREADY" not in conn.PROTOCOL_FINGERPRINTS["APB"]
    assert {"PADDR", "PWDATA", "PRDATA"} <= conn.PROTOCOL_FINGERPRINTS["APB"]
    assert conn.match_protocol_fingerprint(_apb_ports(), "APB")["matched"] is True


def test_axi4_lite_is_never_reported_as_full_axi4():
    lite = conn.classify_amba_protocol(_axi_mm_ports("s01_axi", burst=False, ids=False, lite=True))
    assert lite.status == conn.AmbaClassificationStatus.RESOLVED.value
    assert lite.protocol == "AXI4_LITE"
    assert lite.display_name == "AXI4-Lite"


def test_ace_lite_reports_the_coherency_signals_it_found():
    ace = conn.classify_amba_protocol(_axi_mm_ports("s02_axi", coherency=True))
    assert ace.protocol == "ACE_LITE"
    assert {"ARSNOOP", "AWSNOOP", "ARDOMAIN", "AWDOMAIN"} <= set(ace.evidence_signals)


def test_axi4_stream_is_classified_separately_from_memory_mapped_axi():
    stream = conn.classify_amba_protocol(_axis_ports())
    assert stream.protocol == "AXI4_STREAM"
    assert stream.family == "AXI_STREAM"
    mm = conn.classify_amba_protocol(_axi_mm_ports())
    assert mm.family == "AXI_MM"
    assert stream.family != mm.family


# --- the unresolved / ambiguous half (never a happy-path-only tracer) ------

def test_bridge_module_spanning_two_families_is_ambiguous_not_guessed():
    """A real AHB-to-APB bridge's port list contains BOTH families in full.
    Answering with one protocol at module granularity would invent a fact."""
    bridge = _ahb_ports("ahb_s") | _apb_ports("apb_m", apb3=True)
    result = conn.classify_amba_protocol(bridge)
    assert result.status == conn.AmbaClassificationStatus.AMBIGUOUS_MULTIPLE_PROTOCOLS.value
    assert result.protocol == conn.AMBA_PROTOCOL_UNRESOLVED
    assert sorted(result.candidates) == ["AHB", "APB"]
    assert result.requires_human_confirmation is True


def test_ace_lite_coherency_plus_axi3_wid_is_contradictory_not_resolved():
    """ACE-Lite is defined on AXI4, which removed WID. Both cannot hold."""
    contradictory = _axi_mm_ports("s00_axi", coherency=True, wid=True)
    result = conn.classify_amba_protocol(contradictory)
    assert result.status == conn.AmbaClassificationStatus.AMBIGUOUS_CONTRADICTORY_EVIDENCE.value
    assert result.protocol == conn.AMBA_PROTOCOL_UNRESOLVED
    assert sorted(result.candidates) == ["ACE_LITE", "AXI3"]
    assert result.family == "AXI_MM"
    assert result.requires_human_confirmation is True


def test_axi4_only_qos_on_a_burstless_idless_interface_is_contradictory():
    weird = _axi_mm_ports("s00_axi", burst=False, ids=False, qos=True)
    result = conn.classify_amba_protocol(weird)
    assert result.status == conn.AmbaClassificationStatus.AMBIGUOUS_CONTRADICTORY_EVIDENCE.value
    assert sorted(result.candidates) == ["AXI4", "AXI4_LITE"]


def test_incomplete_interface_is_reported_with_its_missing_signals():
    """AMBA-3: "Do not silently omit partial/incomplete interfaces"."""
    no_read_channel = _axi_mm_ports("s00_axi", omit=("rvalid", "rready", "rdata", "rresp"))
    result = conn.classify_amba_protocol(no_read_channel)
    assert result.status == conn.AmbaClassificationStatus.UNRESOLVED_PARTIAL_EVIDENCE.value
    assert result.family == "AXI_MM"
    assert set(result.missing_signals) == {"RVALID", "RREADY", "RDATA", "RRESP"}
    assert result.requires_human_confirmation is True


def test_non_amba_ports_are_not_amba_and_an_interface_port_is_not_guessed():
    usb = {"CLK", "RESET_N", "DP", "DM", "VBUS"}
    assert conn.classify_amba_protocol(usb).status == \
        conn.AmbaClassificationStatus.NOT_AMBA.value
    # A SystemVerilog interface port (`AXI4 s_axi`) exposes no individual
    # signals. It must land in NOT_AMBA rather than be classified from the
    # interface TYPE name -- that is exactly what AMBA-4 forbids.
    iface_port = {"s_axi", "axi4_lite_if", "ace_lite_if"}
    result = conn.classify_amba_protocol(iface_port)
    assert result.status == conn.AmbaClassificationStatus.NOT_AMBA.value
    assert result.protocol == conn.AMBA_PROTOCOL_UNRESOLVED


def test_classification_cannot_consult_a_module_or_file_name_at_all():
    """AMBA-4: "Never classify protocol solely by filename, module name, or
    port prefix." Enforced structurally -- the function takes no name."""
    assert list(inspect.signature(conn.classify_amba_protocol).parameters) == ["port_names"]
    ports = _apb_ports("u_axi4_master_bridge", apb4=True)   # deliberately lying prefix
    result = conn.classify_amba_protocol(ports)
    assert result.protocol == "APB4"


# --- integration with the existing 4-tier bind classifier -----------------

def test_amba_structural_match_feeds_the_existing_tier_classifier():
    """Reuses classify_bind_tier() rather than introducing a second notion of
    "matched": RESOLVED -> T2; anything unresolved can never be auto-accepted."""
    resolved = conn.amba_structural_match(_axi_mm_ports("s00_axi"))
    assert resolved["matched"] is True
    assert resolved["protocol"] == "AXI4"
    t2 = conn.classify_bind_tier(structural_match=resolved)
    assert t2.tier == conn.BindTier.T2_STRUCTURAL_MATCH

    ambiguous = conn.amba_structural_match(_ahb_ports("ahb_s") | _apb_ports("apb_m", apb3=True))
    assert ambiguous["matched"] is False
    assert ambiguous["amba_classification"]["status"] == \
        conn.AmbaClassificationStatus.AMBIGUOUS_MULTIPLE_PROTOCOLS.value
    t3 = conn.classify_bind_tier(structural_match=ambiguous, naming_match="u_amba_bridge")
    assert t3.tier == conn.BindTier.T3_NAMING_HEURISTIC
    assert t3.auto_acceptable is False
    conn.assert_t3_never_auto_accepted(t3)
    t4 = conn.classify_bind_tier(structural_match=ambiguous)
    assert t4.tier == conn.BindTier.T4_UNDECIDABLE
    assert t4.requires_question_queue_entry is True


def test_legacy_non_amba4_fingerprints_keep_substring_matching_unchanged():
    """The pre-existing coarse "AXI"/"AXI_LITE" buckets and the illustrative
    non-AMBA sets must behave exactly as before this change."""
    legacy = conn.match_protocol_fingerprint({"AWVALID", "AWREADY", "WLAST", "BRESP"}, "AXI")
    assert legacy["matched"] is True
    assert legacy["match_method"] == "SUBSTRING"
    assert conn.PROTOCOL_FINGERPRINTS["AXI"] == {"AWVALID", "AWREADY", "WLAST", "BRESP"}
    assert conn.PROTOCOL_FINGERPRINTS["AXI_LITE"] == {"AWVALID", "AWREADY", "WVALID", "BVALID"}
    assert conn.match_protocol_fingerprint({"S_AXI_AWVALID"}, "AXI4")["match_method"] == "TOKEN"


# --- the synthetic multi-master / multi-slave fabric fixture ---------------

#: A 2-master / 4-slave AMBA4 fabric, one module per fabric-facing interface
#: (the shape a real interconnect wrapper generates), plus one whole-fabric
#: wrapper whose port list spans two families. Deliberately mixes protocols so
#: the AMBA-6 count is not a single-protocol degenerate case, and deliberately
#: includes one genuinely unresolvable port list.
_SYNTHETIC_FABRIC_INTERFACES = {
    # Fabric SLAVE interfaces (external MASTER endpoints drive them)
    "soc_fabric_s00_axi": _axi_mm_ports("s00_axi"),                                # CPU, AXI4
    "soc_fabric_s01_axi": _axi_mm_ports("s01_axi", wid=True),                      # legacy DMA, AXI3
    # Fabric MASTER interfaces (external SLAVE endpoints are driven)
    "soc_fabric_m00_axi": _axi_mm_ports("m00_axi", coherency=True),                # DDR, ACE-Lite
    "soc_fabric_m01_apb": _apb_ports("m01_apb", apb4=True),                        # periph, APB4
    "soc_fabric_m02_ahb": _ahb_ports("m02_ahb"),                                   # SRAM, AHB-Lite
    "soc_fabric_m03_axis": _axis_ports("m03_axis"),                                # video, AXI4-Stream
}


def _fabric_modules():
    """Builds the fixture through the REAL verible_parser dataclasses and the
    REAL build_interface_fingerprints(), so the classifier is exercised on the
    same objects a live parse produces -- not on hand-made port sets."""
    mods = []
    for name, ports in _SYNTHETIC_FABRIC_INTERFACES.items():
        mods.append(conn.verible_parser.ModuleInfo(
            name=name,
            ports=[conn.verible_parser.PortInfo(name=p.lower(), direction="input",
                                                data_type="logic")
                   for p in sorted(ports)],
        ))
    return mods


def test_synthetic_multi_master_multi_slave_fabric_classifies_every_interface():
    fps = conn.build_interface_fingerprints(_fabric_modules())
    assert set(fps) == set(_SYNTHETIC_FABRIC_INTERFACES)
    results = conn.classify_amba_interfaces(fps)
    resolved = {name: r.protocol for name, r in results.items()}
    assert resolved == {
        "soc_fabric_s00_axi": "AXI4",
        "soc_fabric_s01_axi": "AXI3",
        "soc_fabric_m00_axi": "ACE_LITE",
        "soc_fabric_m01_apb": "APB4",
        "soc_fabric_m02_ahb": "AHB_LITE",
        "soc_fabric_m03_axis": "AXI4_STREAM",
    }
    for name, r in results.items():
        assert r.status == conn.AmbaClassificationStatus.RESOLVED.value, (name, r.discriminators)
        assert r.requires_human_confirmation is False
        assert r.discriminators, name          # every verdict cites its own evidence
        assert r.evidence_signals, name


def test_synthetic_fabric_supports_an_amba6_shaped_per_protocol_count():
    """AMBA-6's mandatory summary counts per protocol. This proves the
    classification output is countable in that shape -- it does not build the
    table itself (AMBA-6 is a later step)."""
    results = conn.classify_amba_interfaces(
        conn.build_interface_fingerprints(_fabric_modules()))
    counts = {p: 0 for p in conn.AMBA4_PROTOCOLS}
    for r in results.values():
        if r.status == conn.AmbaClassificationStatus.RESOLVED.value:
            counts[r.protocol] += 1
    assert sum(counts.values()) == len(_SYNTHETIC_FABRIC_INTERFACES)
    assert counts["AXI4"] == 1 and counts["AXI3"] == 1 and counts["ACE_LITE"] == 1
    assert counts["APB4"] == 1 and counts["AHB_LITE"] == 1 and counts["AXI4_STREAM"] == 1
    assert counts["AXI4_LITE"] == 0 and counts["AHB"] == 0


def test_synthetic_fabric_with_an_unresolvable_wrapper_does_not_degrade_the_rest():
    """The whole-fabric wrapper module spans two families and cannot be
    classified as one protocol -- and that must not contaminate the six
    interfaces that ARE resolvable."""
    mods = _fabric_modules()
    mods.append(conn.verible_parser.ModuleInfo(
        name="soc_fabric_top",
        ports=[conn.verible_parser.PortInfo(name=p.lower(), direction="input", data_type="logic")
               for p in sorted(_ahb_ports("ahb_s") | _apb_ports("apb_m", apb3=True))],
    ))
    results = conn.classify_amba_interfaces(conn.build_interface_fingerprints(mods))
    top = results["soc_fabric_top"]
    assert top.status == conn.AmbaClassificationStatus.AMBIGUOUS_MULTIPLE_PROTOCOLS.value
    assert top.requires_human_confirmation is True
    still_resolved = [n for n, r in results.items()
                      if r.status == conn.AmbaClassificationStatus.RESOLVED.value]
    assert sorted(still_resolved) == sorted(_SYNTHETIC_FABRIC_INTERFACES)


def test_classification_is_json_serializable_for_a_downstream_topology_artifact():
    r = conn.classify_amba_protocol(_axi_mm_ports("s00_axi"))
    blob = json.loads(json.dumps(r.to_dict()))
    assert blob["protocol"] == "AXI4"
    assert blob["display_name"] == "AXI4"
    assert blob["status"] == "RESOLVED"
    assert blob["family"] == "AXI_MM"
    assert blob["requires_human_confirmation"] is False


# ===========================================================================
# AMBA-5: master/slave terminology -- BOTH perspectives required
# AMBA-6: count all interfaces before endpoint tracing
#
# Same synthetic-fixture discipline as the AMBA-4 block above: nothing here
# writes, emits or plans a `bind` statement, and one test asserts that of the
# emitted artifact directly (AMBA-30/AMBA-31).
# ===========================================================================

#: The signals a transaction INITIATOR drives, spelled out literally here
#: rather than imported from `connectivity.AMBA_INITIATOR_DRIVEN_REQUEST_SIGNALS`
#: -- building the fixture from the constant under test would make
#: `resolve_fabric_request_direction()` agree with itself by construction.
_INITIATOR_DRIVEN_SUFFIXES = {
    # AXI memory-mapped, master -> slave
    "AWVALID", "AWADDR", "AWLEN", "AWSIZE", "AWBURST", "AWID", "AWQOS", "AWREGION",
    "AWSNOOP", "AWDOMAIN", "AWBAR", "AWPROT",
    "WVALID", "WDATA", "WLAST", "WSTRB", "WID",
    "ARVALID", "ARADDR", "ARLEN", "ARSIZE", "ARBURST", "ARID", "ARQOS", "ARREGION",
    "ARSNOOP", "ARDOMAIN", "ARBAR", "ARPROT",
    "BREADY", "RREADY",
    # AHB, master -> slave (HSEL travels with the request, from the decoder)
    "HADDR", "HTRANS", "HWRITE", "HWDATA", "HSIZE", "HBURST", "HPROT", "HSEL",
    "HMASTLOCK", "HMASTER", "HBUSREQ", "HLOCK",
    # APB, master -> slave
    "PADDR", "PSEL", "PENABLE", "PWRITE", "PWDATA", "PSTRB", "PPROT",
    # AXI4-Stream, source -> sink
    "TVALID", "TDATA", "TSTRB", "TKEEP", "TLAST", "TID", "TDEST", "TUSER",
}


def _fabric_signal_directions(ports, *, fabric_side_role):
    """Real per-port directions for one fabric interface, as seen AT THE FABRIC.

    A fabric SLAVE interface RECEIVES the request signals (an external master
    drives them in); a fabric MASTER interface DRIVES them out. Response
    signals go the other way. This is the shape `verible_parser` produces for a
    real interconnect wrapper's port list."""
    request = "input" if fabric_side_role == conn.FABRIC_SIDE_SLAVE_INTERFACE else "output"
    response = "output" if request == "input" else "input"
    return {p: (request if p.upper().rsplit("_", 1)[-1] in _INITIATOR_DRIVEN_SUFFIXES
                else response)
            for p in sorted(ports)}


#: The AMBA-6 fixture: which side of the fabric each interface of
#: `_SYNTHETIC_FABRIC_INTERFACES` really sits on. Used ONLY to generate real
#: port directions -- every assertion below re-derives the role from those
#: directions, never from this table or from the interface name.
_SYNTHETIC_FABRIC_SIDES = {
    "soc_fabric_s00_axi": conn.FABRIC_SIDE_SLAVE_INTERFACE,
    "soc_fabric_s01_axi": conn.FABRIC_SIDE_SLAVE_INTERFACE,
    "soc_fabric_m00_axi": conn.FABRIC_SIDE_MASTER_INTERFACE,
    "soc_fabric_m01_apb": conn.FABRIC_SIDE_MASTER_INTERFACE,
    "soc_fabric_m02_ahb": conn.FABRIC_SIDE_MASTER_INTERFACE,
    "soc_fabric_m03_axis": conn.FABRIC_SIDE_MASTER_INTERFACE,
}


def _fabric_interface_specs():
    """`build_amba_fabric_inventory()` input for the clean 2-slave/4-master
    fabric: port names plus their real directions, nothing else."""
    return [{"interface": name,
             "dut_instance": "soc_fabric",
             "port_names": sorted(ports),
             "signal_directions": _fabric_signal_directions(
                 ports, fabric_side_role=_SYNTHETIC_FABRIC_SIDES[name])}
            for name, ports in _SYNTHETIC_FABRIC_INTERFACES.items()]


# --- AMBA-5 --------------------------------------------------------------

def test_amba5_reports_the_docs_own_two_worked_examples_verbatim():
    """"External CPU master drives fabric S00_AXI" and "Fabric M00_AXI drives
    DDR controller" -- the doc's own examples, with its own expected values."""
    cpu_facing = conn.determine_fabric_interface_roles("input", protocol="AXI4")
    assert cpu_facing.fabric_side_role == "SLAVE_INTERFACE"
    assert cpu_facing.external_endpoint_role == "MASTER_ENDPOINT"

    ddr_facing = conn.determine_fabric_interface_roles("output", protocol="AXI4")
    assert ddr_facing.fabric_side_role == "MASTER_INTERFACE"
    assert ddr_facing.external_endpoint_role == "SLAVE_ENDPOINT"


def test_amba5_never_renders_a_perspective_less_master_or_slave():
    """"Never output only 'Master' or 'Slave' without perspective." Every
    rendering carries both lines, and every legal value names its perspective."""
    for direction in ("input", "output"):
        rendered = conn.determine_fabric_interface_roles(direction).render_lines()
        assert "FABRIC_SIDE_ROLE = " in rendered
        assert "EXTERNAL_ENDPOINT_ROLE = " in rendered
    for value in conn.FABRIC_SIDE_ROLE_VALUES:
        assert value.endswith("_INTERFACE") or "UNRESOLVED" in value
    for value in conn.EXTERNAL_ENDPOINT_ROLE_VALUES:
        assert value.endswith("_ENDPOINT") or "UNRESOLVED" in value


def test_amba5_takes_no_interface_or_module_name_parameter():
    """The same structural prohibition `classify_amba_protocol()` carries: a
    role must come from direction evidence, never from a name."""
    params = list(inspect.signature(conn.determine_fabric_interface_roles).parameters)
    assert params == ["dut_port_direction", "protocol", "signal_directions"]


def test_amba5_delegates_to_determine_role_from_port_direction_not_a_second_decision():
    """The perspectives are a vocabulary layer over the existing function's
    verdict, so a matrix row built from them still passes role provenance."""
    roles = conn.determine_fabric_interface_roles("output", protocol="AXI4")
    assert roles.vip_role == conn.determine_role_from_port_direction("output")
    assert roles.vip_role.startswith(conn.LEGAL_ROLE_PREFIXES)


def test_amba5_axi4_stream_also_reports_source_sink():
    """"For AXI4-Stream also report SOURCE/SINK where appropriate" -- alongside
    the memory-mapped pair, never instead of it."""
    src = conn.determine_fabric_interface_roles("output", protocol="AXI4_STREAM")
    assert src.fabric_side_role == "MASTER_INTERFACE"
    assert src.stream_fabric_side_role == "SOURCE_INTERFACE"
    assert src.stream_external_endpoint_role == "SINK_ENDPOINT"
    sink = conn.determine_fabric_interface_roles("input", protocol="AXI4_STREAM")
    assert sink.stream_fabric_side_role == "SINK_INTERFACE"
    assert sink.stream_external_endpoint_role == "SOURCE_ENDPOINT"
    assert "FABRIC_SIDE_STREAM_ROLE = SINK_INTERFACE" in sink.render_lines()
    # A memory-mapped interface reports no stream pair at all.
    assert conn.determine_fabric_interface_roles(
        "input", protocol="AXI4").stream_fabric_side_role is None


def test_amba5_inout_alone_is_unresolved_never_guessed():
    roles = conn.determine_fabric_interface_roles("inout", protocol="AXI4")
    assert roles.fabric_side_role == conn.ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS
    assert roles.external_endpoint_role == conn.ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS
    assert roles.direction == conn.DIRECTION_UNRESOLVED
    assert roles.requires_human_confirmation is True
    assert roles.resolved is False


def test_amba5_inout_is_resolved_structurally_from_request_signal_directions():
    """AMBA-5's implied follow-up for the ambiguous case, done for real: the
    aggregate direction is inout, but the initiator-driven request signals
    all agree, so the perspective IS established from RTL evidence."""
    ports = _axi_mm_ports("s00_axi")
    dirs = _fabric_signal_directions(ports, fabric_side_role=conn.FABRIC_SIDE_SLAVE_INTERFACE)
    roles = conn.determine_fabric_interface_roles(
        "inout", protocol="AXI4", signal_directions=dirs)
    assert roles.resolved is True
    assert roles.fabric_side_role == "SLAVE_INTERFACE"
    assert roles.external_endpoint_role == "MASTER_ENDPOINT"
    assert roles.direction == "input"
    assert "structural analysis" in roles.direction_evidence


def test_amba5_contradictory_request_signal_directions_are_reported_not_averaged():
    ports = _axi_mm_ports("s00_axi")
    dirs = _fabric_signal_directions(ports, fabric_side_role=conn.FABRIC_SIDE_SLAVE_INTERFACE)
    dirs["S00_AXI_ARVALID"] = "output"           # one channel wired the other way
    result = conn.resolve_fabric_request_direction(dirs)
    assert result["status"] == conn.REQUEST_DIRECTION_CONTRADICTORY
    assert result["direction"] is None
    roles = conn.determine_fabric_interface_roles(
        "inout", protocol="AXI4", signal_directions=dirs)
    assert roles.resolved is False
    assert conn.REQUEST_DIRECTION_CONTRADICTORY in roles.unresolved_reason


def test_amba5_a_port_name_can_never_supply_the_direction():
    """A port whose NAME says "master" but which carries no AMBA request-signal
    token contributes nothing; the real request signals decide."""
    dirs = {"M99_AXI_MASTER_PORT_ENABLE": "output", "M99_AXI_IS_MASTER": "output"}
    dirs.update(_fabric_signal_directions(
        _axi_mm_ports("m99_axi"), fabric_side_role=conn.FABRIC_SIDE_SLAVE_INTERFACE))
    result = conn.resolve_fabric_request_direction(dirs)
    assert result["status"] == conn.REQUEST_DIRECTION_RESOLVED
    assert result["direction"] == "input"
    assert "M99_AXI_MASTER_PORT_ENABLE" not in result["evidence"]
    roles = conn.determine_fabric_interface_roles(signal_directions=dirs, protocol="AXI4")
    assert roles.fabric_side_role == "SLAVE_INTERFACE"


def test_amba5_no_request_signal_evidence_is_reported_not_defaulted():
    result = conn.resolve_fabric_request_direction({"CLK": "input", "RST_N": "input"})
    assert result["status"] == conn.REQUEST_DIRECTION_NO_EVIDENCE
    assert result["direction"] is None
    roles = conn.determine_fabric_interface_roles(signal_directions={"CLK": "input"})
    assert roles.resolved is False
    assert roles.vip_role is None


def test_amba5_rejects_an_unknown_direction_and_demands_some_evidence():
    with pytest.raises(conn.ConnectivityError):
        conn.resolve_fabric_request_direction({"S_AXI_AWVALID": "sideways"})
    with pytest.raises(conn.ConnectivityError):
        conn.determine_fabric_interface_roles("weird")
    with pytest.raises(conn.ConnectivityError):
        conn.determine_fabric_interface_roles()


# --- AMBA-6 --------------------------------------------------------------

def _clean_inventory():
    return conn.build_amba_fabric_inventory(_fabric_interface_specs())


def test_amba6_inventory_derives_protocol_and_both_perspectives_per_interface():
    inv = {i.interface: i for i in _clean_inventory()}
    assert inv["soc_fabric_s00_axi"].protocol == "AXI4"
    assert inv["soc_fabric_s00_axi"].fabric_side_role == "SLAVE_INTERFACE"
    assert inv["soc_fabric_s01_axi"].protocol == "AXI3"
    assert inv["soc_fabric_m00_axi"].protocol == "ACE_LITE"
    assert inv["soc_fabric_m00_axi"].fabric_side_role == "MASTER_INTERFACE"
    assert inv["soc_fabric_m01_apb"].display_name == "APB4"
    assert inv["soc_fabric_m02_ahb"].display_name == "AHB-Lite"
    stream = inv["soc_fabric_m03_axis"]
    assert stream.display_name == "AXI4-Stream"
    assert stream.roles.stream_fabric_side_role == "SOURCE_INTERFACE"
    assert "EXTERNAL_ENDPOINT_ROLE = SLAVE_ENDPOINT" in stream.render_amba5_block()
    assert json.loads(json.dumps(stream.to_dict()))["roles"]["fabric_side_role"] \
        == "MASTER_INTERFACE"


def test_amba6_count_table_over_the_clean_synthetic_fabric():
    table = conn.build_protocol_interface_count_table(_clean_inventory())
    by_proto = {r["protocol"]: r for r in table["rows"]}
    assert by_proto["AXI4"]["fabric_slave_interfaces"] == 1
    assert by_proto["AXI3"]["fabric_slave_interfaces"] == 1
    assert by_proto["ACE_LITE"]["fabric_master_interfaces"] == 1
    assert by_proto["APB4"]["fabric_master_interfaces"] == 1
    assert by_proto["AHB_LITE"]["fabric_master_interfaces"] == 1
    assert by_proto["AXI4_STREAM"]["fabric_master_interfaces"] == 1
    assert by_proto["AXI4_LITE"]["total"] == 0 and by_proto["AHB"]["total"] == 0
    assert table["total_fabric_slave_ports"] == 2
    assert table["total_fabric_master_ports"] == 4
    assert table["total_amba_ports"] == 6
    assert table["role_unresolved_interfaces"] == []
    assert table["unresolved_protocol_interfaces"] == []
    conn.assert_amba_interface_table_fully_resolved(table)


def test_amba6_table_always_carries_all_ten_rows_in_the_docs_order():
    """A protocol absent from a fabric is a fact the table states, not one the
    reader has to infer from a missing row."""
    empty = conn.build_protocol_interface_count_table([])
    assert [r["protocol"] for r in empty["rows"]] == list(conn.AMBA4_PROTOCOLS)
    assert [r["display_name"] for r in empty["rows"]][:3] == ["AHB", "AHB-Lite", "APB"]
    assert empty["total_amba_ports"] == 0


def test_amba6_renders_the_mandated_table_and_the_three_total_lines():
    rendered = conn.render_protocol_interface_count_table(
        conn.build_protocol_interface_count_table(_clean_inventory()))
    assert "| Protocol | Fabric Slave Interfaces | Fabric Master Interfaces | Total |" in rendered
    assert "| AXI4-Lite | 0 | 0 | 0 |" in rendered
    assert "| ACE-Lite | 0 | 1 | 1 |" in rendered
    assert "TOTAL FABRIC SLAVE PORTS: 2" in rendered
    assert "TOTAL FABRIC MASTER PORTS: 4" in rendered
    assert "TOTAL AMBA PORTS: 6" in rendered


# --- AMBA-6, the unresolved half ------------------------------------------

def _ambiguous_inventory():
    """The clean fabric plus two genuinely undecidable interfaces and one
    non-AMBA one -- the states an untested happy-path-only counter would drop."""
    specs = _fabric_interface_specs()
    bridge_ports = _ahb_ports("ahb_s") | _apb_ports("apb_m", apb3=True)
    specs.append({
        "interface": "soc_fabric_top", "dut_instance": "soc_fabric",
        "port_names": sorted(bridge_ports),
        "signal_directions": _fabric_signal_directions(
            bridge_ports, fabric_side_role=conn.FABRIC_SIDE_SLAVE_INTERFACE)})
    inout_ports = _apb_ports("s02_apb", apb3=True)
    specs.append({
        "interface": "soc_fabric_s02_apb", "dut_instance": "soc_fabric",
        "port_names": sorted(inout_ports), "dut_port_direction": "inout"})
    specs.append({
        "interface": "soc_fabric_usb_sideband", "dut_instance": "soc_fabric",
        "port_names": ["DP", "DM", "VBUS"], "dut_port_direction": "input"})
    return conn.build_amba_fabric_inventory(specs)


def test_amba6_unresolved_protocol_gets_its_own_row_and_is_never_dropped():
    """AMBA-3's "do not silently omit partial/incomplete interfaces" applied to
    the count table: an AHB-to-APB bridge port list spans two families and
    cannot be one protocol, but it is still an AMBA port. Its ROLE is
    resolvable from its port directions even though its protocol is not -- the
    two are independent properties and are reported independently."""
    table = conn.build_protocol_interface_count_table(_ambiguous_inventory())
    rows = {r["protocol"]: r for r in table["rows"]}
    assert conn.AMBA_PROTOCOL_UNRESOLVED in rows
    assert rows[conn.AMBA_PROTOCOL_UNRESOLVED]["total"] == 1
    assert rows[conn.AMBA_PROTOCOL_UNRESOLVED]["fabric_slave_interfaces"] == 1
    assert table["unresolved_protocol_interfaces"] == ["soc_fabric_top"]


def test_amba6_role_unresolved_port_is_in_the_total_but_in_neither_column():
    """The inout APB3 port is the mirror-image case: its PROTOCOL resolves
    cleanly, so it sits in the APB3 row, but its perspective does not, so it is
    counted in neither the slave nor the master column of that row."""
    table = conn.build_protocol_interface_count_table(_ambiguous_inventory())
    assert table["role_unresolved_interfaces"] == ["soc_fabric_s02_apb"]
    apb3_row = next(r for r in table["rows"] if r["protocol"] == "APB3")
    assert apb3_row["role_unresolved_interfaces"] == 1
    assert apb3_row["fabric_slave_interfaces"] == 0
    assert apb3_row["fabric_master_interfaces"] == 0
    assert apb3_row["total"] == 1
    # slave + master + role-unresolved == total, per row and in aggregate.
    for r in table["rows"]:
        assert (r["fabric_slave_interfaces"] + r["fabric_master_interfaces"]
                + r["role_unresolved_interfaces"]) == r["total"]
    assert table["total_amba_ports"] == 8            # 6 clean + bridge + inout APB
    assert table["total_fabric_slave_ports"] + table["total_fabric_master_ports"] == 7
    rendered = conn.render_protocol_interface_count_table(table)
    assert "ROLE-UNRESOLVED AMBA PORTS (1)" in rendered
    assert "soc_fabric_s02_apb" in rendered


def test_amba6_non_amba_interface_is_excluded_from_the_counts_but_named():
    table = conn.build_protocol_interface_count_table(_ambiguous_inventory())
    assert table["excluded_not_amba"] == ["soc_fabric_usb_sideband"]
    assert table["total_amba_ports"] == 8            # the USB sideband is not an AMBA port
    assert "EXCLUDED, NOT AMBA (1)" in conn.render_protocol_interface_count_table(table)


def test_amba6_fully_resolved_assertion_refuses_the_ambiguous_fabric():
    table = conn.build_protocol_interface_count_table(_ambiguous_inventory())
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.assert_amba_interface_table_fully_resolved(table)
    assert exc.value.reason == "AMBA_INTERFACE_TABLE_NOT_FULLY_RESOLVED"


# --- AMBA-6: the per-protocol generalization of the self-check identity ----

def test_amba6_per_protocol_identity_holds_when_every_protocol_reconciles():
    table = conn.build_protocol_interface_count_table(_clean_inventory())
    result = conn.verify_per_protocol_interface_count_identity(
        table, {"AXI4": 1, "AXI3": 1, "ACE_LITE": 1, "APB4": 1,
                "AHB_LITE": 1, "AXI4_STREAM": 1})
    assert result["identity_holds"] is True
    assert result["per_protocol"]["AXI4"] == {
        "interface_count": 1, "vip_instance_count": 1, "exemption_count": 0}
    assert result["total_amba_ports"] == 6
    assert set(result["per_protocol"]) == {
        "AXI4", "AXI3", "ACE_LITE", "APB4", "AHB_LITE", "AXI4_STREAM"}


def test_amba6_per_protocol_identity_catches_a_gap_the_aggregate_hides():
    """The whole reason this generalization exists. One uncovered AXI4 port and
    one spurious extra APB4 VIP cancel exactly, so the SCALAR identity the
    matrix already runs reports a clean reconciliation while both findings are
    real."""
    table = conn.build_protocol_interface_count_table(_clean_inventory())
    counts = {"AXI4": 0, "AXI3": 1, "ACE_LITE": 1, "APB4": 2,
              "AHB_LITE": 1, "AXI4_STREAM": 1}
    # The aggregate really does reconcile -- proving the blind spot is real,
    # not hypothetical.
    assert conn.verify_self_check_identity(
        table["total_amba_ports"], sum(counts.values()), []) is True
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.verify_per_protocol_interface_count_identity(table, counts)
    assert exc.value.reason == "SELF_CHECK_IDENTITY_MISMATCH"


def test_amba6_identity_accepts_a_reasoned_per_protocol_exemption():
    table = conn.build_protocol_interface_count_table(_clean_inventory())
    result = conn.verify_per_protocol_interface_count_identity(
        table, {"AXI4": 1, "AXI3": 1, "ACE_LITE": 1, "APB4": 1, "AHB_LITE": 1},
        [{"interface": "soc_fabric_m03_axis", "protocol": "AXI4_STREAM",
          "reason": "video stream monitored by the display subsystem's own scoreboard"}])
    assert result["per_protocol"]["AXI4_STREAM"]["exemption_count"] == 1
    assert result["total_exemptions"] == 1


def test_amba6_identity_refuses_an_unroutable_or_unexplained_exemption():
    table = conn.build_protocol_interface_count_table(_clean_inventory())
    counts = {"AXI4": 1, "AXI3": 1, "ACE_LITE": 1, "APB4": 1, "AHB_LITE": 1}
    with pytest.raises(conn.ConnectivitySelfCheckError) as no_proto:
        conn.verify_per_protocol_interface_count_identity(
            table, counts, [{"interface": "soc_fabric_m03_axis", "reason": "later"}])
    assert no_proto.value.reason == "EXEMPTION_PROTOCOL_UNROUTABLE"
    # The "every exemption carries a reason" rule is the scalar function's, and
    # is reached through it rather than re-implemented here.
    with pytest.raises(conn.ConnectivitySelfCheckError) as no_reason:
        conn.verify_per_protocol_interface_count_identity(
            table, counts, [{"interface": "soc_fabric_m03_axis",
                             "protocol": "AXI4_STREAM", "reason": ""}])
    assert no_reason.value.reason == "EXEMPTION_MISSING_EXPLANATION"
    with pytest.raises(conn.ConnectivitySelfCheckError) as bad_vip:
        conn.verify_per_protocol_interface_count_identity(table, {"NOT_A_PROTOCOL": 1})
    assert bad_vip.value.reason == "VIP_COUNT_FOR_UNKNOWN_PROTOCOL"


# --- AMBA-6 <-> connectivity matrix ---------------------------------------

def _amba_matrix_rows(inventory):
    """Planning rows for the discovered fabric. `from_amba_fabric_interface()`
    derives protocol/role from the discovery record -- nothing is typed in, and
    no bind statement is produced (`bind_target` is a planned target string a
    human reviews, per AMBA-30/AMBA-31)."""
    return [conn.ConnectivityRow.from_amba_fabric_interface(
        i, vip_type=f"svt_{i.protocol.lower()}_agent", count=1,
        active_passive="active", bind_target=f"soc_fabric.{i.interface}",
        tier=conn.BindTier.T3_NAMING_HEURISTIC.value) for i in inventory]


def test_matrix_row_from_an_amba_interface_carries_protocol_and_fabric_side_role():
    rows = _amba_matrix_rows(_clean_inventory())
    matrix = conn.build_connectivity_matrix(rows)
    assert "protocol" in conn.MATRIX_COLUMNS and "fabric_side_role" in conn.MATRIX_COLUMNS
    assert list(matrix[0].keys()) == conn.MATRIX_COLUMNS
    by_iface = {r["interface"]: r for r in matrix}
    assert by_iface["soc_fabric_s00_axi"]["protocol"] == "AXI4"
    assert by_iface["soc_fabric_s00_axi"]["fabric_side_role"] == "SLAVE_INTERFACE"
    assert by_iface["soc_fabric_m00_axi"]["fabric_side_role"] == "MASTER_INTERFACE"
    # The role column is still the derived VIP role, so provenance holds.
    conn.assert_role_provenance(rows)
    assert by_iface["soc_fabric_s00_axi"]["role"] == \
        conn.determine_role_from_port_direction("input")


def test_matrix_row_refuses_an_interface_whose_perspective_is_unresolved():
    unresolved = next(i for i in _ambiguous_inventory() if not i.roles.resolved)
    with pytest.raises(conn.ConnectivityError) as exc:
        conn.ConnectivityRow.from_amba_fabric_interface(
            unresolved, vip_type="svt_apb_agent", count=1, active_passive="active",
            bind_target="soc_fabric.s02_apb", tier=conn.BindTier.T4_UNDECIDABLE.value)
    assert exc.value.reason == "AMBA_INTERFACE_HAS_NO_ESTABLISHED_DIRECTION"


def test_a_row_never_classified_says_so_rather_than_looking_amba_unresolved():
    """`PROTOCOL_NOT_CLASSIFIED` ("never asked") must stay distinct from
    `AMBA_PROTOCOL_UNRESOLVED` ("asked, evidence did not settle it")."""
    row = conn.ConnectivityRow.from_dut_port(
        dut_instance="chip.core.usb0", interface="utmi", dut_port_direction="output",
        vip_type="svt_usb_agent", count=1, active_passive="active",
        bind_target="chip.core.usb0", tier="T2_STRUCTURAL_MATCH")
    assert row.protocol == conn.PROTOCOL_NOT_CLASSIFIED
    assert row.fabric_side_role == conn.FABRIC_SIDE_ROLE_NOT_CLASSIFIED
    assert conn.count_amba_ports_in_matrix([row]) == 0
    # A pre-schema-change dict row re-loaded from an older manifest reads the
    # same way rather than as a null.
    legacy = {c: "x" for c in conn.MATRIX_COLUMNS[:9]}
    assert conn.build_connectivity_matrix([legacy])[0]["protocol"] == \
        conn.PROTOCOL_NOT_CLASSIFIED


def test_amba6_table_and_matrix_port_counts_cannot_silently_disagree():
    inventory = _clean_inventory()
    rows = _amba_matrix_rows(inventory)
    table = conn.build_protocol_interface_count_table(inventory)
    assert conn.count_amba_ports_in_matrix(rows) == 6
    assert conn.cross_check_amba_table_against_matrix(table, rows)["counts_agree"] is True
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.cross_check_amba_table_against_matrix(table, rows[:-1])
    assert exc.value.reason == "AMBA_TABLE_AND_MATRIX_PORT_COUNTS_DISAGREE"
    assert exc.value.detail["gap"] == 1


def test_emit_connectivity_artifacts_writes_the_amba6_table_and_no_bind_statement(tmp_path):
    inventory = _clean_inventory()
    out = conn.emit_connectivity_artifacts(
        tmp_path / "artifacts", _amba_matrix_rows(inventory), amba_interfaces=inventory)
    written = out["amba_interface_counts"].read_text(encoding="utf-8")
    assert "TOTAL AMBA PORTS: 6" in written
    assert out["amba_interface_count_table"]["total_fabric_slave_ports"] == 2
    # HARD CONSTRAINT (AMBA-30/AMBA-31): discovery/planning artifacts only.
    for path in (out["amba_interface_counts"], out["matrix_table"],
                 out["hierarchy_diagram"], out["matrix_manifest"]):
        assert conn.parse_bind_line(path.read_text(encoding="utf-8")) is None
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not line.strip().startswith("bind ")


def test_emit_connectivity_artifacts_without_an_inventory_writes_no_amba_file(tmp_path):
    """Absence of the artifact means "no AMBA inventory was supplied", never
    "this fabric has no AMBA ports" -- so no empty file is left behind."""
    out = conn.emit_connectivity_artifacts(tmp_path / "artifacts", [_sample_row()])
    assert out["amba_interface_counts"] is None
    assert out["amba_interface_count_table"] is None
    assert not (tmp_path / "artifacts" /
                conn.ARTIFACT_FILENAMES["amba_interface_counts"]).exists()


# ===========================================================================
# Existing binds (grep/parse)
# ===========================================================================

def test_parse_bind_line_extracts_target_module_instance():
    parsed = conn.parse_bind_line("  bind chip.core.evt_ctrl dv_uvm_probe u_evt_probe (.a(a));")
    assert parsed == ("chip.core.evt_ctrl", "dv_uvm_probe", "u_evt_probe")


def test_parse_bind_line_rejects_non_bind_line():
    assert conn.parse_bind_line("  wire bind_flag = 1;") is None


def test_grep_existing_binds_real_filesystem_scan(tmp_path):
    bind_dir = tmp_path / "tb"
    bind_dir.mkdir()
    (bind_dir / "usb_bind.sv").write_text(
        "// header\n"
        "bind chip.core.usb0 dv_uvm_probe u_usb0_probe (.clk(clk), .rst_n(rst_n));\n"
        "  bind axi_slave_wrap dv_uvm_axi_probe u_axi_probe (.awvalid(awvalid));\n",
        encoding="utf-8",
    )
    binds = conn.grep_existing_binds(tmp_path)
    assert len(binds) == 2
    assert binds[0].target == "chip.core.usb0"
    assert binds[0].bound_module == "dv_uvm_probe"
    assert binds[0].line_no == 2
    assert binds[1].target == "axi_slave_wrap"  # bare module name -- Rule 1 territory


def test_grep_existing_binds_empty_dir_returns_empty_not_error(tmp_path):
    assert conn.grep_existing_binds(tmp_path / "does_not_exist") == []


def test_find_existing_bind_for_target_exact_path_match():
    binds = [conn.BindStatement(target="chip.core.usb0", bound_module="m", instance_name="u",
                                 source_file="f.sv", line_no=1, raw_line="x")]
    found = conn.find_existing_bind_for_target(binds, "chip.core.usb0")
    assert found is binds[0]
    assert conn.find_existing_bind_for_target(binds, "chip.core.usb1") is None


# ===========================================================================
# Topology dump / config_db trace parsers (documented-shape synthetic fixtures)
# ===========================================================================

TOPOLOGY_FIXTURE = """
Name                    Type                Size
------------------------------------------------------
uvm_test_top            usb3_test           -
  env                   usb3_env            -
    agent0              usb3_agent          -
      driver            usb3_driver         -
      monitor           usb3_monitor        -
------------------------------------------------------
"""


def test_parse_topology_dump_recovers_hierarchy_from_indent():
    components = conn.parse_topology_dump(TOPOLOGY_FIXTURE)
    paths = {c.path: c.type_name for c in components}
    assert paths["uvm_test_top"] == "usb3_test"
    assert paths["uvm_test_top.env"] == "usb3_env"
    assert paths["uvm_test_top.env.agent0"] == "usb3_agent"
    assert paths["uvm_test_top.env.agent0.driver"] == "usb3_driver"
    assert paths["uvm_test_top.env.agent0.monitor"] == "usb3_monitor"


CFGDB_TRACE_FIXTURE = """
UVM_INFO @ 0: reporter [CFGDB/SET] Configuration 'vif' (virtual interface) set in "uvm_test_top.env.agent0" via top
UVM_INFO @ 0: reporter [CFGDB/GET] Configuration 'vif' (virtual interface) get in "uvm_test_top.env.agent0" via driver
UVM_INFO @ 0: reporter [CFGDB/SET] Configuration 'orphan_vif' (virtual interface) set in "uvm_test_top.env.agent1" via top
"""


def test_parse_config_db_trace_and_find_set_with_no_get():
    events = conn.parse_config_db_trace(CFGDB_TRACE_FIXTURE)
    assert len(events) == 3
    orphaned = conn.find_set_with_no_get(events)
    assert len(orphaned) == 1
    assert orphaned[0].field == "orphan_vif"
    assert orphaned[0].context_path == "uvm_test_top.env.agent1"


def test_capture_vip_topology_honest_not_available_with_no_paths():
    result = conn.capture_vip_topology()
    assert result["status"] == "NOT_AVAILABLE"
    assert "detail" in result


def test_capture_vip_topology_real_when_paths_supplied(tmp_path):
    topo_path = tmp_path / "topology.log"
    topo_path.write_text(TOPOLOGY_FIXTURE, encoding="utf-8")
    cfg_path = tmp_path / "cfgdb.log"
    cfg_path.write_text(CFGDB_TRACE_FIXTURE, encoding="utf-8")
    result = conn.capture_vip_topology(str(topo_path), str(cfg_path))
    assert result["status"] == "REAL"
    assert len(result["components"]) == 5
    assert len(result["set_with_no_get"]) == 1


# ===========================================================================
# DUT instance tree (slang) -- honesty check + synthetic-fixture parser test
# ===========================================================================

def test_capture_dut_instance_tree_honest_not_available_in_this_environment():
    """This environment genuinely has no `slang` on PATH (confirmed live,
    2026-09-03) -- this is a real honesty check, not a mocked assumption."""
    result = conn.capture_dut_instance_tree()
    assert result["status"] == "NOT_AVAILABLE"
    assert "slang" in result["detail"]


SLANG_AST_FIXTURE = {
    "kind": "Instance", "name": "",
    "body": {"name": "chip_top", "members": [
        {"kind": "Instance", "name": "usb0",
         "body": {"name": "usb3_subsystem", "members": [
             {"kind": "Instance", "name": "phy",
              "body": {"name": "usb3_phy", "members": []}},
         ]}},
        {"kind": "Port", "name": "clk"},  # non-instance member, must be skipped
    ]},
}


def test_parse_slang_ast_json_against_documented_shape_fixture():
    tree = conn.parse_slang_ast_json(SLANG_AST_FIXTURE)
    assert tree.module_name == "chip_top"
    assert len(tree.children) == 1
    usb0 = tree.children[0]
    assert usb0.instance_name == "usb0"
    assert usb0.module_name == "usb3_subsystem"
    assert usb0.full_path == "usb0"
    assert usb0.children[0].full_path == "usb0.phy"
    assert usb0.children[0].module_name == "usb3_phy"


def test_capture_dut_instance_tree_real_from_ast_json_file(tmp_path):
    ast_path = tmp_path / "ast.json"
    ast_path.write_text(json.dumps(SLANG_AST_FIXTURE), encoding="utf-8")
    result = conn.capture_dut_instance_tree(str(ast_path))
    assert result["status"] == "REAL"
    assert result["tree"].module_name == "chip_top"


def test_capture_dut_instance_tree_not_available_names_both_capture_methods():
    """The NOT_AVAILABLE detail must document BOTH documented capture
    methods, not just slang -- a site with VCS but no slang has to be told
    the `scope -tree` route is genuinely usable, not a docstring promise."""
    result = conn.capture_dut_instance_tree()
    assert result["status"] == "NOT_AVAILABLE"
    assert "slang" in result["detail"]
    assert "scope -tree" in result["detail"]
    assert "scope_tree_path" in result["detail"]


# ===========================================================================
# DUT instance tree, capture method (b): `simv -ucli -do "scope -tree"`
# ===========================================================================

SCOPE_TREE_FIXTURE = """ucli% scope -tree
tb_top
  dut (chip_top)
    usb0 (usb3_subsystem)
      phy (usb3_phy)
    axi0 (axi_slave_wrap)
$unit
"""


def test_parse_scope_tree_dump_recovers_full_instance_paths():
    parsed = conn.parse_scope_tree_dump(SCOPE_TREE_FIXTURE)
    assert parsed.unparsed_lines == []
    paths = {n.full_path: n.module_name
             for r in parsed.roots for n in conn.flatten_instance_tree(r)}
    assert paths["tb_top"] is None            # no annotation -> honest unknown
    assert paths["tb_top.dut"] == "chip_top"
    assert paths["tb_top.dut.usb0"] == "usb3_subsystem"
    assert paths["tb_top.dut.usb0.phy"] == "usb3_phy"
    assert paths["tb_top.dut.axi0"] == "axi_slave_wrap"
    # `$unit` is a second root at indent 0, not a child of tb_top.
    assert [r.full_path for r in parsed.roots] == ["tb_top", "$unit"]
    assert parsed.parsed_node_count == 6


def test_parse_scope_tree_dump_accepts_brace_and_colon_annotation_forms():
    parsed = conn.parse_scope_tree_dump(
        "tb_top {tb_top_module}\n  dut : chip_top\n    usb0    usb3_subsystem\n")
    assert parsed.unparsed_lines == []
    nodes = {n.full_path: n.module_name for n in conn.flatten_instance_tree(parsed.roots[0])}
    assert nodes["tb_top"] == "tb_top_module"
    assert nodes["tb_top.dut"] == "chip_top"
    assert nodes["tb_top.dut.usb0"] == "usb3_subsystem"


def test_parse_scope_tree_dump_ascii_tree_glyph_indentation():
    """Some UCLI builds draw the tree with `|`/`+`/backtick glyphs -- those
    are indentation, and depth must still come from the name's start column."""
    parsed = conn.parse_scope_tree_dump(
        "tb_top\n"
        "|-- dut (chip_top)\n"
        "|   `-- usb0 (usb3_subsystem)\n"
    )
    assert parsed.unparsed_lines == []
    paths = [n.full_path for n in conn.flatten_instance_tree(parsed.roots[0])]
    assert paths == ["tb_top", "tb_top.dut", "tb_top.dut.usb0"]


def test_parse_scope_tree_dump_preserves_literal_generate_array_indices():
    """Bind-Location Rule 4 requires literal indices in a bind target -- the
    parser must carry `phy_array[0]`/`[1]` through verbatim, never collapse
    them to a wildcard or drop the index."""
    parsed = conn.parse_scope_tree_dump(
        "chip\n  phy_array[0] (usb3_phy)\n  phy_array[1] (usb3_phy)\n")
    paths = [n.full_path for n in conn.flatten_instance_tree(parsed.roots[0])]
    assert paths == ["chip", "chip.phy_array[0]", "chip.phy_array[1]"]


def test_parse_scope_tree_dump_escaped_identifier_keeps_its_depth():
    """A SystemVerilog escaped identifier starts with `\\`, which is also an
    ASCII tree-drawing glyph. It must be read as part of the NAME, not as
    one extra column of indentation (which would silently reparent it)."""
    parsed = conn.parse_scope_tree_dump("chip\n  \\u_phy[0] (usb3_phy)\n")
    child = parsed.roots[0].children[0]
    assert child.instance_name == "\\u_phy[0]"
    assert child.full_path == "chip.\\u_phy[0]"


def test_parse_scope_tree_dump_flat_absolute_path_listing_is_not_double_prefixed():
    parsed = conn.parse_scope_tree_dump(
        "tb_top.dut (chip_top)\ntb_top.dut.usb0 (usb3_subsystem)\n")
    assert [r.full_path for r in parsed.roots] == ["tb_top.dut", "tb_top.dut.usb0"]


def test_parse_scope_tree_dump_is_fail_closed_on_unrecognized_lines():
    """An unrecognized line must be REPORTED, never silently dropped: a
    dropped line is a silently-missing bind target."""
    parsed = conn.parse_scope_tree_dump(
        "tb_top\n  dut (chip_top)\nTop level modules:\n")
    assert parsed.parsed_node_count == 2
    assert len(parsed.unparsed_lines) == 1
    assert parsed.unparsed_lines[0] == (3, "Top level modules:")


def test_capture_dut_instance_tree_real_from_scope_tree_file(tmp_path):
    dump = tmp_path / "scope_tree.txt"
    dump.write_text(SCOPE_TREE_FIXTURE, encoding="utf-8")
    result = conn.capture_dut_instance_tree(scope_tree_path=str(dump))
    assert result["status"] == "REAL"
    assert result["source"] == "simv_ucli_scope_tree"
    assert result["instance_paths"] == [
        "tb_top", "tb_top.dut", "tb_top.dut.usb0", "tb_top.dut.usb0.phy",
        "tb_top.dut.axi0", "$unit",
    ]
    assert result["unparsed_lines"] == []


def test_capture_dut_instance_tree_scope_tree_partial_is_flagged_not_hidden(tmp_path):
    dump = tmp_path / "scope_tree.txt"
    dump.write_text("tb_top\n  dut (chip_top)\n?? weird vcs line ??\n", encoding="utf-8")
    result = conn.capture_dut_instance_tree(scope_tree_path=str(dump))
    assert result["status"] == "REAL_PARTIAL"
    assert result["parsed_node_count"] == 2
    assert len(result["unparsed_lines"]) == 1


def test_capture_dut_instance_tree_scope_tree_parse_failed_not_empty_real(tmp_path):
    """A capture whose format this parser does not understand must NOT come
    back as a confident REAL empty hierarchy."""
    dump = tmp_path / "scope_tree.txt"
    dump.write_text("?? 1 ??\n?? 2 ??\n", encoding="utf-8")
    result = conn.capture_dut_instance_tree(scope_tree_path=str(dump))
    assert result["status"] == "PARSE_FAILED"
    assert result["parsed_node_count"] == 0
    assert result["tree"] is None


def test_capture_dut_instance_tree_rejects_both_sources_at_once(tmp_path):
    ast_path = tmp_path / "ast.json"
    ast_path.write_text(json.dumps(SLANG_AST_FIXTURE), encoding="utf-8")
    dump = tmp_path / "scope_tree.txt"
    dump.write_text(SCOPE_TREE_FIXTURE, encoding="utf-8")
    with pytest.raises(conn.BindTierError) as exc:
        conn.capture_dut_instance_tree(str(ast_path), scope_tree_path=str(dump))
    assert exc.value.reason == "AMBIGUOUS_DUT_TREE_SOURCE"


def test_both_capture_methods_yield_the_same_interchangeable_path_list(tmp_path):
    """The point of implementing method (b): both methods must feed the SAME
    flat full-instance-path list downstream, so a site with only VCS gets the
    same Input 1 a site with only slang gets."""
    ast_path = tmp_path / "ast.json"
    ast_path.write_text(json.dumps(SLANG_AST_FIXTURE), encoding="utf-8")
    from_slang = conn.capture_dut_instance_tree(str(ast_path))
    slang_paths = [n.full_path for n in conn.flatten_instance_tree(from_slang["tree"])
                   if n.full_path]

    dump = tmp_path / "scope_tree.txt"
    dump.write_text("usb0 (usb3_subsystem)\n  phy (usb3_phy)\n", encoding="utf-8")
    from_scope = conn.capture_dut_instance_tree(scope_tree_path=str(dump))

    assert slang_paths == ["usb0", "usb0.phy"]
    assert from_scope["instance_paths"] == slang_paths


# ===========================================================================
# Count-check equations
# ===========================================================================

def test_vip_instance_count_matches_active_interfaces_passing_case():
    vips = [conn.VipInstanceRecord(vip_type="AXI", instance_path="a", active_passive="active"),
            conn.VipInstanceRecord(vip_type="AXI", instance_path="b", active_passive="active")]
    result = conn.check_vip_instance_count_matches_active_interfaces(vips, active_interface_count=2)
    assert result["ok"] is True
    assert result["delta"] == 0


def test_vip_instance_count_matches_active_interfaces_broken_case_passive_monitor_excluded():
    """A passive-monitor-only IP is 1 IP instance but 0 active interfaces --
    deliberately broken: 1 VIP instance vs. 0 active interfaces must NOT be
    reported as matching."""
    vips = [conn.VipInstanceRecord(vip_type="APB", instance_path="mon0", active_passive="passive")]
    result = conn.check_vip_instance_count_matches_active_interfaces(vips, active_interface_count=0)
    assert result["ok"] is False
    assert result["vip_instance_count"] == 1
    assert result["delta"] == 1


def test_determine_role_from_port_direction_output_means_dut_initiator():
    assert "slave_responder" in conn.determine_role_from_port_direction("output")


def test_determine_role_from_port_direction_input_means_dut_target():
    assert "master_initiator" in conn.determine_role_from_port_direction("input")


def test_determine_role_from_port_direction_inout_is_honest_not_guessed():
    assert "AMBIGUOUS" in conn.determine_role_from_port_direction("inout")


def test_determine_role_from_port_direction_never_takes_a_name_parameter():
    sig = inspect.signature(conn.determine_role_from_port_direction)
    assert list(sig.parameters) == ["dut_port_direction"]


def test_determine_role_from_port_direction_rejects_unknown_value():
    with pytest.raises(conn.ConnectivityError):
        conn.determine_role_from_port_direction("weird")


def test_compute_path_combination_count_full_mesh_default():
    result = conn.compute_path_combination_count(["m0", "m1"], ["s0", "s1", "s2"])
    assert result["total_path_combinations"] == 6
    assert result["per_master"]["m0"] == ["s0", "s1", "s2"]


def test_compute_path_combination_count_with_restricted_reachability():
    """A passive monitor on a shared fabric is NOT the same dimension as
    master count -- this checks the real path-combination sizing when
    reachability is restricted (not full mesh)."""
    reach = {"m0": {"s0", "s1"}, "m1": {"s2"}}
    result = conn.compute_path_combination_count(["m0", "m1"], ["s0", "s1", "s2"], reachability=reach)
    assert result["total_path_combinations"] == 3
    assert result["per_master"]["m1"] == ["s2"]


def test_verify_self_check_identity_passing_case():
    exemptions = [{"interface": "chip.dbg0", "reason": "debug-only port, intentionally unconnected to any VIP"}]
    assert conn.verify_self_check_identity(3, 2, exemptions) is True


def test_verify_self_check_identity_fails_loudly_on_mismatch():
    """Deliberately-broken case: 3 verified interfaces, 1 VIP instance, no
    exemptions -- must raise, not return False/print a warning."""
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.verify_self_check_identity(3, 1, [])
    assert exc.value.reason == "SELF_CHECK_IDENTITY_MISMATCH"
    assert exc.value.detail["gap"] == 2


def test_verify_self_check_identity_rejects_exemption_without_reason():
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.verify_self_check_identity(2, 1, [{"interface": "chip.dbg0"}])
    assert exc.value.reason == "EXEMPTION_MISSING_EXPLANATION"


# ===========================================================================
# Connectivity matrix
# ===========================================================================

def _sample_row(tier="T2_STRUCTURAL_MATCH"):
    return conn.ConnectivityRow(
        dut_instance="chip.core.usb0", interface="usb3_if", direction="output",
        role="vip_role=slave_responder", vip_type="USB3", count=1,
        active_passive="active", bind_target="chip.core.usb0", tier=tier,
    )


def test_build_connectivity_matrix_fixed_columns():
    rows = [_sample_row()]
    matrix = conn.build_connectivity_matrix(rows)
    assert list(matrix[0].keys()) == conn.MATRIX_COLUMNS


def test_render_matrix_table_contains_all_values():
    table = conn.render_matrix_table([_sample_row()])
    assert "chip.core.usb0" in table
    assert "USB3" in table
    assert "T2_STRUCTURAL_MATCH" in table


def test_render_matrix_table_empty_is_honest():
    assert conn.render_matrix_table([]) == "(empty connectivity matrix)"


def test_write_connectivity_manifest_round_trips(tmp_path):
    out_path = tmp_path / "manifest.json"
    conn.write_connectivity_manifest(out_path, [_sample_row()], metadata={"project": "test"})
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["columns"] == conn.MATRIX_COLUMNS
    assert loaded["rows"][0]["dut_instance"] == "chip.core.usb0"
    assert loaded["metadata"]["project"] == "test"


def test_render_hierarchy_diagram_is_valid_mermaid_flowchart():
    diagram = conn.render_hierarchy_diagram([_sample_row()])
    assert diagram.startswith("flowchart LR")
    assert "chip.core.usb0" in diagram
    assert "USB3" in diagram


# ===========================================================================
# 3 machine gates
# ===========================================================================

def test_detect_elaboration_tool_prefers_slang_over_vcs():
    which_fn = lambda name: "/usr/bin/slang" if name == "slang" else "/usr/bin/vcs"
    assert conn.detect_elaboration_tool(which_fn) == "slang"


def test_run_gate1_elaboration_check_honest_not_available_in_this_environment():
    """Real, live check against this actual machine: neither slang nor vcs
    is installed here (confirmed 2026-09-03)."""
    result = conn.run_gate1_elaboration_check(["dut.f"], "chip_top")
    assert result.status == conn.GateStatus.NOT_AVAILABLE
    assert "slang" in result.detail["instructions"]
    assert "vcs" in result.detail["instructions"]


def test_run_gate1_elaboration_check_pass_with_injected_tool(monkeypatch):
    which_fn = lambda name: "/usr/bin/slang" if name == "slang" else None

    class FakeProc:
        returncode = 0
        stdout = "{}"
        stderr = ""

    run_fn = lambda argv, **kw: FakeProc()
    result = conn.run_gate1_elaboration_check(["dut.f"], "chip_top", which_fn=which_fn, run_fn=run_fn)
    assert result.status == conn.GateStatus.PASS
    assert result.detail["tool"] == "slang"


def test_run_gate1_elaboration_check_fail_on_nonzero_exit():
    which_fn = lambda name: "/usr/bin/slang" if name == "slang" else None

    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "error: unknown module 'chip_top_wrong'"

    run_fn = lambda argv, **kw: FakeProc()
    result = conn.run_gate1_elaboration_check(["dut.f"], "chip_top_wrong", which_fn=which_fn, run_fn=run_fn)
    assert result.status == conn.GateStatus.FAIL
    assert "chip_top_wrong" in result.detail["stderr"]


def test_evaluate_zero_time_connectivity_passing_fixture():
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "1"), (2, "0"), (3, "1")],
        "rst_n": [(0, "0"), (5, "1")],
        "data_valid": [(0, "0"), (6, "1")],
    })
    result = conn.evaluate_zero_time_connectivity(trace, "clk", "rst_n", ["data_valid"])
    assert result.status == conn.GateStatus.PASS
    assert result.detail["clock_toggles"] is True
    assert result.detail["reset_deasserts"] is True


def test_evaluate_zero_time_connectivity_flags_dead_clock():
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "0"), (2, "0")],  # never toggles -- silent/dead interface
        "rst_n": [(0, "0"), (5, "1")],
        "data_valid": [(0, "0")],
    })
    result = conn.evaluate_zero_time_connectivity(trace, "clk", "rst_n", ["data_valid"])
    assert result.status == conn.GateStatus.FAIL
    assert result.detail["clock_toggles"] is False


def test_evaluate_zero_time_connectivity_flags_x_at_time_zero():
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "1")],
        "rst_n": [(0, "0"), (5, "1")],
        "addr": [(0, "xxxx")],  # X at time zero specifically
    })
    result = conn.evaluate_zero_time_connectivity(trace, "clk", "rst_n", ["addr"])
    assert result.status == conn.GateStatus.FAIL
    assert any("addr" in p for p in result.detail["nonx_at_t0_problems"])


def test_run_gate2_against_live_simv_honest_not_available():
    result = conn.run_gate2_against_live_simv()
    assert result.status == conn.GateStatus.NOT_AVAILABLE


def test_evaluate_transaction_activity_passing_fixture():
    result = conn.evaluate_transaction_activity({"env.agent0.monitor": 5, "env.agent1.monitor": 1})
    assert result.status == conn.GateStatus.PASS
    assert result.detail["silent_monitors"] == {}


def test_evaluate_transaction_activity_flags_silent_monitor():
    """The specific case Part C calls out: a path that's syntactically legal
    and structurally wired but connected to the WRONG instance -- its
    monitor sees zero real transactions."""
    result = conn.evaluate_transaction_activity({"env.agent0.monitor": 5, "env.agent1.monitor": 0})
    assert result.status == conn.GateStatus.FAIL
    assert result.detail["silent_monitors"] == {"env.agent1.monitor": 0}


def test_run_gate3_against_live_simv_honest_not_available():
    result = conn.run_gate3_against_live_simv()
    assert result.status == conn.GateStatus.NOT_AVAILABLE


def test_run_machine_gates_pipeline_runs_all_three_in_order():
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "1")], "rst_n": [(0, "0"), (2, "1")], "addr": [(0, "0")],
    })
    report = conn.run_machine_gates(
        ["dut.f"], "chip_top", trace, required_nonx_signals=["addr"],
        monitor_transaction_counts={"mon0": 1},
    )
    assert report.gate1.gate == "gate1_elaboration"
    assert report.gate2.gate == "gate2_zero_time_connectivity"
    assert report.gate3.gate == "gate3_transaction_activity"
    # Gate1 NOT_AVAILABLE in this real environment; gate2/gate3 real PASS.
    assert report.gate1.status == conn.GateStatus.NOT_AVAILABLE
    assert report.gate2.status == conn.GateStatus.PASS
    assert report.gate3.status == conn.GateStatus.PASS
    assert report.ready_for_human_review() is True  # NOT_AVAILABLE alone does not block
    assert "gate1_elaboration" in report.not_available_gates()


def test_run_machine_gates_pipeline_blocks_on_a_real_fail():
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "0")],  # dead clock -> gate2 FAIL
        "rst_n": [(0, "0"), (2, "1")], "addr": [(0, "0")],
    })
    report = conn.run_machine_gates(["dut.f"], "chip_top", trace, required_nonx_signals=["addr"],
                                     monitor_transaction_counts={"mon0": 1})
    assert report.gate2.status == conn.GateStatus.FAIL
    assert report.ready_for_human_review() is False


def test_run_machine_gates_defaults_to_not_available_gates_without_live_evidence():
    """No signal_trace / no monitor_transaction_counts supplied -> gate2/
    gate3 must honestly report NOT_AVAILABLE, never a fabricated PASS."""
    report = conn.run_machine_gates(["dut.f"], "chip_top", signal_trace=None)
    assert report.gate2.status == conn.GateStatus.NOT_AVAILABLE
    assert report.gate3.status == conn.GateStatus.NOT_AVAILABLE


# ===========================================================================
# Gate-status PENDING/NOT_YET_RUN (2026-09-03, Gap #2 -- mandatory-gate-
# checkpoint workstream: the TCA-hang situation, where no pattern has
# completed yet, must be trackable as PENDING, never conflated with FAIL,
# NOT_AVAILABLE, or silently omitted).
# ===========================================================================

def test_evaluate_transaction_activity_status_pending_when_no_pattern_completed():
    """The exact TCA-hang shape this workstream exists to make trackable:
    no pattern has reached a terminal PASS/FAIL yet -- Gate 3 must report
    PENDING, never FAIL (nothing has actually failed a check) and never
    NOT_AVAILABLE (this is not a tooling gap)."""
    result = conn.evaluate_transaction_activity_status(pattern_completed=False)
    assert result.status == conn.GateStatus.PENDING
    assert result.status != conn.GateStatus.FAIL
    assert result.status != conn.GateStatus.NOT_AVAILABLE
    assert "pattern" in result.detail["reason"]


def test_evaluate_transaction_activity_status_pending_ignores_stray_counts():
    """pattern_completed is the real evidence this function trusts -- a
    caller accidentally passing a (stale/irrelevant) counts dict alongside
    pattern_completed=False must not flip the result to PASS/FAIL."""
    result = conn.evaluate_transaction_activity_status(
        pattern_completed=False, monitor_transaction_counts={"mon0": 5})
    assert result.status == conn.GateStatus.PENDING


def test_evaluate_transaction_activity_status_delegates_to_real_verdict_once_completed():
    passing = conn.evaluate_transaction_activity_status(
        pattern_completed=True, monitor_transaction_counts={"mon0": 3})
    assert passing.status == conn.GateStatus.PASS

    failing = conn.evaluate_transaction_activity_status(
        pattern_completed=True, monitor_transaction_counts={"mon0": 0})
    assert failing.status == conn.GateStatus.FAIL


def test_evaluate_transaction_activity_status_not_available_when_completed_but_no_counts():
    """Pattern finished, but no tooling path exists to source counts from --
    a genuine capability gap, distinct from PENDING."""
    result = conn.evaluate_transaction_activity_status(pattern_completed=True)
    assert result.status == conn.GateStatus.NOT_AVAILABLE


def test_run_machine_gates_reports_gate3_pending_when_pattern_completed_is_false():
    report = conn.run_machine_gates(["dut.f"], "chip_top", signal_trace=None, pattern_completed=False)
    assert report.gate3.status == conn.GateStatus.PENDING
    assert "gate3_transaction_activity" in report.pending_gates()
    # PENDING must never block presenting for human review the way FAIL does.
    assert report.ready_for_human_review() is True


def test_gate_status_enum_has_all_four_required_distinct_values():
    """The explicit requirement: NOT_YET_RUN / PENDING / PASS / FAIL must all
    exist as genuinely distinct enum members, extending the SAME GateStatus
    every gate result already used (not a parallel status type)."""
    values = {s.value for s in conn.GateStatus}
    assert {"NOT_YET_RUN", "PENDING", "PASS", "FAIL", "NOT_AVAILABLE"} == values
    assert conn.GateStatus.PENDING != conn.GateStatus.FAIL
    assert conn.GateStatus.PENDING != conn.GateStatus.NOT_AVAILABLE
    assert conn.GateStatus.NOT_YET_RUN != conn.GateStatus.PENDING


# ===========================================================================
# Mandatory build-status checkpoint (2026-09-03, Gap #2): bind_verification_
# status_block() / render_bind_verification_status_markdown() /
# assert_bind_gates_checkpoint(). This is the code-level half of the
# mechanism; dv_harness_tests/test_bind_verification_lint.py covers the
# standalone report-artifact lint script that operates on the actual
# prose-driven build-status reports IP_UVM_DV_Gen.md's agent produces.
# ===========================================================================

def test_bind_verification_status_block_all_not_yet_run_when_gate_report_is_none():
    """Before the checkpoint (no gate ever invoked): every key must
    explicitly report NOT_YET_RUN -- the block is never simply empty, which
    would be indistinguishable from "the report omitted this section"."""
    block = conn.bind_verification_status_block(None)
    assert block == {
        "gate1_elaboration": "NOT_YET_RUN",
        "gate2_zero_time_connectivity": "NOT_YET_RUN",
        "gate3_transaction_activity": "NOT_YET_RUN",
    }


def test_bind_verification_status_block_reflects_real_gate_report():
    report = conn.run_machine_gates(["dut.f"], "chip_top", signal_trace=None, pattern_completed=False)
    block = conn.bind_verification_status_block(report)
    assert block["gate1_elaboration"] == "NOT_AVAILABLE"  # no slang/vcs in this environment
    assert block["gate3_transaction_activity"] == "PENDING"


def test_render_bind_verification_status_markdown_contains_all_three_gate_lines():
    md = conn.render_bind_verification_status_markdown(None)
    assert "## Bind Verification Status" in md
    assert "Gate 1" in md and "NOT_YET_RUN" in md
    assert "Gate 2" in md
    assert "Gate 3" in md


def test_assert_bind_gates_checkpoint_noop_before_first_compile_succeeds():
    """The checkpoint only fires once first_compile_succeeded=True -- an
    in-progress, not-yet-compiled build is not itself a violation."""
    conn.assert_bind_gates_checkpoint(first_compile_succeeded=False, gate_report=None)  # must not raise


def test_assert_bind_gates_checkpoint_raises_when_gates_never_invoked_at_first_compile():
    """The exact confirmed gap: a build reaches first successful compile but
    the 3-gate standard was never applied -- this must raise, not pass
    silently."""
    with pytest.raises(conn.BindGateCheckpointError) as exc:
        conn.assert_bind_gates_checkpoint(first_compile_succeeded=True, gate_report=None)
    assert exc.value.reason == "GATES_NEVER_INVOKED_AT_FIRST_COMPILE_CHECKPOINT"


def test_assert_bind_gates_checkpoint_accepts_pending_gate3_at_first_compile():
    """Gate 3 PENDING (no pattern completed yet -- the TCA-hang shape) must
    be ACCEPTED at this checkpoint, as long as Gates 1/2 were genuinely
    invoked -- PENDING is an expected, not a violating, state here."""
    report = conn.run_machine_gates(["dut.f"], "chip_top", signal_trace=None, pattern_completed=False)
    conn.assert_bind_gates_checkpoint(first_compile_succeeded=True, gate_report=report)  # must not raise


def test_assert_bind_gates_checkpoint_accepts_any_real_gate1_gate2_status():
    """PASS, FAIL, and NOT_AVAILABLE all count as "genuinely invoked" for
    Gates 1/2 -- only NOT_YET_RUN is the violation this checkpoint guards
    against."""
    trace = conn.SignalTrace(samples={
        "clk": [(0, "0"), (1, "1")], "rst_n": [(0, "0"), (2, "1")], "addr": [(0, "0")],
    })
    report = conn.run_machine_gates(["dut.f"], "chip_top", trace, required_nonx_signals=["addr"],
                                     pattern_completed=False)
    assert report.gate1.status == conn.GateStatus.NOT_AVAILABLE  # real env: no slang/vcs
    assert report.gate2.status == conn.GateStatus.PASS
    conn.assert_bind_gates_checkpoint(first_compile_succeeded=True, gate_report=report)  # must not raise


# ===========================================================================
# Simulated IP_UVM_DV_Gen-style build reaching "first successful compile"
# (2026-09-03, Gap #2 -- the concrete fault-injection proof requested for
# this gap closure: a build that skips running Gates 1/2 must be caught).
# ===========================================================================

def test_simulated_build_workflow_blocked_from_proceeding_when_gates_skipped():
    """Models the exact real incident: an IP_UVM_DV_Gen-style build reaches
    first successful compile/elaboration, then tries to move on to the next
    documented step (Step 10's static self-check / Step 11's deliverables)
    WITHOUT having run Gates 1/2 first. The checkpoint must block this."""
    class FakeBuildWorkflow:
        def __init__(self):
            self.first_compile_succeeded = False
            self.gate_report = None
            self.advanced_past_checkpoint = False

        def compile_succeeds(self):
            self.first_compile_succeeded = True
            # NOTE: deliberately does NOT run Gates 1/2 here -- the real
            # confirmed defect this test reproduces.

        def try_advance_to_next_step(self):
            conn.assert_bind_gates_checkpoint(self.first_compile_succeeded, self.gate_report)
            self.advanced_past_checkpoint = True

    wf = FakeBuildWorkflow()
    wf.compile_succeeds()
    with pytest.raises(conn.BindGateCheckpointError):
        wf.try_advance_to_next_step()
    assert wf.advanced_past_checkpoint is False


def test_simulated_build_workflow_proceeds_once_gates_1_and_2_actually_run():
    """Same simulated workflow, this time genuinely running Gates 1/2 (Gate 3
    legitimately still PENDING -- no pattern has completed) before advancing
    -- the checkpoint must let this through."""
    class FakeBuildWorkflow:
        def __init__(self):
            self.first_compile_succeeded = False
            self.gate_report = None
            self.advanced_past_checkpoint = False

        def compile_succeeds(self):
            self.first_compile_succeeded = True

        def run_gates_1_and_2_as_required_checkpoint(self):
            self.gate_report = conn.run_machine_gates(
                ["dut.f"], "chip_top", signal_trace=None, pattern_completed=False)

        def try_advance_to_next_step(self):
            conn.assert_bind_gates_checkpoint(self.first_compile_succeeded, self.gate_report)
            self.advanced_past_checkpoint = True

    wf = FakeBuildWorkflow()
    wf.compile_succeeds()
    wf.run_gates_1_and_2_as_required_checkpoint()
    wf.try_advance_to_next_step()  # must not raise
    assert wf.advanced_past_checkpoint is True
    assert wf.gate_report.gate3.status == conn.GateStatus.PENDING  # still explicit, never omitted


# ===========================================================================
# Per-row lock/diff mechanism
# ===========================================================================

def test_row_lock_confirm_then_no_op_regeneration_needs_zero_reconfirmation(tmp_path):
    store = conn.RowLockStore(tmp_path / "locks.json")
    row = _sample_row()
    store.confirm_row(row.row_id(), row.to_dict(),
                      confirmed_by="dv-lead@example.com", evidence="rtl/usb_top.sv:214 port list")

    # regenerate with NO change
    regenerated = [_sample_row()]
    needing = store.diff_rows_needing_reconfirmation(regenerated, lambda r: r.row_id())
    assert needing == []


def test_row_lock_changed_row_is_flagged_for_reconfirmation_others_are_not(tmp_path):
    store = conn.RowLockStore(tmp_path / "locks.json")
    row_a = _sample_row()
    row_b = conn.ConnectivityRow(
        dut_instance="chip.core.axi0", interface="axi_if", direction="input",
        role="vip_role=master_initiator", vip_type="AXI", count=1,
        active_passive="active", bind_target="chip.core.axi0", tier="T1_ALREADY_DECIDED",
    )
    store.confirm_row(row_a.row_id(), row_a.to_dict(),
                      confirmed_by="dv-lead@example.com", evidence="rtl/usb_top.sv:214")
    store.confirm_row(row_b.row_id(), row_b.to_dict(),
                      confirmed_by="dv-lead@example.com", evidence="rtl/axi_top.sv:88")

    # regenerate: row_a changes tier (simulated RTL-driven reclassification), row_b unchanged
    row_a_changed = _sample_row(tier="T1_ALREADY_DECIDED")
    needing = store.diff_rows_needing_reconfirmation([row_a_changed, row_b], lambda r: r.row_id())
    assert len(needing) == 1
    assert needing[0].row_id() == row_a.row_id()


def test_row_lock_never_confirmed_row_needs_reconfirmation(tmp_path):
    store = conn.RowLockStore(tmp_path / "locks.json")
    needing = store.diff_rows_needing_reconfirmation([_sample_row()], lambda r: r.row_id())
    assert len(needing) == 1


def test_row_lock_persists_across_store_reload(tmp_path):
    path = tmp_path / "locks.json"
    row = _sample_row()
    store1 = conn.RowLockStore(path)
    store1.confirm_row(row.row_id(), row.to_dict(),
                       confirmed_by="dv-lead@example.com", evidence="rtl/usb_top.sv:214")

    store2 = conn.RowLockStore(path)  # fresh instance, same file
    assert store2.is_locked(row.row_id())
    needing = store2.diff_rows_needing_reconfirmation([_sample_row()], lambda r: r.row_id())
    assert needing == []


# ===========================================================================
# Checker/scoreboard planning-table generator
# ===========================================================================

def test_generate_protocol_check_entry_lists_disabled_with_reason():
    entry = conn.generate_protocol_check_entry(
        "chip.core.usb0::usb3_if", "USB3",
        builtin_checks=["protocol_state_check", "crc_check", "timeout_check"],
        disabled_checks={"timeout_check": "DUT intentionally holds bus past spec timeout during calibration; VIP timeout disabled for this test only"},
    )
    assert entry["kind"] == "protocol_check"
    assert "timeout_check" not in entry["enabled_builtin_checks"]
    assert entry["disabled_builtin_checks"][0]["check"] == "timeout_check"
    assert entry["disabled_builtin_checks"][0]["reason"]


def test_generate_protocol_check_entry_rejects_disabled_check_without_reason():
    with pytest.raises(conn.ConnectivityError) as exc:
        conn.generate_protocol_check_entry(
            "row1", "AXI", builtin_checks=["addr_check"], disabled_checks={"addr_check": ""})
    assert exc.value.reason == "DISABLED_CHECK_MISSING_REASON"


def test_generate_protocol_check_entry_rejects_disabling_unknown_check():
    with pytest.raises(conn.ConnectivityError) as exc:
        conn.generate_protocol_check_entry(
            "row1", "AXI", builtin_checks=["addr_check"], disabled_checks={"not_a_real_check": "because"})
    assert exc.value.reason == "DISABLED_CHECK_NOT_IN_BUILTIN_LIST"


def test_generate_scoreboard_entry_ordering_and_legal_drop_default_to_required_human_input():
    """The core never-auto-filled guarantee: with no explicit ordering/
    legal_drop supplied, both fields must be exactly the REQUIRED_HUMAN_INPUT
    sentinel -- never a guessed value, never silently None with no signal."""
    entry = conn.generate_scoreboard_entry(
        "sb_usb0_axi0", endpoint_pairs=[("chip.core.usb0", "chip.core.axi0")],
        matching_key="transaction_id",
    )
    assert entry["ordering"] == conn.REQUIRED_HUMAN_INPUT
    assert entry["legal_drop_conditions"] == conn.REQUIRED_HUMAN_INPUT
    assert entry["reset_flush_behavior"] == conn.REQUIRED_HUMAN_INPUT
    assert entry["orphan_unmatched_threshold"] == conn.REQUIRED_HUMAN_INPUT
    assert entry["orphan_unmatched_timeout"] == conn.REQUIRED_HUMAN_INPUT


def test_generate_scoreboard_entry_accepts_explicit_human_supplied_values():
    entry = conn.generate_scoreboard_entry(
        "sb_usb0_axi0", endpoint_pairs=[("chip.core.usb0", "chip.core.axi0")],
        matching_key="transaction_id", ordering="in_order", legal_drop_conditions="none permitted",
    )
    assert entry["ordering"] == "in_order"
    assert entry["legal_drop_conditions"] == "none permitted"


def test_generate_scoreboard_entry_structural_fields_never_defaulted():
    """endpoint_pairs/matching_key are structural facts, not part of the
    never-auto-fill guarantee -- they are always required, real arguments."""
    with pytest.raises(TypeError):
        conn.generate_scoreboard_entry("sb0")  # missing required endpoint_pairs/matching_key


def test_generate_system_level_entry_basic_shape():
    entry = conn.generate_system_level_entry(
        "sys0", "performance_check", ["chip.core.usb0", "chip.core.ddr0"],
        "End-to-end USB3-to-DDR bandwidth check under sustained bulk transfer")
    assert entry["kind"] == "system_level"
    assert entry["system_level_kind"] == "performance_check"


def test_build_checker_scoreboard_plan_groups_by_kind():
    plan = conn.build_checker_scoreboard_plan(
        protocol_entries=[{"kind": "protocol_check"}],
        scoreboard_entries=[{"kind": "data_integrity_scoreboard"}],
        system_entries=[{"kind": "system_level"}],
    )
    assert len(plan["protocol_checks"]) == 1
    assert len(plan["data_integrity_scoreboards"]) == 1
    assert len(plan["system_level_checks"]) == 1


# ===========================================================================
# T4 question queue -- real delegation into dv_harness/question_queue.py
# (2026-09-03 review defect F6: this used to hand-build a dict that failed
# question_queue.validate_question() outright, with a caller-supplied q_id
# and a hardcoded blocking=True)
# ===========================================================================

_T4_OPTIONS = [
    {"label": "bind to phy0 (generate-loop index 0)"},
    {"label": "bind to phy1 (generate-loop index 1)"},
]


def _ask_t4(root, **overrides):
    kwargs = dict(
        domain="dut",
        question="Which DUT instance does the second USB3 PHY VIP bind to -- phy0 or phy1?",
        context_path="chip.core.usb_subsys.phy_array[*]",
        options=_T4_OPTIONS,
        recommendation="bind to phy0 (generate-loop index 0)",
        assumption_if_unanswered="assume phy0; re-run connectivity check once designer confirms",
    )
    kwargs.update(overrides)
    return conn.build_t4_question_queue_entry(root, **kwargs)


def test_build_t4_question_queue_entry_output_passes_real_validate_question(tmp_path):
    """The whole point of the F6 fix: the entry this produces is a record the
    REAL question queue accepted, not a look-alike dict."""
    from dv_harness import question_queue as qq

    entry = _ask_t4(tmp_path)
    qq.validate_question(entry)  # raises QuestionValidationError if it does not conform
    assert entry["owner"] == "designer"  # DUT-domain -> designer, via route_owner()


def test_build_t4_question_queue_entry_id_is_derived_not_caller_supplied(tmp_path):
    """No q_id parameter exists any more -- the id is derived from the
    question key, which is what keeps repeat-question-rate=0 provable."""
    from dv_harness import question_queue as qq

    assert "q_id" not in inspect.signature(conn.build_t4_question_queue_entry).parameters
    entry = _ask_t4(tmp_path)
    key = qq.make_question_key("dut", entry["question"], entry["context_path"])
    assert entry["id"] == qq.make_question_id("dut", key)
    # Asking the identical question again derives the identical id.
    assert _ask_t4(tmp_path)["id"] == entry["id"]


def test_build_t4_question_queue_entry_blocking_is_derived_from_tier_classification(tmp_path):
    """`blocking` used to be a hardcoded True default. It is now whatever the
    queue's own classify_tier() derives -- Tier 3 for a T4 bind question,
    because guessing a bind target is a real false-PASS risk."""
    entry = _ask_t4(tmp_path)
    assert entry["tier"] == 3
    assert entry["blocking"] is True
    assert entry["status"] == "OPEN"
    assert "affects_pass_fail_verdict" in entry["tier_reason"]


def test_build_t4_question_queue_entry_is_really_persisted_in_the_queue(tmp_path):
    from dv_harness import question_queue as qq

    entry = _ask_t4(tmp_path)
    store = qq.QuestionQueueStore(tmp_path)
    assert store.get_question(entry["id"]) == entry


def test_build_t4_question_queue_entry_accepts_a_prebuilt_store(tmp_path):
    from dv_harness import question_queue as qq

    store = qq.QuestionQueueStore(tmp_path)
    entry = _ask_t4(store)
    assert store.get_question(entry["id"]) is not None


def test_build_t4_question_queue_entry_routes_vip_domain_to_dv_owner_synopsys_ae(tmp_path):
    entry = _ask_t4(tmp_path, domain="vip")
    assert entry["owner"] == "DV-owner/Synopsys-AE"


def test_build_t4_question_queue_entry_rejects_open_ended_options(tmp_path):
    with pytest.raises(conn.ConnectivityError) as exc:
        _ask_t4(tmp_path, options=[{"label": "only_one_option"}],
                recommendation="only_one_option")
    assert exc.value.reason == "OPTIONS_MUST_BE_PRE_RESEARCHED_2_TO_3"


def test_build_t4_question_queue_entry_rejects_unknown_domain(tmp_path):
    with pytest.raises(conn.ConnectivityError) as exc:
        _ask_t4(tmp_path, domain="not_a_domain")
    assert exc.value.reason == "UNKNOWN_QUESTION_DOMAIN"


def test_build_t4_question_queue_entry_rejects_recommendation_outside_options(tmp_path):
    with pytest.raises(conn.ConnectivityError) as exc:
        _ask_t4(tmp_path, recommendation="bind to some third thing nobody listed")
    assert exc.value.reason == "RECOMMENDATION_MUST_BE_ONE_OF_OPTIONS"


def test_build_t4_question_queue_entry_accepts_plain_string_options(tmp_path):
    """Plain strings are normalized to the queue's {"label": ...} shape."""
    entry = _ask_t4(tmp_path, options=["bind to phy0", "bind to phy1"],
                    recommendation="bind to phy0")
    assert entry["options"] == [{"label": "bind to phy0"}, {"label": "bind to phy1"}]


# ===========================================================================
# Tier gate on the REAL bind-emission path (gap closure 2026-09-04):
# assert_t3_never_auto_accepted()'s docstring named a "downstream consumer"
# that did not exist -- these prove one now does, end to end.
# ===========================================================================

_BASE_ENTRY = {
    "target_instance": "chip.core.usb0",
    "ports": ["phy0_sram_init_done"],
    "reason": "declared at chip.core.usb0 per real RTL evidence",
}


def _entry(**over):
    e = dict(_BASE_ENTRY)
    e.update(over)
    return e


def test_enforce_bind_tier_policy_allows_t1_and_t2():
    decisions = conn.enforce_bind_tier_policy([
        _entry(tier="T1_ALREADY_DECIDED"), _entry(tier="T2_STRUCTURAL_MATCH"),
    ])
    assert [d["auto_emittable"] for d in decisions] == [True, True]


def test_enforce_bind_tier_policy_refuses_unconfirmed_t3():
    with pytest.raises(conn.BindTierError) as exc:
        conn.enforce_bind_tier_policy([_entry(tier="T3_NAMING_HEURISTIC")])
    assert exc.value.reason == "T3_BIND_REQUIRES_HUMAN_CONFIRMATION"


def test_enforce_bind_tier_policy_accepts_t3_with_real_human_confirmation():
    from dv_harness import question_queue
    decisions = conn.enforce_bind_tier_policy([_entry(
        tier="T3_NAMING_HEURISTIC",
        human_confirmation={"source": question_queue.HUMAN_DECISION_SOURCE,
                            "confirmed_by": "dv_owner",
                            "basis": "confirmed against RTL hierarchy dump"},
    )])
    assert decisions[0]["human_confirmed"] is True


def test_t3_confirmation_must_come_from_the_real_human_decision_source():
    """A harness-minted decision source must never satisfy a T3 confirmation
    -- reuses question_queue's own HUMAN_DECISION_SOURCE rule rather than a
    parallel notion of "confirmed"."""
    with pytest.raises(conn.BindTierError) as exc:
        conn.enforce_bind_tier_policy([_entry(
            tier="T3_NAMING_HEURISTIC",
            human_confirmation={"source": "tier2_auto_assumption",
                                "confirmed_by": "harness", "basis": "looked right"},
        )])
    assert exc.value.reason == "T3_BIND_REQUIRES_HUMAN_CONFIRMATION"


def test_t3_entry_hand_marked_auto_acceptable_is_caught_by_the_original_guard():
    with pytest.raises(conn.BindTierError) as exc:
        conn.enforce_bind_tier_policy([_entry(
            tier="T3_NAMING_HEURISTIC", auto_acceptable=True)])
    assert exc.value.reason == "T3_MUST_NEVER_AUTO_ACCEPT"


def test_enforce_bind_tier_policy_never_emits_t4():
    with pytest.raises(conn.BindTierError) as exc:
        conn.enforce_bind_tier_policy([_entry(tier="T4_UNDECIDABLE")])
    assert exc.value.reason == "T4_BIND_MUST_GO_TO_QUESTION_QUEUE"


def test_enforce_bind_tier_policy_rejects_unknown_tier_string():
    with pytest.raises(conn.BindTierError) as exc:
        conn.enforce_bind_tier_policy([_entry(tier="T2_LOOKS_FINE_TO_ME")])
    assert exc.value.reason == "BIND_ENTRY_UNKNOWN_TIER"


def test_untiered_entry_is_unclassified_by_default_but_refused_under_require_tier():
    assert conn.enforce_bind_tier_policy([_entry()])[0]["tier"] == conn.BIND_TIER_UNCLASSIFIED
    with pytest.raises(conn.BindTierError) as exc:
        conn.enforce_bind_tier_policy([_entry()], require_tier=True)
    assert exc.value.reason == "BIND_ENTRY_MISSING_TIER"


def test_one_bad_entry_blocks_the_whole_list():
    """Raises before any entry is emitted, so a list containing one T4 never
    produces a partially-written bind file."""
    with pytest.raises(conn.BindTierError):
        conn.enforce_bind_tier_policy([
            _entry(tier="T1_ALREADY_DECIDED"), _entry(tier="T4_UNDECIDABLE")])


def test_classify_bind_tier_output_feeds_the_gate_directly():
    """End-to-end: the classifier's own tier value is the exact string the
    emission gate consumes -- no translation layer that could drift."""
    t2 = conn.classify_bind_tier(structural_match={"matched": True, "protocol": "AXI",
                                                    "matched_signals": ["AWVALID"]})
    assert conn.enforce_bind_tier_policy([_entry(tier=t2.tier.value)])[0]["auto_emittable"]
    t3 = conn.classify_bind_tier(naming_match="u_usb3_top")
    with pytest.raises(conn.BindTierError):
        conn.enforce_bind_tier_policy([_entry(tier=t3.tier.value)])


# ===========================================================================
# Matrix-level self-check identity + role provenance wiring
# ===========================================================================

def test_from_dut_port_derives_role_instead_of_accepting_one():
    row = conn.ConnectivityRow.from_dut_port(
        dut_instance="chip.core.usb0", interface="axi_if", dut_port_direction="output",
        vip_type="AXI", count=1, active_passive="active",
        bind_target="chip.core.usb0", tier="T2_STRUCTURAL_MATCH")
    assert row.role == conn.determine_role_from_port_direction("output")
    assert row.direction == "output"


def test_assert_role_provenance_rejects_a_naming_derived_role():
    bad = _sample_row()
    bad.role = "master (u_axi_m looks like a master)"
    with pytest.raises(conn.ConnectivityError) as exc:
        conn.assert_role_provenance([bad])
    assert exc.value.reason == "ROLE_NOT_DERIVED_FROM_PORT_DIRECTION"


def test_verify_matrix_self_check_identity_counts_terms_off_the_real_matrix():
    result = conn.verify_matrix_self_check_identity([_sample_row()])
    assert result["verified_interface_count"] == 1
    assert result["vip_instance_count"] == 1
    assert result["identity_holds"] is True


def test_matrix_with_an_uncovered_no_vip_interface_fails_loudly():
    """An uncovered ACTIVE interface names ITSELF rather than reporting a bare
    arithmetic gap. The scalar identity would say only `gap: 1`, leaving the
    reader to work out which row it meant."""
    no_vip = _sample_row()
    no_vip.vip_type = "NONE"
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.verify_matrix_self_check_identity([_sample_row(), no_vip])
    assert exc.value.reason == "ACTIVE_INTERFACE_WITHOUT_VIP"
    assert exc.value.detail["uncovered_active_interfaces"] == ["chip.core.usb0::usb3_if"]


def test_an_uncovered_passive_interface_still_falls_to_the_scalar_identity():
    """The row-aware checks run first, but they do not REPLACE the arithmetic
    backstop -- an uncovered PASSIVE interface is invisible to the
    active-dimension check and must still fail the identity loudly."""
    no_vip = _sample_row()
    no_vip.vip_type = "NONE"
    no_vip.active_passive = "passive"
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.verify_matrix_self_check_identity([_sample_row(), no_vip])
    assert exc.value.reason == "SELF_CHECK_IDENTITY_MISMATCH"
    assert exc.value.detail["gap"] == 1


def test_an_explicit_reasoned_exemption_closes_the_gap():
    no_vip = _sample_row()
    no_vip.vip_type = "NONE"
    result = conn.verify_matrix_self_check_identity(
        [_sample_row(), no_vip],
        exemptions=[{"interface": "usb3_if", "reason": "monitored by the DUT's own internal checker"}])
    assert result["identity_holds"] is True


def test_write_connectivity_manifest_refuses_an_unreconciled_matrix(tmp_path):
    """The manifest file must not exist on disk if the identity failed."""
    no_vip = _sample_row()
    no_vip.vip_type = REQUIRED_HUMAN_INPUT_SENTINEL = conn.REQUIRED_HUMAN_INPUT
    out_path = tmp_path / "manifest.json"
    with pytest.raises(conn.ConnectivitySelfCheckError):
        conn.write_connectivity_manifest(out_path, [_sample_row(), no_vip])
    assert not out_path.exists()


def test_write_connectivity_manifest_records_the_self_check_it_ran(tmp_path):
    out_path = tmp_path / "manifest.json"
    conn.write_connectivity_manifest(out_path, [_sample_row()], metadata={"project": "test"})
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["self_check"]["identity_holds"] is True
    assert loaded["self_check"]["verified_interface_count"] == 1


# ===========================================================================
# Count-mismatch source 1 wired to a REAL matrix: the ACTIVE-interface count
# dimension, the `active_passive` vocabulary it is read from, and exemptions
# actually matched to the row they claim to exempt (2026-09-04).
#
# Before this, `check_vip_instance_count_matches_active_interfaces()` had no
# caller outside its own test; `active_passive` was free text nothing read for
# counting; and `verify_self_check_identity()` could only `len()` exemptions,
# so any string closed any gap.
# ===========================================================================

def _row(**over):
    r = _sample_row()
    for k, v in over.items():
        setattr(r, k, v)
    return r


def test_active_passive_vocabulary_rejects_a_value_that_is_neither(tmp_path):
    """A typo in this column silently drops a row out of the ACTIVE-interface
    count, so it is rejected rather than guessed at."""
    with pytest.raises(conn.ConnectivityError) as exc:
        conn.assert_active_passive_vocabulary([_row(active_passive="actve-ish maybe?")])
    assert exc.value.reason == "ACTIVE_PASSIVE_NOT_IN_VOCABULARY"
    assert exc.value.detail["active_passive"] == "actve-ish maybe?"
    out = tmp_path / "m.json"
    with pytest.raises(conn.ConnectivityError):
        conn.write_connectivity_manifest(out, [_row(active_passive="ACTIVE-ish")])
    assert not out.exists()


def test_active_passive_vocabulary_is_case_and_whitespace_tolerant():
    conn.assert_active_passive_vocabulary([_row(active_passive="  Active "),
                                           _row(interface="apb_if", vip_type="APB",
                                                active_passive="PASSIVE")])


def test_active_interface_count_is_read_off_the_real_matrix_column():
    rows = [_row(), _row(interface="apb_if", vip_type="APB", active_passive="passive"),
            _row(interface="axi_if", vip_type="AXI")]
    assert conn.count_active_interfaces_in_matrix(rows) == 2
    assert conn.count_vip_instances_in_matrix(rows) == 3


def test_matrix_vip_records_feed_the_real_source_1_function():
    """The matrix is convertible into the exact `VipInstanceRecord` list
    `check_vip_instance_count_matches_active_interfaces()` takes -- which is
    what it never had a caller supplying."""
    rows = [_row(), _row(interface="apb_if", vip_type="APB", active_passive="passive")]
    records = conn.matrix_vip_instance_records(rows)
    assert [r.active_passive for r in records] == ["active", "passive"]
    scalar = conn.check_vip_instance_count_matches_active_interfaces(
        records, conn.count_active_interfaces_in_matrix(rows))
    assert scalar["vip_instance_count"] == 2 and scalar["active_interface_count"] == 1


def test_a_passive_monitor_vip_does_not_cancel_an_uncovered_active_interface():
    """The regression this decomposition exists for: 1 passive-monitor VIP
    (+1) and 1 uncovered ACTIVE interface (-1) cancel to a scalar delta of 0,
    which the scalar form reports as ok=True. Two real findings of opposite
    sign must not hide each other."""
    rows = [_row(interface="apb_if", vip_type="APB", active_passive="passive"),
            _row(interface="usb3_if", vip_type="NONE", active_passive="active")]
    scalar = conn.check_vip_instance_count_matches_active_interfaces(
        conn.matrix_vip_instance_records(rows), conn.count_active_interfaces_in_matrix(rows))
    assert scalar["delta"] == 0 and scalar["ok"] is True  # the cancellation, still true of the scalar
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.verify_matrix_vip_active_interface_count(rows)
    assert exc.value.reason == "ACTIVE_INTERFACE_WITHOUT_VIP"
    assert exc.value.detail["uncovered_active_interfaces"] == ["chip.core.usb0::usb3_if"]
    assert exc.value.detail["scalar_delta"] == 0


def test_a_legitimate_passive_monitor_is_recorded_not_blocked():
    """A passive monitor genuinely makes the scalar delta non-zero. That must
    be explained in the record, never treated as a failure."""
    rows = [_row(), _row(interface="apb_if", vip_type="APB", active_passive="passive")]
    result = conn.verify_matrix_vip_active_interface_count(rows)
    assert result["scalar_ok"] is False and result["scalar_delta"] == 1
    assert result["delta_fully_explained"] is True
    assert result["passive_vip_instances"] == ["chip.core.usb0::apb_if"]
    assert result["uncovered_active_interfaces"] == []


def test_an_exemption_naming_an_interface_not_in_the_matrix_is_refused(tmp_path):
    """The scalar identity can only count exemptions, so a stray string used
    to close a gap it did not explain."""
    rows = [_row(), _row(interface="axi_if", vip_type="NONE")]
    out = tmp_path / "m.json"
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.write_connectivity_manifest(
            out, rows, exemptions=[{"interface": "a_totally_unrelated_if", "reason": "handwave"}])
    assert exc.value.reason == "EXEMPTION_INTERFACE_NOT_IN_MATRIX"
    assert not out.exists()


def test_an_exemption_for_an_interface_that_already_has_a_vip_is_refused():
    rows = [_row(), _row(interface="axi_if", vip_type="NONE")]
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.verify_matrix_self_check_identity(
            rows, exemptions=[{"interface": "usb3_if", "reason": "this row already has a VIP"}])
    assert exc.value.reason == "EXEMPTION_COVERS_AN_INTERFACE_THAT_HAS_A_VIP"


def test_two_exemptions_naming_the_same_interface_are_refused():
    rows = [_row(), _row(interface="axi_if", vip_type="NONE"),
            _row(interface="apb_if", vip_type="NONE")]
    with pytest.raises(conn.ConnectivitySelfCheckError) as exc:
        conn.verify_matrix_self_check_identity(rows, exemptions=[
            {"interface": "axi_if", "reason": "a"}, {"interface": "axi_if", "reason": "b"}])
    assert exc.value.reason == "DUPLICATE_EXEMPTION"


def test_a_real_exemption_reconciles_and_marks_an_exempted_active_interface():
    """An exempted ACTIVE interface is the serious kind and is surfaced as
    such, not left indistinguishable from an exempted passive one."""
    rows = [_row(), _row(interface="axi_if", vip_type="NONE", active_passive="active")]
    result = conn.verify_matrix_self_check_identity(
        rows, exemptions=[{"interface": "axi_if", "reason": "driven by the DUT's internal checker"}])
    assert result["identity_holds"] is True
    rec = result["exemptions_reconciled"]
    assert len(rec) == 1
    assert rec[0]["interface"] == "axi_if"
    assert rec[0]["exempts_an_active_interface"] is True
    assert rec[0]["reason"] == "driven by the DUT's internal checker"


def test_the_manifest_on_disk_carries_the_active_dimension_check(tmp_path):
    """End-to-end: the dimension Part C's first mismatch source is defined in
    reaches the artifact a human actually reads."""
    out = tmp_path / "manifest.json"
    conn.write_connectivity_manifest(
        out, [_row(), _row(interface="apb_if", vip_type="APB", active_passive="passive")])
    check = json.loads(out.read_text(encoding="utf-8"))["self_check"]["vip_count_check"]
    assert check["active_interface_count"] == 1
    assert check["passive_interface_count"] == 1
    assert check["vip_instance_count"] == 2
    assert check["passive_vip_instances"] == ["chip.core.usb0::apb_if"]


def test_emit_connectivity_artifacts_refuses_an_unreconciled_matrix(tmp_path):
    """The three-artifact emitter must leave nothing behind either."""
    out = tmp_path / "artifacts"
    with pytest.raises(conn.ConnectivitySelfCheckError):
        conn.emit_connectivity_artifacts(
            out, [_row(), _row(interface="axi_if", vip_type="NONE", active_passive="active")])
    assert list(out.iterdir()) == []


# ===========================================================================
# Scoreboard planning table: all 9 fields sentinel-gated, and every unfilled
# one auto-becoming a REAL question-queue entry (2026-09-04).
#
# Before this, the REQUIRED_HUMAN_INPUT sentinel was a string nobody read:
# `transformation_rules` silently defaulted to `[]` (which READS AS "no
# transform on this path" -- a claim no generator can make), empty
# endpoint_pairs/matching_key passed silently, "tolerance window depth" had no
# column of its own, nothing turned a sentinel into a persisted question, and
# `confirm_row()` would lock a row that still held the sentinel.
# ===========================================================================

def _sb(**kw):
    """A scoreboard entry with only the two structural facts supplied."""
    kw.setdefault("endpoint_pairs", [("chip.core.usb0.axi_if", "chip.core.axi0.s_if")])
    kw.setdefault("matching_key", "transaction_id")
    return conn.generate_scoreboard_entry("sb_usb0_axi0", **kw)


def test_every_scoreboard_plan_field_defaults_to_required_human_input():
    """No field of the planning table may carry a computed default. With only
    the two structural facts supplied, all seven remaining columns must be
    exactly the sentinel."""
    entry = _sb()
    for field_name in conn.SCOREBOARD_PLAN_FIELDS:
        if field_name in ("endpoint_pairs", "matching_key"):
            continue
        assert entry[field_name] == conn.REQUIRED_HUMAN_INPUT, field_name


def test_transformation_rules_no_longer_silently_defaults_to_empty_list():
    """The specific regression: omitting transform rules used to yield `[]`,
    asserting "no width conversion, no packetization, no byte-enable
    remapping" on the generator's own authority."""
    assert _sb()["transformation_rules"] == conn.REQUIRED_HUMAN_INPUT


def test_explicit_empty_transformation_rules_is_a_real_human_confirmation():
    """`None` (nobody said) and `[]` (a human looked and confirmed no
    transform) are different claims and must not be conflated."""
    entry = _sb(transformation_rules=[])
    assert entry["transformation_rules"] == []
    assert "transformation_rules" not in conn.unfilled_plan_fields(entry)


def test_ordering_tolerance_depth_is_its_own_column():
    """Reorder-window depth must not depend on a human happening to write it
    into the free-text `ordering` string."""
    assert "ordering_tolerance_depth" in conn.SCOREBOARD_PLAN_FIELDS
    entry = _sb(ordering="out_of_order permitted")
    assert entry["ordering"] == "out_of_order permitted"
    assert entry["ordering_tolerance_depth"] == conn.REQUIRED_HUMAN_INPUT
    assert conn.unfilled_plan_fields(entry)[0] == "ordering_tolerance_depth"


def test_empty_endpoints_and_matching_key_resolve_to_the_sentinel():
    """They stay required arguments, but an empty value is no longer accepted
    silently -- it routes to the queue like every other unfilled field."""
    entry = conn.generate_scoreboard_entry("sb0", endpoint_pairs=[], matching_key="   ")
    assert entry["endpoint_pairs"] == conn.REQUIRED_HUMAN_INPUT
    assert entry["matching_key"] == conn.REQUIRED_HUMAN_INPUT
    assert conn.unfilled_plan_fields(entry) == list(conn.SCOREBOARD_PLAN_FIELDS)


def test_endpoint_must_be_a_hierarchy_path_not_a_bare_port_name():
    with pytest.raises(conn.ConnectivityError) as exc:
        conn.generate_scoreboard_entry("sb0", endpoint_pairs=[("wdata", "rdata")],
                                       matching_key="tid")
    assert exc.value.reason == "ENDPOINT_NOT_A_HIERARCHY_PATH"


def test_endpoint_pairs_accept_the_dict_form():
    entry = conn.generate_scoreboard_entry(
        "sb0", endpoint_pairs=[{"source": "chip.core.usb0.if", "sink": "chip.core.axi0.if"}],
        matching_key="tid")
    assert entry["endpoint_pairs"][0]["sink"] == "chip.core.axi0.if"


def test_malformed_endpoint_pair_is_a_hard_error():
    with pytest.raises(conn.ConnectivityError) as exc:
        conn.generate_scoreboard_entry("sb0", endpoint_pairs=["chip.core.usb0"], matching_key="tid")
    assert exc.value.reason == "ENDPOINT_PAIR_MALFORMED"


def test_every_plan_field_has_a_pre_researched_question_defined():
    """The routing table must cover every field, or an unfilled field would
    silently never become a question."""
    assert set(conn.SCOREBOARD_FIELD_QUESTIONS) == set(conn.SCOREBOARD_PLAN_FIELDS)
    for name, spec in conn.SCOREBOARD_FIELD_QUESTIONS.items():
        assert 2 <= len(spec["options"]) <= 3, name
        assert spec["recommendation"] in [o["label"] for o in spec["options"]], name
        assert spec["domain"] in ("vip", "dut", "env"), name
        assert spec["assumption_if_unanswered"].strip(), name


def test_unfilled_fields_become_real_blocking_question_queue_entries(tmp_path):
    """The core closure: a sentinel is no longer just a string in a dict --
    it becomes a persisted, schema-valid, Tier-3 blocking question routed to
    a real owner."""
    from dv_harness import question_queue as qq
    store = qq.QuestionQueueStore(tmp_path)
    entry = _sb()

    asked = conn.route_unfilled_fields_to_question_queue(store, entry)

    assert len(asked) == 7
    for q in asked:
        assert q["tier"] == qq.TIER3_CANNOT_ASSUME
        assert q["blocking"] is True
        assert q["status"] == "OPEN"
        qq.validate_question(q)
    # Persisted, not just returned.
    assert len(store.list_questions(status="OPEN")) == 7
    # Routed to whoever actually knows: DUT behavior -> designer,
    # scoreboard policy -> DV-owner.
    owners = {q["context_path"].rsplit("/", 1)[1]: q["owner"] for q in asked}
    assert owners["ordering"] == "designer"
    assert owners["transformation_rules"] == "designer"
    assert owners["orphan_unmatched_timeout"] == "DV-owner"


def test_build_checker_scoreboard_plan_routes_unfilled_fields_when_given_a_store(tmp_path):
    from dv_harness import question_queue as qq
    store = qq.QuestionQueueStore(tmp_path)
    plan = conn.build_checker_scoreboard_plan(
        protocol_entries=[], scoreboard_entries=[_sb()], system_entries=[],
        question_store=store)
    assert plan["unfilled_fields"]["sb_usb0_axi0"][0] == "ordering"
    assert len(plan["open_questions"]) == 7
    assert all(q["blocking"] for q in plan["open_questions"])
    assert len(store.list_questions(status="OPEN")) == 7


def test_plan_reports_unfilled_fields_even_without_a_question_store():
    plan = conn.build_checker_scoreboard_plan([], [_sb()], [])
    assert "open_questions" not in plan
    assert len(plan["unfilled_fields"]["sb_usb0_axi0"]) == 7


def test_a_fully_filled_plan_has_no_unfilled_fields(tmp_path):
    from dv_harness import question_queue as qq
    store = qq.QuestionQueueStore(tmp_path)
    entry = _sb(ordering="in_order", ordering_tolerance_depth=0, transformation_rules=[],
                legal_drop_conditions="none permitted", reset_flush_behavior="both sides flush",
                orphan_threshold=0, orphan_timeout="end-of-test sweep")
    plan = conn.build_checker_scoreboard_plan([], [entry], [], question_store=store)
    assert plan["unfilled_fields"] == {}
    assert plan["open_questions"] == []
    assert store.list_questions() == []


def test_a_human_answer_flows_back_into_the_planning_table(tmp_path):
    """End-to-end: unfilled -> question -> human answers -> field filled."""
    from dv_harness import question_queue as qq
    store = qq.QuestionQueueStore(tmp_path)
    entry = _sb()
    asked = conn.route_unfilled_fields_to_question_queue(store, entry)
    ordering_q = next(q for q in asked if q["context_path"].endswith("/ordering"))

    store.answer_question(ordering_q["id"], answer="Strictly in-order",
                          basis="RTL evidence: single non-reordering datapath, usb_axi_bridge.v:88",
                          decided_by="designer")

    filled = conn.apply_answered_questions(store, entry)
    assert filled["ordering"] == "Strictly in-order"
    # Only the answered field moves; the rest stay unfilled.
    assert filled["legal_drop_conditions"] == conn.REQUIRED_HUMAN_INPUT
    assert "ordering" not in conn.unfilled_plan_fields(filled)


def test_a_human_answer_stops_the_question_being_re_asked(tmp_path):
    """Regenerating the plan must not re-escalate an already-answered field:
    same question_key -> same Q-ID -> Tier-1 self-resolve."""
    from dv_harness import question_queue as qq
    store = qq.QuestionQueueStore(tmp_path)
    entry = _sb()
    first = conn.route_unfilled_fields_to_question_queue(store, entry)
    ordering_q = next(q for q in first if q["context_path"].endswith("/ordering"))
    store.answer_question(ordering_q["id"], answer="Strictly in-order",
                          basis="RTL evidence", decided_by="designer")

    second = conn.route_unfilled_fields_to_question_queue(store, entry)
    reasked = next(q for q in second if q["context_path"].endswith("/ordering"))
    assert reasked["id"] == ordering_q["id"]
    assert reasked["tier"] == qq.TIER1_SELF_RESOLVE
    assert reasked["status"] == "SELF_RESOLVED"
    assert reasked["blocking"] is False


def test_the_harness_own_tier2_guess_never_fills_a_mandatory_review_field(tmp_path):
    """`apply_answered_questions()` reuses classify_tier()'s human-decision
    gate: only a real human answer fills a field, never a machine-authored
    tier-2 auto-assumption sitting in the same decisions store."""
    from dv_harness import question_queue as qq
    store = qq.QuestionQueueStore(tmp_path)
    entry = _sb()
    spec = conn.SCOREBOARD_FIELD_QUESTIONS["ordering"]
    key = qq.make_question_key(spec["domain"], spec["question"],
                               conn.scoreboard_field_context_path("sb_usb0_axi0", "ordering"))
    store._persist_decision(
        question_key=key, domain="dut", owner="designer", question=spec["question"],
        answer="Strictly in-order", basis="machine guess", decided_by="dv_harness(auto)",
        source="tier2_auto_assumption", question_id_of_answer="Q-DUT-DEADBEEF")

    assert store.find_decision(key) is not None      # the guess really is on file
    filled = conn.apply_answered_questions(store, entry)
    assert filled["ordering"] == conn.REQUIRED_HUMAN_INPUT


def test_confirm_row_refuses_a_row_that_still_holds_the_sentinel(tmp_path):
    """The lock gate: confirming an unfilled row would mark it reviewed and
    stop `diff_rows_needing_reconfirmation()` ever surfacing it again."""
    lock_store = conn.RowLockStore(tmp_path / "locks.json")
    entry = _sb()
    with pytest.raises(conn.ConnectivityError) as exc:
        lock_store.confirm_row(conn.scoreboard_entry_row_id(entry), entry,
                               confirmed_by="dv-lead@example.com", evidence="scoreboard plan review")
    assert exc.value.reason == "CANNOT_CONFIRM_ROW_WITH_UNFILLED_REQUIRED_HUMAN_INPUT"
    assert "ordering" in exc.value.detail["unfilled_paths"]
    assert not lock_store.is_locked(conn.scoreboard_entry_row_id(entry))


def test_confirm_row_accepts_a_fully_filled_scoreboard_row(tmp_path):
    lock_store = conn.RowLockStore(tmp_path / "locks.json")
    entry = _sb(ordering="in_order", ordering_tolerance_depth=0, transformation_rules=[],
                legal_drop_conditions="none permitted", reset_flush_behavior="both sides flush",
                orphan_threshold=0, orphan_timeout="end-of-test sweep")
    row_id = conn.scoreboard_entry_row_id(entry)
    lock_store.confirm_row(row_id, entry,
                           confirmed_by="dv-lead@example.com", evidence="scoreboard plan review")
    assert lock_store.is_locked(row_id)
    assert conn.RowLockStore(tmp_path / "locks.json").is_locked(row_id)


def test_confirm_row_finds_a_sentinel_nested_inside_a_list(tmp_path):
    """The gate scans nested content, not just top-level values."""
    lock_store = conn.RowLockStore(tmp_path / "locks.json")
    with pytest.raises(conn.ConnectivityError) as exc:
        lock_store.confirm_row("row1", {"a": [{"b": conn.REQUIRED_HUMAN_INPUT}]},
                               confirmed_by="dv-lead@example.com", evidence="review")
    assert exc.value.detail["unfilled_paths"] == ["a.0.b"]


# ===========================================================================
# Confirmation granularity + locking enforcement + the 3 presentation
# artifacts (2026-09-04 gap closure).
#
# Prior state, all three re-verified live before this change:
#   - `confirm_row()` recorded no `confirmed_by` and no `evidence`, so the
#     lock file could say a row was confirmed without saying by whom or on
#     what basis;
#   - `is_locked()` was never consulted by any other function -- a second
#     `confirm_row()` on an already-locked row with entirely different
#     bind_target/tier content succeeded silently, no error, no diff;
#   - the connectivity manifest itself carried no confirmation state at all
#     (lock state lived only in a side JSON file), and nothing emitted the
#     matrix + hierarchy diagram + question queue as one artifact set.
# ===========================================================================

CONFIRMER = "dv-lead@example.com"
EVIDENCE = {"source": "rtl/usb_top.sv:214", "basis": "port list read directly"}


def _lock_store(tmp_path):
    return conn.RowLockStore(tmp_path / "locks.json")


# -- confirmation record carries WHO and on WHAT evidence --------------------

def test_confirm_row_records_confirmed_by_date_and_evidence(tmp_path):
    store = _lock_store(tmp_path)
    row = _sample_row()
    rec = store.confirm_row(row.row_id(), row.to_dict(),
                            confirmed_by=CONFIRMER, evidence=EVIDENCE)
    assert rec["confirmed_by"] == CONFIRMER
    assert rec["evidence"] == EVIDENCE
    assert rec["confirmed_date"]
    # persisted, not only returned
    reloaded = conn.RowLockStore(tmp_path / "locks.json").confirmation(row.row_id())
    assert reloaded["confirmed_by"] == CONFIRMER
    assert reloaded["evidence"] == EVIDENCE
    assert reloaded["confirmed_date"] == rec["confirmed_date"]


def test_confirm_row_refuses_an_anonymous_confirmation(tmp_path):
    store = _lock_store(tmp_path)
    row = _sample_row()
    for bad in ("", "   ", None):
        with pytest.raises(conn.ConnectivityError) as exc:
            store.confirm_row(row.row_id(), row.to_dict(), confirmed_by=bad, evidence=EVIDENCE)
        assert exc.value.reason == "ROW_CONFIRMATION_REQUIRES_CONFIRMED_BY"
    assert not store.is_locked(row.row_id())


def test_confirm_row_refuses_a_confirmation_with_no_evidence(tmp_path):
    store = _lock_store(tmp_path)
    row = _sample_row()
    for bad in (None, "", "   ", [], {}):
        with pytest.raises(conn.ConnectivityError) as exc:
            store.confirm_row(row.row_id(), row.to_dict(), confirmed_by=CONFIRMER, evidence=bad)
        assert exc.value.reason == "ROW_CONFIRMATION_REQUIRES_EVIDENCE"
    assert not store.is_locked(row.row_id())


# -- locking is ENFORCED, not merely queryable -------------------------------

def test_locked_row_cannot_be_silently_overwritten_with_changed_content(tmp_path):
    """The exact failure this gap closure exists to stop: before it, this
    second confirm_row() succeeded silently and the lock recorded content no
    human had ever reviewed."""
    store = _lock_store(tmp_path)
    row = _sample_row()
    store.confirm_row(row.row_id(), row.to_dict(), confirmed_by=CONFIRMER, evidence=EVIDENCE)
    first_hash = store.locked_hash(row.row_id())

    changed = _sample_row(tier="T3_NAMING_HEURISTIC")
    changed.bind_target = "chip.core.SOMETHING_ELSE"
    with pytest.raises(conn.RowLockConflictError) as exc:
        store.confirm_row(changed.row_id(), changed.to_dict(),
                          confirmed_by=CONFIRMER, evidence=EVIDENCE)
    assert exc.value.reason == "LOCKED_ROW_CHANGED_REQUIRES_EXPLICIT_RECONFIRM"
    # the lock is untouched by the refused write
    assert store.locked_hash(row.row_id()) == first_hash
    assert conn.RowLockStore(tmp_path / "locks.json").locked_hash(row.row_id()) == first_hash


def test_lock_conflict_error_carries_the_real_field_level_diff(tmp_path):
    store = _lock_store(tmp_path)
    row = _sample_row()
    store.confirm_row(row.row_id(), row.to_dict(), confirmed_by=CONFIRMER, evidence=EVIDENCE)
    changed = _sample_row(tier="T3_NAMING_HEURISTIC")
    changed.bind_target = "chip.core.SOMETHING_ELSE"
    with pytest.raises(conn.RowLockConflictError) as exc:
        store.confirm_row(changed.row_id(), changed.to_dict(),
                          confirmed_by=CONFIRMER, evidence=EVIDENCE)
    diff = {d["field"]: d for d in exc.value.detail["diff"]}
    assert set(diff) == {"tier", "bind_target"}
    assert diff["tier"]["old"] == "T2_STRUCTURAL_MATCH"
    assert diff["tier"]["new"] == "T3_NAMING_HEURISTIC"
    assert diff["bind_target"]["new"] == "chip.core.SOMETHING_ELSE"
    assert exc.value.detail["expected_supersedes_hash"] == store.locked_hash(row.row_id())
    assert exc.value.detail["previously_confirmed_by"] == CONFIRMER


def test_explicit_diff_then_reconfirm_with_supersedes_hash_succeeds(tmp_path):
    """The sanctioned way past the lock: read the diff, then re-confirm
    naming the exact confirmation being superseded."""
    store = _lock_store(tmp_path)
    row = _sample_row()
    store.confirm_row(row.row_id(), row.to_dict(), confirmed_by=CONFIRMER, evidence=EVIDENCE)
    old_hash = store.locked_hash(row.row_id())

    changed = _sample_row(tier="T1_ALREADY_DECIDED")
    diff = store.row_diff(changed.row_id(), changed.to_dict())
    assert [d["field"] for d in diff] == ["tier"]

    rec = store.confirm_row(changed.row_id(), changed.to_dict(),
                            confirmed_by="designer@example.com",
                            evidence="existing bind at tb/usb_bind.sv:12",
                            supersedes_hash=old_hash)
    assert rec["supersedes_hash"] == old_hash
    assert rec["confirmed_by"] == "designer@example.com"
    assert store.locked_hash(row.row_id()) == rec["content_hash"] != old_hash


def test_reconfirm_with_a_stale_supersedes_hash_is_still_refused(tmp_path):
    store = _lock_store(tmp_path)
    row = _sample_row()
    store.confirm_row(row.row_id(), row.to_dict(), confirmed_by=CONFIRMER, evidence=EVIDENCE)
    changed = _sample_row(tier="T1_ALREADY_DECIDED")
    with pytest.raises(conn.RowLockConflictError):
        store.confirm_row(changed.row_id(), changed.to_dict(), confirmed_by=CONFIRMER,
                          evidence=EVIDENCE, supersedes_hash="deadbeef")


def test_reconfirming_identical_content_is_allowed_without_supersedes_hash(tmp_path):
    """A countersignature on unchanged content is not a silent overwrite --
    there is nothing a reviewer could have missed."""
    store = _lock_store(tmp_path)
    row = _sample_row()
    store.confirm_row(row.row_id(), row.to_dict(), confirmed_by=CONFIRMER, evidence=EVIDENCE)
    rec = store.confirm_row(row.row_id(), row.to_dict(),
                            confirmed_by="second-reviewer@example.com", evidence="peer review")
    assert rec["confirmed_by"] == "second-reviewer@example.com"


# -- diff artifact -----------------------------------------------------------

def test_diff_row_fields_reports_added_removed_and_changed():
    diff = conn.diff_row_fields({"a": 1, "b": 2}, {"a": 9, "c": 3})
    by_field = {d["field"]: d for d in diff}
    assert by_field["a"] == {"field": "a", "change": "CHANGED", "old": 1, "new": 9}
    assert by_field["b"]["change"] == "REMOVED"
    assert by_field["c"]["change"] == "ADDED"


def test_diff_row_fields_against_never_confirmed_row_is_all_added():
    diff = conn.diff_row_fields(None, {"a": 1, "b": 2})
    assert {d["change"] for d in diff} == {"ADDED"}


def test_pending_reconfirmations_returns_what_changed_not_only_which_rows(tmp_path):
    store = _lock_store(tmp_path)
    row_a = _sample_row()
    row_b = conn.ConnectivityRow(
        dut_instance="chip.core.axi0", interface="axi_if", direction="input",
        role="vip_role=master_initiator", vip_type="AXI", count=1,
        active_passive="active", bind_target="chip.core.axi0", tier="T1_ALREADY_DECIDED",
    )
    store.confirm_row(row_a.row_id(), row_a.to_dict(), confirmed_by=CONFIRMER, evidence=EVIDENCE)
    store.confirm_row(row_b.row_id(), row_b.to_dict(), confirmed_by=CONFIRMER, evidence=EVIDENCE)

    pending = store.pending_reconfirmations(
        [_sample_row(tier="T1_ALREADY_DECIDED"), row_b], lambda r: r.row_id())
    assert len(pending) == 1
    item = pending[0]
    assert item["row_id"] == row_a.row_id()
    assert item["status"] == conn.CONFIRMATION_CHANGED_SINCE_CONFIRMATION
    assert item["supersedes_hash"] == store.locked_hash(row_a.row_id())
    assert [d["field"] for d in item["diff"]] == ["tier"]
    # and the diff renders for a human
    assert "tier" in conn.render_row_diff(item["row_id"], item["diff"])


def test_pending_reconfirmations_marks_a_never_confirmed_row_unconfirmed(tmp_path):
    store = _lock_store(tmp_path)
    pending = store.pending_reconfirmations([_sample_row()], lambda r: r.row_id())
    assert pending[0]["status"] == conn.CONFIRMATION_UNCONFIRMED
    assert pending[0]["supersedes_hash"] is None


# -- manifest writeback ------------------------------------------------------

def test_manifest_writes_back_confirmed_by_date_and_evidence(tmp_path):
    store = _lock_store(tmp_path)
    row = _sample_row()
    store.confirm_row(row.row_id(), row.to_dict(), confirmed_by=CONFIRMER, evidence=EVIDENCE)

    out_path = tmp_path / "manifest.json"
    conn.write_connectivity_manifest(out_path, [row], metadata={"project": "test"},
                                     lock_store=store)
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    block = loaded["rows"][0]["confirmation"]
    assert block["status"] == conn.CONFIRMATION_CONFIRMED
    assert block["confirmed_by"] == CONFIRMER
    assert block["evidence"] == EVIDENCE
    assert block["confirmed_date"]
    assert loaded["confirmation_summary"]["all_rows_confirmed"] is True


def test_manifest_marks_a_row_changed_since_confirmation_and_shows_the_diff(tmp_path):
    store = _lock_store(tmp_path)
    store.confirm_row(_sample_row().row_id(), _sample_row().to_dict(),
                      confirmed_by=CONFIRMER, evidence=EVIDENCE)
    out_path = tmp_path / "manifest.json"
    conn.write_connectivity_manifest(out_path, [_sample_row(tier="T3_NAMING_HEURISTIC")],
                                     lock_store=store)
    block = json.loads(out_path.read_text(encoding="utf-8"))["rows"][0]["confirmation"]
    assert block["status"] == conn.CONFIRMATION_CHANGED_SINCE_CONFIRMATION
    assert [d["field"] for d in block["diff_since_confirmation"]] == ["tier"]


def test_manifest_without_a_lock_store_stamps_every_row_unconfirmed(tmp_path):
    """Absence of a lock store must never read as 'reviewed'."""
    out_path = tmp_path / "manifest.json"
    conn.write_connectivity_manifest(out_path, [_sample_row()])
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["rows"][0]["confirmation"]["status"] == conn.CONFIRMATION_UNCONFIRMED
    assert loaded["confirmation_summary"]["all_rows_confirmed"] is False


# -- hierarchy diagram over a REAL captured DUT instance tree ----------------

def _tree():
    """A real `DutInstanceNode` tree of the shape
    `parse_scope_tree_dump()`/`parse_slang_ast_json()` produce."""
    usb = conn.DutInstanceNode(instance_name="usb0", module_name="usb3_subsystem",
                               full_path="chip.core.usb0", children=[])
    core = conn.DutInstanceNode(instance_name="core", module_name="chip_core",
                                full_path="chip.core", children=[usb])
    return conn.DutInstanceNode(instance_name="chip", module_name="chip_top",
                                full_path="chip", children=[core])


def test_hierarchy_diagram_renders_nested_subgraphs_and_marks_bind_points():
    diagram = conn.render_hierarchy_diagram([_sample_row()], instance_tree=_tree())
    assert diagram.startswith("flowchart TB")
    # real nesting, not a flat edge list
    assert "subgraph N_chip[" in diagram
    assert "subgraph N_chip_core[" in diagram
    # module names are visible, so this is a hierarchy view not just a path string
    assert "chip_core" in diagram and "usb3_subsystem" in diagram
    # the bind point is marked, and a VIP mount hangs off it
    assert "class N_chip_core_usb0 bindpoint;" in diagram
    assert "vipmount" in diagram
    assert "VIP USB3" in diagram


def test_hierarchy_diagram_surfaces_a_bind_target_absent_from_the_captured_tree():
    row = _sample_row()
    row.bind_target = "chip.core.PATH_THAT_DOES_NOT_EXIST"
    diagram = conn.render_hierarchy_diagram([row], instance_tree=_tree())
    assert "UNRESOLVED_BIND_TARGETS" in diagram
    assert "NOT FOUND IN CAPTURED DUT TREE" in diagram


def test_hierarchy_diagram_without_a_tree_keeps_the_flat_overview_mode():
    diagram = conn.render_hierarchy_diagram([_sample_row()])
    assert diagram.startswith("flowchart LR")
    assert "chip.core.usb0" in diagram


def test_hierarchy_diagram_shows_confirmation_status_per_bind_point(tmp_path):
    store = _lock_store(tmp_path)
    diagram = conn.render_hierarchy_diagram([_sample_row()], instance_tree=_tree(),
                                            lock_store=store)
    assert conn.CONFIRMATION_UNCONFIRMED in diagram
    store.confirm_row(_sample_row().row_id(), _sample_row().to_dict(),
                      confirmed_by=CONFIRMER, evidence=EVIDENCE)
    diagram2 = conn.render_hierarchy_diagram([_sample_row()], instance_tree=_tree(),
                                             lock_store=store)
    assert "[" + conn.CONFIRMATION_CONFIRMED + "]" in diagram2


# -- all 3 artifacts emitted together ----------------------------------------

def test_emit_connectivity_artifacts_writes_all_three(tmp_path):
    from dv_harness import question_queue as qq

    qstore = qq.QuestionQueueStore(tmp_path / "queue")
    qstore.add_question(
        domain="dut",
        question="Which of chip.core.usb0 / chip.core.usb1 is the intended bind target?",
        context_path="chip.core.usb0::usb3_if",
        options=[{"label": "chip.core.usb0", "rationale": "matches the captured tree"},
                 {"label": "chip.core.usb1", "rationale": "second instance of the same module"}],
        recommendation="chip.core.usb0",
        assumption_if_unanswered="bind to chip.core.usb0 (the recommendation)",
        context={"affects_pass_fail_verdict": True},
    )
    lock_store = _lock_store(tmp_path)

    out = conn.emit_connectivity_artifacts(
        tmp_path / "artifacts", [_sample_row()],
        metadata={"project": "test"}, lock_store=lock_store,
        question_store=qstore, instance_tree=_tree())

    for key in ("matrix_manifest", "matrix_table", "hierarchy_diagram", "question_queue"):
        assert out[key].exists(), key

    manifest = json.loads(out["matrix_manifest"].read_text(encoding="utf-8"))
    assert manifest["rows"][0]["confirmation"]["status"] == conn.CONFIRMATION_UNCONFIRMED

    table = out["matrix_table"].read_text(encoding="utf-8")
    assert "dut_instance" in table and "chip.core.usb0" in table

    diagram = out["hierarchy_diagram"].read_text(encoding="utf-8")
    assert "mermaid" in diagram and "flowchart TB" in diagram
    assert "bindpoint" in diagram

    questions = out["question_queue"].read_text(encoding="utf-8")
    assert "chip.core.usb0::usb3_if" in questions
    assert "Which of chip.core.usb0" in questions

    # the review worklist rides along with the artifacts
    assert [p["row_id"] for p in out["pending_reconfirmations"]] == [_sample_row().row_id()]


def test_emit_connectivity_artifacts_pending_worklist_empties_once_confirmed(tmp_path):
    lock_store = _lock_store(tmp_path)
    row = _sample_row()
    lock_store.confirm_row(row.row_id(), row.to_dict(),
                           confirmed_by=CONFIRMER, evidence=EVIDENCE)
    out = conn.emit_connectivity_artifacts(tmp_path / "artifacts", [row], lock_store=lock_store)
    assert out["pending_reconfirmations"] == []
    assert out["manifest"]["confirmation_summary"]["all_rows_confirmed"] is True


def test_emit_connectivity_artifacts_says_so_when_no_question_store_was_given(tmp_path):
    out = conn.emit_connectivity_artifacts(tmp_path / "artifacts", [_sample_row()])
    text = out["question_queue"].read_text(encoding="utf-8")
    assert "NOT an assertion that no questions exist" in text


def test_emit_connectivity_artifacts_writes_nothing_when_the_matrix_does_not_reconcile(tmp_path):
    no_vip = _sample_row()
    no_vip.vip_type = conn.REQUIRED_HUMAN_INPUT
    out_dir = tmp_path / "artifacts"
    with pytest.raises(conn.ConnectivitySelfCheckError):
        conn.emit_connectivity_artifacts(out_dir, [_sample_row(), no_vip])
    assert not (out_dir / conn.ARTIFACT_FILENAMES["matrix_manifest"]).exists()
    assert not (out_dir / conn.ARTIFACT_FILENAMES["hierarchy_diagram"]).exists()

