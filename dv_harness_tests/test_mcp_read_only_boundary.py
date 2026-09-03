"""Read-only boundary tests for dv_harness/mcp/ -- statically proves (via
AST, mirroring the scope-enforcement test style
dv_harness_tests/test_vip_distill.py already established for
dv_harness/vip_distill.py's own narrow scope --
test_module_does_not_import_orchestration_or_memory_modules()) that no code
path in this package can mutate env.manifest.json, the evidence DB, or any
RTL/testbench file, PLUS a behavioral proof that invoking every verb
(success paths AND error paths) leaves a real manifest file and a real
evidence DB byte-for-byte unchanged.

"Prove the boundary, don't just document it" (per this task's own brief,
quoting the vip_distill precedent) -- so this file does not just assert
"insert_regression_verdict is never called anywhere in this package's
source", it separately proves via SHA-256 hash comparison that a real
on-disk manifest file and a real on-disk evidence.duckdb file are literally
unchanged after every verb (including deliberately-malformed/unknown-verb
calls) has actually run against them."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("jsonschema")

MCP_PKG_DIR = Path(__file__).resolve().parents[1] / "dv_harness" / "mcp"

# Every real WRITE-capable method this package's real dependencies expose:
# EvidenceStore's own insert_*/close-adjacent write API (evidence_db.py),
# plus generic filesystem/DB mutation call names. A hit on ANY of these
# anywhere under dv_harness/mcp/ fails the test -- there is no legitimate
# reason for this package to ever call one.
FORBIDDEN_CALL_NAMES = {
    # filesystem mutation
    "write_text", "write_bytes", "unlink", "rmdir", "rmtree", "remove",
    "rename", "replace", "mkdir", "copy", "copyfile", "move", "touch",
    # EvidenceStore's real write API (dv_harness/evidence_db.py) + the raw
    # connection-execute escape hatch this package must never reach for
    # (regression_queries.py only ever calls the read-only
    # EvidenceStore.query() wrapper, never `._conn.execute()` directly)
    "insert_job_state", "insert_job_memory_record", "insert_regression_verdict",
    "insert_coverage_sample", "insert_rtl_parse", "insert_normalized_evidence",
    "execute", "executemany", "commit",
}

FORBIDDEN_IMPORTED_MODULES = {"shutil", "subprocess"}


def _iter_mcp_source_files():
    return sorted(MCP_PKG_DIR.rglob("*.py"))


def test_mcp_package_has_source_files_to_scan():
    files = _iter_mcp_source_files()
    assert files, f"expected .py files under {MCP_PKG_DIR}"
    assert any(f.name == "verbs.py" for f in files)


@pytest.mark.parametrize("path", _iter_mcp_source_files(), ids=lambda p: p.name)
def test_no_write_capable_call_anywhere_in_mcp_package(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None)
        if fname in FORBIDDEN_CALL_NAMES:
            hits.append(f"{path.name}:{node.lineno}: {fname}(...)")
        if fname == "open":
            mode_args = list(node.args)[1:2] + [kw.value for kw in node.keywords if kw.arg == "mode"]
            for arg in mode_args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if any(m in arg.value for m in ("w", "a", "x", "+")):
                        hits.append(f"{path.name}:{node.lineno}: open(..., mode={arg.value!r})")
    assert not hits, f"write-capable call(s) found: {hits}"


@pytest.mark.parametrize("path", _iter_mcp_source_files(), ids=lambda p: p.name)
def test_no_write_or_exec_capable_imports(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
            imported.update(a.name for a in node.names)
    hit = imported & FORBIDDEN_IMPORTED_MODULES
    assert not hit, f"{path} imports a write/exec-capable module: {hit}"


def test_regression_queries_module_defines_no_function_named_like_a_write():
    """Belt-and-suspenders on top of the generic call-name scan above:
    confirm no function DEFINED in regression_queries.py itself is named
    anything insert/update/delete/write-shaped, so a future edit can't
    quietly add a same-module write helper that the forbidden-call-name
    list above wouldn't catch (it only catches CALLS, not definitions)."""
    path = MCP_PKG_DIR / "regression_queries.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    write_shaped = [
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(w in node.name.lower() for w in ("insert", "update", "delete", "write", "mutate"))
    ]
    assert not write_shaped, f"write-shaped function definition(s) found: {write_shaped}"


# ---- behavioral proof: real files, byte-identical before/after --------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_calling_every_verb_success_and_error_paths_leaves_files_byte_identical(tmp_path):
    from dv_harness.evidence_db import EvidenceStore
    from dv_harness.mcp.errors import McpError
    from dv_harness.mcp.runtime import ReadOnlyMcpContext

    from .mcp_manifest_fixture import build_fixture_manifest

    manifest_path = tmp_path / "env.manifest.json"
    manifest_path.write_text(
        json.dumps(build_fixture_manifest(), indent=2, sort_keys=True), encoding="utf-8")

    db_path = tmp_path / "evidence.duckdb"
    store = EvidenceStore(db_path)
    store.insert_regression_verdict("usb3_lfps_basic", True, job_id=1)
    store.close()

    before_manifest_hash = _sha256(manifest_path)
    before_db_hash = _sha256(db_path)

    ctx = ReadOnlyMcpContext(manifest_path, db_path)

    # Real, successful calls across all 5 verbs.
    ctx.call("get_vip_config", {})
    ctx.call("get_dut_port", {"module_name": "usb3_top"})
    ctx.call("get_dut_port", {"module_name": "totally_absent_module"})  # NOT_FOUND path
    ctx.call("get_register", {})
    ctx.call("get_topology", {})
    ctx.call("query_regression", {"query_shape": "latest", "limit": 5})

    # Deliberate error/edge attempts -- an unknown verb, malformed params,
    # and a SQL-injection-shaped query_shape string -- must all raise
    # WITHOUT writing anything either.
    for bad_verb, bad_params in [
        ("delete_register", {}),
        ("get_register", {"unexpected_field": 1}),
        ("query_regression", {"query_shape": "'; DROP TABLE regression_verdicts; --"}),
    ]:
        try:
            ctx.call(bad_verb, bad_params)
        except McpError:
            pass

    assert _sha256(manifest_path) == before_manifest_hash, "env.manifest.json was mutated"
    assert _sha256(db_path) == before_db_hash, "evidence.duckdb was mutated"


def test_evidence_db_row_count_unchanged_after_every_verb_call(tmp_path):
    """A second, independent proof alongside the byte-hash check above:
    counts the REAL row count in every EvidenceStore table before and after
    driving every verb, using EvidenceStore.query() itself (the same
    read-only surface this package is scoped to).

    Seeding `store` is closed BEFORE `ctx` (the read-only context under
    test) ever opens the same file, and a fresh EvidenceStore is opened to
    read `after` -- 2026-09-03 gap fix note: this is a real, load-bearing
    ordering, not incidental cleanup. Now that ReadOnlyMcpContext genuinely
    opens `read_only=True` (see runtime.py), DuckDB itself refuses to open
    a second same-process connection to one file with a DIFFERENT access
    mode than an already-open connection to that same file
    (`duckdb.ConnectionException: ... different configuration than
    existing connections`) -- so a still-open read-write `store` handle
    would make every `ctx.call()` below fail, not silently fall back to
    read-write access."""
    from dv_harness.evidence_db import EvidenceStore
    from dv_harness.mcp.runtime import ReadOnlyMcpContext

    from .mcp_manifest_fixture import build_fixture_manifest

    manifest_path = tmp_path / "env.manifest.json"
    manifest_path.write_text(json.dumps(build_fixture_manifest()), encoding="utf-8")

    db_path = tmp_path / "evidence.duckdb"
    TABLES = ("jobs", "job_memory_records", "regression_verdicts",
              "coverage_samples", "failure_signatures", "rtl_modules",
              "normalized_evidence")

    def _counts(s):
        return {table: s.query(f"SELECT count(*) FROM {table}")[0][0] for table in TABLES}

    store = EvidenceStore(db_path)
    store.insert_regression_verdict("usb3_lfps_basic", True, job_id=1)
    store.insert_regression_verdict("apb_smoke", False, job_id=2)
    before = _counts(store)
    store.close()

    ctx = ReadOnlyMcpContext(manifest_path, db_path)
    for _ in range(3):
        ctx.call("query_regression", {"query_shape": "latest", "limit": 100})
        ctx.call("query_regression", {"query_shape": "by_pattern", "pattern": "usb3_lfps_basic"})

    verify_store = EvidenceStore(db_path)
    after = _counts(verify_store)
    verify_store.close()

    assert before == after
    assert after["regression_verdicts"] == 2


# ---- 2026-09-03 gap fix: real read-only-open behavior, not merely a real DB
# that happened to be fully seeded already ----------------------------------
#
# The two byte-identical tests above both pre-seed db_path via a real
# EvidenceStore(db_path) BEFORE ever constructing a ReadOnlyMcpContext -- by
# the time either test compares hashes, the full schema already exists, so
# the CREATE TABLE/SEQUENCE IF NOT EXISTS statements the OLD (buggy)
# ReadOnlyMcpContext ran were all no-ops. Neither test ever drove
# query_regression against a path with NO existing file, or against a file
# with only a PARTIAL schema -- exactly the two states in which the old
# `EvidenceStore(self.evidence_db_path)` call (no read_only=True) proved to
# mkdir() a directory, create a fresh 536KB file, and/or add up to 9 missing
# tables. These two tests close that exact gap: they exercise the real
# `ReadOnlyMcpContext` end to end (not EvidenceStore directly) against both
# states and prove no filesystem/schema mutation happens in either.

def test_query_regression_against_nonexistent_db_creates_no_directory_or_file(tmp_path):
    """Reproduces the reviewer's exact first repro against the FIXED code:
    a `db_path` under a directory that does not exist yet, with NOTHING
    ever having created it. Confirms (a) no directory is created, (b) no
    file is created, (c) a clean result is returned -- not an unhandled
    duckdb.IOException reaching the caller."""
    from dv_harness.mcp.runtime import ReadOnlyMcpContext

    missing_dir = tmp_path / "does_not_exist_yet"
    db_path = missing_dir / "evidence.duckdb"
    manifest_path = tmp_path / "env.manifest.json"  # never read for query_regression

    assert not missing_dir.exists()
    assert not db_path.exists()

    ctx = ReadOnlyMcpContext(manifest_path, db_path)
    result = ctx.call("query_regression", {"query_shape": "latest", "limit": 5})

    assert not missing_dir.exists(), "query_regression against a missing DB created its parent directory"
    assert not db_path.exists(), "query_regression against a missing DB created the DB file"
    assert result == {
        "verb": "query_regression",
        "status": "NOT_AVAILABLE",
        "reason": f"no evidence database exists yet at {db_path}",
        "query_shape": "latest",
        "row_count": 0,
        "rows": [],
    }


def test_query_regression_against_partial_schema_db_adds_no_tables_stays_byte_identical(tmp_path):
    """Reproduces the reviewer's exact second repro against the FIXED code:
    a REAL, pre-existing evidence.duckdb that was seeded with only ONE of
    the real schema's tables (never through EvidenceStore, which would have
    created all of them) -- the exact "partial-schema DB" gap the review
    found the existing byte-identical test never exercised. Confirms the
    file's own SHA-256 hash and its table list are unchanged after driving
    every verb (including several query_regression shapes) through the real
    ReadOnlyMcpContext."""
    from dv_harness.mcp.runtime import ReadOnlyMcpContext

    from .mcp_manifest_fixture import build_fixture_manifest

    manifest_path = tmp_path / "env.manifest.json"
    manifest_path.write_text(
        json.dumps(build_fixture_manifest(), indent=2, sort_keys=True), encoding="utf-8")

    db_path = tmp_path / "evidence.duckdb"
    # Seed via a RAW duckdb connection, matching only regression_verdicts'
    # real column shape from evidence_db.py's _SCHEMA_STATEMENTS --
    # deliberately NOT via EvidenceStore(db_path), which would create every
    # one of the real schema's other 8 tables too and defeat the point of
    # this test.
    raw = duckdb.connect(str(db_path))
    raw.execute("""CREATE TABLE regression_verdicts (
        pattern VARCHAR PRIMARY KEY,
        verdict_passed BOOLEAN,
        job_id BIGINT,
        recorded_at TIMESTAMP DEFAULT now()
    )""")
    raw.execute(
        "INSERT INTO regression_verdicts (pattern, verdict_passed, job_id, recorded_at) "
        "VALUES (?, ?, ?, now())",
        ["usb3_lfps_basic", True, 1],
    )
    raw.close()

    def _tables():
        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            return sorted(r[0] for r in conn.execute("SHOW TABLES").fetchall())
        finally:
            conn.close()

    before_tables = _tables()
    assert before_tables == ["regression_verdicts"], "test setup did not produce the intended partial schema"
    before_hash = _sha256(db_path)

    ctx = ReadOnlyMcpContext(manifest_path, db_path)
    ctx.call("get_vip_config", {})
    ctx.call("get_dut_port", {"module_name": "usb3_top"})
    ctx.call("get_register", {})
    ctx.call("get_topology", {})
    for query_shape, extra in [
        ("latest", {"limit": 5}),
        ("by_pattern", {"pattern": "usb3_lfps_basic"}),
        ("by_verdict", {"verdict_passed": True}),
    ]:
        result = ctx.call("query_regression", {"query_shape": query_shape, **extra})
        assert result["status"] == "OK"
        assert result["row_count"] == 1

    after_hash = _sha256(db_path)
    after_tables = _tables()
    assert after_hash == before_hash, "a partial-schema evidence.duckdb was mutated by ReadOnlyMcpContext"
    assert after_tables == before_tables, (
        f"ReadOnlyMcpContext added table(s) to a partial-schema DB: "
        f"before={before_tables} after={after_tables}")
