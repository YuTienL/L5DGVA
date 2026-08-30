#!/usr/bin/env python3
"""
protocol_structural_completeness_gate.py -- unified structural-completeness
dispatcher for VERIFICATION_ARCHITECTURE, covering 10 protocols behind one
mandatory STAGE_GATES tuple instead of one-tuple-per-protocol.

Why unified, not one gate per protocol (design decision, 2026-08-28):
AMBA4's fabric_topology_completeness_gate.py was built first as its own
separate mandatory tuple, requiring every OTHER protocol's flow through
VERIFICATION_ARCHITECTURE to supply a {"topology_applicable": false, ...}
escape hatch just to decline it. Extending that same one-gate-per-protocol
pattern to PCIe, then to the remaining protocols below, would have left
VERIFICATION_ARCHITECTURE with 10+ mandatory tuples -- every single flow,
regardless of its actual protocol, would need to supply 9+ irrelevant
escape-hatch blocks. That is the exact duplication/bloat problem this whole
audit pass has been fixing at the skill-file level, recreated at the gate
level. This module instead dispatches on one "protocol" field to the correct
per-protocol deterministic structural check, so VERIFICATION_ARCHITECTURE
gains exactly ONE additional mandatory tuple for all 10 protocols combined.
fabric_topology_completeness_gate.py (AMBA4) is left as its own separate,
already-shipped-and-tested gate -- not folded in here, to avoid churning
already-verified code for no functional benefit.

Each check_<protocol>(d) function below was independently designed against
real protocol-spec semantics, then adversarially verified (a dedicated
verify pass executed the function against constructed counterexamples), and
for 8 of the 10, verified again after a fix round that resolved every
must-fix item the first verify pass found. Full provenance/verification
detail for each protocol lives in the session's audit trail; only the
final, verified function bodies are reproduced here.

Every check_<protocol>(d) function follows the same contract:
    result_dict, exit_code = check_<protocol>(d)
    exit_code == 0  <=> result_dict["status"] in {"PASS","SKIPPED_NOT_APPLICABLE"}
    exit_code != 0  <=> result_dict["status"] == "FAIL"
Deterministic STRUCTURAL checks only in every function -- list/matrix
completeness, duplicate/unknown-id detection, enum-membership, waiver-
approval presence. No RTL semantic judgment. Module-level constants/helpers
are suffixed per protocol (_DSI/_CSI2/_CANFD/_SDIO/_EMMC/_EDP/_USB/_UCIE/_PCIE)
to avoid collisions now that 10 independently-authored checkers share one
file; ethernet's checker is fully self-contained (no module-level names).
"""
import argparse, json, pathlib, sys


# ---- PCIe: LTSSM state coverage, TLP-type x completion pairing, config-space
# capability coverage. Adapted from the standalone pcie_protocol_completeness_gate.py
# design (verified GO) into a pure dispatch-case function for the shared dispatcher.

VALID_STATUSES_PCIE = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}

# ---- LTSSM: PCIe Base Spec Ch.4 (Link Training and Status State Machine).
# Top-level LTSSM states are unchanged Gen1 (2.5GT/s) through Gen6 (64GT/s,
# PAM4). Gen3+ (8.0GT/s and above) additionally requires a
# Recovery.Equalization sub-phase (transmitter/receiver link equalization,
# spec 4.2.3/4.2.6) that is not a separately-tracked state at Gen1/Gen2.
BASE_LTSSM_STATES_PCIE = [
    "Detect", "Polling", "Configuration", "Recovery",
    "L0", "L0s", "L1", "L2", "Disabled", "Loopback", "Hot Reset",
]
GEN3_PLUS_EXTRA_STATES_PCIE = ["Recovery.Equalization"]
KNOWN_LTSSM_STATES_PCIE = set(BASE_LTSSM_STATES_PCIE) | set(GEN3_PLUS_EXTRA_STATES_PCIE)

# ---- TLP type -> completion requirement. PCIe Base Spec Ch.2 (Transaction
# Layer): Requests that solicit a Completion vs. Posted Requests that never do.
COMPLETION_REQUIRED_TLP_TYPES_PCIE = {
    "MRd", "MRdLk",
    "CfgRd0", "CfgRd1", "CfgWr0", "CfgWr1",
    "IORd", "IOWr",
    "AtomicOp_FetchAdd", "AtomicOp_Swap", "AtomicOp_CAS",
}
POSTED_TLP_TYPES_PCIE = {"MWr", "Msg", "MsgD"}
KNOWN_TLP_TYPES_PCIE = COMPLETION_REQUIRED_TLP_TYPES_PCIE | POSTED_TLP_TYPES_PCIE

# ---- Config space: every PCIe Function is required (spec 7.5.3) to
# implement the PCI Express Capability structure in STANDARD config space
# at capability ID 0x10.
MANDATORY_STANDARD_CAP_ID_PCIE = 0x10
MANDATORY_STANDARD_CAP_NAME_PCIE = "PCI_EXPRESS_CAP"
VALID_CAP_SPACES_PCIE = {"STANDARD", "EXTENDED"}


def parse_cap_id_pcie(v):
    if isinstance(v, int):
        return v
    s = str(v).strip().replace("_", "")
    return int(s, 0)


def check_pcie(d):
    if d.get("pcie_applicable") is False:
        reason = d.get("pcie_not_applicable_reason")
        if not reason:
            return {"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}, 2
        return {"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}, 0

    required_top = ["link_profile", "ltssm_states", "tlp_types_in_use",
                     "completion_scoreboard", "config_space_capabilities",
                     "capability_coverage"]
    missing = [k for k in required_top if k not in d]
    if missing:
        return {"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing}, 3

    link_profile = d.get("link_profile") or {}
    max_gen = link_profile.get("max_gen")
    if not isinstance(max_gen, int) or isinstance(max_gen, bool) or not (1 <= max_gen <= 6):
        return {"status": "FAIL", "reason": "INVALID_MAX_GEN", "max_gen": max_gen}, 4

    ltssm_states = d.get("ltssm_states") or []
    tlp_types_in_use = d.get("tlp_types_in_use") or []
    completion_scoreboard = d.get("completion_scoreboard") or []
    config_space_capabilities = d.get("config_space_capabilities") or []
    capability_coverage = d.get("capability_coverage") or []

    # ---- 1. LTSSM state coverage ----
    expected_states = set(BASE_LTSSM_STATES_PCIE)
    if max_gen >= 3:
        expected_states |= set(GEN3_PLUS_EXTRA_STATES_PCIE)

    seen_states = {}
    for i, entry in enumerate(ltssm_states):
        state = entry.get("state")
        status = entry.get("status")
        if state not in KNOWN_LTSSM_STATES_PCIE:
            return {"status": "FAIL", "reason": "UNKNOWN_LTSSM_STATE", "index": i, "state": state}, 5
        if status not in VALID_STATUSES_PCIE:
            return {"status": "FAIL", "reason": "INVALID_LTSSM_STATUS",
                    "index": i, "state": state, "status": status}, 6
        if status in ("WAIVED", "NOT_APPLICABLE") and not (entry.get("waiver_approved") and entry.get("waiver_evidence")):
            return {"status": "FAIL", "reason": "UNAPPROVED_LTSSM_WAIVER", "state": state}, 7
        if state in seen_states:
            return {"status": "FAIL", "reason": "DUPLICATE_LTSSM_STATE", "state": state}, 8
        seen_states[state] = status

    missing_states = sorted(expected_states - set(seen_states))
    if missing_states:
        return {"status": "FAIL", "reason": "MISSING_LTSSM_STATES",
                "max_gen": max_gen, "missing_states": missing_states}, 9

    # ---- 2. TLP type x completion pairing ----
    if len(set(tlp_types_in_use)) != len(tlp_types_in_use):
        dup = sorted({t for t in tlp_types_in_use if tlp_types_in_use.count(t) > 1})
        return {"status": "FAIL", "reason": "DUPLICATE_TLP_TYPE", "duplicates": dup}, 10
    unknown_tlp = sorted(set(tlp_types_in_use) - KNOWN_TLP_TYPES_PCIE)
    if unknown_tlp:
        return {"status": "FAIL", "reason": "UNKNOWN_TLP_TYPE", "unknown": unknown_tlp}, 11

    tlp_set = set(tlp_types_in_use)
    expected_completion_types = tlp_set & COMPLETION_REQUIRED_TLP_TYPES_PCIE

    seen_completions = {}
    for i, entry in enumerate(completion_scoreboard):
        ttype = entry.get("tlp_type")
        status = entry.get("status")
        if ttype not in tlp_set:
            return {"status": "FAIL", "reason": "UNKNOWN_TLP_TYPE_IN_COMPLETION_SCOREBOARD",
                    "index": i, "tlp_type": ttype}, 12
        if ttype in POSTED_TLP_TYPES_PCIE:
            return {"status": "FAIL", "reason": "POSTED_TYPE_IN_COMPLETION_SCOREBOARD",
                    "index": i, "tlp_type": ttype}, 13
        if status not in VALID_STATUSES_PCIE:
            return {"status": "FAIL", "reason": "INVALID_COMPLETION_STATUS",
                    "index": i, "tlp_type": ttype, "status": status}, 14
        if status in ("WAIVED", "NOT_APPLICABLE") and not (entry.get("waiver_approved") and entry.get("waiver_evidence")):
            return {"status": "FAIL", "reason": "UNAPPROVED_COMPLETION_WAIVER", "tlp_type": ttype}, 15
        if ttype in seen_completions:
            return {"status": "FAIL", "reason": "DUPLICATE_COMPLETION_ENTRY", "tlp_type": ttype}, 16
        seen_completions[ttype] = status

    missing_completions = sorted(expected_completion_types - set(seen_completions))
    if missing_completions:
        return {"status": "FAIL", "reason": "MISSING_COMPLETION_ENTRIES",
                "missing_tlp_types": missing_completions}, 17

    # ---- 3. Config space capability coverage ----
    if not config_space_capabilities:
        return {"status": "FAIL", "reason": "NO_CAPABILITIES_DECLARED"}, 18

    cap_keys = set()
    for i, c in enumerate(config_space_capabilities):
        space = c.get("capability_space")
        if space not in VALID_CAP_SPACES_PCIE:
            return {"status": "FAIL", "reason": "INVALID_CAPABILITY_SPACE",
                    "index": i, "capability_space": space}, 19
        try:
            cid = parse_cap_id_pcie(c.get("capability_id"))
        except Exception:
            return {"status": "FAIL", "reason": "UNPARSEABLE_CAPABILITY_ID",
                    "index": i, "capability_id": c.get("capability_id")}, 20
        key = (space, cid)
        if key in cap_keys:
            return {"status": "FAIL", "reason": "DUPLICATE_CAPABILITY_ID",
                    "index": i, "capability_space": space, "capability_id": cid}, 21
        cap_keys.add(key)

    if ("STANDARD", MANDATORY_STANDARD_CAP_ID_PCIE) not in cap_keys:
        return {"status": "FAIL", "reason": "MISSING_MANDATORY_CAPABILITY",
                "capability_space": "STANDARD",
                "capability_id": hex(MANDATORY_STANDARD_CAP_ID_PCIE),
                "capability_name": MANDATORY_STANDARD_CAP_NAME_PCIE}, 22

    seen_cap_coverage = {}
    for i, entry in enumerate(capability_coverage):
        space = entry.get("capability_space")
        status = entry.get("status")
        try:
            cid = parse_cap_id_pcie(entry.get("capability_id"))
        except Exception:
            return {"status": "FAIL", "reason": "UNPARSEABLE_CAPABILITY_ID_IN_COVERAGE",
                    "index": i, "capability_id": entry.get("capability_id")}, 23
        key = (space, cid)
        if key not in cap_keys:
            return {"status": "FAIL", "reason": "UNKNOWN_CAPABILITY_IN_COVERAGE",
                    "index": i, "capability_space": space, "capability_id": cid}, 24
        if status not in VALID_STATUSES_PCIE:
            return {"status": "FAIL", "reason": "INVALID_CAPABILITY_COVERAGE_STATUS",
                    "index": i, "capability_space": space, "capability_id": cid, "status": status}, 25
        if status in ("WAIVED", "NOT_APPLICABLE") and not (entry.get("waiver_approved") and entry.get("waiver_evidence")):
            return {"status": "FAIL", "reason": "UNAPPROVED_CAPABILITY_WAIVER",
                    "capability_space": space, "capability_id": cid}, 26
        if key in seen_cap_coverage:
            return {"status": "FAIL", "reason": "DUPLICATE_CAPABILITY_COVERAGE_ENTRY",
                    "capability_space": space, "capability_id": cid}, 27
        seen_cap_coverage[key] = status

    missing_cap_coverage = sorted(cap_keys - set(seen_cap_coverage))
    if missing_cap_coverage:
        return {"status": "FAIL", "reason": "MISSING_CAPABILITY_COVERAGE",
                "missing": [f"{sp}:{hex(cid)}" for sp, cid in missing_cap_coverage]}, 28

    return {
        "status": "PASS",
        "max_gen": max_gen,
        "ltssm_states_checked": len(expected_states),
        "completion_tlp_types_checked": len(expected_completion_types),
        "capabilities_checked": len(cap_keys),
    }, 0

"""
check_mipi_dsi(d) -- MIPI DSI structural completeness checker.

House-style contract (adapted from fabric_topology_completeness_gate.py for a
shared multi-protocol dispatcher):
  - Pure function, no argparse/main()/sys.exit(). Coordinator owns the CLI/dispatch.
  - Deterministic STRUCTURAL checks only (list/matrix completeness, duplicate/
    unknown-id detection, enum-membership, waiver-approval presence). No RTL
    semantic judgment -- e.g. we never decide whether a DUT "should" support a
    given VC, data type, mode or lane count. Those are evidence inputs the
    caller must already have established (RTL/register scan, spec reading,
    Multi-Agent Evidence Consensus per mipi-dsi-environment-builder SKILL.md).
  - Returns (result_dict, exit_code):
        exit_code == 0            -> PASS or SKIPPED_NOT_APPLICABLE
        exit_code in FAIL_CODES   -> FAIL, result_dict["reason"] names the cause
    The coordinator's dispatcher is expected to print(json.dumps(result_dict))
    and use exit_code as (or to derive) the process exit status, exactly as
    fabric_topology_completeness_gate.py does today for the AMBA4 case.
  - Malformed/hand-edited evidence (wrong element types, unhashable values in
    what should be a flat id list, etc.) must never crash the shared
    dispatcher -- it must come back as a clean FAIL, never an exception.

Grounding (MIPI Alliance Specification for Display Serial Interface (DSI)):
  - Two Operation Modes: Video Mode and Command Mode.
  - Video Mode Interface defines three transmission types: Non-Burst with
    Sync Pulses, Non-Burst with Sync Events, Burst.
  - Packet Header carries a Virtual Channel Identifier (2-bit field -> VC 0..3
    in the base spec) and a 6-bit Data Type field (0x00-0x3F).
  - Peripheral-to-Processor (read) transactions require a Bus Turn-Around
    (BTA) / Link Turn-Around on the physical link before the peripheral can
    drive data back to the host.
  - D-PHY: exactly one Clock Lane plus up to 4 Data Lanes, numbered 0-3; only
    Data Lane 0 is a bidirectional lane module (Forward + Reverse capable) --
    Lanes 1-3 are Forward-only, so BTA/read traffic is only ever carried on
    Lane 0.
  - C-PHY: no separate clock lane (clock is embedded in the 3-phase symbol
    stream); lanes are wire "trios", typically 1-3 trios. C-PHY does not have
    the same single-lane bidirectional restriction as D-PHY, so this checker
    does NOT enforce a lane-id constraint on C-PHY BTA entries (see NOTE in
    the BTA section) -- that would require PHY-level semantic judgment this
    checker deliberately does not make. It still checks that a C-PHY BTA
    entry references a lane that is actually declared active (a structural
    fact, not a semantic one).

Fix log (post adversarial-verify NO-GO, must-fix items only):
  - #1: D-PHY lane numbering was internally inconsistent -- the docstring and
    the BTA "==0" rule both assumed 0-indexed lanes (0-3, lane 0 bidirectional)
    but DPHY_LANE_RANGE_DSI was 1-indexed (range(1,5) -> {1,2,3,4}), so lane 0
    could never appear in active_lanes/lane_coverage at all. Fixed:
    DPHY_LANE_RANGE_DSI = range(0, 4). The example payload is regenerated to use
    0-indexed active_lanes/lane_coverage accordingly.
  - #2: A bta_coverage entry's lane_id was never cross-checked against the
    declared active_lanes/lane_set, so a BTA attributed to a lane that was
    never even declared active passed silently (exactly what the buggy
    example did). Fixed: added an explicit lane_id-in-lane_set check for
    every bta_coverage entry (both PHY types -- this part is structural, not
    a semantic judgment call), before the D-PHY-only "must be lane 0" rule.
  - #3: Malformed evidence (e.g. active_vcs containing an unhashable element
    such as a nested list) crashed with an uncaught TypeError instead of
    returning a clean FAIL, because set()-based dedup ran before any
    type validation. Fixed: the whole structural-check body now runs inside
    a try/except that turns TypeError/AttributeError from malformed evidence
    shapes into a MALFORMED_EVIDENCE FAIL instead of propagating.
"""

VALID_STATUSES_DSI = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}
VALID_MODES_DSI = {"VIDEO", "COMMAND"}
VALID_VIDEO_MODE_TYPES_DSI = {"NON_BURST_SYNC_PULSE", "NON_BURST_SYNC_EVENT", "BURST"}
VALID_PHY_TYPES_DSI = {"D-PHY", "C-PHY"}
MAX_VC_ID_DSI = 3          # 2-bit Virtual Channel Identifier -> VC0..VC3
MAX_DT_CODE_DSI = 0x3F      # 6-bit Data Type field
DPHY_LANE_RANGE_DSI = range(0, 4)   # 4 data lanes, numbered 0-3; lane 0 is the sole bidirectional lane
CPHY_LANE_RANGE_DSI = range(1, 4)   # up to 3 trios


def _waiver_ok_dsi(entry):
    return bool(entry.get("waiver_approved")) and bool(entry.get("waiver_evidence"))


def check_mipi_dsi(d):
    # ---- applicability escape hatch (mirrors fabric_topology_completeness_gate.py) ----
    if d.get("dsi_completeness_applicable") is False:
        reason = d.get("dsi_not_applicable_reason")
        if not reason:
            return ({"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}, 1)
        return ({"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}, 0)

    required_top = ["phy_type", "supported_modes", "active_vcs", "expected_data_types",
                     "vc_datatype_matrix", "active_lanes", "lane_coverage"]
    missing = [k for k in required_top if k not in d]
    if missing:
        return ({"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing}, 2)

    try:
        return _check_mipi_dsi_impl(d)
    except (TypeError, AttributeError) as exc:
        # Malformed/hand-edited evidence (e.g. an unhashable element where a
        # flat id list was expected, or a non-dict entry where an object was
        # expected) must not be able to crash a shared multi-protocol
        # dispatcher -- report it as a structural FAIL instead.
        return ({"status": "FAIL", "reason": "MALFORMED_EVIDENCE",
                  "detail": "%s: %s" % (type(exc).__name__, exc)}, 41)


def _check_mipi_dsi_impl(d):
    phy_type = d.get("phy_type")
    if phy_type not in VALID_PHY_TYPES_DSI:
        return ({"status": "FAIL", "reason": "INVALID_PHY_TYPE", "phy_type": phy_type}, 3)

    # =========================================================
    # 1) Command-mode vs Video-mode coverage completeness
    # =========================================================
    supported_modes = d.get("supported_modes") or []
    if not supported_modes:
        return ({"status": "FAIL", "reason": "NO_SUPPORTED_MODES"}, 4)
    if len(set(supported_modes)) != len(supported_modes):
        dup = sorted({m for m in supported_modes if supported_modes.count(m) > 1})
        return ({"status": "FAIL", "reason": "DUPLICATE_MODE", "duplicates": dup}, 5)
    unknown_modes = sorted(set(supported_modes) - VALID_MODES_DSI)
    if unknown_modes:
        return ({"status": "FAIL", "reason": "UNKNOWN_MODE", "modes": unknown_modes}, 6)

    mode_coverage = d.get("mode_coverage") or []
    seen_modes = {}
    for i, entry in enumerate(mode_coverage):
        mode = entry.get("mode")
        status = entry.get("status")
        if mode not in set(supported_modes):
            return ({"status": "FAIL", "reason": "UNKNOWN_MODE_IN_COVERAGE", "index": i, "mode": mode}, 7)
        if status not in VALID_STATUSES_DSI:
            return ({"status": "FAIL", "reason": "INVALID_MODE_COVERAGE_STATUS",
                      "index": i, "mode": mode, "status": status}, 8)
        if status in ("WAIVED", "NOT_APPLICABLE") and not _waiver_ok_dsi(entry):
            return ({"status": "FAIL", "reason": "UNAPPROVED_MODE_COVERAGE_WAIVER", "mode": mode}, 9)
        if mode in seen_modes:
            return ({"status": "FAIL", "reason": "DUPLICATE_MODE_COVERAGE_ENTRY", "mode": mode}, 10)
        seen_modes[mode] = status

    missing_modes = sorted(set(supported_modes) - set(seen_modes))
    if missing_modes:
        return ({"status": "FAIL", "reason": "MISSING_MODE_COVERAGE", "modes": missing_modes}, 11)

    # Video mode sub-type (Non-Burst Sync Pulse / Non-Burst Sync Event / Burst)
    video_mode_type_checked = False
    if "VIDEO" in supported_modes:
        video_mode_type_checked = True
        vmt = d.get("video_mode_type")
        if vmt not in VALID_VIDEO_MODE_TYPES_DSI:
            return ({"status": "FAIL", "reason": "INVALID_VIDEO_MODE_TYPE", "video_mode_type": vmt}, 12)
        vmt_cov = d.get("video_mode_type_coverage") or []
        match = [e for e in vmt_cov if e.get("video_mode_type") == vmt]
        if not match:
            return ({"status": "FAIL", "reason": "MISSING_VIDEO_MODE_TYPE_COVERAGE", "video_mode_type": vmt}, 13)
        vmt_entry = match[0]
        if vmt_entry.get("status") not in VALID_STATUSES_DSI:
            return ({"status": "FAIL", "reason": "INVALID_VIDEO_MODE_TYPE_COVERAGE_STATUS",
                      "video_mode_type": vmt, "status": vmt_entry.get("status")}, 14)
        if vmt_entry.get("status") in ("WAIVED", "NOT_APPLICABLE") and not _waiver_ok_dsi(vmt_entry):
            return ({"status": "FAIL", "reason": "UNAPPROVED_VIDEO_MODE_TYPE_WAIVER", "video_mode_type": vmt}, 15)

    # =========================================================
    # 2) Virtual Channel x Data Type completeness (Packet Header: VC id + DT)
    # =========================================================
    active_vcs = d.get("active_vcs") or []
    if not active_vcs:
        return ({"status": "FAIL", "reason": "NO_ACTIVE_VCS"}, 16)
    # Type/range validation MUST run before any set()-based dedup check: an
    # unhashable element (e.g. a nested list from hand-edited JSON) would
    # otherwise crash `set(active_vcs)` before we get a chance to reject it
    # cleanly. `or` short-circuits so `v < 0`/`v > MAX_VC_ID_DSI` are never
    # evaluated on a non-int v.
    bad_vcs = sorted(
        (v for v in active_vcs if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > MAX_VC_ID_DSI),
        key=repr,
    )
    if bad_vcs:
        return ({"status": "FAIL", "reason": "VC_ID_OUT_OF_RANGE", "invalid": bad_vcs,
                  "max_vc_id": MAX_VC_ID_DSI}, 18)
    if len(set(active_vcs)) != len(active_vcs):
        dup = sorted({v for v in active_vcs if active_vcs.count(v) > 1})
        return ({"status": "FAIL", "reason": "DUPLICATE_VC_ID", "duplicates": dup}, 17)

    expected_dt = d.get("expected_data_types") or {}
    vc_set = set(active_vcs)
    expected_pairs = set()
    for vc in active_vcs:
        dts = expected_dt.get(str(vc), expected_dt.get(vc))
        if not dts:
            return ({"status": "FAIL", "reason": "NO_EXPECTED_DATA_TYPES_FOR_VC", "vc": vc}, 19)
        if len(set(dts)) != len(dts):
            return ({"status": "FAIL", "reason": "DUPLICATE_EXPECTED_DATA_TYPE", "vc": vc}, 20)
        for dt in dts:
            expected_pairs.add((vc, dt))

    matrix = d.get("vc_datatype_matrix") or []
    seen_pairs = {}
    read_pairs = []
    for i, entry in enumerate(matrix):
        vc = entry.get("vc")
        dt = entry.get("data_type")
        status = entry.get("status")
        is_read = entry.get("is_read")
        dt_code = entry.get("dt_code")
        if vc not in vc_set:
            return ({"status": "FAIL", "reason": "UNKNOWN_VC_IN_MATRIX", "index": i, "vc": vc}, 21)
        allowed_dts = expected_dt.get(str(vc), expected_dt.get(vc)) or []
        if dt not in allowed_dts:
            return ({"status": "FAIL", "reason": "UNEXPECTED_DATA_TYPE_IN_MATRIX",
                      "index": i, "vc": vc, "data_type": dt}, 22)
        if dt_code is not None and (not isinstance(dt_code, int) or dt_code < 0 or dt_code > MAX_DT_CODE_DSI):
            return ({"status": "FAIL", "reason": "DATA_TYPE_CODE_OUT_OF_RANGE",
                      "index": i, "vc": vc, "data_type": dt, "dt_code": dt_code,
                      "max_dt_code": MAX_DT_CODE_DSI}, 23)
        if status not in VALID_STATUSES_DSI:
            return ({"status": "FAIL", "reason": "INVALID_VC_DATATYPE_STATUS",
                      "index": i, "vc": vc, "data_type": dt, "status": status}, 24)
        if status in ("WAIVED", "NOT_APPLICABLE") and not _waiver_ok_dsi(entry):
            return ({"status": "FAIL", "reason": "UNAPPROVED_VC_DATATYPE_WAIVER",
                      "vc": vc, "data_type": dt}, 25)
        if not isinstance(is_read, bool):
            return ({"status": "FAIL", "reason": "MISSING_IS_READ_FLAG", "index": i,
                      "vc": vc, "data_type": dt}, 26)
        pair = (vc, dt)
        if pair in seen_pairs:
            return ({"status": "FAIL", "reason": "DUPLICATE_VC_DATATYPE_ENTRY", "vc": vc, "data_type": dt}, 27)
        seen_pairs[pair] = status
        if is_read:
            read_pairs.append(pair)

    missing_pairs = sorted(expected_pairs - set(seen_pairs))
    if missing_pairs:
        return ({"status": "FAIL", "reason": "MISSING_VC_DATATYPE_PAIRS",
                  "expected_pair_count": len(expected_pairs),
                  "missing_pairs": [f"VC{v}->{t}" for v, t in missing_pairs]}, 28)

    # =========================================================
    # 3) Lane completeness + Bus-Turn-Around (BTA) completeness for reads
    # =========================================================
    active_lanes = d.get("active_lanes") or []
    if not active_lanes:
        return ({"status": "FAIL", "reason": "NO_ACTIVE_LANES"}, 29)
    valid_lane_range = DPHY_LANE_RANGE_DSI if phy_type == "D-PHY" else CPHY_LANE_RANGE_DSI
    # Same ordering fix as active_vcs above: validate type/range (no hashing
    # involved) before the set()-based dedup check.
    bad_lanes = sorted(
        (l for l in active_lanes if not isinstance(l, int) or isinstance(l, bool) or l not in valid_lane_range),
        key=repr,
    )
    if bad_lanes:
        return ({"status": "FAIL", "reason": "LANE_ID_OUT_OF_RANGE", "invalid": bad_lanes,
                  "phy_type": phy_type, "valid_range": [valid_lane_range.start, valid_lane_range.stop - 1]}, 31)
    if len(set(active_lanes)) != len(active_lanes):
        dup = sorted({l for l in active_lanes if active_lanes.count(l) > 1})
        return ({"status": "FAIL", "reason": "DUPLICATE_LANE_ID", "duplicates": dup}, 30)

    lane_coverage = d.get("lane_coverage") or []
    lane_set = set(active_lanes)
    seen_lanes = {}
    for i, entry in enumerate(lane_coverage):
        lane_id = entry.get("lane_id")
        status = entry.get("status")
        if lane_id not in lane_set:
            return ({"status": "FAIL", "reason": "UNKNOWN_LANE_IN_COVERAGE", "index": i, "lane_id": lane_id}, 32)
        if status not in VALID_STATUSES_DSI:
            return ({"status": "FAIL", "reason": "INVALID_LANE_COVERAGE_STATUS",
                      "index": i, "lane_id": lane_id, "status": status}, 33)
        if status in ("WAIVED", "NOT_APPLICABLE") and not _waiver_ok_dsi(entry):
            return ({"status": "FAIL", "reason": "UNAPPROVED_LANE_COVERAGE_WAIVER", "lane_id": lane_id}, 34)
        if lane_id in seen_lanes:
            return ({"status": "FAIL", "reason": "DUPLICATE_LANE_COVERAGE_ENTRY", "lane_id": lane_id}, 35)
        seen_lanes[lane_id] = status

    missing_lanes = sorted(lane_set - set(seen_lanes))
    if missing_lanes:
        return ({"status": "FAIL", "reason": "MISSING_LANE_COVERAGE", "lanes": missing_lanes}, 36)

    # BTA is required iff at least one declared VC/DT pair is a read (Peripheral->
    # Processor) transaction -- reads cannot complete on a DSI link without a
    # Bus Turn-Around, regardless of which mode issued them.
    bta_required = len(read_pairs) > 0
    bta_lane_constraint_checked = False
    if bta_required:
        bta_coverage = d.get("bta_coverage") or []
        if not bta_coverage:
            return ({"status": "FAIL", "reason": "MISSING_BTA_COVERAGE",
                      "read_pairs": [f"VC{v}->{t}" for v, t in read_pairs]}, 37)
        for i, entry in enumerate(bta_coverage):
            status = entry.get("status")
            lane_id = entry.get("lane_id")
            if status not in VALID_STATUSES_DSI:
                return ({"status": "FAIL", "reason": "INVALID_BTA_COVERAGE_STATUS", "index": i, "status": status}, 38)
            if status in ("WAIVED", "NOT_APPLICABLE") and not _waiver_ok_dsi(entry):
                return ({"status": "FAIL", "reason": "UNAPPROVED_BTA_COVERAGE_WAIVER", "index": i}, 39)
            # Structural cross-check (both PHY types): a BTA entry must
            # reference a lane that was actually declared active -- a BTA
            # attributed to a lane nobody declared is a real inconsistency,
            # not a semantic judgment call.
            if lane_id not in lane_set:
                return ({"status": "FAIL", "reason": "BTA_LANE_NOT_ACTIVE", "index": i,
                          "lane_id": lane_id, "active_lanes": sorted(lane_set)}, 42)
            if phy_type == "D-PHY":
                # Only Data Lane 0 is a bidirectional lane module on D-PHY; BTA/read
                # traffic cannot legally be attributed to lanes 1-3.
                bta_lane_constraint_checked = True
                if lane_id != 0:
                    return ({"status": "FAIL", "reason": "BTA_ON_NON_BIDIRECTIONAL_LANE",
                              "index": i, "lane_id": lane_id,
                              "note": "D-PHY BTA/read traffic is restricted to Data Lane 0"}, 40)
            # C-PHY: deliberately NOT enforcing a "must be lane X" constraint here
            # -- see module docstring NOTE. Presence/status/waiver and the
            # active-lane cross-check above are still enforced.

    return ({
        "status": "PASS",
        "phy_type": phy_type,
        "modes": sorted(supported_modes),
        "video_mode_type_checked": video_mode_type_checked,
        "vc_count": len(active_vcs),
        "vc_datatype_pairs": len(expected_pairs),
        "lane_count": len(active_lanes),
        "bta_required": bta_required,
        "bta_lane_constraint_checked": bta_lane_constraint_checked,
    }, 0)

VALID_STATUSES_CSI2 = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}

DT_FRAME_START_CSI2 = 0x00
DT_FRAME_END_CSI2 = 0x01
# 0x02 (Line Start) / 0x03 (Line End) ARE standard entries in the CSI-2
# short-packet Data Type table (spec-defined) -- they are simply optional
# and rarely implemented in practice, because a line's extent is normally
# inferred from the enclosing Long Packet's Word Count instead of an
# explicit bracket. They are not "vendor-defined" values; they are a real,
# fixed DT assignment that most DUT/VIP profiles just don't emit. That is
# why LS/LE nesting is only checked when the payload explicitly declares
# line_marker_mode == EXPLICIT_LS_LE -- gating on profile evidence of the
# mechanism being used, not on any ambiguity about what the DT codes mean.
DT_LINE_START_CSI2 = 0x02   # only checked when line_marker_mode == EXPLICIT_LS_LE
DT_LINE_END_CSI2 = 0x03
LONG_PACKET_DT_FLOOR_CSI2 = 0x10   # DT>=0x10 is "long packet" DT-code space
MAX_DT_CSI2 = 0x3F

ECC_CLASSES_CSI2 = {"ECC_SINGLE_BIT_CORRECTED", "ECC_DOUBLE_BIT_DETECTED"}
CRC_CLASSES_CSI2 = {"CRC_MISMATCH_DETECTED"}
SHORT_ERROR_CLASSES_CSI2 = ECC_CLASSES_CSI2
LONG_ERROR_CLASSES_CSI2 = ECC_CLASSES_CSI2 | CRC_CLASSES_CSI2


def _parse_code_csi2(v):
    if isinstance(v, bool):
        raise ValueError("bool is not a valid code")
    if isinstance(v, int):
        return v
    return int(str(v).strip(), 0)


def _packet_class_csi2(dt):
    return "SHORT" if dt < LONG_PACKET_DT_FLOOR_CSI2 else "LONG"


def _waiver_ok_csi2(entry):
    return bool(entry.get("waiver_approved")) and bool(entry.get("waiver_evidence"))


def check_mipi_csi2(d):
    """
    Returns (result_dict, exit_code); exit_code 0 <=> status in
    {"PASS","SKIPPED_NOT_APPLICABLE"}. Coordinator does:
        result, code = check_mipi_csi2(d); print(json.dumps(result)); return code
    Checks: (A) VC x DT matrix completeness, (B) Frame Start/End nesting per
    VC (+ optional Line Start/End when declared), with every frame-sequence
    event's DT required to be a member of the declared active_dts alphabet,
    (C) ECC/CRC error-class coverage keyed off packet class (SHORT vs LONG
    derived from DT value).
    """
    if d.get("csi2_not_applicable") is True:
        reason = d.get("csi2_not_applicable_reason")
        if not reason:
            return ({"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}, 1)
        return ({"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}, 0)

    required_top = ["active_vcs", "active_dts", "vc_dt_matrix", "frame_sequences", "error_injection_matrix"]
    missing = [k for k in required_top if k not in d]
    if missing:
        return ({"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing}, 2)

    raw_vcs = d.get("active_vcs") or []
    raw_dts = d.get("active_dts") or []
    vc_dt_matrix = d.get("vc_dt_matrix") or []
    frame_sequences = d.get("frame_sequences") or {}
    error_matrix = d.get("error_injection_matrix") or []
    line_marker_mode = d.get("line_marker_mode", "NONE")

    if not raw_vcs:
        return ({"status": "FAIL", "reason": "NO_ACTIVE_VCS"}, 3)
    if not raw_dts:
        return ({"status": "FAIL", "reason": "NO_ACTIVE_DTS"}, 4)

    try:
        vcs = [_parse_code_csi2(v) for v in raw_vcs]
    except Exception:
        return ({"status": "FAIL", "reason": "UNPARSEABLE_VC", "active_vcs": raw_vcs}, 5)
    try:
        dts = [_parse_code_csi2(v) for v in raw_dts]
    except Exception:
        return ({"status": "FAIL", "reason": "UNPARSEABLE_DT", "active_dts": raw_dts}, 6)

    if len(set(vcs)) != len(vcs):
        dup = sorted({v for v in vcs if vcs.count(v) > 1})
        return ({"status": "FAIL", "reason": "DUPLICATE_VC", "duplicates": dup}, 7)
    if len(set(dts)) != len(dts):
        dup = sorted({x for x in dts if dts.count(x) > 1})
        return ({"status": "FAIL", "reason": "DUPLICATE_DT", "duplicates": [hex(x) for x in dup]}, 8)

    out_of_range = sorted(x for x in dts if x < 0 or x > MAX_DT_CSI2)
    if out_of_range:
        return ({"status": "FAIL", "reason": "DT_OUT_OF_RANGE", "max_dt": hex(MAX_DT_CSI2),
                  "offending": [hex(x) for x in out_of_range]}, 9)

    vc_set, dt_set = set(vcs), set(dts)
    dt_class = {dt: _packet_class_csi2(dt) for dt in dts}

    # A. VC x DT coverage matrix
    expected_vc_dt = {(vc, dt) for vc in vcs for dt in dts}
    seen_vc_dt = {}
    for i, entry in enumerate(vc_dt_matrix):
        try:
            vc = _parse_code_csi2(entry.get("vc")); dt = _parse_code_csi2(entry.get("dt"))
        except Exception:
            return ({"status": "FAIL", "reason": "UNPARSEABLE_VC_DT_MATRIX_ENTRY", "index": i}, 10)
        status = entry.get("status")
        if vc not in vc_set:
            return ({"status": "FAIL", "reason": "UNKNOWN_VC_IN_VC_DT_MATRIX", "index": i, "vc": vc}, 11)
        if dt not in dt_set:
            return ({"status": "FAIL", "reason": "UNKNOWN_DT_IN_VC_DT_MATRIX", "index": i, "dt": hex(dt)}, 12)
        if status not in VALID_STATUSES_CSI2:
            return ({"status": "FAIL", "reason": "INVALID_VC_DT_STATUS", "index": i,
                      "vc": vc, "dt": hex(dt), "status": status}, 13)
        if status in ("WAIVED", "NOT_APPLICABLE") and not _waiver_ok_csi2(entry):
            return ({"status": "FAIL", "reason": "UNAPPROVED_VC_DT_WAIVER", "vc": vc, "dt": hex(dt)}, 14)
        pair = (vc, dt)
        if pair in seen_vc_dt:
            return ({"status": "FAIL", "reason": "DUPLICATE_VC_DT_ENTRY", "vc": vc, "dt": hex(dt)}, 15)
        seen_vc_dt[pair] = status

    missing_vc_dt = sorted(expected_vc_dt - set(seen_vc_dt))
    if missing_vc_dt:
        return ({"status": "FAIL", "reason": "MISSING_VC_DT_PAIRS", "expected_pair_count": len(expected_vc_dt),
                  "missing_pairs": [f"vc{vc}/dt{hex(dt)}" for vc, dt in missing_vc_dt]}, 16)

    # B. Frame Start/End nesting per VC (+ optional Line Start/End)
    if line_marker_mode not in ("NONE", "EXPLICIT_LS_LE"):
        return ({"status": "FAIL", "reason": "INVALID_LINE_MARKER_MODE", "line_marker_mode": line_marker_mode}, 17)

    missing_seq_vcs = sorted(vc for vc in vcs if str(vc) not in frame_sequences and vc not in frame_sequences)
    if missing_seq_vcs:
        return ({"status": "FAIL", "reason": "MISSING_FRAME_SEQUENCE_FOR_VC", "vcs": missing_seq_vcs}, 18)

    for vc in vcs:
        key = str(vc) if str(vc) in frame_sequences else vc
        events = frame_sequences.get(key) or []
        frame_state = "CLOSED"; line_state = "CLOSED"
        for idx, ev in enumerate(events):
            try:
                edt = _parse_code_csi2(ev.get("dt"))
            except Exception:
                return ({"status": "FAIL", "reason": "UNPARSEABLE_FRAME_SEQUENCE_EVENT", "vc": vc, "index": idx}, 19)

            # MUST-FIX: every frame-sequence event's DT has to be a member of
            # the declared active_dts alphabet (dt_set). Previously only
            # 0x00/0x01(/0x02/0x03) were ever inspected and anything else
            # silently fell through "else: continue" with no validation at
            # all -- not even a 6-bit range check -- letting undeclared or
            # out-of-range DTs (e.g. "0x99", -5, 999999) pass straight
            # through as PASS. This closes that hole the same way
            # vc_dt_matrix/error_injection_matrix already validate their
            # entries against dt_set.
            if edt not in dt_set:
                return ({"status": "FAIL", "reason": "UNDECLARED_DT_IN_FRAME_SEQUENCE",
                          "vc": vc, "index": idx, "dt": hex(edt) if 0 <= edt <= 0xFFFFFFFF else edt}, 37)

            if edt == DT_FRAME_START_CSI2:
                if frame_state == "OPEN":
                    return ({"status": "FAIL", "reason": "FRAME_START_WITHOUT_PRIOR_FRAME_END", "vc": vc, "index": idx}, 20)
                frame_state = "OPEN"; line_state = "CLOSED"
            elif edt == DT_FRAME_END_CSI2:
                if frame_state == "CLOSED":
                    return ({"status": "FAIL", "reason": "FRAME_END_WITHOUT_FRAME_START", "vc": vc, "index": idx}, 21)
                if line_marker_mode == "EXPLICIT_LS_LE" and line_state == "OPEN":
                    return ({"status": "FAIL", "reason": "FRAME_END_WITH_LINE_STILL_OPEN", "vc": vc, "index": idx}, 22)
                frame_state = "CLOSED"
            elif line_marker_mode == "EXPLICIT_LS_LE" and edt == DT_LINE_START_CSI2:
                if frame_state != "OPEN":
                    return ({"status": "FAIL", "reason": "LINE_START_OUTSIDE_FRAME", "vc": vc, "index": idx}, 23)
                if line_state == "OPEN":
                    return ({"status": "FAIL", "reason": "LINE_START_WITHOUT_PRIOR_LINE_END", "vc": vc, "index": idx}, 24)
                line_state = "OPEN"
            elif line_marker_mode == "EXPLICIT_LS_LE" and edt == DT_LINE_END_CSI2:
                if line_state == "CLOSED":
                    return ({"status": "FAIL", "reason": "LINE_END_WITHOUT_LINE_START", "vc": vc, "index": idx}, 25)
                line_state = "CLOSED"
            else:
                continue  # long-packet pixel data / generic codes: no bracket semantics

        if frame_state == "OPEN":
            return ({"status": "FAIL", "reason": "UNCLOSED_FRAME_AT_SEQUENCE_END", "vc": vc}, 26)
        if line_marker_mode == "EXPLICIT_LS_LE" and line_state == "OPEN":
            return ({"status": "FAIL", "reason": "UNCLOSED_LINE_AT_SEQUENCE_END", "vc": vc}, 27)

    # C. ECC/CRC error-class coverage, keyed off packet class
    expected_errors = set()
    for vc in vcs:
        for dt in dts:
            classes = SHORT_ERROR_CLASSES_CSI2 if dt_class[dt] == "SHORT" else LONG_ERROR_CLASSES_CSI2
            for ec in classes:
                expected_errors.add((vc, dt, ec))

    seen_errors = {}
    for i, entry in enumerate(error_matrix):
        try:
            vc = _parse_code_csi2(entry.get("vc")); dt = _parse_code_csi2(entry.get("dt"))
        except Exception:
            return ({"status": "FAIL", "reason": "UNPARSEABLE_ERROR_MATRIX_ENTRY", "index": i}, 28)
        ec = entry.get("error_class"); status = entry.get("status")
        if vc not in vc_set:
            return ({"status": "FAIL", "reason": "UNKNOWN_VC_IN_ERROR_MATRIX", "index": i, "vc": vc}, 29)
        if dt not in dt_set:
            return ({"status": "FAIL", "reason": "UNKNOWN_DT_IN_ERROR_MATRIX", "index": i, "dt": hex(dt)}, 30)
        allowed = SHORT_ERROR_CLASSES_CSI2 if dt_class[dt] == "SHORT" else LONG_ERROR_CLASSES_CSI2
        if ec not in (ECC_CLASSES_CSI2 | CRC_CLASSES_CSI2):
            return ({"status": "FAIL", "reason": "UNKNOWN_ERROR_CLASS", "index": i, "error_class": ec}, 31)
        if ec not in allowed:
            return ({"status": "FAIL", "reason": "ERROR_CLASS_NOT_APPLICABLE_TO_PACKET_CLASS",
                      "vc": vc, "dt": hex(dt), "packet_class": dt_class[dt], "error_class": ec}, 32)
        if status not in VALID_STATUSES_CSI2:
            return ({"status": "FAIL", "reason": "INVALID_ERROR_MATRIX_STATUS", "index": i,
                      "vc": vc, "dt": hex(dt), "error_class": ec, "status": status}, 33)
        if status in ("WAIVED", "NOT_APPLICABLE") and not _waiver_ok_csi2(entry):
            return ({"status": "FAIL", "reason": "UNAPPROVED_ERROR_MATRIX_WAIVER",
                      "vc": vc, "dt": hex(dt), "error_class": ec}, 34)
        key = (vc, dt, ec)
        if key in seen_errors:
            return ({"status": "FAIL", "reason": "DUPLICATE_ERROR_MATRIX_ENTRY",
                      "vc": vc, "dt": hex(dt), "error_class": ec}, 35)
        seen_errors[key] = status

    missing_errors = sorted(expected_errors - set(seen_errors))
    if missing_errors:
        return ({"status": "FAIL", "reason": "MISSING_ERROR_MATRIX_ENTRIES", "expected_entry_count": len(expected_errors),
                  "missing": [f"vc{vc}/dt{hex(dt)}/{ec}" for vc, dt, ec in missing_errors]}, 36)

    return ({"status": "PASS", "active_vcs": len(vcs), "active_dts": len(dts),
              "vc_dt_pairs": len(expected_vc_dt), "frame_sequences_checked": len(vcs),
              "error_matrix_entries": len(expected_errors)}, 0)

"""
Ethernet MAC (+ optional PHY) structural completeness dispatch-case checker.

Fixed version -- see adversarial verify report must-fix items 1-4 (frame-type/
size-class enums only upper-bounded, VLAN max-tagged-size key mismatch, VLAN
axis conflated with size-boundary axis, and unguarded dict/list shape
assumptions that could raise instead of returning a FAIL dict).
"""

FRAME_TYPES = {"UNICAST", "MULTICAST", "BROADCAST"}
# VLAN_TAGGED removed from this enum -- it is not a size boundary, it is an
# independent tag-presence property (must-fix #3). Size-boundary classes only:
SIZE_CLASSES = {"MIN_SIZE", "MAX_SIZE", "JUMBO"}
# New independent axis: is the frame VLAN-tagged or not (must-fix #3).
TAG_CLASSES = {"UNTAGGED", "VLAN_TAGGED"}
VALID_STATUSES = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}
POSITION_CLASSES = {"NORMAL", "WRAP_BOUNDARY"}

# Size classes that are structurally mandatory once a payload declares a
# frame_matrix at all -- every MAC must define its min/max frame boundary
# (must-fix #1). JUMBO stays optional (non-standard vendor extension).
MANDATORY_SIZE_CLASSES = {"MIN_SIZE", "MAX_SIZE"}
# Every MAC must at minimum support untagged frames; VLAN tagging is optional
# (must-fix #1 / #3).
MANDATORY_TAG_CLASSES = {"UNTAGGED"}


def check_ethernet(d):
    """
    Convention (for the shared dispatcher):
      Returns (result: dict, code: int).
      code == 0  -> PASS or SKIPPED_NOT_APPLICABLE (result["status"] names which)
      code != 0  -> FAIL; result["reason"] is a stable machine-readable string,
                    plus whatever context fields the branch attaches.
      This function performs no I/O, no argparse, no sys.exit -- `d` is the
      already-parsed JSON payload dict for a single dv-harness-evidence block
      with "protocol": "ethernet". The integer codes are only unique within
      this function; the dispatcher may remap/ignore them and rely on
      result["status"]/result["reason"] instead.

    Deterministic structural checks only -- no RTL semantic judgment.
    """

    def waived_ok(entry):
        return entry.get("status") not in ("WAIVED", "NOT_APPLICABLE") or (
            entry.get("waiver_approved") and entry.get("waiver_evidence")
        )

    def fail(reason, code, **ctx):
        r = {"status": "FAIL", "reason": reason}
        r.update(ctx)
        return r, code

    # ---- must-fix #4: guard the top-level shape before touching it ----
    if not isinstance(d, dict):
        return fail("MALFORMED_INPUT", 1, got_type=type(d).__name__)

    # ---- top-level applicability gate ----
    if d.get("ethernet_applicable") is False:
        reason = d.get("ethernet_not_applicable_reason")
        if not reason:
            return fail("NOT_APPLICABLE_WITHOUT_JUSTIFICATION", 2)
        return {"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}, 0

    required_top = ["descriptor_rings", "frame_matrix", "flow_control"]
    missing = [k for k in required_top if k not in d]
    if missing:
        return fail("MISSING_FIELDS", 3, missing=missing)

    # =====================================================================
    # Candidate 1: TX/RX descriptor ring state completeness
    # =====================================================================
    rings = d.get("descriptor_rings") or {}
    if not isinstance(rings, dict):
        return fail("MALFORMED_DESCRIPTOR_RINGS", 4, got_type=type(rings).__name__)
    if not rings:
        return fail("NO_DESCRIPTOR_RINGS", 5)

    for ring_name, ring in rings.items():
        if not isinstance(ring, dict):
            return fail("MALFORMED_RING", 6, ring=ring_name, got_type=type(ring).__name__)

        req = ["ring_size", "descriptors", "own_states", "error_flags", "coverage_matrix"]
        rmiss = [k for k in req if k not in ring]
        if rmiss:
            return fail("RING_MISSING_FIELDS", 7, ring=ring_name, missing=rmiss)

        size = ring["ring_size"]
        descs = ring["descriptors"] or []
        own_states = ring["own_states"] or []
        error_flags_raw = ring["error_flags"] or []
        cov = ring["coverage_matrix"] or []

        if not isinstance(descs, list):
            return fail("MALFORMED_DESCRIPTOR_LIST", 8, ring=ring_name, got_type=type(descs).__name__)
        if not isinstance(cov, list):
            return fail("MALFORMED_RING_COVERAGE_LIST", 9, ring=ring_name, got_type=type(cov).__name__)
        if not isinstance(own_states, list):
            return fail("MALFORMED_OWN_STATES", 10, ring=ring_name, got_type=type(own_states).__name__)
        if not isinstance(error_flags_raw, list):
            return fail("MALFORMED_ERROR_FLAGS", 11, ring=ring_name, got_type=type(error_flags_raw).__name__)

        error_flags = set(error_flags_raw)

        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            return fail("INVALID_RING_SIZE", 12, ring=ring_name, ring_size=size)
        if len(descs) != size:
            return fail("RING_LENGTH_MISMATCH", 13, ring=ring_name,
                        declared_size=size, descriptor_count=len(descs))

        seen_idx = {}
        wrap_count = 0
        own_set = set(own_states)
        for i, desc in enumerate(descs):
            if not isinstance(desc, dict):
                return fail("MALFORMED_DESCRIPTOR_ENTRY", 14, ring=ring_name, at=i,
                            got_type=type(desc).__name__)
            idx = desc.get("index")
            own = desc.get("own")
            wrap = desc.get("wrap")
            dflags = set(desc.get("error_flags") or [])
            if idx is None or idx in seen_idx:
                return fail("DUPLICATE_OR_MISSING_RING_INDEX", 15,
                            ring=ring_name, at=i, index=idx)
            seen_idx[idx] = desc
            if own not in own_set:
                return fail("INVALID_OWN_STATE", 16, ring=ring_name, index=idx, own=own)
            if not isinstance(wrap, bool):
                return fail("MISSING_WRAP_BIT", 17, ring=ring_name, index=idx)
            if wrap:
                wrap_count += 1
            unknown_flags = dflags - error_flags
            if unknown_flags:
                return fail("UNKNOWN_ERROR_FLAG", 18, ring=ring_name, index=idx,
                            unknown_flags=sorted(unknown_flags))

        expected_idx = set(range(size))
        if set(seen_idx) != expected_idx:
            return fail("RING_INDEX_GAP", 19, ring=ring_name, expected=size,
                        missing_indices=sorted(expected_idx - set(seen_idx)))
        if wrap_count != 1:
            return fail("RING_WRAP_NOT_UNIQUE", 20, ring=ring_name, wrap_count=wrap_count)

        # ring-state coverage cross product: own_state x position_class x (error_flag|NONE)
        expected_combo = {
            (o, p, f)
            for o in own_states
            for p in POSITION_CLASSES
            for f in (sorted(error_flags) + ["NONE"])
        }
        seen_combo = {}
        for i, entry in enumerate(cov):
            if not isinstance(entry, dict):
                return fail("MALFORMED_RING_COVERAGE_ENTRY", 21, ring=ring_name, index=i,
                            got_type=type(entry).__name__)
            o = entry.get("own_state")
            p = entry.get("position_class")
            f = entry.get("error_flag")
            status = entry.get("status")
            if o not in own_set:
                return fail("UNKNOWN_OWN_STATE_IN_COVERAGE", 22, ring=ring_name, index=i, own_state=o)
            if p not in POSITION_CLASSES:
                return fail("UNKNOWN_POSITION_CLASS_IN_COVERAGE", 23, ring=ring_name, index=i, position_class=p)
            if f != "NONE" and f not in error_flags:
                return fail("UNKNOWN_ERROR_FLAG_IN_COVERAGE", 24, ring=ring_name, index=i, error_flag=f)
            if status not in VALID_STATUSES:
                return fail("INVALID_RING_COVERAGE_STATUS", 25, ring=ring_name, index=i, status=status)
            if not waived_ok(entry):
                return fail("UNAPPROVED_RING_COVERAGE_WAIVER", 26,
                            ring=ring_name, own_state=o, position_class=p, error_flag=f)
            key = (o, p, f)
            if key in seen_combo:
                return fail("DUPLICATE_RING_COVERAGE_ENTRY", 27,
                            ring=ring_name, own_state=o, position_class=p, error_flag=f)
            seen_combo[key] = status

        missing_combo = sorted(expected_combo - set(seen_combo))
        if missing_combo:
            return fail("MISSING_RING_STATE_COVERAGE", 28, ring=ring_name,
                        expected_combo_count=len(expected_combo),
                        missing=[f"{o}/{p}/{f}" for o, p, f in missing_combo])

    # =====================================================================
    # Candidate 2: frame-type x size-class x tag-class completeness
    #
    # must-fix #1: frame_types must equal the full closed FRAME_TYPES set
    # (unicast/multicast/broadcast reception is a structural MAC property,
    # not optional) and size_classes must at least cover MIN_SIZE/MAX_SIZE.
    # must-fix #3: VLAN tag-presence is an independent axis from size
    # boundary, split out into its own declared tag_classes list rather than
    # being folded into the size_classes enum.
    # =====================================================================
    fm = d.get("frame_matrix") or {}
    if not isinstance(fm, dict):
        return fail("MALFORMED_FRAME_MATRIX", 29, got_type=type(fm).__name__)

    freq = ["frame_types", "size_classes", "tag_classes", "coverage_matrix"]
    fmiss = [k for k in freq if k not in fm]
    if fmiss:
        return fail("FRAME_MATRIX_MISSING_FIELDS", 30, missing=fmiss)

    ftypes = fm["frame_types"] or []
    sclasses = fm["size_classes"] or []
    tclasses = fm["tag_classes"] or []
    fcov = fm["coverage_matrix"] or []
    size_bytes = fm.get("size_bytes") or {}

    if not isinstance(ftypes, list) or not isinstance(sclasses, list) or not isinstance(tclasses, list):
        return fail("MALFORMED_FRAME_MATRIX_AXES", 31)
    if not isinstance(fcov, list):
        return fail("MALFORMED_FRAME_MATRIX_COVERAGE_LIST", 32, got_type=type(fcov).__name__)
    if not isinstance(size_bytes, dict):
        return fail("MALFORMED_SIZE_BYTES", 33, got_type=type(size_bytes).__name__)

    # must-fix #1: frame_types is a closed, fully-mandatory 3-element set --
    # reject both unknown extras AND silent omissions (was upper-bound-only).
    if set(ftypes) != FRAME_TYPES:
        return fail("INCOMPLETE_FRAME_TYPES", 34, frame_types=ftypes,
                    required=sorted(FRAME_TYPES))

    if not sclasses or set(sclasses) - SIZE_CLASSES:
        return fail("INVALID_SIZE_CLASSES", 35, size_classes=sclasses)
    if MANDATORY_SIZE_CLASSES - set(sclasses):
        return fail("INCOMPLETE_SIZE_CLASSES", 36, size_classes=sclasses,
                    required=sorted(MANDATORY_SIZE_CLASSES))

    if not tclasses or set(tclasses) - TAG_CLASSES:
        return fail("INVALID_TAG_CLASSES", 37, tag_classes=tclasses)
    if MANDATORY_TAG_CLASSES - set(tclasses):
        return fail("INCOMPLETE_TAG_CLASSES", 38, tag_classes=tclasses,
                    required=sorted(MANDATORY_TAG_CLASSES))

    # spec-grounded numeric bounds (IEEE 802.3 min/max frame; 802.1Q +4B tag).
    # MIN_SIZE/MAX_SIZE are mandatory members of sclasses (checked above) so
    # their bounds are always enforced, not conditionally skippable.
    v = size_bytes.get("MIN_SIZE")
    if v != 64:
        return fail("MIN_FRAME_SIZE_NOT_802_3", 39, declared=v, expected=64)
    v = size_bytes.get("MAX_SIZE")
    if v != 1518:
        return fail("MAX_FRAME_SIZE_NOT_802_3", 40, declared=v, expected=1518)
    if "JUMBO" in sclasses:
        v = size_bytes.get("JUMBO")
        if not isinstance(v, int) or isinstance(v, bool) or v <= 1518:
            return fail("JUMBO_SIZE_NOT_ABOVE_802_3_MAX", 41, declared=v, must_exceed=1518)
    # must-fix #2: renamed from the mismatched "max_tagged_bytes" key to
    # "VLAN_TAGGED" (matching the pattern every other size class uses:
    # size_bytes[<class name>]) and made mandatory once VLAN_TAGGED is
    # declared, instead of silently no-op'ing when the key is absent/misspelled.
    if "VLAN_TAGGED" in tclasses:
        v = size_bytes.get("VLAN_TAGGED")
        if v != 1522:
            return fail("MAX_TAGGED_FRAME_SIZE_NOT_802_1Q", 42, declared=v, expected=1522)

    # must-fix #3: coverage is now a 3-axis cross product (frame_type x
    # size_class x tag_class) so "min-size + VLAN-tagged", "jumbo + VLAN-
    # tagged", etc. are representable/coverable cells instead of being
    # structurally impossible to express.
    expected_triples = {(t, s, g) for t in ftypes for s in sclasses for g in tclasses}
    seen_triples = {}
    for i, entry in enumerate(fcov):
        if not isinstance(entry, dict):
            return fail("MALFORMED_FRAME_MATRIX_ENTRY", 43, index=i, got_type=type(entry).__name__)
        t = entry.get("frame_type")
        s = entry.get("size_class")
        g = entry.get("tag_class")
        status = entry.get("status")
        if t not in set(ftypes):
            return fail("UNKNOWN_FRAME_TYPE_IN_MATRIX", 44, index=i, frame_type=t)
        if s not in set(sclasses):
            return fail("UNKNOWN_SIZE_CLASS_IN_MATRIX", 45, index=i, size_class=s)
        if g not in set(tclasses):
            return fail("UNKNOWN_TAG_CLASS_IN_MATRIX", 46, index=i, tag_class=g)
        if status not in VALID_STATUSES:
            return fail("INVALID_FRAME_MATRIX_STATUS", 47, index=i, status=status)
        if not waived_ok(entry):
            return fail("UNAPPROVED_FRAME_MATRIX_WAIVER", 48, frame_type=t, size_class=s, tag_class=g)
        key = (t, s, g)
        if key in seen_triples:
            return fail("DUPLICATE_FRAME_MATRIX_ENTRY", 49, frame_type=t, size_class=s, tag_class=g)
        seen_triples[key] = status

    missing_triples = sorted(expected_triples - set(seen_triples))
    if missing_triples:
        return fail("MISSING_FRAME_MATRIX_TRIPLES", 50,
                    expected_triple_count=len(expected_triples),
                    missing_triples=[f"{t}x{s}x{g}" for t, s, g in missing_triples])

    # =====================================================================
    # Candidate 3: flow control -- PFC priority-class + pause-state coverage
    # (interrupt-cause bitmask is a bounded, advisory-only sub-check -- the
    #  bit SET is DUT register-map-specific, not spec-fixed, so its
    #  "completeness" cannot be judged here; only declared-bit hygiene is)
    # =====================================================================
    fc = d.get("flow_control") or {}
    if not isinstance(fc, dict):
        return fail("MALFORMED_FLOW_CONTROL", 51, got_type=type(fc).__name__)

    PAUSE_STATES = {"ASSERT", "DEASSERT_TIMEOUT", "QUANTA_RELOAD"}

    pause_cov_raw = fc.get("pause_coverage") or []
    if not isinstance(pause_cov_raw, list):
        return fail("MALFORMED_PAUSE_COVERAGE", 52, got_type=type(pause_cov_raw).__name__)
    pause_cov = set(pause_cov_raw)
    missing_pause = sorted(PAUSE_STATES - pause_cov)
    if missing_pause:
        return fail("MISSING_PAUSE_STATE_COVERAGE", 53, missing=missing_pause)

    if fc.get("pfc_enabled"):
        pcov = fc.get("priority_class_coverage") or []
        if not isinstance(pcov, list):
            return fail("MALFORMED_PFC_COVERAGE_LIST", 54, got_type=type(pcov).__name__)
        seen_pc = {}
        for i, entry in enumerate(pcov):
            if not isinstance(entry, dict):
                return fail("MALFORMED_PFC_ENTRY", 55, index=i, got_type=type(entry).__name__)
            pc = entry.get("priority_class")
            status = entry.get("status")
            # bool is an int subclass -- explicitly reject True/False being
            # silently accepted as priority_class 1/0.
            if not isinstance(pc, int) or isinstance(pc, bool) or not (0 <= pc <= 7):
                return fail("INVALID_PFC_PRIORITY_CLASS", 56, index=i, priority_class=pc)
            if status not in VALID_STATUSES:
                return fail("INVALID_PFC_COVERAGE_STATUS", 57, index=i, status=status)
            if not waived_ok(entry):
                return fail("UNAPPROVED_PFC_WAIVER", 58, priority_class=pc)
            if pc in seen_pc:
                return fail("DUPLICATE_PFC_PRIORITY_CLASS", 59, priority_class=pc)
            seen_pc[pc] = status
        missing_pc = sorted(set(range(8)) - set(seen_pc))
        if missing_pc:
            return fail("MISSING_PFC_PRIORITY_CLASS_COVERAGE", 60, missing=missing_pc)

    ib_note = None
    ib = d.get("interrupt_bitmask")
    if ib:
        if not isinstance(ib, dict):
            return fail("MALFORMED_INTERRUPT_BITMASK", 61, got_type=type(ib).__name__)
        bits = ib.get("bits") or []
        if not isinstance(bits, list):
            return fail("MALFORMED_INTERRUPT_BIT_LIST", 62, got_type=type(bits).__name__)
        seen_bits = {}
        for i, b in enumerate(bits):
            if not isinstance(b, dict):
                return fail("MALFORMED_INTERRUPT_BIT_ENTRY", 63, index=i, got_type=type(b).__name__)
            pos = b.get("bit_position")
            name = b.get("name")
            if pos is None or pos in seen_bits:
                return fail("DUPLICATE_OR_MISSING_INTERRUPT_BIT_POSITION", 64, index=i, bit_position=pos)
            seen_bits[pos] = name
            asserted = bool(b.get("assert_coverage"))
            cleared = bool(b.get("clear_coverage"))
            if not (asserted and cleared):
                return fail("INCOMPLETE_INTERRUPT_BIT_COVERAGE", 65,
                            bit_position=pos, name=name,
                            assert_coverage=asserted, clear_coverage=cleared)
        ib_note = ("structural check only: duplicate-position and assert/clear coverage "
                   "verified for the DECLARED bits; whether the declared bit set is the "
                   "DUT's complete interrupt-cause register requires register-spec "
                   "cross-reference and is out of scope for this checker")

    result = {
        "status": "PASS",
        "rings_checked": sorted(rings),
        "frame_matrix_triples": len(expected_triples),
        "pfc_checked": bool(fc.get("pfc_enabled")),
    }
    if ib_note:
        result["interrupt_bitmask_note"] = ib_note
    return result, 0

VALID_STATUSES_CANFD = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}
VALID_IDE_CANFD = {"STANDARD", "EXTENDED"}
VALID_ARB_FRAME_TYPE_CANFD = {"DATA", "REMOTE"}
VALID_FRAME_FORMAT_CANFD = {"CLASSIC", "FD"}
VALID_BRS_CANFD = {"ON", "OFF", "NOT_APPLICABLE"}
VALID_CONF_STATE_CANFD = {"ACTIVE", "PASSIVE", "BUS_OFF"}
VALID_FD_FLAG_CANFD = {True, False}

LEGAL_CONF_TRANSITIONS_CANFD = {
    ("ACTIVE", "PASSIVE"),
    ("PASSIVE", "ACTIVE"),
    ("PASSIVE", "BUS_OFF"),
    ("BUS_OFF", "ACTIVE"),
}

EXPECTED_FRAME_CELLS_CANFD = {
    ("CLASSIC", "NOT_APPLICABLE", "DATA"),
    ("CLASSIC", "NOT_APPLICABLE", "REMOTE"),
    ("FD", "OFF", "DATA"),
    ("FD", "ON", "DATA"),
}


def parse_id_canfd(v):
    if isinstance(v, int):
        return v
    s = str(v).strip().replace("_", "")
    return int(s, 0)


def _arb_key_canfd(node):
    arb_id = node["_arb_id"]
    ide = node["ide"]
    if ide == "STANDARD":
        base_id = arb_id
        ext_id = 0
    else:
        base_id = arb_id >> 18
        ext_id = arb_id & 0x3FFFF
    ide_rank = 0 if ide == "STANDARD" else 1
    ft_rank = 0 if node["frame_type"] == "DATA" else 1
    return (base_id, ide_rank, ext_id, ft_rank)


def check_canfd(d):
    # ---- applicability gate ----
    if d.get("canfd_applicable") is False:
        reason = d.get("canfd_not_applicable_reason")
        if not reason:
            return ({"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}, 2)
        return ({"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}, 0)

    required_top = ["nodes", "frame_coverage_matrix", "error_confinement_transitions"]
    missing = [k for k in required_top if k not in d]
    if missing:
        return ({"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing}, 3)

    nodes = d.get("nodes") or []
    frame_matrix = d.get("frame_coverage_matrix") or []
    conf_transitions = d.get("error_confinement_transitions") or []

    # ---- (must-fix, hardening) reject non-list containers before iterating ----
    for field_name, container in (
        ("nodes", nodes),
        ("frame_coverage_matrix", frame_matrix),
        ("error_confinement_transitions", conf_transitions),
    ):
        if not isinstance(container, list):
            return ({"status": "FAIL", "reason": "INVALID_CONTAINER_TYPE",
                     "field": field_name, "type": type(container).__name__}, 4)

    if not nodes:
        return ({"status": "FAIL", "reason": "NO_NODES"}, 5)

    # ---- (1) arbitration outcome completeness ----
    node_ids = [n.get("node_id") for n in nodes]

    # BUG 1 FIX: node_id may legitimately be missing (None) on more than one
    # node. The original `sorted({... for nid in node_ids if count>1})` mixed
    # None and str in one set and crashed with an unhandled TypeError from
    # sorted(). Missing ids are counted separately (never sorted alongside
    # strings); only non-None ids are candidates for string-sort duplicates.
    # Two-or-more nodes both missing node_id are still flagged as a defect
    # (they are indistinguishable duplicates), just via a separate counter.
    missing_node_id_count = node_ids.count(None)
    named_ids = [nid for nid in node_ids if nid is not None]
    dup_named_ids = sorted({nid for nid in named_ids if named_ids.count(nid) > 1})
    if dup_named_ids or missing_node_id_count > 1:
        return ({"status": "FAIL", "reason": "DUPLICATE_NODE_ID",
                 "duplicates": dup_named_ids,
                 "missing_node_id_count": missing_node_id_count}, 6)

    parsed = []
    for i, n in enumerate(nodes):
        ide = n.get("ide")
        frame_type = n.get("frame_type")
        if ide not in VALID_IDE_CANFD:
            return ({"status": "FAIL", "reason": "INVALID_IDE", "index": i,
                     "node_id": n.get("node_id"), "ide": ide}, 7)
        if frame_type not in VALID_ARB_FRAME_TYPE_CANFD:
            return ({"status": "FAIL", "reason": "INVALID_ARB_FRAME_TYPE", "index": i,
                     "node_id": n.get("node_id"), "frame_type": frame_type}, 8)

        # BUG 2 FIX: `fd` was coerced with bare Python truthiness
        # (`bool(n.get("fd"))`), so any producer that stringifies booleans
        # (e.g. "fd": "false") silently flipped a non-FD node into FD
        # classification, because bool("false") == True. Validate against
        # the actual JSON boolean type/enum instead of coercing.
        fd_raw = n.get("fd")
        if fd_raw not in VALID_FD_FLAG_CANFD:
            return ({"status": "FAIL", "reason": "INVALID_FD_VALUE", "index": i,
                     "node_id": n.get("node_id"), "fd": fd_raw}, 9)
        is_fd = fd_raw

        if is_fd and frame_type == "REMOTE":
            return ({"status": "FAIL", "reason": "FD_REMOTE_FRAME_NOT_SUPPORTED", "index": i,
                     "node_id": n.get("node_id")}, 10)
        try:
            arb_id = parse_id_canfd(n.get("arb_id"))
        except Exception:
            return ({"status": "FAIL", "reason": "UNPARSEABLE_ARB_ID", "index": i,
                     "node_id": n.get("node_id"), "arb_id": n.get("arb_id")}, 11)
        max_id = 0x7FF if ide == "STANDARD" else 0x1FFFFFFF
        if arb_id < 0 or arb_id > max_id:
            return ({"status": "FAIL", "reason": "ARB_ID_OUT_OF_RANGE", "index": i,
                     "node_id": n.get("node_id"), "arb_id": n.get("arb_id"),
                     "ide": ide, "max_id": max_id}, 12)
        rec = dict(n)
        rec["_arb_id"] = arb_id
        parsed.append(rec)

    ties = []
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            if _arb_key_canfd(parsed[i]) == _arb_key_canfd(parsed[j]):
                ties.append((parsed[i]["node_id"], parsed[j]["node_id"]))
    if ties:
        return ({"status": "FAIL", "reason": "ARBITRATION_TIE",
                 "tied_pairs": [f"{a}<->{b}" for a, b in ties]}, 13)

    # ---- (2) classic vs FD frame-format x BRS coverage matrix ----
    seen_cells = {}
    for i, entry in enumerate(frame_matrix):
        frame_format = entry.get("frame_format")
        brs = entry.get("brs")
        frame_type = entry.get("frame_type")
        status = entry.get("status")

        if frame_format not in VALID_FRAME_FORMAT_CANFD:
            return ({"status": "FAIL", "reason": "INVALID_FRAME_FORMAT", "index": i,
                     "frame_format": frame_format}, 14)
        if brs not in VALID_BRS_CANFD:
            return ({"status": "FAIL", "reason": "INVALID_BRS_VALUE", "index": i,
                     "brs": brs}, 15)
        if frame_type not in VALID_ARB_FRAME_TYPE_CANFD:
            return ({"status": "FAIL", "reason": "INVALID_FRAME_TYPE", "index": i,
                     "frame_type": frame_type}, 16)

        if frame_format == "CLASSIC" and brs != "NOT_APPLICABLE":
            return ({"status": "FAIL", "reason": "BRS_ILLEGAL_FOR_CLASSIC_FRAME", "index": i,
                     "brs": brs}, 17)
        if frame_format == "FD" and brs == "NOT_APPLICABLE":
            return ({"status": "FAIL", "reason": "BRS_REQUIRED_FOR_FD_FRAME", "index": i}, 18)
        if frame_format == "FD" and frame_type == "REMOTE":
            return ({"status": "FAIL", "reason": "FD_REMOTE_FRAME_NOT_SUPPORTED",
                     "index": i, "context": "frame_coverage_matrix"}, 19)

        if status not in VALID_STATUSES_CANFD:
            return ({"status": "FAIL", "reason": "INVALID_FRAME_COVERAGE_STATUS", "index": i,
                     "status": status}, 20)
        if status in ("WAIVED", "NOT_APPLICABLE") and not (entry.get("waiver_approved") and entry.get("waiver_evidence")):
            return ({"status": "FAIL", "reason": "UNAPPROVED_FRAME_COVERAGE_WAIVER", "index": i,
                     "frame_format": frame_format, "brs": brs, "frame_type": frame_type}, 21)

        cell = (frame_format, brs, frame_type)
        if cell in seen_cells:
            return ({"status": "FAIL", "reason": "DUPLICATE_FRAME_COVERAGE_CELL", "index": i,
                     "cell": list(cell)}, 22)
        seen_cells[cell] = status

    missing_cells = sorted(EXPECTED_FRAME_CELLS_CANFD - set(seen_cells))
    if missing_cells:
        return ({"status": "FAIL", "reason": "MISSING_FRAME_COVERAGE_CELLS",
                 "expected_cell_count": len(EXPECTED_FRAME_CELLS_CANFD),
                 "missing_cells": [list(c) for c in missing_cells]}, 23)

    # ---- (3) error-confinement transition coverage ----
    seen_transitions = {}
    for i, entry in enumerate(conf_transitions):
        from_state = entry.get("from_state")
        to_state = entry.get("to_state")
        status = entry.get("status")

        if from_state not in VALID_CONF_STATE_CANFD or to_state not in VALID_CONF_STATE_CANFD:
            return ({"status": "FAIL", "reason": "INVALID_CONFINEMENT_STATE", "index": i,
                     "from_state": from_state, "to_state": to_state}, 24)
        if (from_state, to_state) not in LEGAL_CONF_TRANSITIONS_CANFD:
            return ({"status": "FAIL", "reason": "ILLEGAL_CONFINEMENT_TRANSITION", "index": i,
                     "from_state": from_state, "to_state": to_state}, 25)
        if status not in VALID_STATUSES_CANFD:
            return ({"status": "FAIL", "reason": "INVALID_CONFINEMENT_TRANSITION_STATUS",
                     "index": i, "status": status}, 26)
        if status in ("WAIVED", "NOT_APPLICABLE") and not (entry.get("waiver_approved") and entry.get("waiver_evidence")):
            return ({"status": "FAIL", "reason": "UNAPPROVED_CONFINEMENT_TRANSITION_WAIVER",
                     "index": i, "from_state": from_state, "to_state": to_state}, 27)

        pair = (from_state, to_state)
        if pair in seen_transitions:
            return ({"status": "FAIL", "reason": "DUPLICATE_CONFINEMENT_TRANSITION", "index": i,
                     "from_state": from_state, "to_state": to_state}, 28)
        seen_transitions[pair] = status

    missing_transitions = sorted(LEGAL_CONF_TRANSITIONS_CANFD - set(seen_transitions))
    if missing_transitions:
        return ({"status": "FAIL", "reason": "MISSING_CONFINEMENT_TRANSITION_COVERAGE",
                 "expected_transition_count": len(LEGAL_CONF_TRANSITIONS_CANFD),
                 "missing_transitions": [f"{a}->{b}" for a, b in missing_transitions]}, 29)

    return ({"status": "PASS", "nodes": len(nodes),
             "frame_coverage_cells": len(EXPECTED_FRAME_CELLS_CANFD),
             "confinement_transitions": len(LEGAL_CONF_TRANSITIONS_CANFD)}, 0)

"""
check_sd_sdio(d) -- SD/SDIO structural completeness checker for the shared
protocol-completeness dispatcher.

Convention (documented for the coordinator adapting this into CHECKERS map):
    Returns a tuple (result, exit_code).
    - result is a JSON-serializable dict, always containing "status" in
      {"PASS", "FAIL", "SKIPPED_NOT_APPLICABLE"} and, on FAIL, a "reason"
      code plus whatever keys are needed to locate the offending entry.
    - exit_code is 0 for PASS/SKIPPED_NOT_APPLICABLE, and a distinct
      non-zero small int per FAIL branch (mirrors fabric_topology_completeness_gate.py's
      one-exit-code-per-failure-branch style so a dispatcher can just do
      `sys.exit(exit_code)` after `print(json.dumps(result))` if it wants
      standalone-script semantics).
    No argparse/main()/print()/sys.exit() is performed inside this function --
    the caller (dispatcher) owns I/O.

Structural scope only: no RTL/waveform semantic judgment is performed here.
This checks (a) that spec-mandated response types were observed for every
command the DUT's declared mode profile requires, (b) that the declared
bus-width x speed-mode matrix was fully exercised (and that submitted
bus-width/speed-mode pairs are themselves spec-legal combinations), and
(c) that every declared SDIO function's CCCR-level interrupt path
(enable/pending/service) was exercised.

FIXES applied per adversarial verify-report must-fix list (post-design):
  1. CMD55 (APP_CMD) and ACMD6 (SET_BUS_WIDTH) are SD *memory*-portion
     mechanisms -- they are now gated on `has_memory` instead of being
     unconditional / bus-width-only. A pure I/O-only SDIO card
     (is_sdio=True, is_combo=False) sets bus width via CCCR "Bus
     Interface Control" through CMD52, and never issues CMD55/ACMDx.
  2. CMD13 (SEND_STATUS) re-verified against spec for I/O-only cards:
     it is part of the SD memory command class, not the SDIO I/O
     command set (I/O status is read via CMD52 into CCCR, not CMD13).
     Moved into the `has_memory` gated block alongside CMD55.
  3. Candidate 2's evidence validation now rejects any submitted
     (bus_width, speed_mode) pair that is not a structurally legal SD
     combination (UNKNOWN_BUS_SPEED_PAIR) -- e.g. 1-bit + SDR104 can no
     longer be silently accepted as evidence.
  4. `sdio_function_count` is now validated against the CCCR-fixed
     structural range of 1-7 functions before it is used to derive the
     required-function set (INVALID_SDIO_FUNCTION_COUNT).
"""

# ---------------------------------------------------------------------------
# Candidate 1: command-class x response-type completeness
# ---------------------------------------------------------------------------
# Spec-fixed lookup: SD Physical Layer Specification (command/response type
# table, Part 1) and SDIO Simplified Specification (I/O command response
# types R4/R5). Response type per command index is NOT DUT-dependent -- it
# is fixed by the spec. R1B is kept distinct from R1 because busy-signal
# handling is structurally different evidence.
SPEC_CMD_RESPONSE_SDIO = {
    "CMD0": "NONE",     # GO_IDLE_STATE
    "CMD2": "R2",       # ALL_SEND_CID
    "CMD3": "R6",       # SEND_RELATIVE_ADDR
    "CMD5": "R4",       # SDIO_SEND_OP_COND
    "CMD6": "R1",       # SWITCH_FUNC
    "CMD7": "R1B",      # SELECT/DESELECT_CARD (select = R1b)
    "CMD8": "R7",       # SEND_IF_COND
    "CMD9": "R2",       # SEND_CSD
    "CMD10": "R2",      # SEND_CID
    "CMD11": "R1",      # VOLTAGE_SWITCH
    "CMD12": "R1B",     # STOP_TRANSMISSION
    "CMD13": "R1",      # SEND_STATUS
    "CMD16": "R1",      # SET_BLOCKLEN
    "CMD17": "R1",      # READ_SINGLE_BLOCK
    "CMD18": "R1",      # READ_MULTIPLE_BLOCK
    "CMD19": "R1",      # SEND_TUNING_BLOCK
    "CMD24": "R1",      # WRITE_BLOCK
    "CMD25": "R1",      # WRITE_MULTIPLE_BLOCK
    "CMD28": "R1B",     # SET_WRITE_PROT
    "CMD29": "R1B",     # CLR_WRITE_PROT
    "CMD30": "R1",      # SEND_WRITE_PROT
    "CMD32": "R1",      # ERASE_WR_BLK_START
    "CMD33": "R1",      # ERASE_WR_BLK_END
    "CMD38": "R1B",     # ERASE
    "CMD42": "R1",      # LOCK_UNLOCK
    "CMD52": "R5",      # IO_RW_DIRECT
    "CMD53": "R5",      # IO_RW_EXTENDED
    "CMD55": "R1",      # APP_CMD
    "CMD58": "R3",      # READ_OCR
    "CMD59": "R1",      # CRC_ON_OFF
    "ACMD6": "R1",       # SET_BUS_WIDTH
    "ACMD13": "R1",      # SD_STATUS
    "ACMD41": "R3",      # SD_SEND_OP_COND
    "ACMD51": "R1",      # SEND_SCR
}
VALID_RESPONSE_TYPES_SDIO = {"NONE", "R1", "R1B", "R2", "R3", "R4", "R5", "R6", "R7"}
UHS_TUNING_MODES_SDIO = {"SDR50", "SDR104"}  # spec: tuning (CMD19) mandatory for these


def _required_commands_sdio(caps):
    """Deterministic required-command set derived from DUT-declared mode
    profile bits (not inferred): SD Physical Layer card identification/
    initialization sequence for the memory portion, SDIO Simplified
    Specification I/O-only/combo initialization sequence for the I/O
    portion, plus optional-feature commands gated on the matching
    capability bit the DUT itself declares as supported.

    CMD55/ACMDx (APP_CMD-prefixed commands, including ACMD6) and CMD13
    (SEND_STATUS) belong to the SD *memory* command class and are gated on
    `has_memory` -- a pure I/O-only SDIO card never issues them (bus width
    is switched via CCCR through CMD52, and I/O status is read the same
    way, not via CMD13)."""
    is_sdio = bool(caps.get("is_sdio"))
    is_combo = bool(caps.get("is_combo"))
    has_memory = is_combo or not is_sdio

    req = {"CMD0", "CMD3", "CMD7"}
    if has_memory:
        req |= {"CMD2", "CMD8", "CMD9", "CMD13", "CMD55", "ACMD41", "ACMD51",
                "ACMD13", "CMD17", "CMD18", "CMD24", "CMD25", "CMD12"}
    if is_sdio or is_combo:
        req |= {"CMD5", "CMD52", "CMD53"}
    if caps.get("supports_high_speed") or caps.get("supports_uhs"):
        req.add("CMD6")
    if caps.get("supports_uhs"):
        req.add("CMD11")
    if set(caps.get("uhs_modes") or []) & UHS_TUNING_MODES_SDIO:
        req.add("CMD19")
    if caps.get("supports_erase"):
        req |= {"CMD32", "CMD33", "CMD38"}
    if caps.get("supports_lock_unlock"):
        req.add("CMD42")
    if caps.get("supports_write_protect"):
        req |= {"CMD28", "CMD29", "CMD30"}
    if has_memory and (caps.get("max_bus_width") or 1) >= 4:
        req.add("ACMD6")
    return req


# ---------------------------------------------------------------------------
# Candidate 2: bus-width x speed-mode coverage matrix
# ---------------------------------------------------------------------------
# UHS-I signaling modes are only defined for a 4-bit data bus (SD Physical
# Layer Spec, UHS-I bus speed mode section) -- 1-bit is legacy/default-speed
# only. DS is the mandatory baseline in every bus width the DUT supports; HS
# and each UHS-I mode are required only if the DUT declares support for them.
UHS_MODES_SDIO = {"SDR12", "SDR25", "SDR50", "SDR104", "DDR50"}
VALID_STATUSES_SDIO = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}

# Structurally legal (bus_width, speed_mode) pairs, independent of what any
# given DUT declares supporting: SD only ever defines a 1-bit or 4-bit data
# bus; DS/HS are legal at either width; UHS-I modes are legal only at 4-bit.
# Used to reject nonsensical submitted evidence (e.g. 1-bit + SDR104) that
# the required-set side would never itself ask for.
ALL_VALID_BUS_SPEED_PAIRS_SDIO = {(1, "DS"), (1, "HS"), (4, "DS"), (4, "HS")} | {
    (4, mode) for mode in UHS_MODES_SDIO
}


def _required_bus_speed_pairs_sdio(caps):
    max_bw = caps.get("max_bus_width") or 1
    bus_widths = [1] if max_bw < 4 else [1, 4]
    pairs = set()
    for bw in bus_widths:
        pairs.add((bw, "DS"))
        if caps.get("supports_high_speed"):
            pairs.add((bw, "HS"))
    if max_bw >= 4:
        for mode in (set(caps.get("uhs_modes") or []) & UHS_MODES_SDIO):
            pairs.add((4, mode))
    return pairs


# ---------------------------------------------------------------------------
# Candidate 3: SDIO function x interrupt-source completeness
# ---------------------------------------------------------------------------
# NARROWED SCOPE (see rationale in the trailing docstring): the SDIO
# Simplified Specification fixes the CCCR interrupt structure -- one
# Card Interrupt Enable bit (IENx) and one Interrupt Pending bit (ISPx) per
# function number 1..7 (function 0 = CCCR itself, never a source). That
# existence x enable x pending x serviced completeness IS deterministic.
# What is NOT spec-fixed is the set of internal causes behind a given
# function's IRQ line (that is vendor/function-class specific) -- this
# checker does not attempt to enumerate those.
SDIO_MAX_FUNCTIONS_SDIO = 7  # CCCR IENx/ISPx are structurally defined only for 1..7


def _required_function_numbers_sdio(caps):
    if not (caps.get("is_sdio") or caps.get("is_combo")):
        return set()
    n = caps.get("sdio_function_count") or 0
    return set(range(1, n + 1))


def check_sd_sdio(d):
    if d.get("not_applicable") is True:
        reason = d.get("not_applicable_reason")
        if not reason:
            return {"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}, 2
        return {"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}, 0

    required_top = ["dut_capabilities", "command_evidence", "bus_speed_evidence"]
    missing = [k for k in required_top if k not in d]
    if missing:
        return {"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing}, 3

    caps = d.get("dut_capabilities") or {}
    cmd_evidence = d.get("command_evidence") or []
    bus_evidence = d.get("bus_speed_evidence") or []
    func_evidence = d.get("sdio_function_irq_evidence") or []

    # ---- Candidate 1: command x response-type completeness ----
    seen_cmds = {}
    for i, entry in enumerate(cmd_evidence):
        cmd = entry.get("command")
        if cmd not in SPEC_CMD_RESPONSE_SDIO:
            return {"status": "FAIL", "reason": "UNKNOWN_COMMAND", "index": i, "command": cmd}, 4
        if cmd in seen_cmds:
            return {"status": "FAIL", "reason": "DUPLICATE_COMMAND_ENTRY", "command": cmd}, 5
        status = entry.get("status", "IMPLEMENTED")
        if status not in VALID_STATUSES_SDIO:
            return {"status": "FAIL", "reason": "INVALID_COMMAND_STATUS", "command": cmd, "status": status}, 6
        if status in ("WAIVED", "NOT_APPLICABLE"):
            if not (entry.get("waiver_approved") and entry.get("waiver_evidence")):
                return {"status": "FAIL", "reason": "UNAPPROVED_COMMAND_WAIVER", "command": cmd}, 7
            seen_cmds[cmd] = status
            continue
        rtype = entry.get("response_type")
        if rtype not in VALID_RESPONSE_TYPES_SDIO:
            return {"status": "FAIL", "reason": "INVALID_RESPONSE_TYPE", "command": cmd, "response_type": rtype}, 8
        expected = SPEC_CMD_RESPONSE_SDIO[cmd]
        if rtype != expected:
            return {"status": "FAIL", "reason": "RESPONSE_TYPE_MISMATCH", "command": cmd,
                    "expected": expected, "observed": rtype}, 9
        seen_cmds[cmd] = status

    required_cmds = _required_commands_sdio(caps)
    missing_cmds = sorted(required_cmds - set(seen_cmds))
    if missing_cmds:
        return {"status": "FAIL", "reason": "MISSING_REQUIRED_COMMANDS",
                "required_count": len(required_cmds), "missing_commands": missing_cmds}, 10

    # ---- Candidate 2: bus-width x speed-mode matrix completeness ----
    seen_pairs = {}
    for i, entry in enumerate(bus_evidence):
        bw = entry.get("bus_width")
        mode = entry.get("speed_mode")
        status = entry.get("status")
        if status not in VALID_STATUSES_SDIO:
            return {"status": "FAIL", "reason": "INVALID_BUS_SPEED_STATUS",
                    "index": i, "bus_width": bw, "speed_mode": mode, "status": status}, 11
        if status in ("WAIVED", "NOT_APPLICABLE") and not (entry.get("waiver_approved") and entry.get("waiver_evidence")):
            return {"status": "FAIL", "reason": "UNAPPROVED_BUS_SPEED_WAIVER",
                    "bus_width": bw, "speed_mode": mode}, 12
        pair = (bw, mode)
        if pair not in ALL_VALID_BUS_SPEED_PAIRS_SDIO:
            return {"status": "FAIL", "reason": "UNKNOWN_BUS_SPEED_PAIR",
                    "index": i, "bus_width": bw, "speed_mode": mode}, 21
        if pair in seen_pairs:
            return {"status": "FAIL", "reason": "DUPLICATE_BUS_SPEED_ENTRY",
                    "bus_width": bw, "speed_mode": mode}, 13
        seen_pairs[pair] = status

    required_pairs = _required_bus_speed_pairs_sdio(caps)
    missing_pairs = sorted(required_pairs - set(seen_pairs))
    if missing_pairs:
        return {"status": "FAIL", "reason": "MISSING_BUS_SPEED_PAIRS",
                "expected_pair_count": len(required_pairs),
                "missing_pairs": [f"{bw}bit/{mode}" for bw, mode in missing_pairs]}, 14

    # ---- Candidate 3: SDIO function x CCCR-IRQ-path completeness ----
    if caps.get("is_sdio") or caps.get("is_combo"):
        fn_count = caps.get("sdio_function_count")
        if not isinstance(fn_count, int) or isinstance(fn_count, bool) or not (1 <= fn_count <= SDIO_MAX_FUNCTIONS_SDIO):
            return {"status": "FAIL", "reason": "INVALID_SDIO_FUNCTION_COUNT",
                    "sdio_function_count": fn_count}, 22

    required_funcs = _required_function_numbers_sdio(caps)
    if required_funcs:
        seen_funcs = {}
        for i, entry in enumerate(func_evidence):
            fn = entry.get("function_number")
            if fn not in required_funcs:
                return {"status": "FAIL", "reason": "UNKNOWN_SDIO_FUNCTION", "index": i, "function_number": fn}, 15
            if fn in seen_funcs:
                return {"status": "FAIL", "reason": "DUPLICATE_SDIO_FUNCTION_ENTRY", "function_number": fn}, 16
            status = entry.get("status", "IMPLEMENTED")
            if status not in VALID_STATUSES_SDIO:
                return {"status": "FAIL", "reason": "INVALID_SDIO_FUNCTION_STATUS",
                        "function_number": fn, "status": status}, 17
            if status in ("WAIVED", "NOT_APPLICABLE"):
                if not (entry.get("waiver_approved") and entry.get("waiver_evidence")):
                    return {"status": "FAIL", "reason": "UNAPPROVED_SDIO_FUNCTION_WAIVER", "function_number": fn}, 18
                seen_funcs[fn] = status
                continue
            if not (entry.get("irq_enabled") and entry.get("irq_observed_pending") and entry.get("irq_serviced")):
                return {"status": "FAIL", "reason": "INCOMPLETE_SDIO_FUNCTION_IRQ_PATH",
                        "function_number": fn,
                        "irq_enabled": entry.get("irq_enabled"),
                        "irq_observed_pending": entry.get("irq_observed_pending"),
                        "irq_serviced": entry.get("irq_serviced")}, 19
            seen_funcs[fn] = status

        missing_funcs = sorted(required_funcs - set(seen_funcs))
        if missing_funcs:
            return {"status": "FAIL", "reason": "MISSING_SDIO_FUNCTION_IRQ_EVIDENCE",
                    "required_function_count": len(required_funcs),
                    "missing_functions": missing_funcs}, 20

    return {
        "status": "PASS",
        "required_commands": len(required_cmds),
        "required_bus_speed_pairs": len(required_pairs),
        "required_sdio_functions": len(required_funcs),
    }, 0

"""
check_emmc(d) -- eMMC structural completeness dispatch-case.

Convention (documented for the shared dispatcher coordinator):
    result_dict, exit_code = check_emmc(d)
    - exit_code == 0            -> result_dict["status"] == "PASS"
    - exit_code == 1            -> result_dict["status"] == "SKIPPED_NOT_APPLICABLE"
    - exit_code in 2..N         -> result_dict["status"] == "FAIL", result_dict["reason"] is the
                                     machine-readable failure tag, first-failure-wins (same style as
                                     fabric_topology_completeness_gate.py: no aggregation, stop at the
                                     first broken structural invariant so the coordinator gets one
                                     unambiguous reason per run).
This mirrors fabric_topology_completeness_gate.py's main(): deterministic structural checks only,
no RTL semantic judgment, JSON-serializable dict out. The only difference is main()'s
`print(json.dumps(...)); return <int>` becomes `return (dict, <int>)` since this function is called
in-process by the dispatcher instead of being its own CLI entry point.

Fix history (post adversarial-verify pass on the original draft):
  - Added CMD21 (SEND_TUNING_BLOCK, R1) to EMMC_CMD_RESPONSE -- eMMC repurposes CMD21 for
    HS200/HS400 tuning (unlike SD, which uses CMD19); it was a real spec-table gap that produced
    a false-negative UNKNOWN_COMMAND_INDEX for any DUT legitimately declaring CMD21.
  - Added MANDATORY_EMMC_COMMANDS + a MISSING_MANDATORY_COMMANDS failure branch. Candidate (1)
    previously only validated response types of *whatever* commands were declared and never
    checked that the mandatory card-init/session command set was declared at all -- it was
    mislabeled "completeness" while having no completeness check. This closes that gap.
  - Added an EXTRA_TIMING_WIDTH_PAIR_BEYOND_CAPABILITY branch for candidate (3), mirroring
    candidate (2)'s extra_partitions / PARTITION_COVERAGE_FOR_DISABLED_PARTITION check: a
    coverage entry for a (mode, width) pair that is globally spec-legal but outside the DUT's
    *declared* supported_modes x supported_widths capability now fails instead of passing
    silently, restoring the structural symmetry between the two coverage candidates.
"""

VALID_COVERAGE_STATUSES_EMMC = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}

# ---------------------------------------------------------------------------
# Candidate 1: command x response-type completeness.
# Fixed core command -> response-type table, JEDEC JESD84-B51 (eMMC 5.1),
# "Command Types" / individual command definition clauses. Only the
# mandatory/core command set is enumerated; command indices 60-63 are
# manufacturer-reserved (spec leaves their response type to the vendor) and
# are deliberately NOT in this table -- see VENDOR_RESERVED_CMDS_EMMC below.
#
# CMD7 is the one context-dependent entry in the whole table: SELECT_CARD
# (RCA != 0) returns R1b, but DESELECT_CARD (RCA == 0000, moving the
# addressed card to Stand-by) returns NO response. Both are spec-legal, so
# CMD7's allowed set has two members instead of one; every other command
# index maps to exactly one response type.
#
# CMD21 (SEND_TUNING_BLOCK) is eMMC-specific tuning support for HS200/HS400
# (eMMC reuses CMD21 for this since CMD19 is already BUSTEST_W, unlike SD
# which uses CMD19 for tuning) -- single-valued R1.
# ---------------------------------------------------------------------------
EMMC_CMD_RESPONSE = {
    0: {"NONE"},        # GO_IDLE_STATE
    1: {"R3"},          # SEND_OP_COND
    2: {"R2"},          # ALL_SEND_CID
    3: {"R1"},          # SET_RELATIVE_ADDR
    4: {"NONE"},        # SET_DSR
    5: {"R1B"},         # SLEEP_AWAKE
    6: {"R1B"},         # SWITCH
    7: {"R1B", "NONE"}, # SELECT_CARD (R1b) / DESELECT_CARD (NONE)
    8: {"R1"},          # SEND_EXT_CSD
    9: {"R2"},          # SEND_CSD
    10: {"R2"},         # SEND_CID
    12: {"R1B"},        # STOP_TRANSMISSION
    13: {"R1"},         # SEND_STATUS
    14: {"R1"},         # BUSTEST_R
    15: {"NONE"},       # GO_INACTIVE_STATE
    16: {"R1"},         # SET_BLOCKLEN
    17: {"R1"},         # READ_SINGLE_BLOCK
    18: {"R1"},         # READ_MULTIPLE_BLOCK
    19: {"R1"},         # BUSTEST_W
    21: {"R1"},         # SEND_TUNING_BLOCK (HS200/HS400 tuning)
    23: {"R1"},         # SET_BLOCK_COUNT
    24: {"R1"},         # WRITE_BLOCK
    25: {"R1"},         # WRITE_MULTIPLE_BLOCK
    26: {"R1"},         # PROGRAM_CID
    27: {"R1"},         # PROGRAM_CSD
    28: {"R1B"},        # SET_WRITE_PROT
    29: {"R1B"},        # CLR_WRITE_PROT
    30: {"R1"},         # SEND_WRITE_PROT
    31: {"R1"},         # SEND_WRITE_PROT_TYPE
    35: {"R1"},         # ERASE_GROUP_START
    36: {"R1"},         # ERASE_GROUP_END
    38: {"R1B"},        # ERASE
    39: {"R4"},         # FAST_IO
    40: {"R5"},         # GO_IRQ_STATE
    42: {"R1B"},        # LOCK_UNLOCK
    44: {"R1"},         # QUEUED_TASK_PARAMS  (CMDQ)
    45: {"R1"},         # QUEUED_TASK_ADDRESS (CMDQ)
    46: {"R1"},         # EXECUTE_READ_TASK   (CMDQ)
    47: {"R1"},         # EXECUTE_WRITE_TASK  (CMDQ)
    48: {"R1B"},        # CMDQ_TASK_MGMT
    49: {"R1"},         # SET_TIME
    55: {"R1"},         # APP_CMD
    56: {"R1"},         # GEN_CMD
}
VENDOR_RESERVED_CMDS_EMMC = {60, 61, 62, 63}

# Minimal mandatory command subset every eMMC device must declare regardless
# of optional feature support: the card-identification/selection sequence
# (CMD0/1/2/3/7) plus the two baseline data-readout commands every DUT needs
# to bring up and interrogate a card (CMD8 SEND_EXT_CSD, CMD9 SEND_CSD) and
# CMD13 SEND_STATUS (polling primitive used by essentially every transaction
# flow). This is what candidate (1) was missing: without it, "completeness"
# meant nothing more than "response types of whatever was declared are legal".
MANDATORY_EMMC_COMMANDS = {0, 1, 2, 3, 7, 8, 9, 13}

# ---------------------------------------------------------------------------
# Candidate 2: partition/boot-area completeness.
# Fixed EXT_CSD-driven enable rules, JEDEC JESD84-B51 EXT_CSD register map:
#   - USER_AREA        : always present (unconditional).
#   - BOOT1, BOOT2     : both present iff BOOT_SIZE_MULT > 0 (the two boot
#                        areas are a fixed pair -- the spec has no notion of
#                        exactly one boot area existing).
#   - RPMB             : present iff RPMB_SIZE_MULT > 0 (gated independently
#                        of PARTITIONING_SUPPORT).
#   - ENH_USER_AREA    : present iff PARTITIONING_SUPPORT bit0 == 1 AND
#                        PARTITION_SETTING_COMPLETED == 1 AND ENH_SIZE_MULT > 0.
#   - GP1..GP4         : present iff PARTITIONING_SUPPORT bit0 == 1 AND
#                        PARTITION_SETTING_COMPLETED == 1 AND that GPn's own
#                        GP_SIZE_MULT_n > 0 (each GP partition gated
#                        independently once the two global bits are set).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Candidate 3: HS200/HS400 timing-mode x bus-width legality/coverage.
# Fixed legality table, JEDEC JESD84-B51 bus-speed-mode clauses (HS_TIMING
# field semantics + the HS400/HS400ES clauses that restrict those modes to
# 8-bit): Legacy and High-Speed SDR run at 1/4/8-bit; anything DDR-based
# (High-Speed DDR, HS200 is SDR-only so it is NOT DDR -- listed separately)
# requires at least 4-bit; HS400/HS400ES are defined ONLY for 8-bit DDR.
# 1-bit bus width is illegal for HS200, HS400 and HS400ES.
# ---------------------------------------------------------------------------
TIMING_MODE_WIDTH_LEGALITY_EMMC = {
    "LEGACY": {"1BIT", "4BIT", "8BIT"},
    "HS_SDR": {"1BIT", "4BIT", "8BIT"},
    "HS_DDR": {"4BIT", "8BIT"},
    "HS200": {"4BIT", "8BIT"},
    "HS400": {"8BIT"},
    "HS400ES": {"8BIT"},
}

FIXED_PARTITIONS_EMMC = ("USER_AREA", "BOOT1", "BOOT2", "RPMB", "ENH_USER_AREA",
                     "GP1", "GP2", "GP3", "GP4")


def _fail_emmc(reason, **extra):
    r = {"status": "FAIL", "reason": reason}
    r.update(extra)
    return r


def _expected_partitions_emmc(ext_csd):
    """Deterministically derive the set of partitions EXT_CSD declares enabled."""
    expected = {"USER_AREA"}
    if int(ext_csd.get("boot_size_mult", 0)) > 0:
        expected.add("BOOT1")
        expected.add("BOOT2")
    if int(ext_csd.get("rpmb_size_mult", 0)) > 0:
        expected.add("RPMB")
    partitioning_en = int(ext_csd.get("partitioning_support", 0)) & 0x1 == 1
    setting_completed = int(ext_csd.get("partition_setting_completed", 0)) == 1
    if partitioning_en and setting_completed:
        if int(ext_csd.get("enh_size_mult", 0)) > 0:
            expected.add("ENH_USER_AREA")
        gp_mults = ext_csd.get("gp_size_mult", [0, 0, 0, 0])
        for i, mult in enumerate(gp_mults[:4]):
            if int(mult) > 0:
                expected.add(f"GP{i + 1}")
    return expected


def check_emmc(d):
    """
    Deterministic structural completeness checks for eMMC, covering:
      1. command x response-type completeness (EMMC_CMD_RESPONSE), including a
         mandatory-command-set presence check (MANDATORY_EMMC_COMMANDS)
      2. partition/boot-area completeness (EXT_CSD-derived, _expected_partitions_emmc)
      3. HS200/HS400 timing-mode x bus-width legality + coverage, both missing
         and extra-beyond-declared-capability (TIMING_MODE_WIDTH_LEGALITY_EMMC)

    Input `d` shape -- see the JSON example shipped alongside this function.
    Returns (result_dict, exit_code); exit_code 0 == PASS.
    """
    if d.get("emmc_applicable") is False:
        reason = d.get("emmc_not_applicable_reason")
        if not reason:
            return _fail_emmc("NOT_APPLICABLE_WITHOUT_JUSTIFICATION"), 2
        return {"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}, 0

    required_top = ["ext_csd", "declared_commands", "partition_access_coverage",
                     "device_capability", "timing_mode_width_coverage"]
    missing = [k for k in required_top if k not in d]
    if missing:
        return _fail_emmc("MISSING_FIELDS", missing=missing), 3

    # ---- (1) command x response-type completeness ----
    declared_commands = d.get("declared_commands") or []
    if not declared_commands:
        return _fail_emmc("NO_DECLARED_COMMANDS"), 4

    seen_cmds = set()
    for i, entry in enumerate(declared_commands):
        cmd = entry.get("cmd_index")
        resp = entry.get("response_type")
        if cmd is None or resp is None:
            return _fail_emmc("MALFORMED_COMMAND_ENTRY", index=i, entry=entry), 5
        if cmd in seen_cmds:
            return _fail_emmc("DUPLICATE_COMMAND_ENTRY", cmd_index=cmd), 6
        seen_cmds.add(cmd)
        if cmd in VENDOR_RESERVED_CMDS_EMMC:
            continue  # spec leaves vendor-reserved command response types unconstrained
        expected = EMMC_CMD_RESPONSE.get(cmd)
        if expected is None:
            return _fail_emmc("UNKNOWN_COMMAND_INDEX", cmd_index=cmd), 7
        if resp not in expected:
            return _fail_emmc("RESPONSE_TYPE_MISMATCH", cmd_index=cmd,
                          declared=resp, expected_one_of=sorted(expected)), 8

    missing_mandatory = sorted(MANDATORY_EMMC_COMMANDS - seen_cmds)
    if missing_mandatory:
        return _fail_emmc("MISSING_MANDATORY_COMMANDS",
                      expected_mandatory_count=len(MANDATORY_EMMC_COMMANDS),
                      missing_commands=missing_mandatory), 9

    # ---- (2) partition/boot-area completeness ----
    ext_csd = d.get("ext_csd") or {}
    expected_partitions = _expected_partitions_emmc(ext_csd)

    coverage = d.get("partition_access_coverage") or []
    seen_partitions = {}
    for i, entry in enumerate(coverage):
        part = entry.get("partition")
        status = entry.get("status")
        if part not in FIXED_PARTITIONS_EMMC:
            return _fail_emmc("UNKNOWN_PARTITION_IN_COVERAGE", index=i, partition=part), 10
        if status not in VALID_COVERAGE_STATUSES_EMMC:
            return _fail_emmc("INVALID_PARTITION_COVERAGE_STATUS", index=i,
                          partition=part, status=status), 11
        if status in ("WAIVED", "NOT_APPLICABLE") and not (
                entry.get("waiver_approved") and entry.get("waiver_evidence")):
            return _fail_emmc("UNAPPROVED_PARTITION_COVERAGE_WAIVER", partition=part), 12
        if part in seen_partitions:
            return _fail_emmc("DUPLICATE_PARTITION_COVERAGE_ENTRY", partition=part), 13
        seen_partitions[part] = status

    missing_partitions = sorted(expected_partitions - set(seen_partitions))
    if missing_partitions:
        return _fail_emmc("MISSING_PARTITION_COVERAGE",
                      expected_partition_count=len(expected_partitions),
                      missing_partitions=missing_partitions), 14

    extra_partitions = sorted(
        p for p in seen_partitions
        if p not in expected_partitions and p != "USER_AREA"
    )
    if extra_partitions:
        return _fail_emmc("PARTITION_COVERAGE_FOR_DISABLED_PARTITION",
                      partitions=extra_partitions), 15

    # ---- (3) HS200/HS400 timing-mode x bus-width legality + coverage ----
    cap = d.get("device_capability") or {}
    supported_widths = set(cap.get("supported_bus_widths") or [])
    supported_modes = set(cap.get("supported_timing_modes") or [])
    unknown_modes = supported_modes - set(TIMING_MODE_WIDTH_LEGALITY_EMMC)
    if unknown_modes:
        return _fail_emmc("UNKNOWN_TIMING_MODE_DECLARED", modes=sorted(unknown_modes)), 16

    expected_pairs = set()
    for mode in supported_modes:
        legal_widths = TIMING_MODE_WIDTH_LEGALITY_EMMC[mode]
        for width in (supported_widths & legal_widths):
            expected_pairs.add((mode, width))

    tw_coverage = d.get("timing_mode_width_coverage") or []
    seen_pairs = {}
    for i, entry in enumerate(tw_coverage):
        mode = entry.get("timing_mode")
        width = entry.get("bus_width")
        status = entry.get("status")
        if mode not in TIMING_MODE_WIDTH_LEGALITY_EMMC:
            return _fail_emmc("UNKNOWN_TIMING_MODE_IN_COVERAGE", index=i, timing_mode=mode), 17
        if width not in TIMING_MODE_WIDTH_LEGALITY_EMMC[mode]:
            return _fail_emmc("ILLEGAL_TIMING_MODE_WIDTH_PAIR", index=i,
                          timing_mode=mode, bus_width=width,
                          legal_widths=sorted(TIMING_MODE_WIDTH_LEGALITY_EMMC[mode])), 18
        if status not in VALID_COVERAGE_STATUSES_EMMC:
            return _fail_emmc("INVALID_TIMING_WIDTH_COVERAGE_STATUS", index=i,
                          timing_mode=mode, bus_width=width, status=status), 19
        if status in ("WAIVED", "NOT_APPLICABLE") and not (
                entry.get("waiver_approved") and entry.get("waiver_evidence")):
            return _fail_emmc("UNAPPROVED_TIMING_WIDTH_COVERAGE_WAIVER",
                          timing_mode=mode, bus_width=width), 20
        pair = (mode, width)
        if pair in seen_pairs:
            return _fail_emmc("DUPLICATE_TIMING_WIDTH_COVERAGE_ENTRY",
                          timing_mode=mode, bus_width=width), 21
        seen_pairs[pair] = status

    missing_pairs = sorted(expected_pairs - set(seen_pairs))
    if missing_pairs:
        return _fail_emmc("MISSING_TIMING_WIDTH_PAIRS",
                      expected_pair_count=len(expected_pairs),
                      missing_pairs=[f"{m}@{w}" for m, w in missing_pairs]), 22

    extra_pairs = sorted(pair for pair in seen_pairs if pair not in expected_pairs)
    if extra_pairs:
        return _fail_emmc("EXTRA_TIMING_WIDTH_PAIR_BEYOND_CAPABILITY",
                      pairs=[f"{m}@{w}" for m, w in extra_pairs]), 23

    return {
        "status": "PASS",
        "commands_checked": len(declared_commands),
        "partitions_expected": len(expected_partitions),
        "timing_width_pairs_expected": len(expected_pairs),
    }, 0

# check_edp(d) -- eDP / DisplayPort structural completeness checker (FIXED)
#
# Convention: returns (result: dict, exit_code: int).
#   exit_code == 0  -> result["status"] in {"PASS", "SKIPPED_NOT_APPLICABLE"}
#   exit_code != 0  -> result["status"] == "FAIL", result["reason"] names the branch
# This function never prints or calls sys.exit, and never raises on malformed-but-
# plausible input -- every .get()/iteration site is type-guarded so bad shapes come
# back as a clean FAIL instead of an uncaught exception. Same convention as the other
# CHECKERS entries.
#
# Deterministic structural checks only -- no RTL semantic judgment, no timing/electrical
# analysis. Two independent completeness domains, each keyed off a set the DUT itself
# declares as applicable (mirroring masters/slaves in the AMBA fabric gate):
#
#   (1) Link-training CR/EQ completeness -- VESA DP link-training state machine
#       (Clock Recovery via TPS1, Channel Equalization via TPS2/3/4), driven through DPCD
#       LINK_BW_SET(0x100)/LANE_COUNT_SET(0x101)/TRAINING_PATTERN_SET(0x102) and observed
#       through DPCD LANE0_1_STATUS/LANE2_3_STATUS(0x202-0x203) CR_DONE + CHANNEL_EQ_DONE +
#       SYMBOL_LOCKED, and LANE_ALIGN_STATUS_UPDATED(0x204) INTERLANE_ALIGN_DONE. Declared
#       supported_link_rates x supported_lane_counts is a fixed enumerable cell set, same
#       "M x N must all appear" shape as the AMBA scoreboard matrix.
#
#       SCOPE LIMIT (fixed after adversarial review): this uniform cr_done/ch_eq_done/
#       symbol_locked/interlane_align_done shape is only valid for the 8b/10b channel-coding
#       family (RBR/HBR/HBR2/HBR3). DP2.0-style 128b/132b rates (UHBR10/UHBR13_5/UHBR20) use
#       different training semantics (adds CDS; SYMBOL_LOCKED/CHANNEL_EQ_DONE don't carry the
#       same meaning), so mapping them onto these three booleans would require a protocol-
#       semantic judgment call this checker deliberately avoids. UHBR/128b132b rates are
#       therefore explicitly out of scope and rejected with a distinct reason rather than
#       silently mis-checked; a dedicated 128b/132b completeness checker should cover them.
#
#   (2) AUX-channel transaction-type completeness -- DP AUX CH request-field encoding fixes
#       Native AUX Write/Read and I2C-over-AUX Write/Read/Write-Status-Update as the
#       transaction-type universe. Declared applicable_types subset must each appear at
#       least once in the transaction log with a valid ACK'd reply.
#
#       MOT NOTE (corrected after adversarial review): MOT ("middle of transaction") is a
#       modifier bit that applies to ALL THREE I2C-over-AUX command types (write, read, and
#       write-status-update), not just write-status-update. AUX_TRANSACTION_UNIVERSE_EDP does not
#       track MOT as a separate dimension for any token -- this is an intentional collapse
#       (MOT=0 and MOT=1 sequences of the same type are not distinguished), not a reflection
#       of MOT only mattering for one command. If a compliance/MST plan needs MOT=1 sequences
#       exercised and observed separately, that must be added as its own explicit dimension --
#       it is not implied by anything in this universe today.
#
# MST topology completeness is intentionally NOT implemented -- see accompanying notes:
# MST branch/port/payload topology is runtime-discovered (LINK_ADDRESS, ENUM_PATH_RESOURCES)
# and DUT/system-specific, not a fixed spec-enumerable set, so no universal rule is forced.

VALID_STATUSES_EDP = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}
VALID_ROLES_EDP = {"SOURCE", "SINK"}
VALID_LANE_COUNTS_EDP = {1, 2, 4}
# 8b/10b family only -- see SCOPE LIMIT note above. DP2.0 128b/132b tokens are handled by the
# explicit UHBR_128B132B_TOKENS_EDP out-of-scope check below, not silently accepted here.
VALID_LINK_RATE_TOKENS_EDP = {"RBR", "HBR", "HBR2", "HBR3"}
UHBR_128B132B_TOKENS_EDP = {"UHBR10", "UHBR13_5", "UHBR20"}
AUX_TRANSACTION_UNIVERSE_EDP = {"NATIVE_READ", "NATIVE_WRITE", "I2C_READ", "I2C_WRITE", "I2C_WRITE_STATUS_UPDATE"}
VALID_AUX_REPLIES_EDP = {"ACK", "NACK", "DEFER", "I2C_NACK", "I2C_DEFER"}


def _is_plain_int_edp(x):
    # bool is a subclass of int in Python; never accept True/False where an int is expected.
    return isinstance(x, int) and not isinstance(x, bool)


def check_edp(d):
    if d.get("edp_applicable") is False:
        reason = d.get("edp_not_applicable_reason")
        if not reason:
            return {"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}, 2
        return {"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}, 0

    required_top = ["role", "link_training", "aux_transactions"]
    missing = [k for k in required_top if k not in d]
    if missing:
        return {"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing}, 3

    role = d.get("role")
    if role not in VALID_ROLES_EDP:
        return {"status": "FAIL", "reason": "INVALID_ROLE", "role": role}, 4

    # ---- (1) Link-training CR/EQ completeness ----
    lt = d.get("link_training") or {}
    if not isinstance(lt, dict):
        return {"status": "FAIL", "reason": "INVALID_LINK_TRAINING_TYPE",
                "link_training_type": type(lt).__name__}, 27

    link_rates = lt.get("supported_link_rates") or []
    if not isinstance(link_rates, list):
        return {"status": "FAIL", "reason": "INVALID_LINK_RATES_TYPE",
                "supported_link_rates_type": type(link_rates).__name__}, 28

    lane_counts = lt.get("supported_lane_counts") or []
    if not isinstance(lane_counts, list):
        return {"status": "FAIL", "reason": "INVALID_LANE_COUNTS_TYPE",
                "supported_lane_counts_type": type(lane_counts).__name__}, 29

    sequences = lt.get("sequences") or []
    if not isinstance(sequences, list):
        return {"status": "FAIL", "reason": "INVALID_SEQUENCES_TYPE",
                "sequences_type": type(sequences).__name__}, 30

    if not link_rates:
        return {"status": "FAIL", "reason": "NO_SUPPORTED_LINK_RATES"}, 5
    if not lane_counts:
        return {"status": "FAIL", "reason": "NO_SUPPORTED_LANE_COUNTS"}, 6

    uhbr_used = sorted((r for r in link_rates if isinstance(r, str) and r in UHBR_128B132B_TOKENS_EDP), key=str)
    if uhbr_used:
        return {"status": "FAIL", "reason": "UHBR_128B132B_OUT_OF_SCOPE", "rates": uhbr_used,
                "detail": ("128b/132b (DP2.0 UHBR) link-training completion uses different "
                           "CR/EQ/CDS DPCD semantics than 8b/10b; this checker only covers "
                           "8b/10b (RBR/HBR/HBR2/HBR3). Route UHBR sequences to a dedicated "
                           "128b/132b completeness checker.")}, 31

    # Guard membership/sort against unhashable or wrong-typed entries (e.g. a dict/list
    # smuggled into the rates/lane-counts arrays) before they ever reach a set() or sorted().
    bad_rates = sorted((r for r in link_rates if not (isinstance(r, str) and r in VALID_LINK_RATE_TOKENS_EDP)), key=str)
    if bad_rates:
        return {"status": "FAIL", "reason": "INVALID_LINK_RATE_TOKEN", "rates": bad_rates}, 7
    bad_lanes = sorted((n for n in lane_counts if not (_is_plain_int_edp(n) and n in VALID_LANE_COUNTS_EDP)), key=str)
    if bad_lanes:
        return {"status": "FAIL", "reason": "INVALID_LANE_COUNT", "lane_counts": bad_lanes}, 8

    if len(set(link_rates)) != len(link_rates):
        dup = sorted({r for r in link_rates if link_rates.count(r) > 1})
        return {"status": "FAIL", "reason": "DUPLICATE_LINK_RATE", "duplicates": dup}, 9
    if len(set(lane_counts)) != len(lane_counts):
        dup = sorted({n for n in lane_counts if lane_counts.count(n) > 1})
        return {"status": "FAIL", "reason": "DUPLICATE_LANE_COUNT", "duplicates": dup}, 10

    rate_set = set(link_rates)
    lane_set = set(lane_counts)
    expected_pairs = {(r, n) for r in link_rates for n in lane_counts}
    seen_pairs = {}

    for i, seq in enumerate(sequences):
        if not isinstance(seq, dict):
            return {"status": "FAIL", "reason": "INVALID_SEQUENCE_ENTRY_TYPE", "index": i,
                    "entry_type": type(seq).__name__}, 32

        rate = seq.get("link_rate")
        lanes_n = seq.get("lane_count")
        status = seq.get("status")

        if rate not in rate_set:
            return {"status": "FAIL", "reason": "UNKNOWN_LINK_RATE_IN_SEQUENCE", "index": i, "link_rate": rate}, 11
        if lanes_n not in lane_set:
            return {"status": "FAIL", "reason": "UNKNOWN_LANE_COUNT_IN_SEQUENCE", "index": i, "lane_count": lanes_n}, 12
        if status not in VALID_STATUSES_EDP:
            return {"status": "FAIL", "reason": "INVALID_SEQUENCE_STATUS", "index": i,
                    "link_rate": rate, "lane_count": lanes_n, "status": status}, 13
        if status in ("WAIVED", "NOT_APPLICABLE") and not (seq.get("waiver_approved") and seq.get("waiver_evidence")):
            return {"status": "FAIL", "reason": "UNAPPROVED_LINK_TRAINING_WAIVER",
                    "link_rate": rate, "lane_count": lanes_n}, 14

        pair = (rate, lanes_n)
        if pair in seen_pairs:
            return {"status": "FAIL", "reason": "DUPLICATE_LINK_TRAINING_SEQUENCE",
                    "link_rate": rate, "lane_count": lanes_n}, 15
        seen_pairs[pair] = status

        if status == "IMPLEMENTED":
            lanes = seq.get("lanes") or []
            if not isinstance(lanes, list):
                return {"status": "FAIL", "reason": "INVALID_LANES_TYPE", "index": i,
                        "link_rate": rate, "lane_count": lanes_n,
                        "lanes_type": type(lanes).__name__}, 33
            if len(lanes) != lanes_n:
                return {"status": "FAIL", "reason": "LANE_ENTRY_COUNT_MISMATCH", "index": i,
                        "link_rate": rate, "declared_lane_count": lanes_n, "lane_entries": len(lanes)}, 16
            if not all(isinstance(ln, dict) for ln in lanes):
                return {"status": "FAIL", "reason": "INVALID_LANE_ENTRY_TYPE", "index": i,
                        "link_rate": rate, "lane_count": lanes_n}, 34

            lane_id_values = [ln.get("lane_id") for ln in lanes]
            if not all(_is_plain_int_edp(x) for x in lane_id_values):
                return {"status": "FAIL", "reason": "INVALID_LANE_ID_SET", "index": i,
                        "link_rate": rate, "lane_count": lanes_n,
                        "lane_ids": [str(x) for x in lane_id_values]}, 17
            lane_ids = sorted(lane_id_values)
            if lane_ids != list(range(lanes_n)):
                return {"status": "FAIL", "reason": "INVALID_LANE_ID_SET", "index": i,
                        "link_rate": rate, "lane_count": lanes_n, "lane_ids": lane_ids}, 17

            for ln in lanes:
                if not (ln.get("cr_done") and ln.get("ch_eq_done") and ln.get("symbol_locked")):
                    return {"status": "FAIL", "reason": "INCOMPLETE_LANE_TRAINING", "index": i,
                            "link_rate": rate, "lane_count": lanes_n, "lane_id": ln.get("lane_id"),
                            "cr_done": ln.get("cr_done"), "ch_eq_done": ln.get("ch_eq_done"),
                            "symbol_locked": ln.get("symbol_locked")}, 18
            if not seq.get("interlane_align_done"):
                return {"status": "FAIL", "reason": "MISSING_INTERLANE_ALIGN_DONE", "index": i,
                        "link_rate": rate, "lane_count": lanes_n}, 19

    missing_pairs = sorted(expected_pairs - set(seen_pairs))
    if missing_pairs:
        return {"status": "FAIL", "reason": "MISSING_LINK_TRAINING_PAIRS",
                "expected_pair_count": len(expected_pairs),
                "missing_pairs": [f"{r}@{n}lane" for r, n in missing_pairs]}, 20

    # ---- (2) AUX transaction-type completeness ----
    aux = d.get("aux_transactions") or {}
    if not isinstance(aux, dict):
        return {"status": "FAIL", "reason": "INVALID_AUX_TRANSACTIONS_TYPE",
                "aux_transactions_type": type(aux).__name__}, 35

    applicable_types = aux.get("applicable_types") or []
    if not isinstance(applicable_types, list):
        return {"status": "FAIL", "reason": "INVALID_APPLICABLE_TYPES_TYPE",
                "applicable_types_type": type(applicable_types).__name__}, 36

    observed = aux.get("observed") or []
    if not isinstance(observed, list):
        return {"status": "FAIL", "reason": "INVALID_OBSERVED_TYPE",
                "observed_type": type(observed).__name__}, 37

    if not applicable_types:
        return {"status": "FAIL", "reason": "NO_APPLICABLE_AUX_TRANSACTION_TYPES"}, 21

    bad_types = sorted((t for t in applicable_types if not (isinstance(t, str) and t in AUX_TRANSACTION_UNIVERSE_EDP)), key=str)
    if bad_types:
        return {"status": "FAIL", "reason": "INVALID_AUX_TRANSACTION_TYPE", "types": bad_types}, 22
    if len(set(applicable_types)) != len(applicable_types):
        dup = sorted({t for t in applicable_types if applicable_types.count(t) > 1})
        return {"status": "FAIL", "reason": "DUPLICATE_APPLICABLE_AUX_TYPE", "duplicates": dup}, 23

    applicable_set = set(applicable_types)
    acked_types = set()
    for i, obs in enumerate(observed):
        if not isinstance(obs, dict):
            return {"status": "FAIL", "reason": "INVALID_AUX_OBSERVATION_TYPE", "index": i,
                    "entry_type": type(obs).__name__}, 38

        ttype = obs.get("type")
        reply = obs.get("reply")
        count = obs.get("count", 0)
        if ttype not in applicable_set:
            return {"status": "FAIL", "reason": "UNDECLARED_AUX_TRANSACTION_TYPE", "index": i, "type": ttype}, 24
        if reply not in VALID_AUX_REPLIES_EDP:
            return {"status": "FAIL", "reason": "INVALID_AUX_REPLY", "index": i, "type": ttype, "reply": reply}, 25
        if reply == "ACK" and _is_plain_int_edp(count) and count > 0:
            acked_types.add(ttype)

    missing_types = sorted(applicable_set - acked_types)
    if missing_types:
        return {"status": "FAIL", "reason": "MISSING_ACKED_AUX_TRANSACTION_TYPES",
                "applicable_count": len(applicable_set), "missing_types": missing_types}, 26

    return {
        "status": "PASS",
        "role": role,
        "link_training_pairs": len(expected_pairs),
        "aux_transaction_types": len(applicable_set),
    }, 0

# --- USB structural completeness checker (dispatcher case) ---------------
# Slot this into the shared dispatcher's CHECKERS map keyed by protocol=="USB".
# Style matches tools/verification_flow/fabric_topology_completeness_gate.py:
# deterministic structural checks only, no RTL/runtime semantic judgment.
#
# Return convention: (result_dict, exit_code).
#   exit_code == 0  <=>  result_dict["status"] in {"PASS","SKIPPED_NOT_APPLICABLE"}
#   exit_code != 0  <=>  result_dict["status"] == "FAIL"
# The numeric exit codes are local ordinals only (mirrors the AMBA gate's own
# per-branch numbering) -- the coordinator may renumber/namespace them when
# merging into the shared dispatcher; only "status"/"reason" are the stable
# cross-checker contract fields.
#
# Deliberately NOT implemented: USB3 U0/U1/U2/U3 link-state transition
# coverage. U1/U2 support is optional and negotiated at runtime (LPM
# LGO_U1/LGO_U2, U1_ENABLE/U2_ENABLE, SEL/PEL timers) -- only U0 and U3 are
# spec-mandatory -- so "which states/transitions this DUT must cover" is not
# derivable from static declared topology the way an address map or a
# transfer-type matrix is. The physical-layer training substates (Polling,
# Recovery, Compliance, Loopback, Rx.Detect) are additionally driven by
# analog/timing events (LFPS, receiver detection), i.e. runtime trace
# evidence, not JSON-payload structure. Forcing a fixed cross-product here
# would be inventing a rule the spec does not make deterministic.

USB_TRANSFER_TYPES = {"CONTROL", "BULK", "INTERRUPT", "ISOCHRONOUS"}
USB_SPEEDS = {"LS", "FS", "HS", "SS", "SSP"}
# USB 2.0 spec 5.3.1 / 9.6.6: Low-Speed endpoints must not be Bulk or
# Isochronous -- these two (transfer_type, speed) cells are spec-illegal,
# not merely un-implemented, so they are excluded from the required set and
# any declared entry landing on them is itself a FAIL.
USB_LS_ILLEGAL_TRANSFER_TYPES = {"BULK", "ISOCHRONOUS"}

# USB 2.0 spec 9.4.3 / Table 9-5: standard descriptor types obtainable via a
# standalone GET_DESCRIPTOR request. INTERFACE(4) and ENDPOINT(5) are
# intentionally excluded from this set -- spec 9.4.3 states there is no way
# to request them independently; they are only ever returned nested inside
# a CONFIGURATION descriptor's payload. BOS(0x0F) is the USB3 / USB2-LPM
# addition (spec 9.6.2 family).
USB_STANDALONE_DESCRIPTOR_TYPES = {
    "DEVICE", "CONFIGURATION", "STRING",
    "DEVICE_QUALIFIER", "OTHER_SPEED_CONFIGURATION", "BOS",
}
USB_NON_STANDALONE_DESCRIPTOR_TYPES = {"INTERFACE", "ENDPOINT"}

# Speeds that make a device "dual-speed" per USB2 spec 9.6.2 (HS-capable
# devices always also support a lower fallback speed) and speeds that make
# it USB3-capable. These are used to cross-validate the caller-supplied
# dual_speed/usb3_capable flags below (must-fix: see CONTRADICTORY_SPEED_
# FLAG_DECLARATION) rather than trusting them as free-standing booleans.
USB_HS_SPEED = "HS"
USB_LOWER_SPEEDS = {"FS", "LS"}
USB3_SPEEDS = {"SS", "SSP"}

VALID_STATUSES_USB = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}


def _waiver_ok_usb(entry):
    return bool(entry.get("waiver_approved") and entry.get("waiver_evidence"))


def check_usb(d):
    # ---- optional escape hatch, mirrors topology_applicable in the AMBA gate ----
    if d.get("usb_not_applicable") is True:
        reason = d.get("usb_not_applicable_reason")
        if not reason:
            return ({"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}, 2)
        return ({"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}, 0)

    required_top = ["declared_speeds", "transfer_type_matrix",
                    "num_configurations_declared", "descriptor_requests"]
    missing = [k for k in required_top if k not in d]
    if missing:
        return ({"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing}, 3)

    declared_speeds = d.get("declared_speeds") or []
    dual_speed = bool(d.get("dual_speed", False))
    lpm_capable = bool(d.get("lpm_capable", False))
    usb3_capable = bool(d.get("usb3_capable", False))
    string_indices_declared = d.get("string_indices_declared") or []
    num_configs = d.get("num_configurations_declared")
    matrix = d.get("transfer_type_matrix") or []
    descriptor_requests = d.get("descriptor_requests") or []
    configurations = d.get("configurations") or []

    if not declared_speeds:
        return ({"status": "FAIL", "reason": "NO_DECLARED_SPEEDS"}, 4)
    if any(s not in USB_SPEEDS for s in declared_speeds):
        bad = sorted({s for s in declared_speeds if s not in USB_SPEEDS})
        return ({"status": "FAIL", "reason": "INVALID_SPEED_VALUE", "invalid": bad}, 5)
    if len(set(declared_speeds)) != len(declared_speeds):
        dup = sorted({s for s in declared_speeds if declared_speeds.count(s) > 1})
        return ({"status": "FAIL", "reason": "DUPLICATE_DECLARED_SPEED", "duplicates": dup}, 6)

    speed_set = set(declared_speeds)

    # ---- must-fix: dual_speed/usb3_capable are structurally derivable from
    # declared_speeds (HS + a lower speed => dual-speed; SS/SSP => USB3-
    # capable). Previously these flags were trusted as independent booleans
    # with no cross-check, so a payload could under-declare them (e.g. leave
    # dual_speed=False on a device that declares HS+FS) to silently skip the
    # DEVICE_QUALIFIER/OTHER_SPEED_CONFIGURATION/BOS requirements below --
    # gaming the gate rather than tripping it. lpm_capable is intentionally
    # NOT cross-checked here: LPM is an optional per-device capability not
    # implied by which speeds are declared, so no structural derivation for
    # it exists without fabricating a rule the spec doesn't state.
    derived_dual_speed = (USB_HS_SPEED in speed_set) and bool(speed_set & USB_LOWER_SPEEDS)
    derived_usb3_capable = bool(speed_set & USB3_SPEEDS)
    if dual_speed != derived_dual_speed:
        return ({"status": "FAIL", "reason": "CONTRADICTORY_SPEED_FLAG_DECLARATION",
                 "flag": "dual_speed", "declared_value": dual_speed,
                 "expected_value": derived_dual_speed, "declared_speeds": sorted(speed_set)}, 25)
    if usb3_capable != derived_usb3_capable:
        return ({"status": "FAIL", "reason": "CONTRADICTORY_SPEED_FLAG_DECLARATION",
                 "flag": "usb3_capable", "declared_value": usb3_capable,
                 "expected_value": derived_usb3_capable, "declared_speeds": sorted(speed_set)}, 25)

    # ================= (1) transfer-type x speed-mode completeness =================
    expected_pairs = {
        (t, s) for t in USB_TRANSFER_TYPES for s in speed_set
        if not (s == "LS" and t in USB_LS_ILLEGAL_TRANSFER_TYPES)
    }
    seen_pairs = {}
    for i, entry in enumerate(matrix):
        t = entry.get("transfer_type")
        s = entry.get("speed")
        status = entry.get("status")
        if t not in USB_TRANSFER_TYPES:
            return ({"status": "FAIL", "reason": "UNKNOWN_TRANSFER_TYPE_IN_MATRIX",
                     "index": i, "transfer_type": t}, 7)
        if s not in speed_set:
            return ({"status": "FAIL", "reason": "UNKNOWN_SPEED_IN_MATRIX",
                     "index": i, "speed": s}, 8)
        if s == "LS" and t in USB_LS_ILLEGAL_TRANSFER_TYPES:
            return ({"status": "FAIL", "reason": "SPEC_INVALID_TRANSFER_SPEED_PAIR",
                     "index": i, "transfer_type": t, "speed": s,
                     "detail": "USB2 spec 5.3.1/9.6.6: Low-Speed endpoints must not be "
                               "Bulk or Isochronous"}, 12)
        if status not in VALID_STATUSES_USB:
            return ({"status": "FAIL", "reason": "INVALID_MATRIX_STATUS",
                     "index": i, "transfer_type": t, "speed": s, "status": status}, 9)
        if status in ("WAIVED", "NOT_APPLICABLE") and not _waiver_ok_usb(entry):
            return ({"status": "FAIL", "reason": "UNAPPROVED_MATRIX_WAIVER",
                     "transfer_type": t, "speed": s}, 10)
        pair = (t, s)
        if pair in seen_pairs:
            return ({"status": "FAIL", "reason": "DUPLICATE_MATRIX_ENTRY",
                     "transfer_type": t, "speed": s}, 11)
        seen_pairs[pair] = status

    missing_pairs = sorted(expected_pairs - set(seen_pairs))
    if missing_pairs:
        return ({"status": "FAIL", "reason": "MISSING_TRANSFER_SPEED_PAIRS",
                 "expected_pair_count": len(expected_pairs),
                 "missing_pairs": [f"{t}@{s}" for t, s in missing_pairs]}, 13)

    # ================= (2) enumeration / descriptor-request completeness =================
    # (opportunistic nice-to-have fix, trivial and in the same block: Python
    # bool is a subclass of int, so isinstance(True, int) is True -- without
    # this guard a payload could pass num_configurations_declared=True/False.)
    if isinstance(num_configs, bool) or not isinstance(num_configs, int) or num_configs < 1:
        return ({"status": "FAIL", "reason": "INVALID_NUM_CONFIGURATIONS_DECLARED",
                 "num_configurations_declared": num_configs}, 14)

    # (opportunistic nice-to-have fix, trivial and in the same block:
    # validate string indices before folding them into the required set, so
    # garbage/negative indices surface as a direct INVALID_STRING_INDEX FAIL
    # instead of an always-unsatisfiable MISSING_DESCRIPTOR_REQUESTS trap.)
    bad_string_indices = [
        idx for idx in string_indices_declared
        if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0
    ]
    if bad_string_indices:
        return ({"status": "FAIL", "reason": "INVALID_STRING_INDEX",
                 "invalid": bad_string_indices}, 26)

    required_descriptor_requests = {("DEVICE", 0)}
    required_descriptor_requests |= {("CONFIGURATION", i) for i in range(num_configs)}
    if string_indices_declared:
        required_descriptor_requests.add(("STRING", 0))  # LANGID, spec 9.6.7
        required_descriptor_requests |= {
            ("STRING", idx) for idx in string_indices_declared if idx != 0
        }
    if dual_speed:
        # spec 9.6.2: only dual-speed (HS + FS/LS capable) devices carry these;
        # a single-speed device must STALL such a request instead.
        required_descriptor_requests.add(("DEVICE_QUALIFIER", 0))
        required_descriptor_requests |= {
            ("OTHER_SPEED_CONFIGURATION", i) for i in range(num_configs)
        }
    if usb3_capable or lpm_capable:
        required_descriptor_requests.add(("BOS", 0))

    seen_requests = {}
    for i, entry in enumerate(descriptor_requests):
        dtype = entry.get("descriptor_type")
        index = entry.get("index")
        status = entry.get("status")
        if dtype in USB_NON_STANDALONE_DESCRIPTOR_TYPES:
            return ({"status": "FAIL", "reason": "DISALLOWED_STANDALONE_DESCRIPTOR_REQUEST",
                     "index": i, "descriptor_type": dtype,
                     "detail": "USB2 spec 9.4.3: INTERFACE/ENDPOINT descriptors are only "
                               "returned nested inside a CONFIGURATION descriptor, never "
                               "requested standalone"}, 15)
        if dtype not in USB_STANDALONE_DESCRIPTOR_TYPES:
            return ({"status": "FAIL", "reason": "UNKNOWN_DESCRIPTOR_TYPE",
                     "index": i, "descriptor_type": dtype}, 16)
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            return ({"status": "FAIL", "reason": "INVALID_DESCRIPTOR_INDEX",
                     "index": i, "descriptor_type": dtype, "value": index}, 17)
        if status not in VALID_STATUSES_USB:
            return ({"status": "FAIL", "reason": "INVALID_DESCRIPTOR_STATUS",
                     "descriptor_type": dtype, "descriptor_index": index, "status": status}, 18)
        if status in ("WAIVED", "NOT_APPLICABLE") and not _waiver_ok_usb(entry):
            return ({"status": "FAIL", "reason": "UNAPPROVED_DESCRIPTOR_WAIVER",
                     "descriptor_type": dtype, "descriptor_index": index}, 19)
        key = (dtype, index)
        if key in seen_requests:
            return ({"status": "FAIL", "reason": "DUPLICATE_DESCRIPTOR_REQUEST_ENTRY",
                     "descriptor_type": dtype, "descriptor_index": index}, 20)
        seen_requests[key] = status

    missing_requests = sorted(required_descriptor_requests - set(seen_requests))
    if missing_requests:
        return ({"status": "FAIL", "reason": "MISSING_DESCRIPTOR_REQUESTS",
                 "required_count": len(required_descriptor_requests),
                 "missing": [f"{t}#{i}" for t, i in missing_requests]}, 21)

    # ---- INTERFACE/ENDPOINT completeness is nesting-count consistency, not request coverage ----
    if configurations:
        if len(configurations) != num_configs:
            return ({"status": "FAIL", "reason": "CONFIGURATION_COUNT_MISMATCH",
                     "declared": num_configs, "actual": len(configurations)}, 22)
        for cfg in configurations:
            ci = cfg.get("config_index")
            declared_n_if = cfg.get("num_interfaces_declared")
            interfaces = cfg.get("interfaces") or []
            if declared_n_if != len(interfaces):
                return ({"status": "FAIL", "reason": "CONFIGURATION_INTERFACE_COUNT_MISMATCH",
                         "config_index": ci, "declared": declared_n_if,
                         "actual": len(interfaces)}, 23)
            for iface in interfaces:
                ii = iface.get("interface_index")
                declared_n_ep = iface.get("num_endpoints_declared")
                endpoints = iface.get("endpoints") or []
                if declared_n_ep != len(endpoints):
                    return ({"status": "FAIL", "reason": "INTERFACE_ENDPOINT_COUNT_MISMATCH",
                             "config_index": ci, "interface_index": ii,
                             "declared": declared_n_ep, "actual": len(endpoints)}, 24)

    return ({
        "status": "PASS",
        "declared_speeds": sorted(speed_set),
        "transfer_speed_pairs_required": len(expected_pairs),
        "descriptor_requests_required": len(required_descriptor_requests),
        "configurations_checked": len(configurations),
    }, 0)

"""
check_ucie(d) -- UCIe structural completeness checker, written in the house
style of tools/verification_flow/fabric_topology_completeness_gate.py, but
packaged as a pure dispatch-case function (no argparse/main/sys.exit of its
own) for a shared dispatcher keyed on a top-level "protocol" field.

Convention (document this at the CHECKERS-map call site):
    result_dict, exit_code = check_ucie(d)
    print(json.dumps(result_dict))
    return exit_code
result_dict["status"] is one of PASS / FAIL / SKIPPED_NOT_APPLICABLE.
exit_code 0 covers both PASS and SKIPPED_NOT_APPLICABLE; every FAIL branch
gets its own nonzero code (local to this function -- the coordinator may
offset/renumber them when merging into the shared dispatcher's code space,
exactly as fabric_topology_completeness_gate.py's own codes are local to it).
"""

VALID_STATUSES_UCIE = {"IMPLEMENTED", "WAIVED", "NOT_APPLICABLE"}


def _needs_waiver_evidence_ucie(status, entry):
    return status in ("WAIVED", "NOT_APPLICABLE") and not (
        entry.get("waiver_approved") and entry.get("waiver_evidence")
    )


def _check_bijection_ucie(required_ids, coverage_list, id_key, reasons):
    """
    Generic "every required id has exactly one coverage entry with a valid,
    justified status" check, shared by all three sections below.

    reasons: dict with keys unknown/duplicate/invalid_status/unapproved_waiver/missing,
    each an (reason_string, exit_code) pair.

    Returns None on success, or (result_dict, exit_code) on the first failure.
    """
    required_set = set(required_ids)
    seen = {}
    for i, entry in enumerate(coverage_list):
        rid = entry.get(id_key)
        status = entry.get("status")
        if rid not in required_set:
            reason, code = reasons["unknown"]
            return {"status": "FAIL", "reason": reason, "index": i, id_key: rid}, code
        if rid in seen:
            reason, code = reasons["duplicate"]
            return {"status": "FAIL", "reason": reason, id_key: rid}, code
        if status not in VALID_STATUSES_UCIE:
            reason, code = reasons["invalid_status"]
            return {"status": "FAIL", "reason": reason, id_key: rid, "status_value": status}, code
        if _needs_waiver_evidence_ucie(status, entry):
            reason, code = reasons["unapproved_waiver"]
            return {"status": "FAIL", "reason": reason, id_key: rid}, code
        seen[rid] = status

    missing = sorted(required_set - set(seen))
    if missing:
        reason, code = reasons["missing"]
        return {"status": "FAIL", "reason": reason, "missing": missing}, code
    return None


def check_ucie(d):
    # ---- top-level applicability gate (same pattern as topology_applicable) ----
    if d.get("ucie_applicable") is False:
        reason = d.get("ucie_not_applicable_reason")
        if not reason:
            return {"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}, 2
        return {"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}, 0

    required_top = ["ucie_version", "link_training_states", "protocol_stacks", "module_width_repair"]
    missing_top = [k for k in required_top if k not in d]
    if missing_top:
        return {"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing_top}, 3

    # ---- Candidate 1: link-training / sideband state-machine completeness ----
    lts = d.get("link_training_states") or {}
    required_lts_fields = ["expected_states_reference", "expected_states_reference_source", "declared_state_coverage"]
    missing_lts = [k for k in required_lts_fields if k not in lts]
    if missing_lts:
        return {"status": "FAIL", "reason": "MISSING_LINK_TRAINING_FIELDS", "missing": missing_lts}, 4

    expected_states = lts.get("expected_states_reference") or []
    if not expected_states:
        return {"status": "FAIL", "reason": "EMPTY_EXPECTED_STATES_REFERENCE"}, 5
    if not (lts.get("expected_states_reference_source") or "").strip():
        return {"status": "FAIL", "reason": "EXPECTED_STATES_REFERENCE_MISSING_SPEC_CITATION"}, 6
    if len(set(expected_states)) != len(expected_states):
        dup = sorted({s for s in expected_states if expected_states.count(s) > 1})
        return {"status": "FAIL", "reason": "DUPLICATE_EXPECTED_STATE", "duplicates": dup}, 7

    lts_fail = _check_bijection_ucie(
        expected_states, lts.get("declared_state_coverage") or [], "state",
        {
            "unknown": ("UNKNOWN_STATE_IN_DECLARED_COVERAGE", 8),
            "duplicate": ("DUPLICATE_STATE_IN_DECLARED_COVERAGE", 9),
            "invalid_status": ("INVALID_STATE_STATUS", 10),
            "unapproved_waiver": ("UNAPPROVED_STATE_WAIVER", 11),
            "missing": ("MISSING_LINK_TRAINING_STATE_COVERAGE", 12),
        },
    )
    if lts_fail:
        return lts_fail

    # ---- Candidate 2: protocol-layer x stack completeness (Protocol ID coverage) ----
    pstacks = d.get("protocol_stacks") or {}
    required_ps_fields = ["declared_protocol_stacks", "stack_coverage"]
    missing_ps = [k for k in required_ps_fields if k not in pstacks]
    if missing_ps:
        return {"status": "FAIL", "reason": "MISSING_PROTOCOL_STACK_FIELDS", "missing": missing_ps}, 13

    declared_stacks = pstacks.get("declared_protocol_stacks") or []
    if not declared_stacks:
        return {"status": "FAIL", "reason": "EMPTY_DECLARED_PROTOCOL_STACKS"}, 14
    if len(set(declared_stacks)) != len(declared_stacks):
        dup = sorted({s for s in declared_stacks if declared_stacks.count(s) > 1})
        return {"status": "FAIL", "reason": "DUPLICATE_DECLARED_PROTOCOL_STACK", "duplicates": dup}, 15

    ps_fail = _check_bijection_ucie(
        declared_stacks, pstacks.get("stack_coverage") or [], "stack",
        {
            "unknown": ("UNKNOWN_STACK_IN_COVERAGE", 16),
            "duplicate": ("DUPLICATE_STACK_IN_COVERAGE", 17),
            "invalid_status": ("INVALID_STACK_STATUS", 18),
            "unapproved_waiver": ("UNAPPROVED_STACK_WAIVER", 19),
            "missing": ("MISSING_PROTOCOL_STACK_COVERAGE", 20),
        },
    )
    if ps_fail:
        return ps_fail

    # ---- Candidate 3: module width / per-lane repair-degradation coverage ----
    # (structural sanity only -- legal width/scenario sets are DUT-declared,
    # not asserted here from a hardcoded spec table; see module docstring)
    mwr = d.get("module_width_repair") or {}
    required_mwr_fields = [
        "module_full_width", "declared_supported_degraded_widths", "degradation_coverage",
        "declared_required_repair_scenarios", "repair_scenario_coverage",
    ]
    missing_mwr = [k for k in required_mwr_fields if k not in mwr]
    if missing_mwr:
        return {"status": "FAIL", "reason": "MISSING_MODULE_WIDTH_REPAIR_FIELDS", "missing": missing_mwr}, 21

    full_width = mwr.get("module_full_width")
    if not isinstance(full_width, int) or full_width <= 0:
        return {"status": "FAIL", "reason": "INVALID_MODULE_FULL_WIDTH", "module_full_width": full_width}, 22

    degraded_widths = mwr.get("declared_supported_degraded_widths") or []
    if not degraded_widths:
        return {"status": "FAIL", "reason": "EMPTY_DECLARED_SUPPORTED_DEGRADED_WIDTHS"}, 23
    if len(set(degraded_widths)) != len(degraded_widths):
        dup = sorted({w for w in degraded_widths if degraded_widths.count(w) > 1})
        return {"status": "FAIL", "reason": "DUPLICATE_DEGRADED_WIDTH", "duplicates": dup}, 24
    bad_widths = [w for w in degraded_widths if not isinstance(w, int) or w <= 0 or w > full_width]
    if bad_widths:
        return {"status": "FAIL", "reason": "OUT_OF_RANGE_DEGRADED_WIDTH",
                "module_full_width": full_width, "bad_widths": bad_widths}, 25
    if full_width not in degraded_widths:
        return {"status": "FAIL", "reason": "FULL_WIDTH_MISSING_FROM_DEGRADED_WIDTH_SET",
                "module_full_width": full_width}, 26

    dw_fail = _check_bijection_ucie(
        degraded_widths, mwr.get("degradation_coverage") or [], "width",
        {
            "unknown": ("UNKNOWN_WIDTH_IN_DEGRADATION_COVERAGE", 27),
            "duplicate": ("DUPLICATE_WIDTH_IN_DEGRADATION_COVERAGE", 28),
            "invalid_status": ("INVALID_DEGRADATION_STATUS", 29),
            "unapproved_waiver": ("UNAPPROVED_DEGRADATION_WAIVER", 30),
            "missing": ("MISSING_DEGRADATION_COVERAGE", 31),
        },
    )
    if dw_fail:
        return dw_fail

    required_scenarios = mwr.get("declared_required_repair_scenarios") or []
    if not required_scenarios:
        return {"status": "FAIL", "reason": "EMPTY_DECLARED_REQUIRED_REPAIR_SCENARIOS"}, 32
    if len(set(required_scenarios)) != len(required_scenarios):
        dup = sorted({s for s in required_scenarios if required_scenarios.count(s) > 1})
        return {"status": "FAIL", "reason": "DUPLICATE_REQUIRED_REPAIR_SCENARIO", "duplicates": dup}, 33

    rs_fail = _check_bijection_ucie(
        required_scenarios, mwr.get("repair_scenario_coverage") or [], "scenario",
        {
            "unknown": ("UNKNOWN_SCENARIO_IN_REPAIR_COVERAGE", 34),
            "duplicate": ("DUPLICATE_SCENARIO_IN_REPAIR_COVERAGE", 35),
            "invalid_status": ("INVALID_REPAIR_SCENARIO_STATUS", 36),
            "unapproved_waiver": ("UNAPPROVED_REPAIR_SCENARIO_WAIVER", 37),
            "missing": ("MISSING_REPAIR_SCENARIO_COVERAGE", 38),
        },
    )
    if rs_fail:
        return rs_fail

    return {
        "status": "PASS",
        "ucie_version": d.get("ucie_version"),
        "link_training_states": len(expected_states),
        "protocol_stacks": len(declared_stacks),
        "module_full_width": full_width,
        "degraded_width_modes": len(degraded_widths),
        "repair_scenarios": len(required_scenarios),
    }, 0

# --- Dispatcher -------------------------------------------------------------
CHECKERS = {
    "PCIE": check_pcie,
    "MIPI_DSI": check_mipi_dsi,
    "MIPI_CSI2": check_mipi_csi2,
    "ETHERNET": check_ethernet,
    "CANFD": check_canfd,
    "SD_SDIO": check_sd_sdio,
    "EMMC": check_emmc,
    "EDP": check_edp,
    "USB": check_usb,
    "UCIE": check_ucie,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocol-topology", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.protocol_topology).read_text())

    # Top-level escape hatch: for a protocol genuinely outside this
    # dispatcher's 10-protocol coverage (e.g. a future/uncommon interface),
    # or for AMBA4 fabric flows already covered by
    # fabric_topology_completeness_gate.py -- not for the 10 protocols this
    # dispatcher itself covers, which should instead set "protocol" and let
    # the matching checker run.
    if d.get("protocol_completeness_applicable") is False:
        reason = d.get("protocol_completeness_not_applicable_reason")
        if not reason:
            print(json.dumps({"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}))
            return 2
        print(json.dumps({"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}))
        return 0

    protocol = d.get("protocol")
    checker = CHECKERS.get(protocol)
    if not checker:
        print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_OR_UNSUPPORTED_PROTOCOL",
                          "protocol": protocol, "supported_protocols": sorted(CHECKERS)}))
        return 3

    result, code = checker(d)
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    sys.exit(main())
