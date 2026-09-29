"""dv_harness/dependency_supply_chain.py -- what this project actually depends
on, and whether those dependencies satisfy a real, checkable policy.

THE GAP (re-verified by direct search on 2026-09-06 before anything was
written): `grep -rn "supply_chain|dependency_audit|SBOM|pinned.version" -i`
over the whole tree matched NOTHING executable. No module anywhere read
`pyproject.toml` or `requirements-harness.txt` as a dependency declaration, no
code compared a declared dependency against what is really installed, and no
code anywhere asked whether a dependency version was pinned. So "which
third-party components is this harness built on, at which versions, and are
any of them unconstrained" was a question this project could not answer about
itself.

WHAT IS REUSED RATHER THAN REBUILT. The DesignWare VIP half of the inventory
is `env_manifest.build_vip_release()` / `scan_designware_home()` -- the real
filesystem scan of `$DESIGNWARE_HOME` that already answers "which VIP release
is this environment actually built against", including its three honestly
distinct NOT_AVAILABLE reasons. There is no second VIP scanner here, and this
module never reads a VIP version out of a document. File integrity records use
`env_manifest.file_ref()` (the same path+sha256+bytes shape the manifest's own
document references use), so a supply-chain report and an env.manifest.json
describe a file the same way. Version arithmetic is `packaging`'s
(`SpecifierSet`/`Version`), the PyPA reference implementation of PEP 440 --
hand-rolling version comparison is how a supply-chain check silently accepts a
version it should have refused.

THE THREE CHECKS, AND WHAT EACH ONE HONESTLY IS:

- PINNED_VERSION -- real, and it runs everywhere. Every declared Python
  requirement is classified from its own specifier set (PINNED_EXACT /
  BOUNDED_RANGE / LOWER_BOUND_ONLY / UNCONSTRAINED); an installed VIP package
  is PINNED_EXACT when the install tree really names a version directory and
  UNCONSTRAINED when it does not, because "which VIP is this" is then
  unanswerable from the install itself.
- DECLARED_VS_INSTALLED -- real, and it runs wherever an interpreter can be
  interrogated. Each Python requirement is resolved against the REAL running
  interpreter through `importlib.metadata`, so a declared dependency nobody
  installed, and an installed version outside its own declared range, are both
  findings rather than assumptions.
- VULNERABILITY_ADVISORY -- **NOT_AVAILABLE in this environment, and it says
  so rather than reporting a clean scan.** There is no offline advisory source
  here: `pip-audit` and `safety` are not installed (checked at run time, by
  name, not assumed), and the OSV/PyPI advisory APIs are network services,
  which a LOCAL_ANALYSIS run must not contact. A project that HAS a real
  offline advisory database declares it (`.dv-harness/supply_chain/policy.json`
  or `--advisory-db`) and the check really runs against it, reporting that
  database's own source and as-of date; without one, the check reports
  NOT_AVAILABLE with the real reason and the overall status can never be
  POLICY_CLEAN. Never claim a security scan happened when no real check ran --
  the same rule `connectivity.py` applies to a NOT_AVAILABLE gate and
  `platform_health.py` applies to an unmeasured subsystem, and the reason
  NOT_FULLY_CHECKED outranks POLICY_CLEAN here.

DELIBERATELY BOUNDED, stated rather than implied closed.
(1) The Python inventory is what this project DECLARES plus what is really
    installed for those declarations. It is not a transitive dependency graph:
    resolving one requires a resolver run against an index, which is a network
    act. Transitive components are therefore absent from the inventory and the
    report says so -- an SBOM this is not.
(2) It READS ONLY. No file is written, no approval minted, no stage run, no
    build/regression/LSF submission started, and there is deliberately no
    stage gate: a gate that passed because no advisory database was present
    would be worse than none.
(3) A finding is a finding about THIS declaration set. An exempted unpinned
    dependency still appears in the inventory carrying its exemption reason --
    an exemption suppresses the finding, never the fact.
(4) Disclosed precisely, the same way `golden_flow_readiness.py` discloses it:
    the `dv-harness supply-chain` CLI WRAPPER still constructs a `DVHarness`
    and appends the usual `CLI_ACCESS` audit event before dispatch, exactly as
    `status`/`explain` do. `python -m dv_harness.dependency_supply_chain`
    carries the untouched-tree guarantee.
(5) It is REACHED, not WIRED: no `run_stage()`/`advance()` call site invokes
    it, no graph node declares it, and it is not on the dashboard.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"


class SupplyChainError(Exception):
    """A supply-chain declaration (policy file, advisory database) that cannot
    be used as declared. Raised rather than degraded, because silently ignoring
    a broken advisory database is exactly the fabricated-clean-result failure
    this module exists to prevent."""


# --------------------------------------------------------------------------
# Vocabularies. None of these tokens may collide with `models.Status` --
# a supply-chain finding is not a verification verdict, and a log grep or a
# string comparison must never be able to take one for the other. Held by
# assert_no_verification_verdict_vocabulary(), the same guard and the same
# reason as capability_evolution.py's.
# --------------------------------------------------------------------------

ECOSYSTEM_PYTHON = "python"
ECOSYSTEM_VIP = "designware_vip"
ECOSYSTEMS = (ECOSYSTEM_PYTHON, ECOSYSTEM_VIP)

#: How tightly a component's version is constrained by its own declaration.
PIN_EXACT = "PINNED_EXACT"
PIN_BOUNDED = "BOUNDED_RANGE"
PIN_LOWER_ONLY = "LOWER_BOUND_ONLY"
PIN_UNCONSTRAINED = "UNCONSTRAINED"
PIN_UNDETERMINED = "PIN_UNDETERMINED"
PIN_STATUSES = (PIN_EXACT, PIN_BOUNDED, PIN_LOWER_ONLY, PIN_UNCONSTRAINED, PIN_UNDETERMINED)

#: What the real environment holds against that declaration.
RESOLUTION_SATISFIED = "SATISFIED"
RESOLUTION_VIOLATED = "CONSTRAINT_VIOLATED"
RESOLUTION_NOT_INSTALLED = "NOT_INSTALLED"
RESOLUTION_NOT_AVAILABLE = "RESOLUTION_NOT_AVAILABLE"
RESOLUTIONS = (RESOLUTION_SATISFIED, RESOLUTION_VIOLATED,
               RESOLUTION_NOT_INSTALLED, RESOLUTION_NOT_AVAILABLE)

#: Whether a policy check really ran. A check that could not run is never
#: reported as one that ran and found nothing.
CHECK_RAN = "CHECKED"
CHECK_NOT_AVAILABLE = "NOT_AVAILABLE"

CHECK_PINNED_VERSION = "PINNED_VERSION"
CHECK_DECLARED_VS_INSTALLED = "DECLARED_VS_INSTALLED"
CHECK_VULNERABILITY_ADVISORY = "VULNERABILITY_ADVISORY"
CHECKS = (CHECK_PINNED_VERSION, CHECK_DECLARED_VS_INSTALLED, CHECK_VULNERABILITY_ADVISORY)

#: Overall report status. NOT_FULLY_CHECKED outranks POLICY_CLEAN for the same
#: reason platform_health.py ranks UNKNOWN above HEALTHY: an absent measurement
#: is never conflated with a good one.
STATUS_FINDINGS = "POLICY_FINDINGS"
STATUS_NOT_FULLY_CHECKED = "NOT_FULLY_CHECKED"
STATUS_CLEAN = "POLICY_CLEAN"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
REPORT_STATUSES = (STATUS_FINDINGS, STATUS_NOT_FULLY_CHECKED, STATUS_CLEAN, STATUS_NOT_AVAILABLE)

SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
SEVERITIES = (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW)

#: Finding kinds, each naming the concrete real thing it found.
FINDING_UNPINNED = "UNPINNED_DEPENDENCY"
FINDING_NOT_INSTALLED = "DECLARED_DEPENDENCY_NOT_INSTALLED"
FINDING_CONSTRAINT_VIOLATED = "INSTALLED_VERSION_VIOLATES_CONSTRAINT"
FINDING_VIP_VERSION_UNKNOWN = "VIP_PACKAGE_VERSION_UNKNOWN"
FINDING_KNOWN_VULNERABILITY = "KNOWN_VULNERABILITY"
FINDING_ADVISORY_DB_STALE = "ADVISORY_DATABASE_STALE"
FINDING_KINDS = (FINDING_UNPINNED, FINDING_NOT_INSTALLED, FINDING_CONSTRAINT_VIOLATED,
                 FINDING_VIP_VERSION_UNKNOWN, FINDING_KNOWN_VULNERABILITY,
                 FINDING_ADVISORY_DB_STALE)

#: Severity of an unpinned declaration, by how much room the declaration
#: leaves. UNCONSTRAINED is HIGH because any future release of that package --
#: including one that has not been written yet -- satisfies it; LOWER_BOUND_ONLY
#: is MEDIUM because the next MAJOR release satisfies it; a bounded range is LOW
#: because the blast radius is declared even though the exact artifact is not.
_UNPINNED_SEVERITY = {
    PIN_UNCONSTRAINED: SEVERITY_HIGH,
    PIN_LOWER_ONLY: SEVERITY_MEDIUM,
    PIN_BOUNDED: SEVERITY_LOW,
    PIN_UNDETERMINED: SEVERITY_MEDIUM,
}

#: Advisory-database staleness ceiling. 30 days is this module's default and is
#: a POLICY number, not a measurement -- it is overridable per project and is
#: reported alongside every advisory check so a reader sees the bar that was
#: applied rather than trusting a docstring.
DEFAULT_MAX_ADVISORY_AGE_DAYS = 30

#: Optional per-project policy and advisory database, under the project's own
#: state directory -- never a new parallel state root.
POLICY_RELATIVE_PATH = ".dv-harness/supply_chain/policy.json"

#: Tools that, if installed, would make a real offline-capable advisory check
#: possible. Probed BY NAME at run time rather than assumed absent, so this
#: module's NOT_AVAILABLE reason stays true if a project installs one.
_ADVISORY_TOOL_MODULES = ("pip_audit", "safety")

REPORT_DISCLOSURE = (
    "Declared dependencies plus what is really installed for them; NOT a transitive "
    "dependency graph and NOT an SBOM -- resolving transitive components needs a resolver "
    "run against a package index, which is a network act. Reads only: writes no file, mints "
    "no approval, runs no stage, starts no build/regression/LSF submission, and gates nothing."
)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's vocabularies must share no token with `models.Status`.

    A supply-chain finding must never be something a reader, a log grep or a
    string comparison could take for a stage-gate verdict. Making the
    disjointness checkable here (rather than asserting it in prose) is what
    keeps it true after a later edit adds a token."""
    from .models import Status

    verdicts = {s.value for s in Status}
    for name, vocabulary in (
        ("PIN_STATUSES", PIN_STATUSES),
        ("RESOLUTIONS", RESOLUTIONS),
        ("REPORT_STATUSES", REPORT_STATUSES),
        ("FINDING_KINDS", FINDING_KINDS),
        ("SEVERITIES", SEVERITIES),
    ):
        collision = verdicts.intersection(vocabulary)
        if collision:
            raise SupplyChainError(
                f"{name} collides with dv_harness.models.Status on {sorted(collision)}; a "
                "supply-chain token must never be readable as a verification verdict")


assert_no_verification_verdict_vocabulary()


# --------------------------------------------------------------------------
# Requirement parsing. `packaging` is the PyPA reference implementation of
# PEP 440/508; when it is genuinely absent the pin classification and the
# installed-version comparison both report their own honest UNDETERMINED /
# NOT_AVAILABLE rather than falling back to a hand-rolled comparison that
# would silently accept a version it should have refused.
# --------------------------------------------------------------------------

def packaging_available() -> bool:
    return importlib.util.find_spec("packaging") is not None


#: Lines a requirements file may carry that are not requirements. Recorded as
#: skipped with their real reason rather than dropped, so an inventory built
#: from a file containing `-r base.txt` cannot silently omit that file's
#: contents without saying so.
_NON_REQUIREMENT_PREFIXES = ("-r", "--requirement", "-c", "--constraint", "-e", "--editable",
                             "-i", "--index-url", "--extra-index-url", "-f", "--find-links",
                             "--no-binary", "--only-binary", "--pre", "--hash", "--trusted-host")

_COMMENT_RE = re.compile(r"(^|\s)#.*$")


def _strip_comment(line: str) -> str:
    return _COMMENT_RE.sub("", line).strip()


def parse_requirement_line(line: str) -> Optional[Dict[str, Any]]:
    """One requirements-file line -> a component record, or None for a blank
    line. A non-requirement directive returns a record whose `kind` says what
    it was, so `-r base.txt` is visible in the inventory as an unfollowed
    include rather than silently absent."""
    text = _strip_comment(line)
    if not text:
        return None
    for prefix in _NON_REQUIREMENT_PREFIXES:
        if text == prefix or text.startswith(prefix + " ") or text.startswith(prefix + "="):
            return {"kind": "DIRECTIVE_NOT_FOLLOWED", "raw": text,
                    "reason": f"pip directive {prefix!r} is recorded, not followed -- following it "
                              "would need a resolver/index and this module reads declarations only"}
    return {"kind": "REQUIREMENT", "raw": text}


def _parse_with_packaging(raw: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """(name, specifier_text, extras, marker) from a PEP 508 requirement, or a
    parse error in the fourth slot's place. Returns (None, None, None, error)
    when the string is not a requirement this project can reason about."""
    from packaging.requirements import Requirement, InvalidRequirement
    try:
        req = Requirement(raw)
    except InvalidRequirement as e:
        return (None, None, None, f"INVALID_REQUIREMENT: {e}")
    extras = ",".join(sorted(req.extras)) or None
    marker = str(req.marker) if req.marker else None
    return (req.name, str(req.specifier), extras, marker)


def classify_pin(specifier_text: Optional[str]) -> Tuple[str, str]:
    """(pin_status, reason) for a PEP 440 specifier set.

    An `==`/`===` specifier without a wildcard is the only thing that names ONE
    artifact, so it is the only PINNED_EXACT. `==1.2.*` and `~=1.2.3` both
    admit a range and are reported as such rather than as pins, which is the
    distinction a "pinned version" policy exists to make."""
    if not packaging_available():
        return (PIN_UNDETERMINED,
                "the `packaging` library is not installed, so this declaration's specifier set "
                "was not interpreted -- a hand-rolled version comparison would silently accept a "
                "version it should have refused")
    if specifier_text is None:
        return (PIN_UNDETERMINED, "no specifier was recorded for this component")
    from packaging.specifiers import SpecifierSet, InvalidSpecifier
    try:
        spec = SpecifierSet(specifier_text)
    except InvalidSpecifier as e:
        return (PIN_UNDETERMINED, f"INVALID_SPECIFIER: {e}")
    if len(spec) == 0:
        return (PIN_UNCONSTRAINED,
                "no version constraint at all -- any release of this package, including one not "
                "yet published, satisfies this declaration")
    exact = [s for s in spec if s.operator in ("==", "===") and "*" not in s.version]
    if exact:
        return (PIN_EXACT, f"names exactly one artifact: {exact[0].operator}{exact[0].version}")
    has_upper = any(s.operator in ("<", "<=") for s in spec)
    # `~=X.Y.Z` is a compatible release: >=X.Y.Z, ==X.Y.*, i.e. a real upper
    # bound even though no `<` appears in the text.
    has_upper = has_upper or any(s.operator == "~=" for s in spec)
    has_upper = has_upper or any(s.operator == "==" and "*" in s.version for s in spec)
    has_lower = any(s.operator in (">", ">=", "~=") for s in spec)
    if has_upper:
        return (PIN_BOUNDED,
                f"bounded range {specifier_text} -- the blast radius is declared, the exact "
                "artifact is not")
    if has_lower:
        return (PIN_LOWER_ONLY,
                f"lower bound only ({specifier_text}) -- the next MAJOR release of this package "
                "satisfies this declaration")
    return (PIN_UNCONSTRAINED, f"no lower or upper bound in {specifier_text}")


def resolve_installed(name: str, specifier_text: Optional[str]) -> Dict[str, Any]:
    """What the REAL running interpreter holds for this distribution, and
    whether it satisfies the declaration. `importlib.metadata` reads the
    installed distribution's own metadata -- it is not an import attempt, so a
    package with an import-time side effect is never executed by this check."""
    from importlib import metadata
    try:
        installed = metadata.version(name)
    except metadata.PackageNotFoundError:
        return {"resolution": RESOLUTION_NOT_INSTALLED, "installed_version": None,
                "reason": f"no distribution named {name!r} is installed for this interpreter"}
    except Exception as e:  # a broken/partial dist-info is a real, reportable state
        return {"resolution": RESOLUTION_NOT_AVAILABLE, "installed_version": None,
                "reason": f"{type(e).__name__} reading installed metadata for {name!r}: {e}"}
    if not packaging_available() or specifier_text is None:
        return {"resolution": RESOLUTION_NOT_AVAILABLE, "installed_version": installed,
                "reason": "the installed version was read, but the declaration's specifier set "
                          "was not interpreted (the `packaging` library is not installed)"}
    from packaging.specifiers import SpecifierSet, InvalidSpecifier
    try:
        spec = SpecifierSet(specifier_text)
    except InvalidSpecifier as e:
        return {"resolution": RESOLUTION_NOT_AVAILABLE, "installed_version": installed,
                "reason": f"INVALID_SPECIFIER: {e}"}
    # prereleases=True so an installed pre-release is judged against the
    # declaration rather than being silently excluded and read as a violation.
    if spec.contains(installed, prereleases=True):
        return {"resolution": RESOLUTION_SATISFIED, "installed_version": installed,
                "reason": f"installed {installed} satisfies {specifier_text or '(any)'}"}
    return {"resolution": RESOLUTION_VIOLATED, "installed_version": installed,
            "reason": f"installed {installed} does NOT satisfy declared {specifier_text}"}


# --------------------------------------------------------------------------
# Inventory: pyproject.toml, requirements files, installed VIP packages.
# --------------------------------------------------------------------------

def _file_ref(path) -> Dict[str, Any]:
    """path + sha256 + real byte size for a manifest file this inventory read.
    Reuses env_manifest's own doc_file_ref shape so a supply-chain report and
    an env.manifest.json describe the same file the same way."""
    from . import env_manifest
    return env_manifest.file_ref(path)


def _toml_loader():
    try:
        import tomllib
        return tomllib, None
    except ModuleNotFoundError:
        try:
            import tomli
            return tomli, None
        except ModuleNotFoundError:
            return None, ("neither `tomllib` (Python 3.11+) nor `tomli` is available, so "
                          "pyproject.toml was not parsed")


def inventory_pyproject(root) -> Dict[str, Any]:
    """`[build-system].requires`, `[project].dependencies` and every
    `[project.optional-dependencies]` group, each component carrying the field
    it was declared in -- a build requirement and a runtime dependency are
    different obligations and collapsing them would hide which is which."""
    path = Path(root) / "pyproject.toml"
    if not path.is_file():
        return {"source_kind": "pyproject", "path": str(path), "present": False,
                "reason": f"no pyproject.toml at {path}", "file": None,
                "requires_python": None, "components": []}
    loader, err = _toml_loader()
    if loader is None:
        return {"source_kind": "pyproject", "path": str(path), "present": True,
                "reason": err, "file": _file_ref(path), "requires_python": None,
                "components": []}
    with path.open("rb") as f:
        doc = loader.load(f)
    project = doc.get("project") or {}
    declared: List[Tuple[str, str]] = []
    for raw in (doc.get("build-system") or {}).get("requires") or []:
        declared.append(("build-system.requires", raw))
    for raw in project.get("dependencies") or []:
        declared.append(("project.dependencies", raw))
    for group, entries in (project.get("optional-dependencies") or {}).items():
        for raw in entries or []:
            declared.append((f"project.optional-dependencies.{group}", raw))
    components = [_python_component(str(path), field, raw) for field, raw in declared]
    return {"source_kind": "pyproject", "path": str(path), "present": True, "reason": None,
            "file": _file_ref(path), "requires_python": project.get("requires-python"),
            "components": components}


def _python_component(source_path: str, source_field: str, raw: str) -> Dict[str, Any]:
    name, spec_text, extras, marker_or_error = (None, None, None, None)
    parse_error = None
    if packaging_available():
        name, spec_text, extras, marker_or_error = _parse_with_packaging(raw)
        if name is None:
            parse_error = marker_or_error
            marker_or_error = None
    else:
        parse_error = ("the `packaging` library is not installed, so this declaration was "
                       "recorded but not interpreted")
    pin_status, pin_reason = (PIN_UNDETERMINED, parse_error) if parse_error else classify_pin(spec_text)
    component: Dict[str, Any] = {
        "ecosystem": ECOSYSTEM_PYTHON,
        "name": name,
        "declared_as": raw,
        "specifier": spec_text,
        "extras": extras,
        "marker": marker_or_error,
        "source_path": source_path,
        "source_field": source_field,
        "pin_status": pin_status,
        "pin_reason": pin_reason,
        "parse_error": parse_error,
    }
    if name and not parse_error:
        component["installed"] = resolve_installed(name, spec_text)
    else:
        component["installed"] = {
            "resolution": RESOLUTION_NOT_AVAILABLE, "installed_version": None,
            "reason": parse_error or "no distribution name could be read from this declaration"}
    return component


def inventory_requirements_file(path) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"source_kind": "requirements", "path": str(p), "present": False,
                "reason": f"no requirements file at {p}", "file": None,
                "components": [], "directives": []}
    components: List[Dict[str, Any]] = []
    directives: List[Dict[str, Any]] = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        parsed = parse_requirement_line(line)
        if parsed is None:
            continue
        if parsed["kind"] == "DIRECTIVE_NOT_FOLLOWED":
            directives.append({"line": lineno, **parsed})
            continue
        component = _python_component(str(p), f"line {lineno}", parsed["raw"])
        components.append(component)
    return {"source_kind": "requirements", "path": str(p), "present": True, "reason": None,
            "file": _file_ref(p), "components": components, "directives": directives}


def discover_requirements_files(root) -> List[Path]:
    """Every `requirements*.txt` at the project root, sorted for a stable
    diff. Root-level only: a requirements file inside a generated environment
    or a vendored tree is that tree's declaration, not this project's."""
    return sorted(p for p in Path(root).glob("requirements*.txt") if p.is_file())


def inventory_vip(designware_home=None) -> Dict[str, Any]:
    """Installed DesignWare VIP packages, from the REAL `$DESIGNWARE_HOME`
    scan `env_manifest.build_vip_release()` already performs. Its three
    honestly distinct outcomes (unset / stale path / scanned) are carried
    through verbatim -- an unset DESIGNWARE_HOME and a typo'd one are different
    operator problems and this module does not collapse them."""
    from . import env_manifest
    release = env_manifest.build_vip_release(designware_home)
    components: List[Dict[str, Any]] = []
    for pkg in release.get("packages") or []:
        version = pkg.get("version")
        if version:
            pin_status = PIN_EXACT
            pin_reason = (f"the install tree names exactly one version directory: {version}")
        else:
            pin_status = PIN_UNCONSTRAINED
            pin_reason = ("the install tree carries no version directory for this package, so "
                          "which VIP release is installed is unanswerable from the install itself")
        components.append({
            "ecosystem": ECOSYSTEM_VIP,
            "name": pkg.get("name"),
            "declared_as": pkg.get("install_path"),
            "specifier": version,
            "extras": None,
            "marker": None,
            "source_path": release.get("designware_home"),
            "source_field": "designware_home_scan",
            "pin_status": pin_status,
            "pin_reason": pin_reason,
            "parse_error": None,
            "install_path": pkg.get("install_path"),
            "release_notes": pkg.get("release_notes"),
            "feature_matrix": pkg.get("feature_matrix"),
            "installed": {
                "resolution": RESOLUTION_SATISFIED if version else RESOLUTION_NOT_AVAILABLE,
                "installed_version": version,
                "reason": ("this record IS the installed tree -- it was produced by scanning it"
                           if version else
                           "the package directory exists but names no version"),
            },
        })
    return {"source_kind": "designware_vip", "path": release.get("designware_home"),
            "present": release.get("status") == "SCANNED", "reason": release.get("reason"),
            "file": None, "scan_status": release.get("status"), "components": components}


def build_inventory(root=".", *, designware_home=None,
                    include_vip: bool = True) -> Dict[str, Any]:
    """Every real dependency declaration this project carries, from every real
    source on disk. An empty component list from a source that EXISTS is a real
    finding ("this project declares no runtime dependency"), not an error."""
    sources: List[Dict[str, Any]] = [inventory_pyproject(root)]
    for req in discover_requirements_files(root):
        sources.append(inventory_requirements_file(req))
    if include_vip:
        sources.append(inventory_vip(designware_home))
    components: List[Dict[str, Any]] = []
    for source in sources:
        components.extend(source.get("components") or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(Path(root).resolve()),
        "sources": sources,
        "components": components,
        "component_count": len(components),
        "python_environment": {
            "packaging_available": packaging_available(),
            "transitive_dependencies": "NOT_RESOLVED_NEEDS_INDEX",
        },
        "disclosure": REPORT_DISCLOSURE,
    }


# --------------------------------------------------------------------------
# Policy.
# --------------------------------------------------------------------------

def default_policy() -> Dict[str, Any]:
    return {
        "require_exact_pins": True,
        "exempt_unpinned": [],
        "advisory_database": None,
        "max_advisory_age_days": DEFAULT_MAX_ADVISORY_AGE_DAYS,
    }


def load_policy(root=".", *, path: Optional[str] = None) -> Dict[str, Any]:
    """The optional per-project policy at `.dv-harness/supply_chain/policy.json`
    (policy-as-data, the same shape `context_budget.policy.json` and
    `harness_deploy.manifest.json` use). Absent -> the documented defaults,
    carrying `declared: False` so a report says whether a human ever chose
    them."""
    p = Path(path) if path else Path(root) / POLICY_RELATIVE_PATH
    policy = default_policy()
    policy["path"] = str(p)
    policy["declared"] = False
    if not p.is_file():
        return policy
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SupplyChainError(f"{p}: unreadable supply-chain policy: {e}") from e
    if not isinstance(doc, Mapping):
        raise SupplyChainError(f"{p}: supply-chain policy must be a JSON object")
    unknown = set(doc) - set(default_policy())
    if unknown:
        raise SupplyChainError(
            f"{p}: unknown policy key(s) {sorted(unknown)}; a misspelled key would silently "
            f"leave the default in force. Known keys: {sorted(default_policy())}")
    for entry in doc.get("exempt_unpinned") or []:
        if not isinstance(entry, Mapping) or not entry.get("name") or not entry.get("reason"):
            raise SupplyChainError(
                f"{p}: every exempt_unpinned entry needs a name AND a reason -- an unexplained "
                "exemption is indistinguishable from an oversight")
    policy.update(doc)
    policy["declared"] = True
    return policy


def _exemption_for(policy: Mapping[str, Any], component: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    name = (component.get("name") or "").lower()
    for entry in policy.get("exempt_unpinned") or []:
        if str(entry.get("name", "")).lower() == name:
            return entry
    return None


# --------------------------------------------------------------------------
# Check 1 + 2: pinned versions, and declared vs. really installed.
# --------------------------------------------------------------------------

def check_pinned_versions(inventory: Mapping[str, Any],
                          policy: Mapping[str, Any]) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    counts = {status: 0 for status in PIN_STATUSES}
    for component in inventory.get("components") or []:
        status = component.get("pin_status", PIN_UNDETERMINED)
        counts[status] = counts.get(status, 0) + 1
        if status == PIN_EXACT:
            continue
        exemption = _exemption_for(policy, component)
        if exemption is not None:
            component["exemption"] = dict(exemption)
            continue
        if not policy.get("require_exact_pins", True):
            continue
        kind = (FINDING_VIP_VERSION_UNKNOWN if component.get("ecosystem") == ECOSYSTEM_VIP
                else FINDING_UNPINNED)
        findings.append({
            "kind": kind,
            "severity": _UNPINNED_SEVERITY.get(status, SEVERITY_MEDIUM),
            "component": component.get("name"),
            "ecosystem": component.get("ecosystem"),
            "declared_as": component.get("declared_as"),
            "source_path": component.get("source_path"),
            "source_field": component.get("source_field"),
            "pin_status": status,
            "detail": component.get("pin_reason"),
        })
    return {"check": CHECK_PINNED_VERSION, "status": CHECK_RAN,
            "reason": None, "pin_counts": counts, "findings": findings,
            "require_exact_pins": bool(policy.get("require_exact_pins", True))}


def check_declared_vs_installed(inventory: Mapping[str, Any]) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    counts = {resolution: 0 for resolution in RESOLUTIONS}
    for component in inventory.get("components") or []:
        installed = component.get("installed") or {}
        resolution = installed.get("resolution", RESOLUTION_NOT_AVAILABLE)
        counts[resolution] = counts.get(resolution, 0) + 1
        if resolution == RESOLUTION_NOT_INSTALLED:
            findings.append({
                "kind": FINDING_NOT_INSTALLED,
                # MEDIUM, not HIGH: an optional/build-time declaration nobody
                # installed is a real drift between what this project says it
                # needs and what it runs on, but it breaks nothing that is
                # currently working.
                "severity": SEVERITY_MEDIUM,
                "component": component.get("name"),
                "ecosystem": component.get("ecosystem"),
                "declared_as": component.get("declared_as"),
                "source_path": component.get("source_path"),
                "source_field": component.get("source_field"),
                "detail": installed.get("reason"),
            })
        elif resolution == RESOLUTION_VIOLATED:
            findings.append({
                "kind": FINDING_CONSTRAINT_VIOLATED,
                "severity": SEVERITY_HIGH,
                "component": component.get("name"),
                "ecosystem": component.get("ecosystem"),
                "declared_as": component.get("declared_as"),
                "installed_version": installed.get("installed_version"),
                "source_path": component.get("source_path"),
                "source_field": component.get("source_field"),
                "detail": installed.get("reason"),
            })
    return {"check": CHECK_DECLARED_VS_INSTALLED, "status": CHECK_RAN, "reason": None,
            "resolution_counts": counts, "findings": findings}


# --------------------------------------------------------------------------
# Check 3: vulnerability advisories -- REAL against a declared offline
# database, and an honest NOT_AVAILABLE without one. Never a fabricated clean
# result.
# --------------------------------------------------------------------------

ADVISORY_SCHEMA_VERSION = "1.0"


def load_advisory_database(path) -> Dict[str, Any]:
    """A real, offline, checkable advisory source in an OSV-shaped subset:

        {"schema_version": "1.0", "source": "<where these came from>",
         "as_of": "2026-09-01",
         "advisories": [{"id", "ecosystem", "package",
                         "affected": [{"introduced": "0", "fixed": "4.0.0"}],
                         "severity", "summary", "reference"}]}

    Every field except `severity`/`summary`/`reference` is REQUIRED, because a
    database that cannot say where it came from or how current it is cannot
    support a claim about whether this project is exposed."""
    p = Path(path)
    if not p.is_file():
        raise SupplyChainError(f"no advisory database at {p}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SupplyChainError(f"{p}: unreadable advisory database: {e}") from e
    if not isinstance(doc, Mapping):
        raise SupplyChainError(f"{p}: advisory database must be a JSON object")
    # `advisories` is required to be PRESENT but may legitimately be EMPTY: a
    # real feed that currently carries nothing affecting this ecosystem is a
    # usable database, and refusing it would push a project back to having no
    # advisory source at all. The three provenance fields must additionally be
    # non-empty -- a database that cannot say where it came from or how current
    # it is cannot support a claim about whether this project is exposed.
    for required in ("schema_version", "source", "as_of", "advisories"):
        if required not in doc:
            raise SupplyChainError(
                f"{p}: advisory database is missing required field {required!r}")
    for required in ("schema_version", "source", "as_of"):
        if not doc.get(required):
            raise SupplyChainError(
                f"{p}: advisory database field {required!r} is empty -- a database that cannot "
                "state its own source and as-of date cannot support a security claim")
    if str(doc["schema_version"]) != ADVISORY_SCHEMA_VERSION:
        raise SupplyChainError(
            f"{p}: advisory database schema_version {doc['schema_version']!r} != "
            f"{ADVISORY_SCHEMA_VERSION!r}")
    if not isinstance(doc["advisories"], list):
        raise SupplyChainError(f"{p}: 'advisories' must be a JSON list")
    for i, advisory in enumerate(doc["advisories"]):
        if not isinstance(advisory, Mapping):
            raise SupplyChainError(f"{p}: advisories[{i}] must be a JSON object")
        for required in ("id", "ecosystem", "package", "affected"):
            if not advisory.get(required):
                raise SupplyChainError(
                    f"{p}: advisories[{i}] is missing required field {required!r}")
    try:
        _dt.date.fromisoformat(str(doc["as_of"]))
    except ValueError as e:
        raise SupplyChainError(f"{p}: as_of {doc['as_of']!r} is not an ISO date: {e}") from e
    return {"path": str(p), "file": _file_ref(p), "source": doc["source"],
            "as_of": str(doc["as_of"]), "advisory_count": len(doc["advisories"]),
            "advisories": list(doc["advisories"])}


def advisory_tooling_probe() -> Dict[str, Any]:
    """Which real advisory tools are importable here, probed BY NAME rather
    than assumed. Reported in the NOT_AVAILABLE reason so it stays true if a
    project installs one."""
    return {name: importlib.util.find_spec(name) is not None
            for name in _ADVISORY_TOOL_MODULES}


def _version_in_range(version: str, affected: Sequence[Mapping[str, Any]]) -> Tuple[bool, str]:
    """OSV `introduced`/`fixed` half-open ranges: introduced <= v < fixed."""
    from packaging.version import Version, InvalidVersion
    try:
        current = Version(version)
    except InvalidVersion as e:
        return (False, f"INSTALLED_VERSION_NOT_PEP440: {e}")
    for entry in affected:
        introduced = entry.get("introduced")
        fixed = entry.get("fixed")
        try:
            if introduced is not None and current < Version(str(introduced)):
                continue
            if fixed is not None and current >= Version(str(fixed)):
                continue
        except InvalidVersion as e:
            return (False, f"ADVISORY_RANGE_NOT_PEP440: {e}")
        return (True, f"{introduced or '0'} <= {version} < {fixed or 'unfixed'}")
    return (False, f"{version} is outside every declared affected range")


def check_vulnerability_advisories(inventory: Mapping[str, Any],
                                   policy: Mapping[str, Any],
                                   *, advisory_db_path: Optional[str] = None) -> Dict[str, Any]:
    """Match this project's REALLY INSTALLED component versions against a real
    advisory database, or report NOT_AVAILABLE with the real reason.

    Matching uses the INSTALLED version, never the declared specifier: an
    advisory is about an artifact in use, and a declared range is not one."""
    declared_path = advisory_db_path or policy.get("advisory_database")
    if not declared_path:
        probe = advisory_tooling_probe()
        return {
            "check": CHECK_VULNERABILITY_ADVISORY,
            "status": CHECK_NOT_AVAILABLE,
            "reason": (
                "no offline advisory database is declared for this project "
                f"(policy key 'advisory_database' in {policy.get('path')}, or --advisory-db), "
                f"and no local advisory tool is importable here ({probe}). The OSV/PyPI advisory "
                "APIs are network services and are deliberately NOT contacted. NO SECURITY SCAN "
                "RAN -- this is not a clean result."),
            "advisory_tooling": probe,
            "database": None,
            "matched_components": 0,
            "unmatchable_components": [],
            "findings": [],
        }
    database = load_advisory_database(declared_path)
    if not packaging_available():
        return {
            "check": CHECK_VULNERABILITY_ADVISORY,
            "status": CHECK_NOT_AVAILABLE,
            "reason": ("an advisory database was declared and read, but the `packaging` library "
                       "is not installed, so no version could be compared against an advisory "
                       "range. NO SECURITY SCAN RAN -- this is not a clean result."),
            "advisory_tooling": advisory_tooling_probe(),
            "database": {k: v for k, v in database.items() if k != "advisories"},
            "matched_components": 0,
            "unmatchable_components": [],
            "findings": [],
        }

    by_package: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for advisory in database["advisories"]:
        key = (str(advisory["ecosystem"]).lower(), str(advisory["package"]).lower())
        by_package.setdefault(key, []).append(advisory)

    findings: List[Dict[str, Any]] = []
    unmatchable: List[Dict[str, Any]] = []
    matched = 0
    for component in inventory.get("components") or []:
        name = component.get("name")
        if not name:
            continue
        installed = (component.get("installed") or {}).get("installed_version")
        if not installed:
            # Not clean, and not a vulnerability either: there is no artifact
            # in use to match. Reported per component so an inventory of
            # uninstalled declarations can never read as a scanned one.
            unmatchable.append({
                "component": name, "ecosystem": component.get("ecosystem"),
                "reason": (component.get("installed") or {}).get(
                    "reason", "no installed version could be read")})
            continue
        matched += 1
        for advisory in by_package.get(
                (str(component.get("ecosystem")).lower(), str(name).lower()), []):
            hit, detail = _version_in_range(str(installed), advisory["affected"])
            if not hit:
                continue
            findings.append({
                "kind": FINDING_KNOWN_VULNERABILITY,
                "severity": str(advisory.get("severity") or SEVERITY_HIGH).upper(),
                "advisory_id": advisory["id"],
                "component": name,
                "ecosystem": component.get("ecosystem"),
                "installed_version": installed,
                "affected_range": detail,
                "summary": advisory.get("summary"),
                "reference": advisory.get("reference"),
                "advisory_source": database["source"],
                "advisory_as_of": database["as_of"],
                "source_path": component.get("source_path"),
                "detail": (f"{advisory['id']}: installed {name} {installed} falls in a declared "
                           f"affected range ({detail})"),
            })

    age_days = (_dt.date.today() - _dt.date.fromisoformat(database["as_of"])).days
    max_age = int(policy.get("max_advisory_age_days") or DEFAULT_MAX_ADVISORY_AGE_DAYS)
    stale = age_days > max_age
    if stale:
        findings.append({
            "kind": FINDING_ADVISORY_DB_STALE,
            "severity": SEVERITY_MEDIUM,
            "component": None,
            "ecosystem": None,
            "detail": (f"the advisory database at {database['path']} is as of "
                       f"{database['as_of']} ({age_days} days old, policy ceiling {max_age}); "
                       "an advisory published since then would not appear in this result"),
        })
    return {
        "check": CHECK_VULNERABILITY_ADVISORY,
        "status": CHECK_RAN,
        # A real check against a real database is still only a statement about
        # THAT database. Said on every render rather than left to be assumed.
        "reason": (f"matched {matched} installed component version(s) against "
                   f"{database['advisory_count']} advisory record(s) from {database['source']} "
                   f"(as of {database['as_of']}). This is a statement about that database, not "
                   "a proof that no vulnerability exists."),
        "advisory_tooling": advisory_tooling_probe(),
        "database": {k: v for k, v in database.items() if k != "advisories"},
        "database_age_days": age_days,
        "database_stale": stale,
        "matched_components": matched,
        "unmatchable_components": unmatchable,
        "findings": findings,
    }


# --------------------------------------------------------------------------
# The report.
# --------------------------------------------------------------------------

def analyze_supply_chain(root=".", *, designware_home=None, include_vip: bool = True,
                         policy_path: Optional[str] = None,
                         advisory_db_path: Optional[str] = None) -> Dict[str, Any]:
    """Inventory + the three checks + one overall status.

    POLICY_CLEAN requires that every check RAN and none of them found
    anything. A check that could not run makes the report NOT_FULLY_CHECKED,
    never clean -- an absent measurement is not a good one."""
    policy = load_policy(root, path=policy_path)
    inventory = build_inventory(root, designware_home=designware_home, include_vip=include_vip)
    checks = [
        check_pinned_versions(inventory, policy),
        check_declared_vs_installed(inventory),
        check_vulnerability_advisories(inventory, policy, advisory_db_path=advisory_db_path),
    ]
    findings: List[Dict[str, Any]] = []
    for check in checks:
        for finding in check["findings"]:
            findings.append({**finding, "check": check["check"]})
    not_run = [c["check"] for c in checks if c["status"] != CHECK_RAN]

    if not inventory["components"] and not any(s.get("present") for s in inventory["sources"]):
        status = STATUS_NOT_AVAILABLE
    elif findings:
        status = STATUS_FINDINGS
    elif not_run:
        status = STATUS_NOT_FULLY_CHECKED
    else:
        status = STATUS_CLEAN

    severity_counts = {s: 0 for s in SEVERITIES}
    for finding in findings:
        severity_counts[finding.get("severity", SEVERITY_MEDIUM)] = \
            severity_counts.get(finding.get("severity", SEVERITY_MEDIUM), 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "root": inventory["root"],
        "policy": {k: v for k, v in policy.items() if k != "exempt_unpinned"},
        "policy_exemptions": policy.get("exempt_unpinned") or [],
        "inventory": inventory,
        "checks": checks,
        "checks_not_run": not_run,
        "findings": findings,
        "finding_count": len(findings),
        "severity_counts": severity_counts,
        "disclosure": REPORT_DISCLOSURE,
    }


def format_report(report: Mapping[str, Any]) -> str:
    inv = report["inventory"]
    lines = [
        f"dependency supply chain: {report['root']}  [{report['status']}]",
        f"  components inventoried: {inv['component_count']}",
    ]
    for source in inv["sources"]:
        present = "present" if source.get("present") else "absent"
        detail = f" -- {source['reason']}" if source.get("reason") else ""
        lines.append(f"    {source['source_kind']:<16} {present:<8} "
                     f"{len(source.get('components') or [])} component(s)  "
                     f"{source.get('path')}{detail}")
    for check in report["checks"]:
        lines.append(f"  {check['check']:<24} {check['status']}"
                     f"{'  (' + str(len(check['findings'])) + ' finding(s))' if check['findings'] else ''}")
        if check.get("reason"):
            lines.append(f"      {check['reason']}")
    if report["findings"]:
        lines.append(f"  findings ({report['finding_count']}): "
                     + ", ".join(f"{k}={v}" for k, v in report["severity_counts"].items() if v))
        for finding in report["findings"]:
            where = finding.get("component") or finding.get("source_path") or "-"
            lines.append(f"    {finding['severity']:<6} {finding['kind']} {where}")
            lines.append(f"           {finding.get('detail')}")
    if report["checks_not_run"]:
        lines.append("  NOT FULLY CHECKED: " + ", ".join(report["checks_not_run"])
                     + " -- this report is not a clean security result")
    lines.append(f"  disclosure: {report['disclosure']}")
    return "\n".join(lines)


_EXIT_BY_STATUS = {
    STATUS_CLEAN: 0,
    STATUS_FINDINGS: 1,
    STATUS_NOT_FULLY_CHECKED: 2,
    STATUS_NOT_AVAILABLE: 2,
}


def execute_verb(verb: str, *, root: Any = ".", designware_home: Optional[str] = None,
                 include_vip: bool = True, policy_path: Optional[str] = None,
                 advisory_db_path: Optional[str] = None,
                 as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `dv-harness supply-chain <verb>` and
    `python -m dv_harness.dependency_supply_chain <verb>`. Returns
    (text, exit_code): 0 POLICY_CLEAN, 1 a real policy finding, 2 a check that
    could not run or nothing to inventory. Reads only."""
    if verb == "inventory":
        inventory = build_inventory(root, designware_home=designware_home,
                                    include_vip=include_vip)
        if as_json:
            return json.dumps(inventory, indent=2), 0 if inventory["components"] else 2
        lines = [f"dependency inventory: {inventory['root']}",
                 f"  components: {inventory['component_count']}"]
        for component in inventory["components"]:
            installed = (component.get("installed") or {})
            lines.append(
                f"    {component['ecosystem']:<15} {str(component.get('name')):<24} "
                f"{component['pin_status']:<18} "
                f"installed={installed.get('installed_version') or '-':<12} "
                f"{installed.get('resolution')}")
            lines.append(f"        declared {component.get('declared_as')} "
                         f"({component.get('source_field')} of {component.get('source_path')})")
        for source in inventory["sources"]:
            if source.get("reason"):
                lines.append(f"    NOTE {source['source_kind']}: {source['reason']}")
        lines.append(f"  disclosure: {inventory['disclosure']}")
        return "\n".join(lines), 0 if inventory["components"] else 2

    if verb == "check":
        report = analyze_supply_chain(root, designware_home=designware_home,
                                      include_vip=include_vip, policy_path=policy_path,
                                      advisory_db_path=advisory_db_path)
        text = json.dumps(report, indent=2) if as_json else format_report(report)
        return text, _EXIT_BY_STATUS.get(report["status"], 2)

    if verb == "advisory-status":
        policy = load_policy(root, path=policy_path)
        inventory = build_inventory(root, designware_home=designware_home,
                                    include_vip=include_vip)
        check = check_vulnerability_advisories(inventory, policy,
                                               advisory_db_path=advisory_db_path)
        if as_json:
            return json.dumps(check, indent=2), 0 if check["status"] == CHECK_RAN and not check["findings"] else (
                1 if check["findings"] else 2)
        lines = [f"vulnerability advisory check: {check['status']}", f"  {check['reason']}"]
        for entry in check.get("unmatchable_components") or []:
            lines.append(f"    NOT_MATCHED {entry['component']}: {entry['reason']}")
        for finding in check["findings"]:
            lines.append(f"    {finding['severity']:<6} {finding['kind']} {finding.get('detail')}")
        if check["status"] != CHECK_RAN:
            lines.append("  NO SECURITY SCAN RAN -- this is not a clean result.")
        code = 0 if (check["status"] == CHECK_RAN and not check["findings"]) else (
            1 if check["findings"] else 2)
        return "\n".join(lines), code

    return (f"unknown supply-chain verb {verb!r}", 2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.dependency_supply_chain",
        description="Inventory this project's REAL declared dependencies (pyproject.toml, "
                    "requirements*.txt, installed DesignWare VIP packages) and check them "
                    "against a real policy: pinned versions, declared-vs-really-installed, and "
                    "a vulnerability-advisory lookup that reports NOT_AVAILABLE rather than a "
                    "fabricated clean result when no real offline advisory source exists. "
                    "Reads only -- writes nothing, gates nothing.")
    ap.add_argument("verb", choices=("inventory", "check", "advisory-status"))
    ap.add_argument("--root", default=".", help="Project root to inventory.")
    ap.add_argument("--designware-home", default=None,
                    help="Explicit VIP install tree to scan (default: $DESIGNWARE_HOME).")
    ap.add_argument("--no-vip", action="store_true",
                    help="Skip the DesignWare VIP install scan entirely.")
    ap.add_argument("--policy", default=None,
                    help=f"Policy JSON (default: <root>/{POLICY_RELATIVE_PATH}).")
    ap.add_argument("--advisory-db", default=None,
                    help="Offline advisory database JSON to check installed versions against.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(a.verb, root=a.root, designware_home=a.designware_home,
                                  include_vip=not a.no_vip, policy_path=a.policy,
                                  advisory_db_path=a.advisory_db, as_json=a.json)
    except SupplyChainError as e:
        print(f"{type(e).__name__}: {e}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
