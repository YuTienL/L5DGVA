"""Connection tests for the two Evidence-Layer edges the architecture
diagram draws but that had no live call site in code before 2026-09-04:

    FSDB    -> Distillation -> vip_distill.py -> DuckDB
    verible -> parsers                        -> DuckDB

Both halves of each edge were already real and unit-tested in isolation
(`vip_distill.distill_fsdbreport()`, `evidence_db.insert_rtl_parse()`,
`verible_parser.run_export_json()`), and both halves stayed unit-tested in
isolation forever, because nothing outside a test body ever called them
together -- a repo-wide grep for `distill_fsdbreport` and `insert_rtl_parse`
hit only their own definitions, docstrings and test files, and
.work/evidence-db-wiring-step1-report.md / step2-report.md both listed
`insert_rtl_parse` explicitly as "remains unwired".

So these tests deliberately do NOT re-test either half. Every test here
drives the REAL production entry point end to end -- `dv_harness.cli.main()`
for the actual `dv-harness fsdb-report` / `dv-harness env-manifest generate`
commands -- and then asserts a real row is queryable back out of a real
DuckDB file on disk. A test that passed while the CLI branch was deleted
would prove nothing about the edge, which is exactly the failure mode the
pre-2026-09-04 unit tests had.

What is real here vs. substituted, stated honestly:
  - verible: REAL. `verible-verilog-syntax` is installed on this machine, so
    the env-manifest tests run the real subprocess against a synthesized
    minimal .sv fixture (never proprietary project RTL -- CLAUDE.md's
    No Golden-Reference Content Mining rule). Skipped, never faked, when the
    binary is absent.
  - DuckDB: REAL. A real `.dv-harness/evidence/evidence.duckdb` file is
    created on disk under tmp_path and read back with real SQL.
  - vip_distill / fsdb_report parsing / evidence_db: REAL, unmodified.
  - `fsdbreport` itself: SUBSTITUTED, and only this. It is a proprietary
    Synopsys Verdi binary that exists only on the Linux DV server (see
    fsdb_report.py's own module docstring: "This machine has no Verdi/
    fsdbreport install"). `run_fsdbreport` is replaced with one returning
    real-shaped CSV report text; everything downstream of it -- the CSV
    parse, the distillation, the envelope, the DuckDB write -- is the real
    code path.
"""
from __future__ import annotations

import json
import shutil
import sys
import textwrap

import pytest

import dv_harness.cli as cli_mod
from dv_harness import evidence_db, fsdb_report

duckdb = pytest.importorskip("duckdb")

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

# Real fsdbreport `-csv` output shape: a header row plus data rows, which is
# exactly what parse_fsdbreport_output() structures (it never hardcodes
# column names -- whatever header a real run emits becomes the field names).
FSDB_CSV_TEXT = "signal,time,value\nu_dut.lfps_det,100,0\nu_dut.lfps_det,250,1\n"

FIFO_FIXTURE = textwrap.dedent("""\
    module lfps_detect #(
        parameter int WIDTH = 8
    ) (
        input  logic             clk,
        input  logic             rst_n,
        input  logic [WIDTH-1:0] rx_data,
        output logic             lfps_seen
    );

        logic [WIDTH-1:0] shadow;

        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) shadow <= '0;
            else        shadow <= rx_data;
        end

        assign lfps_seen = |shadow;

    endmodule
    """)


def _run_cli(monkeypatch, tmp_path, args, capsys):
    monkeypatch.setattr(sys, "argv", ["dv-harness", "--project-root", str(tmp_path)] + args)
    try:
        rc = cli_mod.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    return (rc if rc is not None else 0), out


def _open_store(tmp_path):
    """Opens the REAL evidence DB the CLI run just created, at the real
    default path -- not a path this test chose. If the CLI wrote nowhere,
    this fails, which is the point."""
    db_path = evidence_db.default_db_path(tmp_path)
    assert db_path.exists(), f"the CLI run created no evidence DB at {db_path}"
    return evidence_db.EvidenceStore(db_path, read_only=True)


def _fake_fsdbreport(monkeypatch, report_text=FSDB_CSV_TEXT):
    monkeypatch.setattr(
        fsdb_report, "run_fsdbreport",
        lambda *a, **k: {"ok": True, "report_text": report_text, "stderr": ""})


# ===========================================================================
# FSDB -> Distillation -> vip_distill.py -> DuckDB
# ===========================================================================

def test_cli_fsdb_report_lands_a_normalized_evidence_row_in_duckdb(monkeypatch, tmp_path, capsys):
    """THE edge. Before this wiring, `dv-harness fsdb-report` printed JSON
    and touched the evidence store not at all; distill_fsdbreport() had zero
    live callers. This asserts the real command now produces a real,
    queryable `normalized_evidence` row with source_kind='fsdbreport'."""
    fsdb = tmp_path / "dump.fsdb"
    fsdb.write_bytes(b"\x00fake fsdb bytes")
    _fake_fsdbreport(monkeypatch)

    rc, out = _run_cli(monkeypatch, tmp_path, [
        "fsdb-report", "--fsdb", str(fsdb), "--topic", "lfps_handshake",
        "--job-id", "9911", "--pattern", "usb3_lfps_basic"], capsys)
    assert rc == 0

    with _open_store(tmp_path) as store:
        rows = store.query(
            "SELECT evidence_id, source_kind, job_id, pattern, verdict, counts_json "
            "FROM normalized_evidence")
    assert len(rows) == 1
    evidence_id, source_kind, job_id, pattern, verdict, counts_json = rows[0]
    assert source_kind == "fsdbreport"
    assert job_id == 9911
    assert pattern == "usb3_lfps_basic"
    # fsdbreport is trace evidence, not a checker -- vip_distill deliberately
    # leaves verdict/counts structurally absent rather than inventing them,
    # and that honesty must survive the round-trip into SQL as real NULLs.
    assert verdict is None
    assert counts_json is None
    assert evidence_id.startswith("EVID-")


def test_cli_fsdb_report_row_carries_the_real_parsed_csv_not_raw_text(monkeypatch, tmp_path, capsys):
    """Proves the row went through the real Distillation stage rather than
    dumping report_text: the stored detail must contain the structured
    records `fsdb_report.parse_fsdbreport_output()` produced, and the topic
    the operator asked about."""
    fsdb = tmp_path / "dump.fsdb"
    fsdb.write_bytes(b"\x00fake fsdb bytes")
    _fake_fsdbreport(monkeypatch)

    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "fsdb-report", "--fsdb", str(fsdb), "--topic", "lfps_handshake"], capsys)
    assert rc == 0

    with _open_store(tmp_path) as store:
        detail_json, provenance_json = store.query(
            "SELECT detail_json, provenance_json FROM normalized_evidence")[0]
    detail = json.loads(detail_json)
    assert detail["topic"] == "lfps_handshake"
    assert detail["fsdbreport"]["parsed"] is True
    assert detail["fsdbreport"]["fieldnames"] == ["signal", "time", "value"]
    assert detail["fsdbreport"]["records"][1] == {
        "signal": "u_dut.lfps_det", "time": "250", "value": "1"}
    assert json.loads(provenance_json)["parser"] == "fsdb_report.parse_fsdbreport_output"


def test_cli_fsdb_report_reports_the_evidence_id_it_landed(monkeypatch, tmp_path, capsys):
    """The command's own JSON output must name the row it wrote, so an
    operator (or a later Debug/RCA query) can join this run's console output
    to the DuckDB row without guessing."""
    fsdb = tmp_path / "dump.fsdb"
    fsdb.write_bytes(b"\x00fake fsdb bytes")
    _fake_fsdbreport(monkeypatch)

    rc, out = _run_cli(monkeypatch, tmp_path, ["fsdb-report", "--fsdb", str(fsdb)], capsys)
    assert rc == 0
    reported = json.loads(out)["evidence_id"]

    with _open_store(tmp_path) as store:
        stored = store.query("SELECT evidence_id FROM normalized_evidence")[0][0]
    assert reported == stored


def test_cli_fsdb_report_ingest_is_idempotent_on_re_run(monkeypatch, tmp_path, capsys):
    """vip_distill's evidence_id is a deterministic content hash, so
    re-reporting the SAME fsdb extract twice must upsert one row, not
    accumulate duplicates in the evidence store."""
    fsdb = tmp_path / "dump.fsdb"
    fsdb.write_bytes(b"\x00fake fsdb bytes")
    _fake_fsdbreport(monkeypatch)

    for _ in range(2):
        rc, _ = _run_cli(monkeypatch, tmp_path, [
            "fsdb-report", "--fsdb", str(fsdb), "--topic", "lfps_handshake"], capsys)
        assert rc == 0

    with _open_store(tmp_path) as store:
        assert store.query("SELECT count(*) FROM normalized_evidence")[0][0] == 1


def test_cli_fsdb_report_still_succeeds_when_evidence_db_is_disabled(monkeypatch, tmp_path, capsys):
    """The bridge is best-effort by design: turning the evidence store off
    must leave the real fsdb-report run and its JSON output intact, and must
    not create a DB file."""
    (tmp_path / ".dv-harness").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".dv-harness" / "config.json").write_text(
        json.dumps({"evidence_db": {"enabled": False}}), encoding="utf-8")
    fsdb = tmp_path / "dump.fsdb"
    fsdb.write_bytes(b"\x00fake fsdb bytes")
    _fake_fsdbreport(monkeypatch)

    rc, out = _run_cli(monkeypatch, tmp_path, ["fsdb-report", "--fsdb", str(fsdb)], capsys)
    assert rc == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["parsed_report"]["parsed"] is True
    assert "evidence_id" not in payload
    assert not evidence_db.default_db_path(tmp_path).exists()


def test_cli_fsdb_report_failure_writes_no_evidence_row(monkeypatch, tmp_path, capsys):
    """A failed fsdbreport run has no report to distill. It must land no
    row at all -- never a fabricated 'we looked and saw nothing' record."""
    fsdb = tmp_path / "dump.fsdb"
    fsdb.write_bytes(b"\x00fake fsdb bytes")
    monkeypatch.setattr(fsdb_report, "run_fsdbreport",
                         lambda *a, **k: {"ok": False, "error": "FSDBREPORT_NONZERO_EXIT",
                                          "returncode": 2, "stderr": "boom"})

    rc, _ = _run_cli(monkeypatch, tmp_path, ["fsdb-report", "--fsdb", str(fsdb)], capsys)
    assert rc == 1
    assert not evidence_db.default_db_path(tmp_path).exists()


# ===========================================================================
# verible -> parsers -> DuckDB
# ===========================================================================

@requires_verible
def test_cli_env_manifest_generate_lands_real_verible_rows_in_duckdb(monkeypatch, tmp_path, capsys):
    """THE edge, driven end to end through the REAL verible subprocess.
    Before this wiring, `env-manifest generate` routed its verible output
    into env.manifest.json only and `insert_rtl_parse()` had zero live
    callers, so the rtl_* traceability tables were permanently empty."""
    rtl = tmp_path / "lfps_detect.sv"
    rtl.write_text(FIFO_FIXTURE, encoding="utf-8")
    out_manifest = tmp_path / "env.manifest.json"

    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(out_manifest), "--rtl-file", str(rtl)], capsys)
    assert rc == 0
    assert out_manifest.exists()

    with _open_store(tmp_path) as store:
        modules = store.query(
            "SELECT module_name, file_path, verible_version FROM rtl_modules")
        ports = store.query(
            "SELECT p.port_name, p.direction FROM rtl_ports p "
            "JOIN rtl_modules m ON p.module_id = m.id "
            "WHERE m.module_name = 'lfps_detect' ORDER BY p.port_name")
        params = store.query(
            "SELECT p.param_name FROM rtl_parameters p "
            "JOIN rtl_modules m ON p.module_id = m.id "
            "WHERE m.module_name = 'lfps_detect'")

    assert [m[0] for m in modules] == ["lfps_detect"]
    assert modules[0][1] == str(rtl)
    # A real version string from the real binary, not a placeholder.
    assert modules[0][2]
    assert {p[0] for p in ports} == {"clk", "rst_n", "rx_data", "lfps_seen"}
    assert dict(ports)["lfps_seen"] == "output"
    assert [p[0] for p in params] == ["WIDTH"]


@requires_verible
def test_cli_env_manifest_duckdb_rows_agree_with_the_manifest_it_wrote(monkeypatch, tmp_path, capsys):
    """The two destinations of the SAME verible parse must not disagree.
    This is the cross-check a per-side unit test structurally cannot make:
    env.manifest.json and the DuckDB rows are asserted against each other,
    not each against a hand-written expectation."""
    rtl = tmp_path / "lfps_detect.sv"
    rtl.write_text(FIFO_FIXTURE, encoding="utf-8")
    out_manifest = tmp_path / "env.manifest.json"

    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(out_manifest), "--rtl-file", str(rtl)], capsys)
    assert rc == 0

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    parsed_file = manifest["dut_facts"]["rtl"]["files"][0]
    manifest_module = parsed_file["modules"][0]

    with _open_store(tmp_path) as store:
        row = store.query(
            "SELECT module_name, file_path, source_sha256, verible_version FROM rtl_modules")[0]
        db_ports = {r[0] for r in store.query("SELECT port_name FROM rtl_ports")}
        db_signals = {r[0] for r in store.query("SELECT signal_name FROM rtl_signals")}

    assert row[0] == manifest_module["name"]
    assert row[1] == parsed_file["file_path"]
    assert row[2] == parsed_file["source_sha256"]
    assert row[3] == parsed_file["verible_version"]
    assert db_ports == {p["name"] for p in manifest_module["ports"]}
    assert db_signals == {s["name"] for s in manifest_module["signals"]}


@requires_verible
def test_cli_env_manifest_ingest_is_idempotent_across_repeated_generates(monkeypatch, tmp_path, capsys):
    """`env-manifest generate` is re-run routinely against untouched RTL,
    and `insert_rtl_parse()` is deliberately append-only, so without the
    bridge's parse-identity check this edge would grow duplicate module/port
    rows on every regeneration and corrupt any count query over them."""
    rtl = tmp_path / "lfps_detect.sv"
    rtl.write_text(FIFO_FIXTURE, encoding="utf-8")
    out_manifest = tmp_path / "env.manifest.json"

    for _ in range(2):
        rc, _ = _run_cli(monkeypatch, tmp_path, [
            "env-manifest", "generate", "--out", str(out_manifest), "--rtl-file", str(rtl)], capsys)
        assert rc == 0

    with _open_store(tmp_path) as store:
        assert store.query(
            "SELECT count(*) FROM rtl_modules WHERE module_name = 'lfps_detect'")[0][0] == 1
        assert store.query("SELECT count(*) FROM rtl_ports")[0][0] == 4


@requires_verible
def test_cli_env_manifest_records_a_new_parse_when_the_rtl_actually_changes(monkeypatch, tmp_path, capsys):
    """The other half of the idempotency contract: dedup must not become
    "never record anything again". Editing the RTL changes source_sha256, so
    the next generate really does append a second, genuinely different parse
    -- which is the change history the append-only rtl_modules table exists
    to hold, and what a later Debug/RCA join needs to see."""
    rtl = tmp_path / "lfps_detect.sv"
    rtl.write_text(FIFO_FIXTURE, encoding="utf-8")
    out_manifest = tmp_path / "env.manifest.json"

    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(out_manifest), "--rtl-file", str(rtl)], capsys)
    assert rc == 0

    # A real edit: one more output port on the same module.
    rtl.write_text(FIFO_FIXTURE.replace("output logic             lfps_seen",
                                         "output logic             lfps_seen,\n"
                                         "    output logic             lfps_err"),
                    encoding="utf-8")
    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(out_manifest), "--rtl-file", str(rtl)], capsys)
    assert rc == 0

    with _open_store(tmp_path) as store:
        shas = store.query(
            "SELECT source_sha256 FROM rtl_modules WHERE module_name = 'lfps_detect' "
            "ORDER BY parsed_at")
        newest_ports = store.query(
            "SELECT p.port_name FROM rtl_ports p JOIN rtl_modules m ON p.module_id = m.id "
            "WHERE m.id = (SELECT max(id) FROM rtl_modules WHERE module_name = 'lfps_detect')")
    assert len(shas) == 2 and shas[0][0] != shas[1][0]
    assert "lfps_err" in {p[0] for p in newest_ports}


def test_cli_env_manifest_without_rtl_writes_no_rtl_rows(monkeypatch, tmp_path, capsys):
    """dut_facts.rtl NOT_AVAILABLE (no --rtl-file supplied) means no RTL was
    parsed at all. That must produce no rows and no fabricated placeholder
    module -- and must not fail the manifest generation it rides along with.
    Runs without verible because no RTL is parsed."""
    out_manifest = tmp_path / "env.manifest.json"
    rc, _ = _run_cli(monkeypatch, tmp_path, [
        "env-manifest", "generate", "--out", str(out_manifest)], capsys)
    assert rc == 0
    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    assert manifest["dut_facts"]["rtl"]["status"] == "NOT_AVAILABLE"
    db_path = evidence_db.default_db_path(tmp_path)
    if db_path.exists():
        with evidence_db.EvidenceStore(db_path, read_only=True) as store:
            assert store.query("SELECT count(*) FROM rtl_modules")[0][0] == 0


# ===========================================================================
# Static proof the live call sites exist (the thing that was missing)
# ===========================================================================

def test_the_bridges_have_real_non_test_call_sites():
    """The pre-2026-09-04 state was precisely "real function, real store, no
    caller". This pins the caller down: both bridges must be invoked from
    dv_harness/cli.py's real command dispatch, not only from this file.
    Deleting either CLI call would leave every behavioral test above red;
    this one names WHY, so the next reader does not have to re-derive it."""
    import pathlib

    src = (pathlib.Path(cli_mod.__file__)).read_text(encoding="utf-8")
    assert "fsdb_report.ingest_report_to_evidence_db(" in src
    assert "env_manifest.ingest_rtl_parse_to_evidence_db(" in src


def test_fsdb_bridge_does_not_import_vip_distill_at_module_scope():
    """vip_distill imports fsdb_report at ITS module scope, so a top-level
    import back would be a hard circular import. Pinned so a later cleanup
    pass that "tidies" the function-local imports upward fails loudly here
    instead of at some importer's runtime."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(fsdb_report.__file__).read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = set()
    for node in top_level:
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[-1])
            names.update(a.name.split(".")[-1] for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name.split(".")[-1] for a in node.names)
    assert "vip_distill" not in names
    assert "evidence_db" not in names
