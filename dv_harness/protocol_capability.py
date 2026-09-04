"""dv_harness/protocol_capability.py -- what protocol-specific generation this
harness can actually DO, derived from the code that exists rather than from a
label somebody typed into a JSON file.

BUG FIX (2026-09-04, multi-protocol-scope gap closure): every one of the 11
protocols in .dv-harness/qualification/protocol_capability_registry.json
carried `"status": "REAL_GENERATION_READY"` and
`"generation_capability": "REAL_CODE_GENERATOR_AVAILABLE"`. For Ethernet,
SD_SDIO, eDP and UCIe that claim was false: there is no protocol-specific
Python module behind it, only the flat ProtocolEnvGenerator skeleton every
protocol gets plus a doc-only builder_profile.json that (confirmed by
`grep -rln "builder_profile" --include=*.py .` returning nothing) no code in
this repo reads. The registry is not inert prose -- dashboard.py's
`_protocol_registry()` reads it and renders it as this project's real
protocol readiness, and `_qualification_tier_reached()` derives the
Qualification-Tiers card from it -- so the overstatement reached a real
production surface.

The fix is not a better adjective. One label conflated two independent
questions, so this module splits them and answers each from a checkable fact:

  * "is a generic UVM skeleton available?" -- yes, for every protocol,
    always, from GENERIC_SKELETON_GENERATOR. That part of the old claim was
    true and stays true.
  * "is there a module that models THIS protocol's own behaviour?" --
    answered by PROTOCOL_MODELS below, whose every entry is verified to
    resolve as a real importable module and a real standalone tool file
    before it is reported. A protocol with no such module reports NONE, and
    cannot be talked up.
  * "has it ever been proven against a real DUT?" -- answered by
    `dut_proof` paths that must exist on disk. Only USB has any.

`derive_status()` computes each protocol's status from those three facts, and
`assert_registry_matches_code()` refuses a registry that disagrees with the
computation, that reintroduces the collapsed `generation_capability` key, or
that names a module/tool/evidence path which is not there. `--sync` rewrites
the registry from the code; `--check` (also wired into
tools/universal_protocol/protocol_status.py) exits 2 on drift, so the status
command cannot print a readiness this repo does not have.

Scope boundary, stated so it is not mistaken for more: this closes the
CLAIM, not the capability. No non-USB protocol is proven against a real DUT
by this module and none becomes so by being described honestly.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Where this harness's own modules, tools and evidence artifacts live. The
# `root` argument threaded through the registry functions below is the PROJECT
# root (which registry to read); tool and dut_proof paths are harness assets and
# are always resolved here instead, so a downstream project using this harness
# does not report every generator missing merely because its own tree has no
# tools/ directory.
HARNESS_ROOT = Path(__file__).resolve().parents[1]

REGISTRY_RELPATH = Path(".dv-harness") / "qualification" / "protocol_capability_registry.json"
SEMANTIC_MODELS_RELDIR = Path(".dv-harness") / "semantic-models"

# The flat, protocol-agnostic UVM environment skeleton emitter. Real for every
# protocol -- it is the true half of the old collapsed claim.
GENERIC_SKELETON_GENERATOR = "dv_harness.uvm_generator.protocol_env_generator"

# The one status token this module refuses on sight, plus the key that carried
# it. Kept as constants so the drift guard names the thing it rejects.
LEGACY_CAPABILITY_KEY = "generation_capability"
LEGACY_CAPABILITY_VALUE = "REAL_CODE_GENERATOR_AVAILABLE"
LEGACY_STATUS_VALUE = "REAL_GENERATION_READY"
# The per-entry prose that restated the same blanket claim in a third place.
# Superseded verbatim by each entry's own capability_note, so leaving it would
# be exactly the stale-comment accumulation CLAUDE.md's comment-hygiene rule
# forbids.
LEGACY_ENTRY_NOTE = (
    "Real generation machinery present; project qualification pending actual DUT/VIP/tool execution."
)

# Honest per-protocol status vocabulary. Deliberately NOT merged into
# qualification.QualificationTier's 8-tier ladder: that ladder measures how far
# a generated environment has been PROVEN (compile -> smoke -> regression ->
# production) and is tracked per protocol in `qualification_status`. This one
# measures what generation code EXISTS. A protocol can have a deep protocol
# model and still sit at BUILDER_AVAILABLE, which is exactly PCIe's situation.
STATUS_GENERIC_SKELETON_ONLY = "GENERIC_SKELETON_ONLY"
STATUS_PROTOCOL_MODEL_PARTIAL = "PROTOCOL_MODEL_PARTIAL"
STATUS_PROTOCOL_MODEL_COMPLETE = "PROTOCOL_MODEL_COMPLETE"
STATUS_DUT_PROVEN = "DUT_PROVEN"

STATUS_VOCABULARY: Tuple[str, ...] = (
    STATUS_GENERIC_SKELETON_ONLY,
    STATUS_PROTOCOL_MODEL_PARTIAL,
    STATUS_PROTOCOL_MODEL_COMPLETE,
    STATUS_DUT_PROVEN,
)


class ProtocolCapabilityDriftError(Exception):
    """The registry on disk claims something the code does not support.

    Carries every mismatch at once (`.problems`) rather than the first one --
    a fix pass should see the whole disagreement, not play whack-a-mole.
    """

    def __init__(self, problems: List[str]):
        self.problems = list(problems)
        super().__init__(
            "protocol_capability_registry.json disagrees with the code:\n  - "
            + "\n  - ".join(self.problems)
        )


@dataclass(frozen=True)
class ProtocolModel:
    """A real module that computes something protocol-SPECIFIC.

    `models` / `does_not_model` are quoted from each module's own SCOPE /
    "WHAT THIS DOES NOT DO" docstring section, so the partial-ness of a
    partial model is data a reader gets without opening the module.
    """

    module: str
    tool: str
    models: Tuple[str, ...]
    does_not_model: Tuple[str, ...]


@dataclass(frozen=True)
class ProtocolCapability:
    protocol: str
    model: Optional[ProtocolModel] = None
    # Repo-relative paths whose existence IS the DUT proof. Empty for every
    # protocol that has never been bound to real RTL.
    dut_proof: Tuple[str, ...] = ()
    aliases: Tuple[str, ...] = ()
    note: str = ""


# --- The real generators, one entry per protocol key the registry uses. ------
# Every `module` here was confirmed present in dv_harness/uvm_generator/ and
# every `tool` in tools/ on 2026-09-04; `assert_registry_matches_code()`
# re-confirms both on every run, so a deleted or renamed module fails loudly
# instead of leaving a claim standing.

_PCIE = ProtocolModel(
    module="dv_harness.uvm_generator.pcie_ltssm_generator",
    tool="tools/generate_pcie_ltssm_environment.py",
    models=("ltssm_top_level_state_graph", "ltssm_transition_validator", "link_width_encoding"),
    does_not_model=("ltssm_sub_states", "ltssm_timeout_constants", "tlp_layer", "config_space"),
)

_MIPI_DPHY_MODELS = ("dphy_lane_lp_hs_state_transitions", "escape_mode_and_ulps_entry")
_MIPI_DPHY_TOOL = "tools/generate_mipi_dphy_environment.py"
_MIPI_DPHY_MODULE = "dv_harness.uvm_generator.mipi_dphy_generator"

_EMMC_CMDQ_MODELS = ("cmdq_tag_lifecycle", "outstanding_tag_drain_check", "hs200_tuning_search_shape")
_EMMC_CMDQ_TOOL = "tools/generate_emmc_cmdq_environment.py"
_EMMC_CMDQ_MODULE = "dv_harness.uvm_generator.emmc_cmdq_generator"

PROTOCOL_CAPABILITIES: Tuple[ProtocolCapability, ...] = (
    ProtocolCapability(
        protocol="USB_2_3x",
        model=None,
        dut_proof=(
            "examples/generated_usb_real_evidence_v12/environment_manifest.json",
            "examples/generated_usb_real_evidence_v1/manifest_inputs/usb_bind_topology.json",
        ),
        aliases=("USB",),
        note=(
            "The only protocol ever grounded against real external RTL. Its proof is "
            "generated evidence artifacts, not a protocol-model module -- USB behaviour "
            "lives in the main uvm_generator path, so protocol_model_generator is "
            "legitimately NONE here and the DUT_PROVEN status comes from dut_proof."
        ),
    ),
    ProtocolCapability(
        protocol="PCIe",
        model=_PCIE,
        note=(
            "examples/generated_pcie_uvm_env/ proves the generation path executes end to "
            "end shape-wise, but examples/NOTICE_SCAFFOLDING_ONLY.md states it is an "
            "unconnected skeleton with no DUT ever bound and it has never been compiled. "
            "Reachable only via the standalone tool, not from engine.py/cli.py."
        ),
    ),
    ProtocolCapability(
        protocol="Ethernet",
        model=None,
        note=(
            "No ethernet_*.py exists anywhere in dv_harness/. The "
            "builders/Ethernet/builder_profile.json under universal-protocol-platform is "
            "doc-only metadata no Python file reads."
        ),
    ),
    ProtocolCapability(
        protocol="MIPI_CSI2",
        model=ProtocolModel(
            module=_MIPI_DPHY_MODULE, tool=_MIPI_DPHY_TOOL, models=_MIPI_DPHY_MODELS,
            does_not_model=(
                "csi2_short_and_long_packet_layer", "virtual_channels", "packet_ecc_and_crc",
                "cphy", "dphy_timing_constants",
            ),
        ),
        note=(
            "The D-PHY electrical lane layer only -- shared with MIPI_DSI. The CSI-2 "
            "packet layer has no generator code. connectivity.PROTOCOL_FINGERPRINTS['CSI2'] "
            "is flagged illustrative and unverified, and the simplex-streaming branch_fw "
            "topology variant is documented UNTESTED."
        ),
    ),
    ProtocolCapability(
        protocol="MIPI_DSI",
        model=ProtocolModel(
            module=_MIPI_DPHY_MODULE, tool=_MIPI_DPHY_TOOL, models=_MIPI_DPHY_MODELS,
            does_not_model=(
                "dsi_command_and_video_packet_layer", "virtual_channels", "packet_ecc_and_crc",
                "cphy", "dphy_timing_constants",
            ),
        ),
        note="Same shared D-PHY electrical layer as MIPI_CSI2; the DSI packet layer is unmodeled.",
    ),
    ProtocolCapability(
        protocol="CAN_FD",
        model=ProtocolModel(
            module="dv_harness.uvm_generator.canfd_arbitration_generator",
            tool="tools/generate_canfd_arbitration_environment.py",
            models=("bitwise_dominant_recessive_arbitration", "tec_rec_error_state_machine",
                    "crc15_crc17_crc21"),
            does_not_model=("bit_timing_segments_and_resynchronisation", "fd_bit_rate_switching",
                            "transceiver_delay_compensation"),
        ),
        note=(
            "Genuinely protocol-specific math, unit-tested. Unlike PCIe it has produced no "
            "examples/generated_canfd_* artifact -- never even a full skeleton, let alone a "
            "DUT bind."
        ),
    ),
    ProtocolCapability(
        protocol="AMBA4_MULTI_MASTER_MULTI_SLAVE",
        model=ProtocolModel(
            module="dv_harness.uvm_generator.amba_fabric_generator",
            tool="tools/generate_amba_fabric_environment.py",
            models=("mxn_address_decode_overlap_gap_coverage", "id_width_resolution",
                    "per_master_slave_pair_scoreboard_pairing"),
            does_not_model=("axi_ahb_apb_handshake_signals", "burst_wrap_exclusive_qos",
                            "ace_lite_coherency", "axi_stream"),
        ),
        aliases=("AMBA4_MMxMS",),
        note=(
            "The only protocol model imported by production-adjacent code: "
            "uvm_generator/address_map_verifier.py does `from .amba_fabric_generator import "
            "parse_addr`, and that verifier is called from connectivity.py, "
            "agent_checkpoint_check.py and bind_verification_lint.py. ACE-Lite and AXI-Stream "
            "return zero hits in the module and are structurally out of reach of an "
            "address-decode fabric model."
        ),
    ),
    ProtocolCapability(
        protocol="eMMC",
        model=ProtocolModel(
            module=_EMMC_CMDQ_MODULE, tool=_EMMC_CMDQ_TOOL, models=_EMMC_CMDQ_MODELS,
            does_not_model=("emmc_command_set_and_response_types", "boot_and_rpmb_partitions",
                            "bus_timing_constants"),
        ),
        note="JEDEC-shaped command-queue tag lifecycle only; the eMMC command set is unmodeled.",
    ),
    ProtocolCapability(
        protocol="SD_SDIO",
        model=ProtocolModel(
            module=_EMMC_CMDQ_MODULE, tool=_EMMC_CMDQ_TOOL, models=_EMMC_CMDQ_MODELS,
            does_not_model=("sd_command_set_and_response_types", "sdio_cmd52_cmd53_io_functions",
                            "card_identification_and_initialisation", "bus_timing_constants"),
        ),
        note=(
            "Reuses the same protocol-agnostic tag-lifecycle model as eMMC -- real, but it is "
            "the command-queue bookkeeping, not anything SD/SDIO-specific."
        ),
    ),
    ProtocolCapability(
        protocol="eDP_DisplayPort",
        model=None,
        aliases=("eDP",),
        note="No eDP/DisplayPort module in dv_harness/; AUX, link training and video are unmodeled.",
    ),
    ProtocolCapability(
        protocol="UCIe",
        model=None,
        note="No UCIe module in dv_harness/; adapter/PHY link bring-up is unmodeled.",
    ),
)

_BY_NAME: Dict[str, ProtocolCapability] = {}
for _cap in PROTOCOL_CAPABILITIES:
    _BY_NAME[_cap.protocol] = _cap
    for _alias in _cap.aliases:
        _BY_NAME[_alias] = _cap


def known_protocols() -> Tuple[str, ...]:
    """Registry-canonical protocol keys, in declaration order (aliases excluded)."""
    return tuple(c.protocol for c in PROTOCOL_CAPABILITIES)


def capability_for(protocol: str) -> Optional[ProtocolCapability]:
    """Accepts either the registry key or a known alias (e.g. the
    semantic-models spelling `USB` / `AMBA4_MMxMS`)."""
    return _BY_NAME.get(protocol)


def module_is_importable(dotted: str) -> bool:
    """Real resolution through the import system -- not a string check and not
    a `Path.exists()` on a guessed filename."""
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def derive_status(cap: ProtocolCapability) -> str:
    """The status this protocol has EARNED, from code + filesystem only."""
    if cap.dut_proof and all((HARNESS_ROOT / p).exists() for p in cap.dut_proof):
        return STATUS_DUT_PROVEN
    if cap.model is None:
        return STATUS_GENERIC_SKELETON_ONLY
    if cap.model.does_not_model:
        return STATUS_PROTOCOL_MODEL_PARTIAL
    return STATUS_PROTOCOL_MODEL_COMPLETE


def capability_row(cap: ProtocolCapability) -> Dict[str, object]:
    """One protocol's honest capability record -- the exact shape written into
    the registry by `--sync` and compared against it by `--check`."""
    model = cap.model
    row: Dict[str, object] = {
        "generic_skeleton_generator": GENERIC_SKELETON_GENERATOR,
        "protocol_model_generator": model.module if model else "NONE",
        "protocol_model_tool": model.tool if model else "NONE",
        "models": list(model.models) if model else [],
        "does_not_model": list(model.does_not_model) if model else [],
        "dut_proof": list(cap.dut_proof),
        "capability_status": derive_status(cap),
    }
    if cap.note:
        row["capability_note"] = cap.note
    return row


def capability_rows() -> List[Dict[str, object]]:
    return [dict(protocol=c.protocol, **capability_row(c)) for c in PROTOCOL_CAPABILITIES]


# --- registry read / sync / drift check -------------------------------------

# Fields this module owns in each registry entry. Everything else in an entry
# (qualification_status, builder_profile, qualification_suite, ...) belongs to
# other mechanisms and is left untouched by --sync.
_OWNED_FIELDS = (
    "generic_skeleton_generator", "protocol_model_generator", "protocol_model_tool",
    "models", "does_not_model", "dut_proof", "capability_status", "capability_note",
)


# The registry's one non-protocol block. It claimed the same retired blanket
# status for its two named paths, VIP_ADAPTER and NATIVE_UVC, while
# `grep -rn "NATIVE_UVC\|VIP_ADAPTER" --include=*.py .` returns nothing at all
# -- there is no Python implementing either path, so it gets the same honest
# floor a protocol with no model generator gets.
NEW_INTERFACE_FRAMEWORK_STATUS = STATUS_GENERIC_SKELETON_ONLY
NEW_INTERFACE_FRAMEWORK_NOTE = (
    "VIP_ADAPTER and NATIVE_UVC are named paths with no implementing Python module in "
    "this repo; only the protocol-agnostic skeleton generator is real for them."
)


def registry_path(root: Path) -> Path:
    return root / REGISTRY_RELPATH


def load_registry(root: Path) -> Dict[str, object]:
    path = registry_path(root)
    if not path.exists():
        raise FileNotFoundError(f"no protocol capability registry at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _check_entry(name: str, entry: Dict[str, object], cap: ProtocolCapability,
                 problems: List[str]) -> None:
    if LEGACY_CAPABILITY_KEY in entry:
        problems.append(
            f"{name}: reintroduces the collapsed {LEGACY_CAPABILITY_KEY!r} key "
            f"({entry[LEGACY_CAPABILITY_KEY]!r}); it conflated 'a generic skeleton exists' "
            f"with 'this protocol is modelled' and must stay split"
        )
    if entry.get("status") == LEGACY_STATUS_VALUE:
        problems.append(
            f"{name}: status is the retired blanket {LEGACY_STATUS_VALUE!r}; use one of "
            f"{STATUS_VOCABULARY} in capability_status"
        )
    if entry.get("note") == LEGACY_ENTRY_NOTE:
        problems.append(
            f"{name}: still carries the retired blanket note, now superseded by capability_note"
        )

    expected = capability_row(cap)
    for key in _OWNED_FIELDS:
        if key not in expected:
            if key in entry:
                problems.append(f"{name}: has {key!r} but the code declares none")
            continue
        if key not in entry:
            problems.append(f"{name}: missing {key!r} (code says {expected[key]!r})")
        elif entry[key] != expected[key]:
            problems.append(
                f"{name}: {key} is {entry[key]!r} on disk but the code says {expected[key]!r}"
            )

    if entry.get("capability_status") not in (None,) and \
            entry.get("capability_status") not in STATUS_VOCABULARY:
        problems.append(
            f"{name}: capability_status {entry.get('capability_status')!r} is not one of "
            f"{STATUS_VOCABULARY}"
        )

    # The claims themselves must be resolvable, not merely agreed-upon strings.
    if cap.model is not None:
        if not module_is_importable(cap.model.module):
            problems.append(f"{name}: declared protocol model {cap.model.module!r} does not import")
        if not (HARNESS_ROOT / cap.model.tool).exists():
            problems.append(f"{name}: declared tool {cap.model.tool!r} does not exist")
    for proof in cap.dut_proof:
        if not (HARNESS_ROOT / proof).exists():
            problems.append(f"{name}: declared DUT proof {proof!r} does not exist")


def assert_registry_matches_code(root: Path) -> None:
    """Raise ProtocolCapabilityDriftError unless every registry entry's
    capability claim is exactly what the code supports."""
    problems: List[str] = []

    if not module_is_importable(GENERIC_SKELETON_GENERATOR):
        problems.append(
            f"the generic skeleton generator {GENERIC_SKELETON_GENERATOR!r} does not import -- "
            f"no protocol's 'generic skeleton available' claim holds"
        )

    data = load_registry(root)
    protocols = data.get("protocols")
    if not isinstance(protocols, dict):
        raise ProtocolCapabilityDriftError(["registry has no 'protocols' object"])

    for name in known_protocols():
        if name not in protocols:
            problems.append(f"{name}: declared in code but absent from the registry")

    for name, entry in protocols.items():
        if not isinstance(entry, dict):
            problems.append(f"{name}: registry entry is not an object")
            continue
        cap = capability_for(name)
        if cap is None:
            problems.append(
                f"{name}: in the registry but has no PROTOCOL_CAPABILITIES entry -- its "
                f"capability claim is unverifiable"
            )
            continue
        _check_entry(name, entry, cap, problems)

    nif = data.get("new_interface_framework")
    if isinstance(nif, dict):
        if nif.get("status") != NEW_INTERFACE_FRAMEWORK_STATUS:
            problems.append(
                f"new_interface_framework: status is {nif.get('status')!r} but no Python "
                f"implements VIP_ADAPTER/NATIVE_UVC, so it is "
                f"{NEW_INTERFACE_FRAMEWORK_STATUS!r}"
            )
        if LEGACY_CAPABILITY_KEY in nif:
            problems.append(f"new_interface_framework: reintroduces {LEGACY_CAPABILITY_KEY!r}")

    if problems:
        raise ProtocolCapabilityDriftError(problems)


def sync_registry(root: Path) -> List[str]:
    """Rewrite the registry's capability fields from the code. Returns the
    protocol names whose entries actually changed."""
    path = registry_path(root)
    data = load_registry(root)
    protocols = data.setdefault("protocols", {})
    changed: List[str] = []
    for cap in PROTOCOL_CAPABILITIES:
        entry = protocols.setdefault(cap.protocol, {})
        before = {k: entry.get(k) for k in _OWNED_FIELDS}
        before_legacy = (entry.get(LEGACY_CAPABILITY_KEY), entry.get("status"), entry.get("note"))
        entry.pop(LEGACY_CAPABILITY_KEY, None)
        if entry.get("status") == LEGACY_STATUS_VALUE:
            entry.pop("status", None)
        if entry.get("note") == LEGACY_ENTRY_NOTE:
            entry.pop("note", None)
        expected = capability_row(cap)
        for key in _OWNED_FIELDS:
            if key in expected:
                entry[key] = expected[key]
            else:
                entry.pop(key, None)
        after_legacy = (entry.get(LEGACY_CAPABILITY_KEY), entry.get("status"), entry.get("note"))
        if before_legacy != after_legacy or \
                any(before.get(k) != entry.get(k) for k in _OWNED_FIELDS):
            changed.append(cap.protocol)
    nif = data.get("new_interface_framework")
    if isinstance(nif, dict) and nif.get("status") != NEW_INTERFACE_FRAMEWORK_STATUS:
        nif.pop(LEGACY_CAPABILITY_KEY, None)
        nif["status"] = NEW_INTERFACE_FRAMEWORK_STATUS
        nif["capability_note"] = NEW_INTERFACE_FRAMEWORK_NOTE
        changed.append("new_interface_framework")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


def sync_semantic_models(root: Path) -> List[str]:
    """The same split applied to .dv-harness/semantic-models/<protocol>.json,
    which asserted the identical collapsed `generation_capability` value for
    all 10 of its files. No Python reads these, which is precisely why an
    overstatement can sit in them unnoticed."""
    d = root / SEMANTIC_MODELS_RELDIR
    changed: List[str] = []
    if not d.is_dir():
        return changed
    for path in sorted(d.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cap = capability_for(str(data.get("protocol") or path.stem))
        if cap is None:
            continue
        row = capability_row(cap)
        before = json.dumps(data, sort_keys=True)
        data.pop(LEGACY_CAPABILITY_KEY, None)
        data["generic_skeleton_generator"] = row["generic_skeleton_generator"]
        data["protocol_model_generator"] = row["protocol_model_generator"]
        data["capability_status"] = row["capability_status"]
        if json.dumps(data, sort_keys=True) != before:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            changed.append(path.name)
    return changed


def find_legacy_capability_claims(root: Path) -> List[str]:
    """Every .dv-harness JSON file still asserting the collapsed claim. The
    drift guard covers the registry; this catches a second copy of the same
    overstatement parked somewhere else under .dv-harness/."""
    hits: List[str] = []
    base = root / ".dv-harness"
    if not base.is_dir():
        return hits
    for path in sorted(base.rglob("*.json")):
        # Memory records are an append-only historical log of what was believed
        # at the time; rewriting them would falsify the record.
        if "memory" in path.relative_to(base).parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if LEGACY_CAPABILITY_VALUE in text or f'"{LEGACY_CAPABILITY_KEY}"' in text:
            hits.append(str(path.relative_to(root)).replace("\\", "/"))
    return hits


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.protocol_capability",
        description="Per-protocol generation capability, derived from the code that exists.",
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true",
                   help="Exit 2 if the registry claims more than the code supports.")
    g.add_argument("--sync", action="store_true",
                   help="Rewrite the registry (and semantic-models) capability fields from the code.")
    ap.add_argument("--json", action="store_true", help="Machine-readable output.")
    ap.add_argument("--root", default=None, help="Project root (default: this repo).")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]

    if args.sync:
        changed = sync_registry(root) + sync_semantic_models(root)
        print("synced" if changed else "already in sync")
        for c in changed:
            print(f"  {c}")
        return 0

    if args.check:
        try:
            assert_registry_matches_code(root)
        except (ProtocolCapabilityDriftError, FileNotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        stray = find_legacy_capability_claims(root)
        if stray:
            print(
                f"{LEGACY_CAPABILITY_KEY!r}/{LEGACY_CAPABILITY_VALUE!r} still asserted in:\n  - "
                + "\n  - ".join(stray),
                file=sys.stderr,
            )
            return 2
        print("protocol capability registry matches the code")
        return 0

    rows = capability_rows()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"{'PROTOCOL':34} {'CAPABILITY STATUS':26} PROTOCOL MODEL GENERATOR")
    print("-" * 100)
    for r in rows:
        print(f"{r['protocol']:34} {r['capability_status']:26} {r['protocol_model_generator']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
