"""L5DGVA canonical-repository identity, root discovery and the wrong-repository guard (M1A-2).

Motivation (see M0_5_M1_BOOTSTRAP_PREREQUISITES.md #4 and the M0.5 dual-repo
divergence root cause): the parent/v50 divergence this migration exists to
fix was caused by Claude Code sessions being launched from an inconsistent
working directory over several weeks. This module makes "which directory is
the real L5DGVA canonical repository" a checkable fact instead of an
assumption baked into whatever directory a session happens to start in.

Identity is carried by ONE marker file: ``.l5dgva/repository.json``, whose
*presence and content* -- never the absolute filesystem path it lives at --
is what makes a directory the L5DGVA canonical repository. A directory may
be freely copied, cloned, moved or renamed to any path or basename without
invalidating discovery (see
test_repository_identity_does_not_encode_the_bootstrap_absolute_path_as_identity
and test_discover_repo_root_does_not_require_directory_basename_L5_DGVA in
dv_harness_tests/test_l5dgva_repo.py). ``bootstrap.bootstrap_source_head`` in
that file is historical provenance only -- nothing here reads it to derive
a path.

Two runtime modes (Final Canonical Platform Architecture Freeze / M0.5 #4):
DEVELOPER_MODE (a real ``.git`` directory is present) and
DEPLOYMENT_COPY_MODE (git absent -- e.g. an extracted archive with no git
history). Neither mode is treated as more "real" than the other; callers
that need git (e.g. provenance tooling) must check the mode first rather
than assuming git is always available.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional, Union

MARKER_DIR_NAME = ".l5dgva"
MARKER_FILE_NAME = "repository.json"
PRODUCT_IDENTITY = "L5DGVA"

DEVELOPER_MODE = "DEVELOPER_MODE"
DEPLOYMENT_COPY_MODE = "DEPLOYMENT_COPY_MODE"


class L5DGVARepositoryNotFoundError(RuntimeError):
    """Raised when no valid L5DGVA repository marker is found walking up
    from the given start path, or when a marker is found but fails
    identity validation (wrong ``product_identity``)."""


class WrongL5RepositoryError(RuntimeError):
    """Raised by :func:`assert_l5dgva_repo` when the given path is not
    inside any L5DGVA canonical repository.

    ``.condition`` is the stable, machine-readable string
    ``'WRONG_L5_REPOSITORY'`` -- the guard condition named in the Final
    Canonical Platform Architecture Freeze -- so a caller can branch on it
    without parsing prose.
    """

    condition = "WRONG_L5_REPOSITORY"


def _marker_path(candidate: Path) -> Path:
    return candidate / MARKER_DIR_NAME / MARKER_FILE_NAME


def _read_identity(marker_file: Path) -> Optional[dict]:
    try:
        data = json.loads(marker_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def discover_repo_root(start_path: Union[str, Path], validate: bool = False) -> Path:
    """Walk up from ``start_path`` looking for ``.l5dgva/repository.json``.

    Returns the first ancestor (inclusive of ``start_path`` itself) that
    contains the marker. Never consults the directory's own basename or
    any absolute-path convention -- only the marker file's presence (and,
    if ``validate=True``, its ``product_identity`` field) decides the
    result.

    Raises :class:`L5DGVARepositoryNotFoundError` if no marker is found
    before reaching the filesystem root, or if ``validate=True`` and the
    nearest marker's ``product_identity`` is not ``'L5DGVA'``.
    """
    current = Path(start_path).resolve()
    for candidate in (current, *current.parents):
        marker_file = _marker_path(candidate)
        if marker_file.is_file():
            if validate:
                identity = _read_identity(marker_file)
                if not identity or identity.get("product_identity") != PRODUCT_IDENTITY:
                    raise L5DGVARepositoryNotFoundError(
                        "Marker found at %s but product_identity is not '%s' "
                        "(found %r)." % (marker_file, PRODUCT_IDENTITY,
                                          (identity or {}).get("product_identity"))
                    )
            return candidate
    raise L5DGVARepositoryNotFoundError(
        "No %s/%s marker found walking up from %s to the filesystem root."
        % (MARKER_DIR_NAME, MARKER_FILE_NAME, current)
    )


def load_repository_identity(root: Union[str, Path]) -> dict:
    """Load and return the parsed ``.l5dgva/repository.json`` at ``root``.

    Raises :class:`L5DGVARepositoryNotFoundError` if the marker is
    missing, unparseable, or declares a ``product_identity`` other than
    ``'L5DGVA'``.
    """
    marker_file = _marker_path(Path(root))
    identity = _read_identity(marker_file) if marker_file.is_file() else None
    if not identity:
        raise L5DGVARepositoryNotFoundError(
            "No valid %s/%s marker at %s." % (MARKER_DIR_NAME, MARKER_FILE_NAME, root)
        )
    if identity.get("product_identity") != PRODUCT_IDENTITY:
        raise L5DGVARepositoryNotFoundError(
            "Marker at %s declares product_identity %r, expected %r."
            % (marker_file, identity.get("product_identity"), PRODUCT_IDENTITY)
        )
    return identity


def detect_mode(root: Union[str, Path]) -> str:
    """DEVELOPER_MODE if ``root/.git`` exists, else DEPLOYMENT_COPY_MODE.

    A plain existence check, not a git invocation -- so this never fails
    or blocks even where git itself is unavailable on PATH.
    """
    return DEVELOPER_MODE if (Path(root) / ".git").exists() else DEPLOYMENT_COPY_MODE


def cross_check_git_root(root: Union[str, Path]) -> dict:
    """Compare the marker-discovered root against git's own idea of the
    repository top level (``git rev-parse --show-toplevel``).

    Returns a dict with a ``"status"`` key:
      - ``"MATCH"``: git agrees with the marker-discovered root.
      - ``"MISMATCH"``: git reports a different top level (real divergence
        risk -- exactly the class of bug this module exists to catch).
      - ``"GIT_CAPABILITY_UNAVAILABLE"``: DEPLOYMENT_COPY_MODE (no
        ``.git``) or the ``git`` executable itself could not be invoked --
        an honest capability gap, never treated as a MATCH by default.
    """
    root = Path(root).resolve()
    if detect_mode(root) != DEVELOPER_MODE:
        return {"status": "GIT_CAPABILITY_UNAVAILABLE", "reason": "no .git directory (DEPLOYMENT_COPY_MODE)"}
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root, capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"status": "GIT_CAPABILITY_UNAVAILABLE", "reason": str(exc)}
    git_root = Path(proc.stdout.strip()).resolve()
    if git_root == root:
        return {"status": "MATCH", "git_root": str(git_root)}
    return {"status": "MISMATCH", "git_root": str(git_root), "marker_root": str(root)}


def is_l5dgva_repo(path: Union[str, Path]) -> bool:
    """Non-raising boolean check: is ``path`` inside a valid L5DGVA repository?"""
    try:
        discover_repo_root(path, validate=True)
        return True
    except L5DGVARepositoryNotFoundError:
        return False


def assert_l5dgva_repo(path: Union[str, Path]) -> None:
    """Raise :class:`WrongL5RepositoryError` (condition ``WRONG_L5_REPOSITORY``)
    if ``path`` is not inside a valid L5DGVA canonical repository.

    Intended as the standing session/CLI-entry guard: call this before
    trusting that "here" is the canonical repository, rather than
    assuming it from the current working directory's path or name.
    """
    try:
        discover_repo_root(path, validate=True)
    except L5DGVARepositoryNotFoundError as exc:
        raise WrongL5RepositoryError(
            "%s is not inside any L5DGVA canonical repository: %s" % (path, exc)
        ) from exc
