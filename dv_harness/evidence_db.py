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
  - `regression_verdict_history`
                         <- the SAME real verdict events `regression_verdicts`
                            mirrors, kept APPEND-ONLY instead of upserted
                            (cross-run-trend task, 2026-09-03). Deliberately a
                            second table, not a replacement: `regression_verdicts`
                            is the one-row-per-pattern "currently verified PASS"
                            snapshot that mirrors regression.list's own
                            semantics and that `dv_harness/mcp/regression_queries.py`
                            already reads -- overwriting a pattern's row on
                            every cycle is CORRECT for that question ("is this
                            pattern passing right now?") and structurally
                            destroys the different question the cross-run time
                            dimension asks ("what was this pattern's verdict
                            yesterday, and against which RTL commit?"). This
                            table answers only the second, carries the real
                            `git_sha` the job ran against (`JobState.git_sha`,
                            already captured per job) so a PASS->FAIL
                            transition can be attributed to a real commit
                            range, and is written by the SAME
                            `insert_regression_verdict()` call so no
                            production call site has to remember to write
                            both.
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
  - `normalized_evidence`  <- the real "Normalized Evidence" envelope dict
                            `dv_harness.vip_distill.py`'s `distill_sim_log()`/
                            `distill_job_record()`/`distill_fsdbreport()`/
                            `merge_evidence()` all return (and
                            `write_normalized_evidence()` writes to disk
                            unchanged) -- `schema_version`/`evidence_id`/
                            `source_kind`/`job_id`/`pattern`/`protocol`/
                            `run_dir`/`verdict`/`counts`/`detail`/
                            `provenance`, 1:1 (evidence-db-wiring step 2,
                            2026-09-03; closes the exact gap both
                            `.work/governance-vip-distill-report.md` and
                            `.work/governance-evidence-report.md` flagged as
                            open when each landed independently -- vip_distill
                            producing a schema with nowhere to land, this
                            store having no table shaped for it). Upsert key
                            is `evidence_id` itself, vip_distill's own
                            deterministic content hash (same real evidence ->
                            same id -> re-ingesting is idempotent), not a
                            second key invented here -- the real, already-
                            defined shape of this record IS `evidence_id`-
                            keyed at its own source.

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

# Additive column migrations for an evidence.duckdb that already exists from
# an earlier run (cross-run-trend task, 2026-09-03). `CREATE TABLE IF NOT
# EXISTS` alone silently leaves an OLD database on its old column set, so a
# column added to a table below would exist only in freshly-created files --
# every real .dv-harness/evidence/evidence.duckdb already on disk would keep
# failing the insert. Each statement here must be idempotent (`ADD COLUMN IF
# NOT EXISTS`, verified real DuckDB 1.5 syntax) because __init__ replays the
# whole list on every single connect.
_MIGRATION_STATEMENTS = [
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS runtime_seconds DOUBLE",
]

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
        runtime_seconds DOUBLE,
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
    "CREATE SEQUENCE IF NOT EXISTS regression_verdict_history_id_seq",
    """CREATE TABLE IF NOT EXISTS regression_verdict_history (
        id BIGINT PRIMARY KEY DEFAULT nextval('regression_verdict_history_id_seq'),
        pattern VARCHAR,
        verdict_passed BOOLEAN,
        job_id BIGINT,
        git_sha VARCHAR,
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
    """CREATE TABLE IF NOT EXISTS normalized_evidence (
        evidence_id VARCHAR PRIMARY KEY,
        schema_version VARCHAR,
        source_kind VARCHAR,
        job_id BIGINT,
        pattern VARCHAR,
        protocol VARCHAR,
        run_dir VARCHAR,
        verdict VARCHAR,
        counts_json VARCHAR,
        detail_json VARCHAR,
        provenance_json VARCHAR,
        distilled_at DOUBLE,
        distiller VARCHAR,
        ingested_at TIMESTAMP DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS golden_scenarios (
        capsule_id VARCHAR PRIMARY KEY,
        project VARCHAR,
        subsystem VARCHAR,
        protocol VARCHAR,
        test_name VARCHAR,
        sequence_name VARCHAR,
        seed VARCHAR,
        expected_result VARCHAR,
        evidence_id VARCHAR,
        evidence_verdict VARCHAR,
        job_id BIGINT,
        verified_sha VARCHAR,
        verified_at VARCHAR,
        requirements_json VARCHAR,
        vip_versions_json VARCHAR,
        configuration_json VARCHAR,
        command_txt_inputs_json VARCHAR,
        known_limitations_json VARCHAR,
        watched_paths_json VARCHAR,
        recorded_at TIMESTAMP DEFAULT now()
    )""",
]

#: `golden_scenarios` columns holding a list/dict serialized as JSON text, and
#: the `GoldenScenario` field each mirrors. Same convention
#: `insert_job_memory_record()` already uses for `failure_signature_json`.
_GOLDEN_SCENARIO_JSON_FIELDS = (
    ("requirements", "requirements_json"),
    ("vip_versions", "vip_versions_json"),
    ("configuration", "configuration_json"),
    ("command_txt_inputs", "command_txt_inputs_json"),
    ("known_limitations", "known_limitations_json"),
    ("watched_paths", "watched_paths_json"),
)

_GOLDEN_SCENARIO_SCALAR_COLS = (
    "capsule_id", "project", "subsystem", "protocol", "test_name", "sequence_name",
    "seed", "expected_result", "evidence_id", "job_id", "verified_sha", "verified_at",
)


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
        for stmt in _MIGRATION_STATEMENTS:
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
                "last_change_time", "state_fingerprint", "runtime_seconds"]
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
                                   job_id: Optional[int] = None,
                                   git_sha: Optional[str] = None) -> None:
        """Records one real PASS/FAIL verdict for `pattern` in BOTH shapes the
        rest of this harness asks for:

        1. `regression_verdicts` -- upserted, one row per pattern. The
           "currently verified PASS" snapshot that mirrors regression.list's
           own one-line-per-pattern semantics, and the table
           `dv_harness/mcp/regression_queries.py` reads. Unchanged.
        2. `regression_verdict_history` -- APPENDED, one row per call, carrying
           the real `git_sha` this verdict was produced against
           (cross-run-trend task, 2026-09-03).

        Both, from one call, deliberately: the upsert in (1) OVERWRITES the
        previous row, so before (2) existed no query could answer "what was
        this pattern's verdict yesterday" or "between which two RTL commits
        did it stop passing" -- the history was destroyed as it was written.
        Writing both here rather than adding a second method means no
        production call site (today: `regression_reporter.
        _write_reconciliation_evidence_if_configured()`) can grow history
        that silently disagrees with the snapshot.

        `git_sha` is optional and never invented: a caller with no real SHA
        for the job passes nothing and the history row records NULL, which
        `trend_analysis.detect_pattern_regressions()` then reports honestly as
        an un-bisectable transition rather than guessing a commit."""
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
        self._conn.execute(
            """INSERT INTO regression_verdict_history
               (pattern, verdict_passed, job_id, git_sha, recorded_at)
               VALUES (?, ?, ?, ?, now())""",
            [pattern, verdict_passed, job_id, git_sha],
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

    # ---- normalized_evidence (vip_distill.py envelope mirror) --------------

    def insert_normalized_evidence(self, record: dict) -> None:
        """Upserts one row from a real `vip_distill.py` Normalized Evidence
        envelope -- whatever `distill_sim_log()`/`distill_job_record()`/
        `distill_fsdbreport()`/`merge_evidence()` returned (or the same dict
        read back from a `write_normalized_evidence()`'d JSON file). Keyed
        on `record["evidence_id"]`, vip_distill's OWN deterministic
        content-derived id (see `vip_distill._evidence_id()`'s docstring --
        the same real evidence always hashes to the same id), so
        re-distilling and re-ingesting the same sim.log/job record/
        fsdbreport twice upserts the SAME row rather than duplicating it --
        the identical idempotent-upsert-by-real-natural-key convention
        `insert_job_memory_record()` above already follows for
        `memory_id`. `counts`/`detail`/`provenance` are stored as JSON text
        (same convention `insert_job_memory_record()` uses for
        `failure_signature_json`/`prior_related_knowledge_json`) since their
        internal shape varies by `source_kind` and this table does not
        itself need to query into them structurally."""
        if not record.get("evidence_id"):
            raise ValueError("insert_normalized_evidence: record['evidence_id'] is required")
        cols = ["evidence_id", "schema_version", "source_kind", "job_id", "pattern",
                "protocol", "run_dir", "verdict", "distilled_at", "distiller"]
        values = [record.get(c) for c in cols]
        cols += ["counts_json", "detail_json", "provenance_json"]
        counts = record.get("counts")
        values += [
            json.dumps(counts, default=str) if counts is not None else None,
            json.dumps(record.get("detail", {}), default=str),
            json.dumps(record.get("provenance", {}), default=str),
        ]
        assignments = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "evidence_id")
        placeholders = ", ".join("?" for _ in cols)
        self._conn.execute(
            f"INSERT INTO normalized_evidence ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT (evidence_id) DO UPDATE SET {assignments}",
            values,
        )

    # ---- golden_scenarios (golden_scenario.GoldenScenario mirror) ---------

    def insert_golden_scenario(self, capsule: dict, *,
                                evidence_verdict: Optional[str] = None) -> None:
        """Upserts one row from a real `golden_scenario.GoldenScenario`
        (spec section 225's reference capsule), keyed on its own
        `capsule_id` -- re-recording the same capsule after a fresh verified
        PASS updates that one row (new verified_sha/verified_at/evidence_id)
        rather than minting a second capsule for the same test, the same
        idempotent-upsert-by-real-natural-key convention every other table
        here follows.

        This store deliberately does NOT persist a freshness flag:
        `golden_scenario.evaluate_freshness()` derives FRESH/STALE/UNKNOWN
        from real git history at the moment it is asked, and a stored flag
        would be wrong the instant someone commits.

        `evidence_verdict` is the verdict `record_golden_scenario()` really
        read off the cited `normalized_evidence` row when it accepted this
        capsule -- kept here so a later reader can see WHAT was checked
        without re-joining, never as a substitute for that row itself."""
        if not capsule.get("capsule_id"):
            raise ValueError("insert_golden_scenario: capsule['capsule_id'] is required")
        if not capsule.get("evidence_id"):
            raise ValueError("insert_golden_scenario: capsule['evidence_id'] is required")
        cols = list(_GOLDEN_SCENARIO_SCALAR_COLS)
        values = [capsule.get(c) for c in cols]
        cols.append("evidence_verdict")
        values.append(evidence_verdict)
        for field_name, col in _GOLDEN_SCENARIO_JSON_FIELDS:
            cols.append(col)
            values.append(json.dumps(capsule.get(field_name), default=str))
        assignments = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "capsule_id")
        placeholders = ", ".join("?" for _ in cols)
        self._conn.execute(
            f"INSERT INTO golden_scenarios ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT (capsule_id) DO UPDATE SET {assignments}, recorded_at = now()",
            values,
        )

    def _golden_scenario_rows(self, where: str = "", params: Optional[list] = None) -> list:
        # A read_only=True connection skips this class's schema DDL entirely
        # (see __init__), so an evidence.duckdb created before this table
        # existed genuinely has no golden_scenarios relation. That is "no
        # capsules have ever been recorded", which the caller reports as
        # NOT_AVAILABLE -- not a crash, and never a silent PASS.
        exists = self._conn.execute(
            "SELECT 1 FROM duckdb_tables() WHERE table_name = 'golden_scenarios'"
        ).fetchone()
        if not exists:
            return []
        cols = list(_GOLDEN_SCENARIO_SCALAR_COLS) + ["evidence_verdict"] + \
            [col for _, col in _GOLDEN_SCENARIO_JSON_FIELDS]
        sql = f"SELECT {', '.join(cols)} FROM golden_scenarios {where} ORDER BY capsule_id"
        out = []
        for row in self._conn.execute(sql, params or []).fetchall():
            record = dict(zip(cols, row))
            for field_name, col in _GOLDEN_SCENARIO_JSON_FIELDS:
                raw = record.pop(col, None)
                try:
                    record[field_name] = json.loads(raw) if raw else None
                except (TypeError, ValueError):
                    record[field_name] = None
                if record[field_name] is None:
                    record[field_name] = {} if field_name in ("vip_versions", "configuration") else []
            out.append(record)
        return out

    def get_golden_scenario(self, capsule_id: str) -> Optional[dict]:
        rows = self._golden_scenario_rows("WHERE capsule_id = ?", [capsule_id])
        return rows[0] if rows else None

    def list_golden_scenarios(self) -> list:
        return self._golden_scenario_rows()

    # ---- generic read-back (tests / ad-hoc CLI inspection) -----------------

    def query(self, sql: str, params: Optional[list] = None) -> list:
        return self._conn.execute(sql, params or []).fetchall()
