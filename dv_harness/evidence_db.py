"""dv_harness/evidence_db.py -- DuckDB-backed evidence store (2026-09-03,
verible+DuckDB task; user's own spec: "DuckDB 則很適合吃 regression /
coverage / job / failure signature / traceability 資料").

Schema design principle: every table mirrors a REAL data shape this project
already produces -- never an invented generic schema. Sources, read in full
before designing this schema:
  - `jobs`               <- dv_harness.lsf_client.JobState (every field,
                            1:1 -- the real per-job on-disk state
                            .dv-harness/lsf/jobs/<id>.json already holds).
  - `job_memory_records` <- the real `kind in ("job_result","job_failure")`
                            record dict `lsf_client._upsert_job_tier_memory_
                            record()` builds and routes through
                            `memory_router.route_and_store()`.
  - `failure_signatures` <- the real dict `memory_vault.build_failure_
                            signature()` returns (protocol/pattern/symptom/
                            root_cause_hint/uvm_error_count/uvm_fatal_count/
                            assertion_failure/simulator_crash/
                            terminal_signature/lsf_status/
                            abnormal_termination/extra_text), aggregated
                            here by a stable hash of that same dict so a
                            recurring failure shape accumulates one row
                            with a real occurrence_count/first_seen/
                            last_seen instead of one row per occurrence.
  - `regression_verdicts` <- the real one-pattern-per-line PASS semantics of
                            `uvm_generator.regression_list_manager.
                            record_verdict()`/`apply_verdict_to_file()`
                            (a pattern's presence in regression.list IS the
                            "currently verified PASS" claim; a FAIL evicts
                            it) -- this table is the queryable mirror of
                            that same file, gaining a real recorded_at this
                            project's flat-file format has no room for.
  - `coverage_samples`    <- the real per-category shape
                            `coverage_analysis.parse_coverage_summary()`
                            validates ({"name","percent","bins_total",
                            "bins_hit"}) and `append_history_sample()`'s
                            real {"timestamp","percent"} trend-history shape.
  - `rtl_modules`/`rtl_ports`/`rtl_signals`/`rtl_parameters` (traceability)
                            <- `dv_harness.verible_parser.FileParseResult`/
                            `ModuleInfo`/`PortInfo`/`SignalInfo`/`ParamInfo`,
                            the real structured output of running verible
                            `--export_json` against an actual .sv/.v file.

Deliberately NOT built: a full ETL pipeline, a generic "events" table, or
any speculative column with no real producer in this codebase today. This
module only proves the real ingestion path end to end -- one function per
real record shape above, each an upsert (job_id/memory_id/pattern/
signature_key are real natural keys already, so re-ingesting the same
record is idempotent, matching this project's own JSON-store upsert
convention in `memory.py`/`lsf_client.save_job_state()`)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Optional

DB_PATH_PARTS = (".dv-harness", "evidence", "evidence.duckdb")

_SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS jobs (
        job_id BIGINT PRIMARY KEY,
        regression_id VARCHAR,
        pattern VARCHAR,
        options VARCHAR,
        run_dir VARCHAR,
        sim_log VARCHAR,
        seed VARCHAR,
        fsdb_path VARCHAR,
        lsf_status VARCHAR,
        sim_status VARCHAR,
        last_log_offset BIGINT,
        uvm_error_count INTEGER,
        uvm_fatal_count INTEGER,
        assertion_failure BOOLEAN,
        simulator_crash BOOLEAN,
        terminal_signature VARCHAR,
        early_kill BOOLEAN,
        kill_reason VARCHAR,
        root_cause_status VARCHAR,
        fix_proposal_status VARCHAR,
        git_sha VARCHAR,
        server_sha VARCHAR,
        last_change_time VARCHAR,
        state_fingerprint VARCHAR,
        ingested_at TIMESTAMP DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS job_memory_records (
        memory_id VARCHAR PRIMARY KEY,
        kind VARCHAR,
        job_id BIGINT,
        pattern VARCHAR,
        scope VARCHAR,
        title VARCHAR,
        lsf_status VARCHAR,
        dv_analysis_status VARCHAR,
        uvm_error_count INTEGER,
        uvm_fatal_count INTEGER,
        terminal_signature VARCHAR,
        seed VARCHAR,
        fsdb_path VARCHAR,
        failure_signature_json VARCHAR,
        prior_related_knowledge_json VARCHAR,
        ingested_at TIMESTAMP DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS regression_verdicts (
        pattern VARCHAR PRIMARY KEY,
        verdict_passed BOOLEAN,
        job_id BIGINT,
        recorded_at TIMESTAMP DEFAULT now()
    )""",
    "CREATE SEQUENCE IF NOT EXISTS coverage_samples_id_seq",
    """CREATE TABLE IF NOT EXISTS coverage_samples (
        id BIGINT PRIMARY KEY DEFAULT nextval('coverage_samples_id_seq'),
        category_name VARCHAR,
        percent DOUBLE,
        bins_total BIGINT,
        bins_hit BIGINT,
        sample_timestamp VARCHAR,
        source VARCHAR,
        ingested_at TIMESTAMP DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS failure_signatures (
        signature_key VARCHAR PRIMARY KEY,
        protocol VARCHAR,
        pattern VARCHAR,
        symptom VARCHAR,
        root_cause_hint VARCHAR,
        uvm_error_count INTEGER,
        uvm_fatal_count INTEGER,
        assertion_failure BOOLEAN,
        simulator_crash BOOLEAN,
        terminal_signature VARCHAR,
        lsf_status VARCHAR,
        abnormal_termination BOOLEAN,
        extra_text VARCHAR,
        occurrence_count INTEGER,
        first_seen TIMESTAMP,
        last_seen TIMESTAMP,
        sample_job_id BIGINT,
        sample_memory_id VARCHAR
    )""",
    "CREATE SEQUENCE IF NOT EXISTS rtl_modules_id_seq",
    """CREATE TABLE IF NOT EXISTS rtl_modules (
        id BIGINT PRIMARY KEY DEFAULT nextval('rtl_modules_id_seq'),
        file_path VARCHAR,
        source_sha256 VARCHAR,
        verible_version VARCHAR,
        module_name VARCHAR,
        parsed_at TIMESTAMP DEFAULT now()
    )""",
    "CREATE SEQUENCE IF NOT EXISTS rtl_ports_id_seq",
    """CREATE TABLE IF NOT EXISTS rtl_ports (
        id BIGINT PRIMARY KEY DEFAULT nextval('rtl_ports_id_seq'),
        module_id BIGINT,
        port_name VARCHAR,
        direction VARCHAR,
        data_type VARCHAR
    )""",
    "CREATE SEQUENCE IF NOT EXISTS rtl_signals_id_seq",
    """CREATE TABLE IF NOT EXISTS rtl_signals (
        id BIGINT PRIMARY KEY DEFAULT nextval('rtl_signals_id_seq'),
        module_id BIGINT,
        signal_name VARCHAR,
        data_type VARCHAR,
        unpacked_dims VARCHAR
    )""",
    "CREATE SEQUENCE IF NOT EXISTS rtl_parameters_id_seq",
    """CREATE TABLE IF NOT EXISTS rtl_parameters (
        id BIGINT PRIMARY KEY DEFAULT nextval('rtl_parameters_id_seq'),
        module_id BIGINT,
        param_name VARCHAR,
        type_text VARCHAR,
        default_text VARCHAR
    )""",
]


def default_db_path(root: Path) -> Path:
    return Path(root).joinpath(*DB_PATH_PARTS)


def _as_dict(obj) -> dict:
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, dict):
        return obj
    raise TypeError(f"expected a dict or dataclass instance, got {type(obj)!r}")


def signature_key(failure_signature: dict) -> str:
    """Stable dedup key for a `build_failure_signature()` dict -- identical
    real evidence (same protocol/pattern/symptom/counts/flags/terminal
    signature) hashes identically, so `insert_job_memory_record()` can
    accumulate occurrence_count/first_seen/last_seen on ONE row per
    distinct failure shape rather than minting a new row per occurrence."""
    canonical = json.dumps(failure_signature, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EvidenceStore:
    """Thin wrapper around a DuckDB connection with this project's real
    evidence schema. Safe to construct repeatedly against the same
    `db_path` -- schema init is `CREATE TABLE/SEQUENCE IF NOT EXISTS`
    throughout, so it never clobbers existing rows.

    `read_only=True` (2026-09-03, MCP read-only-boundary gap fix) opens the
    connection via `duckdb.connect(path, read_only=True)` and skips the
    mkdir()/schema-DDL step entirely -- see `__init__`'s own comment for
    why. Use this for any caller (e.g. `dv_harness/mcp/runtime.py`'s
    `ReadOnlyMcpContext`) whose entire design premise is that it must never
    write to, or even create, the evidence database."""

    def __init__(self, db_path, *, read_only: bool = False):
        import duckdb  # imported here, not at module load, so importing this
        # module never fails for a caller that only needs signature_key()/
        # default_db_path() on a machine without the duckdb package yet.
        self.db_path = Path(db_path)
        self.read_only = read_only
        if read_only:
            # A genuinely read-only caller (dv_harness/mcp/runtime.py's
            # ReadOnlyMcpContext, 2026-09-03 gap fix) must never be able to
            # conjure a database into existence or alter an existing one's
            # schema, no matter what state db_path is in -- so the mkdir()
            # and CREATE TABLE/SEQUENCE DDL below are skipped ENTIRELY
            # rather than merely made a no-op. duckdb.connect(...,
            # read_only=True) itself raises duckdb.IOException when
            # db_path does not already exist (verified: it never creates
            # the file), and would raise duckdb.InvalidInputException on
            # any DDL/DML a caller attempted afterward -- so DuckDB's own
            # read-only connection already refuses writes at the engine
            # level as defense in depth on top of this class simply never
            # issuing any DDL in this branch.
            self._conn = duckdb.connect(str(self.db_path), read_only=True)
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self.db_path))
        for stmt in _SCHEMA_STATEMENTS:
            self._conn.execute(stmt)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ---- jobs (JobState mirror) -------------------------------------------

    def insert_job_state(self, state) -> None:
        """Upserts one row from a real `lsf_client.JobState` (dataclass
        instance or an equivalent dict, e.g. `json.loads()` of an on-disk
        `.dv-harness/lsf/jobs/<id>.json`). No-op-safe on a JobState with no
        `job_id` yet (nothing to key the row on)."""
        d = _as_dict(state)
        if d.get("job_id") is None:
            raise ValueError("insert_job_state: state.job_id is required")
        cols = ["job_id", "regression_id", "pattern", "options", "run_dir", "sim_log",
                "seed", "fsdb_path", "lsf_status", "sim_status", "last_log_offset",
                "uvm_error_count", "uvm_fatal_count", "assertion_failure",
                "simulator_crash", "terminal_signature", "early_kill", "kill_reason",
                "root_cause_status", "fix_proposal_status", "git_sha", "server_sha",
                "last_change_time", "state_fingerprint"]
        values = [d.get(c) for c in cols]
        assignments = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "job_id")
        placeholders = ", ".join("?" for _ in cols)
        self._conn.execute(
            f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT (job_id) DO UPDATE SET {assignments}",
            values,
        )

    # ---- job_memory_records (job_result/job_failure mirror) ---------------

    def insert_job_memory_record(self, record: dict) -> None:
        """Upserts one row from a real job-tier memory record -- the exact
        dict shape `lsf_client._upsert_job_tier_memory_record()` builds
        (kind in "job_result"/"job_failure", `memory_id` the real natural
        key MemoryStore.add() already upserts by). When `record` carries a
        `failure_signature` dict (only ever present for `kind=="job_failure"`
        with real UVM_ERROR/UVM_FATAL/abnormal-termination evidence -- see
        that function's own docstring), also upserts the aggregated
        `failure_signatures` row so repeat occurrences of the SAME failure
        shape accumulate one real occurrence_count/first_seen/last_seen
        instead of duplicating rows."""
        if not record.get("memory_id"):
            raise ValueError("insert_job_memory_record: record['memory_id'] is required")
        failure_signature = record.get("failure_signature")
        prior = record.get("prior_related_knowledge")
        cols = ["memory_id", "kind", "job_id", "pattern", "scope", "title",
                "lsf_status", "dv_analysis_status", "uvm_error_count",
                "uvm_fatal_count", "terminal_signature", "seed", "fsdb_path"]
        values = [record.get(c) for c in cols]
        cols += ["failure_signature_json", "prior_related_knowledge_json"]
        values += [
            json.dumps(failure_signature) if failure_signature is not None else None,
            json.dumps(prior) if prior is not None else None,
        ]
        assignments = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "memory_id")
        placeholders = ", ".join("?" for _ in cols)
        self._conn.execute(
            f"INSERT INTO job_memory_records ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT (memory_id) DO UPDATE SET {assignments}",
            values,
        )
        if failure_signature is not None:
            self._upsert_failure_signature(failure_signature,
                                            job_id=record.get("job_id"),
                                            memory_id=record.get("memory_id"))

    def _upsert_failure_signature(self, failure_signature: dict, *,
                                   job_id: Optional[int], memory_id: Optional[str]) -> None:
        key = signature_key(failure_signature)
        existing = self._conn.execute(
            "SELECT occurrence_count FROM failure_signatures WHERE signature_key = ?",
            [key],
        ).fetchone()
        if existing is None:
            self._conn.execute(
                """INSERT INTO failure_signatures
                   (signature_key, protocol, pattern, symptom, root_cause_hint,
                    uvm_error_count, uvm_fatal_count, assertion_failure,
                    simulator_crash, terminal_signature, lsf_status,
                    abnormal_termination, extra_text, occurrence_count,
                    first_seen, last_seen, sample_job_id, sample_memory_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                           now(), now(), ?, ?)""",
                [key,
                 failure_signature.get("protocol"), failure_signature.get("pattern"),
                 failure_signature.get("symptom"), failure_signature.get("root_cause_hint"),
                 failure_signature.get("uvm_error_count"), failure_signature.get("uvm_fatal_count"),
                 failure_signature.get("assertion_failure"), failure_signature.get("simulator_crash"),
                 failure_signature.get("terminal_signature"), failure_signature.get("lsf_status"),
                 failure_signature.get("abnormal_termination"), failure_signature.get("extra_text"),
                 job_id, memory_id],
            )
        else:
            self._conn.execute(
                """UPDATE failure_signatures
                   SET occurrence_count = occurrence_count + 1,
                       last_seen = now()
                   WHERE signature_key = ?""",
                [key],
            )

    # ---- regression_verdicts (regression.list mirror) ----------------------

    def insert_regression_verdict(self, pattern: str, verdict_passed: bool,
                                   job_id: Optional[int] = None) -> None:
        if not pattern:
            raise ValueError("insert_regression_verdict: pattern must be non-empty")
        self._conn.execute(
            """INSERT INTO regression_verdicts (pattern, verdict_passed, job_id, recorded_at)
               VALUES (?, ?, ?, now())
               ON CONFLICT (pattern) DO UPDATE SET
                   verdict_passed = excluded.verdict_passed,
                   job_id = excluded.job_id,
                   recorded_at = now()""",
            [pattern, verdict_passed, job_id],
        )

    # ---- coverage_samples (parse_coverage_summary category mirror) --------

    def insert_coverage_sample(self, category: dict, *, timestamp=None,
                                source: Optional[str] = None) -> None:
        """`category` is one already-validated entry from
        `coverage_analysis.parse_coverage_summary()`'s own
        `{"name","percent","bins_total","bins_hit"}` shape. `timestamp`
        mirrors `append_history_sample()`'s own str|number trend-history
        timestamp (stored as-is, as text, since this table does not itself
        decide a canonical clock -- the caller's real coverage-run
        timestamp is passed straight through)."""
        required = ("name", "percent", "bins_total", "bins_hit")
        if not all(k in category for k in required):
            raise ValueError(f"insert_coverage_sample: category missing one of {required}")
        self._conn.execute(
            """INSERT INTO coverage_samples
               (category_name, percent, bins_total, bins_hit, sample_timestamp, source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [category["name"], category["percent"], category["bins_total"],
             category["bins_hit"], str(timestamp) if timestamp is not None else None, source],
        )

    # ---- traceability: rtl_modules/rtl_ports/rtl_signals/rtl_parameters ---

    def insert_rtl_parse(self, parse_result: dict) -> list:
        """`parse_result` is `verible_parser.to_dict(FileParseResult)`'s own
        shape. Inserts one `rtl_modules` row per module in the file plus its
        ports/signals/parameters, and returns the list of new `rtl_modules`
        row ids (one per module, in file order) -- a caller wiring this into
        a debug/RCA flow can then join a job's `pattern`/RTL hierarchy path
        against these ids for traceability."""
        module_ids = []
        for mod in parse_result.get("modules", []):
            row = self._conn.execute(
                """INSERT INTO rtl_modules (file_path, source_sha256, verible_version, module_name)
                   VALUES (?, ?, ?, ?) RETURNING id""",
                [parse_result.get("file_path"), parse_result.get("source_sha256"),
                 parse_result.get("verible_version"), mod.get("name")],
            ).fetchone()
            module_id = row[0]
            module_ids.append(module_id)
            for p in mod.get("ports", []):
                self._conn.execute(
                    "INSERT INTO rtl_ports (module_id, port_name, direction, data_type) VALUES (?, ?, ?, ?)",
                    [module_id, p.get("name"), p.get("direction"), p.get("data_type")],
                )
            for s in mod.get("signals", []):
                self._conn.execute(
                    "INSERT INTO rtl_signals (module_id, signal_name, data_type, unpacked_dims) VALUES (?, ?, ?, ?)",
                    [module_id, s.get("name"), s.get("data_type"), s.get("unpacked_dims")],
                )
            for prm in mod.get("parameters", []):
                self._conn.execute(
                    "INSERT INTO rtl_parameters (module_id, param_name, type_text, default_text) VALUES (?, ?, ?, ?)",
                    [module_id, prm.get("name"), prm.get("type_text"), prm.get("default_text")],
                )
        return module_ids

    # ---- generic read-back (tests / ad-hoc CLI inspection) -----------------

    def query(self, sql: str, params: Optional[list] = None) -> list:
        return self._conn.execute(sql, params or []).fetchall()
