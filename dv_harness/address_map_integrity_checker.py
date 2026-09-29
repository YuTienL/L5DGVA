"""dv_harness/address_map_integrity_checker.py -- pure address-map integrity
arithmetic over a CALLER-SUPPLIED list of declared address regions
(base/size/owner), per this batch's own task scope.

WHY THIS IS NOT `uvm_generator/amba_fabric_generator.compute_address_regions()`
(read before writing a line of this file, per REUSE OVER REINVENT): that
function is a GENERATION-TIME validator with different, stricter semantics
that do not fit this task -- it RAISES on the first overlap/gap found (one
finding, not a full report), and it REQUIRES the region set to cover the
entire `[0, 2**addr_width)` address space (a generator must never emit a
topology with a silently-unmapped residual region). This module's job is the
opposite shape: given an ARBITRARY caller-declared region list (which may
legitimately have gaps -- reserved space is normal outside generation), walk
it and REPORT every overlap, every unmapped hole, and every illegal burst/
transfer crossing, never raising on the first one and never assuming full
coverage was ever intended. Address PARSING is reused, not re-derived:
`amba_fabric_generator.parse_addr()` (int passthrough, or an optionally
underscore-grouped, optionally 0x/0b-prefixed string via `int(s, 0)`) is
imported directly so this module cannot silently parse an address
differently from the rest of the AMBA family.

Three checks, matching the task's own three items:

(a) OVERLAP -- any two declared regions whose [base, base+size) ranges
    intersect. Checked pairwise (O(n^2), correctness over cleverness for the
    modest region counts a real address map has) so every finding cites the
    REAL region pair and the REAL overlapping sub-range -- never a generic
    "overlap exists" with no owner/value attached.

(b) UNMAPPED HOLE -- a real gap in address-space COVERAGE. Regions are
    merged into contiguous coverage groups (a running-max-end merge, so a
    large region that fully contains a smaller declared one never manufactures
    a phantom hole against it) and every gap between groups is reported
    citing the real bounding regions on both sides (`region_before`/
    `region_after`, either `None` at the very start/end of a declared
    `address_space_bits` span). Never raises: an intentionally reserved gap
    is a normal, reportable fact, not an error.

(c) ILLEGAL BURST/TRANSFER -- a caller-declared transaction (address plus
    either an explicit `length` or a `burst_len`/`beat_size` pair) that:
      - crosses a 4KB boundary (the real AMBA AXI/AHB rule that a single
        burst must never cross a 4KB address boundary), or
      - crosses a DECLARED PROTOCOL-REGION boundary -- grouped by each
        region's own `protocol_region` field (defaulting to that region's
        `owner` when not supplied, so two regions belonging to one owner but
        different bus segments are never silently treated as one protocol
        region, and two regions of one DECLARED protocol_region, e.g. two
        banks of the same memory, are correctly never flagged just for
        having different owners).
    A transaction whose range is not fully covered by any declared region at
    all -- either touching NOTHING (`TRANSFER_TARGETS_UNMAPPED_ADDRESS`) or
    only PART of its range (`TRANSFER_PARTIALLY_UNMAPPED`) -- is reported as
    that honest, distinct fact rather than silently assumed legal: this
    module never claims a transfer is protocol-region-clean when there is no
    region evidence to check it against.

Evidence Truth Rule applied directly: a region/transaction missing a
required field (owner, base, size, a resolvable length) is refused outright
(`AddressMapIntegrityError`, fail-closed) rather than silently defaulted or
guessed -- this module never invents an owner, an address, or a length. A
transaction whose target address(es) carry no declared region evidence at
all is reported as the honest `TRANSFER_TARGETS_UNMAPPED_ADDRESS` /
`TRANSFER_PARTIALLY_UNMAPPED` finding rather than a silently-assumed legal
PASS -- the closest analogue this pure-arithmetic domain has to an
UNKNOWN/NOT_AVAILABLE status, since "legal" is a claim this module must never
make without a real declared region to check against.

Deliberately bounded, and stated rather than implied closed: this module
performs NO RTL/VIP discovery, decides NO fabric topology, and computes NO
performance/timing value of any kind (out of scope for this whole batch per
this session's own governing instructions). It reads a caller-supplied region/
transaction list and reports arithmetic facts about it -- nothing more. There
is no `dv-harness` CLI verb and no `gates.py` entry (out of this task's own
file-safety scope); the front door is this module's own Python API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from dv_harness.uvm_generator.amba_fabric_generator import parse_addr

FOUR_KB = 4096


class AddressMapIntegrityError(ValueError):
    """Fail-closed refusal: a region or transaction is missing a required
    field, or carries a value this module cannot honestly parse/accept. Never
    silently defaulted or guessed -- see the module docstring's Evidence
    Truth Rule paragraph."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class AddressRegion:
    """One normalized, caller-declared address region. `protocol_region`
    defaults to `owner` (set by `normalize_regions()`) when the caller does
    not declare one -- so two regions of one owner but different bus
    segments never silently collapse into "the same protocol region", and a
    caller who DOES group several owners under one declared protocol region
    (e.g. two banks of one memory) gets that grouping honored rather than
    ignored."""

    owner: str
    base: int
    size: int
    protocol_region: str

    @property
    def end(self) -> int:
        return self.base + self.size

    def to_dict(self) -> Dict[str, Any]:
        return {
            "owner": self.owner,
            "base": self.base,
            "size": self.size,
            "end": self.end,
            "protocol_region": self.protocol_region,
        }


def _region_ref(region: Optional[AddressRegion]) -> Optional[Dict[str, Any]]:
    return region.to_dict() if region is not None else None


def normalize_regions(raw_regions: Optional[Sequence[dict]]) -> List[AddressRegion]:
    """Validates and parses a caller-supplied region list into `AddressRegion`
    objects. `raw_regions` may legitimately be an empty list (a project that
    has declared no regions yet, or none at all) -- that is not an error, it
    is the honest "nothing declared" state, reported downstream as one giant
    unmapped hole when `address_space_bits` is supplied. Only `None` (the
    caller supplied nothing to check at all) or a genuinely malformed entry
    is refused."""
    if raw_regions is None:
        raise AddressMapIntegrityError("NO_REGIONS_SUPPLIED", {"regions": raw_regions})
    normalized: List[AddressRegion] = []
    for idx, r in enumerate(raw_regions):
        if not isinstance(r, dict):
            raise AddressMapIntegrityError("REGION_NOT_A_MAPPING", {"index": idx, "value": r})
        owner = r.get("owner")
        if not owner:
            raise AddressMapIntegrityError("REGION_MISSING_OWNER", {"index": idx, "region": r})
        if "base" not in r or r["base"] is None or "size" not in r or r["size"] is None:
            raise AddressMapIntegrityError(
                "REGION_MISSING_BASE_OR_SIZE", {"index": idx, "owner": owner, "region": r}
            )
        try:
            base = parse_addr(r["base"])
            size = parse_addr(r["size"])
        except (TypeError, ValueError) as exc:
            raise AddressMapIntegrityError(
                "REGION_ADDRESS_UNPARSEABLE", {"index": idx, "owner": owner, "error": str(exc)}
            ) from exc
        if base < 0:
            raise AddressMapIntegrityError("REGION_BASE_NEGATIVE", {"index": idx, "owner": owner, "base": base})
        if size <= 0:
            raise AddressMapIntegrityError("REGION_SIZE_NOT_POSITIVE", {"index": idx, "owner": owner, "size": size})
        protocol_region = r.get("protocol_region") or owner
        normalized.append(
            AddressRegion(owner=str(owner), base=base, size=size, protocol_region=str(protocol_region))
        )
    return normalized


def check_overlaps(regions: Sequence[AddressRegion]) -> List[Dict[str, Any]]:
    """Every pair of declared regions whose ranges intersect, each finding
    citing the real region pair and the real overlapping sub-range."""
    findings: List[Dict[str, Any]] = []
    for i in range(len(regions)):
        a = regions[i]
        for j in range(i + 1, len(regions)):
            b = regions[j]
            if a.base < b.end and b.base < a.end:
                overlap_start = max(a.base, b.base)
                overlap_end = min(a.end, b.end)
                findings.append(
                    {
                        "type": "OVERLAP",
                        "region_a": a.to_dict(),
                        "region_b": b.to_dict(),
                        "overlap_start": overlap_start,
                        "overlap_end": overlap_end,
                        "overlap_size": overlap_end - overlap_start,
                    }
                )
    return findings


def check_unmapped_holes(
    regions: Sequence[AddressRegion], address_space_bits: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Real gaps in declared-region COVERAGE, computed via a running-max-end
    merge (so a large region fully containing a smaller declared one never
    manufactures a phantom hole). `address_space_bits`, when supplied,
    additionally reports a leading hole (space below the first region) and a
    trailing hole (space above the last region) against `[0, 2**bits)`."""
    findings: List[Dict[str, Any]] = []
    if not regions:
        if address_space_bits is not None:
            full_size = 1 << address_space_bits
            findings.append(
                {
                    "type": "UNMAPPED_HOLE",
                    "start": 0,
                    "end": full_size,
                    "size": full_size,
                    "region_before": None,
                    "region_after": None,
                    "reason": "no regions declared; the entire declared address space is unmapped",
                }
            )
        return findings

    ordered = sorted(regions, key=lambda r: r.base)
    groups: List[Dict[str, Any]] = []
    for r in ordered:
        if groups and r.base <= groups[-1]["end"]:
            if r.end > groups[-1]["end"]:
                groups[-1]["end"] = r.end
                groups[-1]["end_region"] = r
        else:
            groups.append({"start": r.base, "end": r.end, "start_region": r, "end_region": r})

    if address_space_bits is not None:
        full_size = 1 << address_space_bits
        if groups[0]["start"] > 0:
            findings.append(
                {
                    "type": "UNMAPPED_HOLE",
                    "start": 0,
                    "end": groups[0]["start"],
                    "size": groups[0]["start"],
                    "region_before": None,
                    "region_after": _region_ref(groups[0]["start_region"]),
                    "reason": "declared address space starts below the first declared region",
                }
            )
        if groups[-1]["end"] < full_size:
            findings.append(
                {
                    "type": "UNMAPPED_HOLE",
                    "start": groups[-1]["end"],
                    "end": full_size,
                    "size": full_size - groups[-1]["end"],
                    "region_before": _region_ref(groups[-1]["end_region"]),
                    "region_after": None,
                    "reason": "declared address space extends beyond the last declared region",
                }
            )

    for prev, cur in zip(groups, groups[1:]):
        findings.append(
            {
                "type": "UNMAPPED_HOLE",
                "start": prev["end"],
                "end": cur["start"],
                "size": cur["start"] - prev["end"],
                "region_before": _region_ref(prev["end_region"]),
                "region_after": _region_ref(cur["start_region"]),
                "reason": None,
            }
        )

    return findings


def _covers_range(regions: Sequence[AddressRegion], start: int, end: int) -> bool:
    """True iff the merged coverage of `regions` fully spans [start, end)."""
    if not regions:
        return False
    ordered = sorted(regions, key=lambda r: r.base)
    cur = start
    for r in ordered:
        if r.base > cur:
            return False
        cur = max(cur, r.end)
        if cur >= end:
            return True
    return cur >= end


def _resolve_transfer_length(t: dict) -> Optional[int]:
    if t.get("length") is not None:
        return parse_addr(t["length"])
    if t.get("burst_len") is not None and t.get("beat_size") is not None:
        return parse_addr(t["burst_len"]) * parse_addr(t["beat_size"])
    return None


def check_transfer_legality(
    transactions: Sequence[dict], regions: Sequence[AddressRegion]
) -> List[Dict[str, Any]]:
    """Every caller-declared transaction (`address` plus either `length` or
    `burst_len`+`beat_size`) that crosses a 4KB boundary or a declared
    protocol-region boundary, plus the honest unmapped-target findings
    described in the module docstring. Refuses (raises) rather than guesses
    when a transaction carries no way to resolve a real length -- an illegal-
    transfer claim about a transaction of unknown size would be fabricated."""
    findings: List[Dict[str, Any]] = []
    for idx, t in enumerate(transactions):
        if not isinstance(t, dict):
            raise AddressMapIntegrityError("TRANSFER_NOT_A_MAPPING", {"index": idx, "value": t})
        txn_id = t.get("id", idx)
        if t.get("address") is None:
            raise AddressMapIntegrityError("TRANSFER_MISSING_ADDRESS", {"index": idx, "id": txn_id})
        try:
            address = parse_addr(t["address"])
        except (TypeError, ValueError) as exc:
            raise AddressMapIntegrityError(
                "TRANSFER_ADDRESS_UNPARSEABLE", {"index": idx, "id": txn_id, "error": str(exc)}
            ) from exc
        if address < 0:
            raise AddressMapIntegrityError("TRANSFER_ADDRESS_NEGATIVE", {"index": idx, "id": txn_id, "address": address})

        length = _resolve_transfer_length(t)
        if length is None:
            raise AddressMapIntegrityError(
                "TRANSFER_MISSING_LENGTH",
                {"index": idx, "id": txn_id, "reason": "no 'length', and no resolvable 'burst_len'+'beat_size', declared"},
            )
        if length <= 0:
            raise AddressMapIntegrityError("TRANSFER_LENGTH_NOT_POSITIVE", {"index": idx, "id": txn_id, "length": length})

        end = address + length

        start_page = address // FOUR_KB
        end_page = (end - 1) // FOUR_KB
        if start_page != end_page:
            findings.append(
                {
                    "type": "CROSSES_4KB_BOUNDARY",
                    "transaction_id": txn_id,
                    "address": address,
                    "length": length,
                    "end": end,
                    "boundary_crossed": (start_page + 1) * FOUR_KB,
                }
            )

        touched = [r for r in regions if r.base < end and address < r.end]
        if not touched:
            findings.append(
                {
                    "type": "TRANSFER_TARGETS_UNMAPPED_ADDRESS",
                    "transaction_id": txn_id,
                    "address": address,
                    "length": length,
                    "end": end,
                }
            )
            continue

        distinct_protocol_regions = sorted({r.protocol_region for r in touched})
        if len(distinct_protocol_regions) > 1:
            findings.append(
                {
                    "type": "CROSSES_PROTOCOL_REGION_BOUNDARY",
                    "transaction_id": txn_id,
                    "address": address,
                    "length": length,
                    "end": end,
                    "protocol_regions_crossed": distinct_protocol_regions,
                    "regions_touched": [r.to_dict() for r in touched],
                }
            )
        elif not _covers_range(touched, address, end):
            findings.append(
                {
                    "type": "TRANSFER_PARTIALLY_UNMAPPED",
                    "transaction_id": txn_id,
                    "address": address,
                    "length": length,
                    "end": end,
                    "regions_touched": [r.to_dict() for r in touched],
                }
            )

    return findings


@dataclass
class AddressMapIntegrityReport:
    status: str
    overlaps: List[Dict[str, Any]]
    holes: List[Dict[str, Any]]
    illegal_transfers: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "overlaps": self.overlaps,
            "holes": self.holes,
            "illegal_transfers": self.illegal_transfers,
        }

    def render_text(self) -> str:
        lines = [f"Address Map Integrity: {self.status}"]
        lines.append(f"  overlaps: {len(self.overlaps)}")
        for f in self.overlaps:
            lines.append(
                f"    OVERLAP {f['region_a']['owner']}[{hex(f['region_a']['base'])}:{hex(f['region_a']['end'])}) "
                f"x {f['region_b']['owner']}[{hex(f['region_b']['base'])}:{hex(f['region_b']['end'])}) "
                f"-> [{hex(f['overlap_start'])}:{hex(f['overlap_end'])})"
            )
        lines.append(f"  unmapped holes: {len(self.holes)}")
        for f in self.holes:
            before = f["region_before"]["owner"] if f["region_before"] else "<space start>"
            after = f["region_after"]["owner"] if f["region_after"] else "<space end>"
            lines.append(f"    HOLE [{hex(f['start'])}:{hex(f['end'])}) between {before} and {after}")
        lines.append(f"  illegal transfers: {len(self.illegal_transfers)}")
        for f in self.illegal_transfers:
            lines.append(f"    {f['type']} txn={f['transaction_id']} [{hex(f['address'])}:{hex(f['end'])})")
        return "\n".join(lines)


def analyze_address_map(
    regions: Sequence[dict],
    transactions: Optional[Sequence[dict]] = None,
    address_space_bits: Optional[int] = None,
) -> AddressMapIntegrityReport:
    """The one entry point: normalizes `regions`, runs all three checks, and
    folds `status` to `FAIL` iff a real overlap or illegal-transfer finding
    exists. Unmapped holes never force `FAIL` on their own -- a declared gap
    (reserved space) is a normal, reportable engineering fact, not a defect;
    a caller wanting "no gaps at all" checks `report.holes` itself."""
    normalized = normalize_regions(regions)
    overlaps = check_overlaps(normalized)
    holes = check_unmapped_holes(normalized, address_space_bits=address_space_bits)
    illegal_transfers = (
        check_transfer_legality(transactions, normalized) if transactions else []
    )
    status = "FAIL" if (overlaps or illegal_transfers) else "PASS"
    return AddressMapIntegrityReport(
        status=status, overlaps=overlaps, holes=holes, illegal_transfers=illegal_transfers
    )
