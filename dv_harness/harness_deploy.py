"""dv_harness/harness_deploy.py -- sync THIS harness checkout to the shared
Linux Agent deployment path.

WHY THIS EXISTS
---------------
`docs/workflow/USAGE_MULTI_USER_SAFETY.md:16-19` records as standing policy that "every
harness update must sync to `/home/svcacct/AI/Agent`". A 2026-09-05 audit
confirmed that half of the policy had a POLICY STATEMENT and no MECHANISM:

  - `dv_harness/cli.py` had no `deploy`/`harness-sync`/`push-remote` verb
    (only `memory sync`, a different subsystem, and `resync-notes`);
  - repo-wide search for `deploy_harness`/`harness_deploy`/`push_harness`/
    `sync_harness` returned zero hits;
  - `justfile:27` flags "whether dv_harness itself is deployed on the Linux
    server" as explicitly UNCONFIRMED;
  - every `.work/*.md` report describing a sync narrates a manual, ad hoc
    file-by-file copy the agent performed by hand that session.

The other half -- writing distilled skills/capabilities back to the shared
Knowledge Center DB path -- was already real (`dv_harness/knowledge_center.py`).
This module is the missing codebase half.

WHAT IT REUSES RATHER THAN REBUILDS
-----------------------------------
Nothing here re-derives hash math or transport. The diff engine is the real,
tested `tools/remote/source_identity.py` (`parse_md5sum_output()`,
`three_way_diff()`, `aggregate_source_id()`) -- the same primitive
`tools/verification_flow/server_sync_identity_gate.py` already uses to verify
PC-vs-server identity, used here to COMPUTE A PUSH DELTA instead of to judge
a build gate. The remote manifest arrives through the same real-transcript
convention that gate established (`tools/verification_flow/_remote_transcript.py`
markers over a captured `remote_exec.py "md5sum ..."` stdout). The transport
is `tools/remote/remote_hop.py`'s already-documented whole-directory pattern
(tar -> `--put` -> `tar xzf`), narrowed to the diff set instead of the whole
tree. The audit record is `StateStore.event()`, the one real events.jsonl
every other "who changed what, when" view already reads.

WHAT COUNTS AS "THE HARNESS" IS DATA
------------------------------------
`harness_deploy.manifest.json`, beside this file -- same policy-as-data shape
as `context_budget.policy.json`. Extend the JSON for a project's own layout,
never this Python.

THREE SAFETY PROPERTIES, EACH ENFORCED IN CODE
-----------------------------------------------
1. **Never blind-overwrite.** The push set is `local_only | different` only.
   `remote_only` files are SURFACED as a required human decision and never
   deleted -- server-side drift could be a legitimate hotfix somebody made
   under deadline, or an accidental leftover, and this tool cannot tell which.
2. **Never ship a credential.** The manifest's `never_sync` list RAISES
   (`SecretPathRefusedError`) rather than silently skipping. This is not
   hypothetical: `replay.ps1` -- the real, gitignored (.gitignore:11),
   untracked local credential script CLAUDE.md's Remote Linux Execution
   amendment describes -- sits in this checkout's root, and the shared path
   this tool pushes to is used by multiple people.
3. **Never reach the network by accident.** `plan()` performs ZERO network
   calls by construction: it takes the remote side as either a local
   directory (`--target-root`, the synthetic-target mode that makes the whole
   tool unit-testable) or an already-captured transcript file. The remote
   apply path builds the command sequence and executes it only through an
   injected `run_fn`, defaulting to NOT executing at all unless `--execute` is
   passed -- so a LOCAL_ANALYSIS workflow can build and test this end to end
   without a live relay, exactly as this module's own tests do.
"""
from __future__ import annotations

import fnmatch
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# tools/remote/ is not an installed package -- this is the same sys.path
# convention dv_harness_tests/test_source_identity.py and
# tools/verification_flow/server_sync_identity_gate.py already use, not a
# second import mechanism.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "tools" / "remote") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools" / "remote"))
if str(_ROOT / "tools" / "verification_flow") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools" / "verification_flow"))

from source_identity import (  # noqa: E402
    aggregate_source_id,
    parse_md5sum_output,
    three_way_diff,
)

MANIFEST_PATH = Path(__file__).resolve().parent / "harness_deploy.manifest.json"

#: The one events.jsonl event name this subsystem writes, so "was the harness
#: actually synced, when, and what changed" is answerable from the real audit
#: trail `dv-harness audit` already surfaces.
EVENT_NAME = "HARNESS_DEPLOY_SYNC"

#: How many pushed paths an audit event inlines before truncating. A first
#: deployment pushes the whole harness (993 files in this repo as of
#: 2026-09-05), which would append ~100KB of paths to events.jsonl on a single
#: line -- a file `dv-harness audit` and the dashboard both read back. The
#: count, the truncation flag and both SOURCE_IDs are always recorded in full,
#: so "what exactly was synced" stays answerable (re-derivable from the
#: SOURCE_ID) while the trail stays readable.
EVENT_PATH_LIST_CAP = 50

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2
EXIT_REMOTE_ONLY_NEEDS_DECISION = 3


class HarnessDeployError(Exception):
    """Base for every refusal this module raises. `reason` is a
    SCREAMING_SNAKE_CASE code (same convention as
    `connectivity.ConnectivityError` subclasses and the verification_flow
    gates); `detail` is context a caller folds into its own payload."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {"status": "REFUSED", "reason": self.reason, **self.detail}


class ManifestError(HarnessDeployError):
    """Missing/unparseable/vacuous deploy manifest."""


class SecretPathRefusedError(HarnessDeployError):
    """A file matching the manifest's `never_sync` list was about to be
    included. Raised, never skipped -- see safety property 2 in the module
    docstring."""


class RemoteManifestError(HarnessDeployError):
    """The remote side could not be established from a real source."""


# ---- Manifest ---------------------------------------------------------------

@dataclass
class DeployManifest:
    """The declared answer to 'what IS the harness'. Every field comes from
    harness_deploy.manifest.json; this dataclass adds no policy of its own."""

    include: List[str]
    exclude: List[str] = field(default_factory=list)
    never_sync: List[str] = field(default_factory=list)
    remote_deployment_root: str = ""
    manifest_version: str = ""


def load_manifest(path=None) -> DeployManifest:
    p = Path(path) if path else MANIFEST_PATH
    if not p.is_file():
        raise ManifestError("HARNESS_DEPLOY_MANIFEST_NOT_FOUND", {"path": str(p)})
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(
            "HARNESS_DEPLOY_MANIFEST_UNPARSEABLE", {"path": str(p), "error": str(exc)}
        ) from exc
    if not isinstance(data, dict):
        raise ManifestError("HARNESS_DEPLOY_MANIFEST_NOT_AN_OBJECT", {"path": str(p)})
    include = data.get("include")
    if not isinstance(include, list) or not include:
        raise ManifestError(
            "HARNESS_DEPLOY_MANIFEST_HAS_NO_INCLUDE",
            {"path": str(p),
             "why": ("include is what defines the harness; with none declared the "
                     "computed push set would be empty and every sync would report "
                     "'already in sync' forever.")},
        )
    return DeployManifest(
        include=list(include),
        exclude=list(data.get("exclude") or []),
        never_sync=list(data.get("never_sync") or []),
        remote_deployment_root=str(data.get("remote_deployment_root") or ""),
        manifest_version=str(data.get("manifest_version") or ""),
    )


def _matches_any(rel_posix: str, patterns: List[str]) -> Optional[str]:
    """First matching pattern, or None. Matched against the project-root-
    relative POSIX path AND its bare basename, so a `never_sync` entry like
    "replay.ps1" catches the file wherever the include globs found it."""
    name = rel_posix.rsplit("/", 1)[-1]
    for pat in patterns:
        if fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(name, pat):
            return pat
    return None


def collect_local_files(project_root, manifest: DeployManifest) -> List[str]:
    """Every real file the manifest's include globs match, minus excludes, as
    sorted project-root-relative POSIX paths.

    Sorted so the resulting SOURCE_ID and push order are independent of
    filesystem enumeration order -- glob order differs between Windows and
    Linux, and this tool compares a Windows-side manifest with a Linux-side
    one for a living.

    Raises SecretPathRefusedError if any surviving file matches `never_sync`.
    The check runs HERE, at the single point every caller obtains its file
    list, rather than at each push site -- a deny list only one code path
    consults is a deny list waiting to be bypassed by the next code path."""
    root = Path(project_root)
    found = set()
    for pattern in manifest.include:
        for p in root.glob(pattern):
            if p.is_file():
                found.add(p.relative_to(root).as_posix())

    kept = []
    for rel in sorted(found):
        if _matches_any(rel, manifest.exclude):
            continue
        kept.append(rel)

    refused = [(rel, _matches_any(rel, manifest.never_sync)) for rel in kept]
    refused = [(rel, pat) for rel, pat in refused if pat]
    if refused:
        raise SecretPathRefusedError(
            "NEVER_SYNC_PATH_MATCHED",
            {"paths": [rel for rel, _ in refused],
             "patterns": sorted({pat for _, pat in refused}),
             "why": ("harness_deploy.manifest.json's never_sync list matched a file the "
                     "include globs picked up. The destination is a SHARED multi-user "
                     "deployment path; this refuses the whole sync rather than silently "
                     "dropping the file, so the operator fixes the include glob knowingly.")},
        )
    return kept


# ---- Local / remote manifests ----------------------------------------------

def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_local_manifest(project_root, files: List[str]) -> Dict[str, str]:
    """{relative posix path: md5}. md5 (not sha256) deliberately: the remote
    side is produced by GNU coreutils `md5sum` over the relay, and a manifest
    the two sides cannot compare is not a manifest."""
    root = Path(project_root)
    return {rel: _md5_file(root / rel) for rel in files}


def scan_target_root(target_root, manifest: DeployManifest) -> Dict[str, str]:
    """Remote-side manifest read from a LOCAL directory standing in for the
    remote deployment path. This is the synthetic-target mode that makes the
    whole tool testable with zero network calls, and it is also genuinely
    useful for a staging copy on a shared filesystem.

    `never_sync` is deliberately NOT enforced here: this side is being READ,
    not pushed, and a stray credential already sitting on the target is
    something the operator should SEE in `remote_only` rather than have the
    tool refuse to look at."""
    root = Path(target_root)
    if not root.is_dir():
        # Deliberately NOT auto-created. A typo'd --target-root that silently
        # becomes an empty directory reads as "the target has nothing" and
        # pushes the entire harness to the wrong place. Creating the intended
        # directory first is one command; recovering from a misdirected full
        # sync is not.
        raise RemoteManifestError(
            "TARGET_ROOT_NOT_A_DIRECTORY",
            {"target_root": str(root),
             "why": ("an absent target root is not treated as an empty one -- create the "
                     "directory first, or declare a first-ever deployment explicitly with "
                     "--assume-remote-empty.")},
        )
    out: Dict[str, str] = {}
    for pattern in manifest.include:
        for p in root.glob(pattern):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if _matches_any(rel, manifest.exclude):
                continue
            out[rel] = _md5_file(p)
    return out


def remote_md5sum_command(files: List[str], remote_root: str) -> str:
    """The exact command an agent runs to capture the remote side, using the
    sanctioned client only (`remote_exec.py`, never `remote_relay.py` -- see
    CLAUDE.md's standing rule). Its stdout, saved to a file, is what
    `parse_remote_transcript()` reads back.

    `cd`-then-relative-`md5sum` rather than absolute paths, so the parsed
    manifest keys are project-root-relative and line up with the local side
    without any path rewriting.

    An explicit file list rather than a `find`: it asks about exactly the
    manifest's files and nothing else, so a stray file on the server shows up
    as `remote_only` only when the manifest claims to own that path. The cost
    is command length -- ~993 paths is ~40KB of argv here, well inside Linux's
    ARG_MAX but worth knowing before adding a much larger include set."""
    joined = " ".join(files)
    return (
        f"python tools/remote/remote_exec.py --cwd {remote_root} "
        f"\"md5sum {joined}\""
    )


def parse_remote_transcript(path) -> Dict[str, str]:
    """Remote-side manifest from a REAL captured remote_exec.py transcript.

    The REMOTE_HOST=/EXIT_CODE=/STATUS= marker check is the shared
    `_remote_transcript.py` helper -- the same one
    server_sync_identity_gate.py and remote_execution_provenance_gate.py use
    -- so an inline string or a hand-written file cannot stand in for a real
    remote invocation, and a nonzero remote exit is a refusal rather than a
    manifest that silently looks like 'the server has nothing'."""
    from _remote_transcript import TranscriptError, parse_markers, read_transcript

    try:
        content = read_transcript(path)
        markers = parse_markers(content)
    except TranscriptError as exc:
        raise RemoteManifestError("REMOTE_" + exc.reason, dict(exc.detail)) from exc

    if markers["exit_code"] != 0:
        raise RemoteManifestError(
            "REMOTE_MD5SUM_NONZERO_EXIT",
            {"exit_code": markers["exit_code"], "path": str(path),
             "why": ("a failed remote md5sum yields a short/empty manifest, which would "
                     "read as 'the server is missing everything' and push the whole tree.")},
        )
    parsed = parse_md5sum_output(content)
    if not parsed:
        raise RemoteManifestError(
            "REMOTE_MD5SUM_MANIFEST_EMPTY",
            {"path": str(path),
             "why": ("an empty remote manifest is indistinguishable from a first-ever "
                     "deployment; declare that explicitly with --assume-remote-empty "
                     "rather than inferring it from an unparseable transcript.")},
        )
    return parsed


# ---- Plan -------------------------------------------------------------------

@dataclass
class DeployPlan:
    """The computed delta. `push` is the ONLY thing an apply ever writes."""

    push: List[str]
    remote_only: List[str]
    unchanged: List[str]
    local_only: List[str]
    different: List[str]
    local_source_id: str
    remote_source_id: str
    in_sync: bool
    line_ending_only: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "in_sync": self.in_sync,
            "push_count": len(self.push),
            "push": self.push,
            "local_only": self.local_only,
            "different": self.different,
            "remote_only": self.remote_only,
            "unchanged_count": len(self.unchanged),
            "line_ending_only_count": len(self.line_ending_only),
            "line_ending_only": self.line_ending_only,
            "local_source_id": self.local_source_id,
            "remote_source_id": self.remote_source_id,
            "remote_only_requires_human_decision": bool(self.remote_only),
        }


def build_plan(local_manifest: Dict[str, str], remote_manifest: Dict[str, str]) -> DeployPlan:
    """`three_way_diff()` (the real, tested primitive) turned into a push
    decision. push == local_only + different, sorted. remote_only is reported
    and NEVER acted on -- deleting it is a human decision this tool has no
    evidence to make."""
    diff = three_way_diff(local_manifest, remote_manifest)
    push = sorted(set(diff["local_only"]) | set(diff["different"]))
    unchanged = sorted(
        p for p in local_manifest
        if p in remote_manifest and local_manifest[p] == remote_manifest[p]
    )
    return DeployPlan(
        push=push,
        remote_only=list(diff["remote_only"]),
        unchanged=unchanged,
        local_only=list(diff["local_only"]),
        different=list(diff["different"]),
        local_source_id=aggregate_source_id(local_manifest),
        remote_source_id=aggregate_source_id(remote_manifest),
        in_sync=not push and not diff["remote_only"],
    )


def _line_ending_variant_md5s(path: Path) -> set:
    """This file's md5 under BOTH LF and CRLF line endings. Empty for a binary
    file, where line-ending normalization is meaningless and a NUL byte is the
    same cheap heuristic git itself uses to decide a blob is binary."""
    raw = path.read_bytes()
    if b"\0" in raw:
        return set()
    lf = raw.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    return {hashlib.md5(lf).hexdigest(), hashlib.md5(crlf).hexdigest()}


def classify_line_ending_only_differences(
    project_root, plan: DeployPlan, remote_manifest: Dict[str, str]
) -> DeployPlan:
    """Move files that differ ONLY by line endings out of `push`.

    THIS IS NOT COSMETIC. This repo's `core.autocrlf` is `true`, so the Windows
    working copy holds CRLF while git's own blobs (and therefore a
    `git clone`-populated `/home/svcacct/AI/Agent`, which is exactly how
    `docs/workflow/USAGE_MULTI_USER_SAFETY.md:37-39` and `docs/remote/REMOTE_LOGIN_GUIDE.md:34-38`
    describe that tree being created) hold LF. Verified on this checkout:
    `dv_harness/engine.py` hashes to 020fb26f... as CRLF and a14df5e9... as LF.
    Without this step EVERY text file in the harness lands in `different` on
    every plan, forever -- the tool would report ~950 files of permanent drift,
    re-push the entire harness on each run, and never once reach `in_sync`. A
    diff that is always maximal is not a diff.

    The raw three-way diff is still computed by the real
    `source_identity.three_way_diff()` and is never bypassed; this is a
    post-filter over its `different` set only, and it needs no remote content
    -- the remote md5 the transcript already carries is compared against both
    line-ending renderings of the LOCAL bytes. A file whose content ALSO
    changed matches neither rendering and stays in `push`, so a real edit is
    never mistaken for a line-ending artifact.

    `local_source_id`/`remote_source_id` are deliberately NOT recomputed: they
    are aggregates over the raw md5s and the raw bytes really do differ, so
    they stay honestly unequal even when `in_sync` is True. A reader seeing
    that pair disagree under `in_sync: true` is reading the correct fact --
    `line_ending_only_count` in the same payload is why."""
    if not plan.different:
        return plan
    root = Path(project_root)
    le_only = []
    for rel in plan.different:
        remote_md5 = remote_manifest.get(rel)
        if remote_md5 and remote_md5 in _line_ending_variant_md5s(root / rel):
            le_only.append(rel)
    if not le_only:
        return plan
    le_set = set(le_only)
    different = [p for p in plan.different if p not in le_set]
    push = [p for p in plan.push if p not in le_set]
    return DeployPlan(
        push=push,
        remote_only=plan.remote_only,
        # Same content, so `unchanged` is where these honestly belong.
        unchanged=sorted(plan.unchanged + le_only),
        local_only=plan.local_only,
        different=different,
        local_source_id=plan.local_source_id,
        remote_source_id=plan.remote_source_id,
        in_sync=not push and not plan.remote_only,
        line_ending_only=sorted(le_only),
    )


def plan_exit_code(plan: DeployPlan) -> int:
    """0 in sync; 3 when server-side drift needs a human; 1 when there is
    simply work to push. remote_only outranks push because it is the case a
    caller must not automate past."""
    if plan.remote_only:
        return EXIT_REMOTE_ONLY_NEEDS_DECISION
    return EXIT_DRIFT if plan.push else EXIT_OK


# ---- Transport --------------------------------------------------------------

def build_tarball(project_root, files: List[str], out_path) -> dict:
    """Package exactly the push set -- never the whole tree.

    `remote_hop.py`'s own module docstring establishes tar-then-`--put` as the
    sanctioned whole-directory transfer ("base64-over-telnet is ~400 bytes per
    round trip"); this narrows that recipe to the diff. Written with Python's
    `tarfile` rather than shelling out to `tar` so the local half works
    identically on the Windows PC side, where the harness actually lives.

    Members are stored under their project-root-relative POSIX paths, so a
    plain `tar xzf -C <remote_root>` lands each file exactly where its
    manifest key says it belongs.

    Byte-deterministic for identical content: per-member uid/gid/uname/gname/
    mtime are normalized, and the gzip wrapper is opened explicitly with
    mtime=0 and no stored filename (`tarfile.open(path, "w:gz")` would stamp
    the current time and the local tarball's own name into the gzip header,
    making two packs of identical content differ). That matters because the
    tarball name is derived from the SOURCE_ID of what it carries -- two packs
    of the same delta should be the same artifact."""
    root = Path(project_root)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with out.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w") as tf:
            for rel in files:
                src = root / rel
                info = tf.gettarinfo(str(src), arcname=rel)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                with src.open("rb") as fh:
                    tf.addfile(info, fh)
                total += src.stat().st_size
    return {"tarball": str(out), "file_count": len(files), "uncompressed_bytes": total,
            "tarball_bytes": out.stat().st_size}


def build_transport_commands(tarball_path, remote_root: str, *, remote_tarball_name: str) -> List[str]:
    """The real command sequence that lands a built tarball on the server.

    `remote_exec.py` only -- `remote_relay.py` (the credentialed leg) is never
    named here, per CLAUDE.md's standing rule that it must never be invoked
    from an agent tool call. Returned as data so `--execute`-less callers can
    print it for a human to run, and so a test can assert the sequence without
    any relay existing."""
    staging = f"{remote_root}/.harness_deploy"
    remote_tarball = f"{staging}/{remote_tarball_name}"
    return [
        f"python tools/remote/remote_exec.py \"mkdir -p {staging}\"",
        f"python tools/remote/remote_exec.py --put {tarball_path} {remote_tarball}",
        (f"python tools/remote/remote_exec.py --cwd {remote_root} "
         f"\"tar xzf {remote_tarball} -C {remote_root} && rm -f {remote_tarball}\""),
    ]


def _default_run_fn(command: str) -> tuple:
    """Real subprocess execution of one transport command. Only ever reached
    through `apply_via_remote_exec(execute=True)`; every test injects its own
    run_fn instead, which is why no test of this module can touch a relay."""
    proc = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=str(_ROOT))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def apply_to_local_target(project_root, target_root, plan: DeployPlan) -> dict:
    """Apply the push set to a LOCAL directory standing in for the remote
    deployment path. Real file copies, real directory creation -- this is a
    working deployment mode (a shared/staging filesystem target), not a
    simulation, which is exactly what makes the whole tool testable without a
    relay. `remote_only` files are left untouched."""
    src_root, dst_root = Path(project_root), Path(target_root)
    dst_root.mkdir(parents=True, exist_ok=True)
    copied = []
    for rel in plan.push:
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_root / rel, dst)
        copied.append(rel)
    return {"status": "APPLIED", "transport": "local_target_root",
            "target_root": str(dst_root), "copied": copied, "copied_count": len(copied),
            "remote_only_untouched": plan.remote_only}


def apply_via_remote_exec(
    project_root,
    plan: DeployPlan,
    remote_root: str,
    *,
    execute: bool = False,
    run_fn: Optional[Callable[[str], tuple]] = None,
    tarball_path=None,
) -> dict:
    """Build the tarball of the push set and (only with execute=True) run the
    transport sequence through remote_exec.py.

    execute defaults to FALSE: the tarball is built and the exact command
    sequence returned for a human or a separately-confirmed REMOTE_EXECUTION
    phase to run. That default is the structural reason a LOCAL_ANALYSIS
    workflow can build, wire and test this file end to end without ever
    reaching the live server."""
    if not plan.push:
        return {"status": "NOTHING_TO_PUSH", "transport": "remote_exec",
                "remote_root": remote_root, "commands": [], "executed": False,
                "remote_only_untouched": plan.remote_only}

    name = f"harness_deploy_{plan.local_source_id[:12]}.tgz"
    tarball_path = Path(tarball_path) if tarball_path else Path(tempfile.gettempdir()) / name
    pack = build_tarball(project_root, plan.push, tarball_path)
    commands = build_transport_commands(tarball_path, remote_root, remote_tarball_name=name)

    result = {"status": "PREPARED", "transport": "remote_exec", "remote_root": remote_root,
              "commands": commands, "executed": False,
              "remote_only_untouched": plan.remote_only, **pack}
    if not execute:
        result["why_not_executed"] = (
            "execute=False (the default). Run the printed commands from a session that has "
            "completed CLAUDE.md's SSH/Remote Transport Connection Intake, or re-invoke with "
            "--execute from such a session.")
        return result

    runner = run_fn or _default_run_fn
    transcripts = []
    for cmd in commands:
        code, out = runner(cmd)
        transcripts.append({"command": cmd, "exit_code": code, "stdout": out})
        if code != 0:
            result.update({"status": "TRANSPORT_FAILED", "executed": True,
                           "transcripts": transcripts, "failed_command": cmd})
            return result
    result.update({"status": "APPLIED", "executed": True, "transcripts": transcripts})
    return result


# ---- Audit trail ------------------------------------------------------------

def _cap_path_list(payload: dict, key: str) -> dict:
    """Inline at most EVENT_PATH_LIST_CAP paths for `key`, recording the true
    total and a truncation flag alongside. Applied to the event payload only
    -- the plan/apply JSON a caller reads on stdout is never truncated."""
    paths = payload.get(key)
    if not isinstance(paths, list) or len(paths) <= EVENT_PATH_LIST_CAP:
        return payload
    payload[key] = paths[:EVENT_PATH_LIST_CAP]
    payload[key + "_truncated"] = True
    payload[key + "_total"] = len(paths)
    return payload


def record_event(project_root, payload: dict, *, store=None) -> dict:
    """One HARNESS_DEPLOY_SYNC entry in the project's real
    `.dv-harness/events.jsonl`, via the same `StateStore.event()` every other
    audited action uses -- never a second parallel audit file. Best-effort,
    mirroring engine.py's `_promote_*`/`_record_*` convention: an audit-write
    failure must never turn an already-completed sync into a crash."""
    from .control_plane import now as cp_now

    payload = dict(payload)
    for key in ("pushed", "remote_only"):
        _cap_path_list(payload, key)
    event = {"ts": cp_now(), "event": EVENT_NAME, **payload}
    try:
        if store is None:
            from .storage import StateStore
            store = StateStore(Path(project_root))
        store.event(event)
        event["_recorded"] = True
    except Exception as exc:  # noqa: BLE001 -- audit must never break the sync
        event["_recorded"] = False
        event["_record_error"] = str(exc)
    return event


# ---- Orchestration ----------------------------------------------------------

def resolve_remote_manifest(
    manifest: DeployManifest,
    *,
    target_root=None,
    remote_md5sum_transcript=None,
    assume_remote_empty: bool = False,
) -> tuple:
    """Establish the remote side from exactly one real source. Returns
    (manifest_dict, source_label).

    A first-ever deployment must be DECLARED (`assume_remote_empty`), never
    inferred from a missing file -- otherwise a typo'd transcript path would
    silently become "the server has nothing" and push everything."""
    supplied = [bool(target_root), bool(remote_md5sum_transcript), bool(assume_remote_empty)]
    if sum(supplied) != 1:
        raise RemoteManifestError(
            "REMOTE_SIDE_NOT_UNAMBIGUOUSLY_SPECIFIED",
            {"target_root": str(target_root) if target_root else None,
             "remote_md5sum_transcript": str(remote_md5sum_transcript) if remote_md5sum_transcript else None,
             "assume_remote_empty": assume_remote_empty,
             "why": "supply exactly one of --target-root / --remote-md5sum-transcript / --assume-remote-empty"},
        )
    if target_root:
        return scan_target_root(target_root, manifest), f"target_root:{target_root}"
    if remote_md5sum_transcript:
        return parse_remote_transcript(remote_md5sum_transcript), f"transcript:{remote_md5sum_transcript}"
    return {}, "assumed_remote_empty"


def run_plan(
    project_root,
    *,
    manifest: Optional[DeployManifest] = None,
    target_root=None,
    remote_md5sum_transcript=None,
    assume_remote_empty: bool = False,
    strict_line_endings: bool = False,
) -> tuple:
    """Compute the plan. ZERO network calls by construction -- both remote
    sources are local reads. Returns (plan, context).

    `strict_line_endings=True` skips `classify_line_ending_only_differences()`
    and reports the raw byte diff. Off by default because on this
    `core.autocrlf=true` checkout the raw diff against a git-cloned Linux tree
    is every text file, every time."""
    manifest = manifest or load_manifest()
    files = collect_local_files(project_root, manifest)
    local = compute_local_manifest(project_root, files)
    remote, source = resolve_remote_manifest(
        manifest,
        target_root=target_root,
        remote_md5sum_transcript=remote_md5sum_transcript,
        assume_remote_empty=assume_remote_empty,
    )
    plan = build_plan(local, remote)
    if not strict_line_endings:
        plan = classify_line_ending_only_differences(project_root, plan, remote)
    context = {"remote_source": source, "local_file_count": len(files),
               "remote_file_count": len(remote),
               "line_ending_tolerant": not strict_line_endings,
               "manifest_version": manifest.manifest_version,
               "remote_deployment_root": manifest.remote_deployment_root}
    return plan, context


def execute_verb(
    project_root,
    verb: str,
    *,
    manifest_path=None,
    target_root=None,
    remote_md5sum_transcript=None,
    assume_remote_empty: bool = False,
    remote_root=None,
    execute: bool = False,
    print_md5sum_command: bool = False,
    strict_line_endings: bool = False,
    store=None,
    run_fn: Optional[Callable[[str], tuple]] = None,
) -> tuple:
    """The single implementation of what a `harness-deploy` invocation DOES,
    shared by both front doors -- `dv-harness harness-deploy` (cli.py) and
    `python -m dv_harness.harness_deploy` (main() below).

    Returns (exit_code, payload). Deliberately one function rather than the
    same orchestration written twice: this project's standing rule is that a
    second parallel mechanism for one behavior is a defect, and two CLI
    handlers that drift apart is exactly that failure at CLI scale. Raises
    nothing -- a HarnessDeployError becomes (EXIT_ERROR, refusal payload), so
    both callers report a refusal identically."""
    root = Path(project_root)
    try:
        manifest = load_manifest(manifest_path)
        effective_remote_root = remote_root or manifest.remote_deployment_root

        if verb == "manifest":
            files = collect_local_files(root, manifest)
            local = compute_local_manifest(root, files)
            payload = {"manifest_version": manifest.manifest_version,
                       "remote_deployment_root": effective_remote_root,
                       "file_count": len(files), "files": files,
                       "local_source_id": aggregate_source_id(local)}
            if print_md5sum_command:
                payload["remote_md5sum_command"] = remote_md5sum_command(files, effective_remote_root)
            return EXIT_OK, payload

        plan, context = run_plan(
            root, manifest=manifest, target_root=target_root,
            remote_md5sum_transcript=remote_md5sum_transcript,
            assume_remote_empty=assume_remote_empty,
            strict_line_endings=strict_line_endings)

        if verb == "plan":
            return plan_exit_code(plan), {"status": "PLANNED", **context, **plan.to_dict()}

        if target_root:
            result = apply_to_local_target(root, target_root, plan)
        else:
            result = apply_via_remote_exec(root, plan, effective_remote_root,
                                           execute=execute, run_fn=run_fn)
        record_event(root, {"verb": "apply", "remote_source": context["remote_source"],
                            "remote_root": effective_remote_root, "status": result["status"],
                            "executed": bool(result.get("executed", target_root is not None)),
                            "pushed_count": len(plan.push), "pushed": plan.push,
                            "remote_only": plan.remote_only,
                            # Recorded so the trail explains a small push set:
                            # without it, "993 local files, 0 pushed" reads as a
                            # no-op rather than as line-ending-only agreement.
                            "line_ending_only_count": len(plan.line_ending_only),
                            "line_ending_tolerant": context["line_ending_tolerant"],
                            "local_source_id": plan.local_source_id,
                            "remote_source_id": plan.remote_source_id},
                     store=store)
        code = EXIT_OK if result["status"] in ("APPLIED", "NOTHING_TO_PUSH", "PREPARED") else EXIT_ERROR
        return code, {**context, **result}

    except HarnessDeployError as exc:
        return EXIT_ERROR, exc.to_dict()


# ---- CLI --------------------------------------------------------------------

def _print(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv: Optional[list] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.harness_deploy",
        description="Sync this harness checkout to the shared Linux Agent deployment path.")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--manifest", default=None, help="Override harness_deploy.manifest.json")
    sub = ap.add_subparsers(dest="verb", required=True)

    p_man = sub.add_parser("manifest", help="Print the resolved file set and local SOURCE_ID. No remote side needed.")
    p_man.add_argument("--print-md5sum-command", action="store_true",
                       help="Also print the remote_exec.py md5sum command that captures the remote side.")
    p_man.add_argument("--remote-root", default=None)

    for name, helptext in (("plan", "Compute the push delta. Zero network calls."),
                           ("apply", "Push the delta. Local target by default; --execute required for the relay.")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--target-root", default=None,
                        help="A local directory standing in for the remote deployment path.")
        sp.add_argument("--remote-md5sum-transcript", default=None,
                        help="A captured `remote_exec.py \"md5sum ...\"` stdout transcript.")
        sp.add_argument("--assume-remote-empty", action="store_true",
                        help="Declare a first-ever deployment explicitly.")
        sp.add_argument("--remote-root", default=None)
        sp.add_argument("--strict-line-endings", action="store_true",
                        help="Report the raw byte diff, without treating a CRLF-vs-LF-only "
                             "difference as unchanged.")
        if name == "apply":
            sp.add_argument("--execute", action="store_true",
                            help="Actually run the remote_exec.py transport sequence. Requires a session "
                                 "that has completed the SSH/Remote Transport Connection Intake.")

    a = ap.parse_args(argv)
    code, payload = execute_verb(
        Path(a.project_root).resolve(), a.verb,
        manifest_path=a.manifest,
        target_root=getattr(a, "target_root", None),
        remote_md5sum_transcript=getattr(a, "remote_md5sum_transcript", None),
        assume_remote_empty=getattr(a, "assume_remote_empty", False),
        remote_root=getattr(a, "remote_root", None),
        execute=getattr(a, "execute", False),
        print_md5sum_command=getattr(a, "print_md5sum_command", False),
        strict_line_endings=getattr(a, "strict_line_endings", False))
    _print(payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
