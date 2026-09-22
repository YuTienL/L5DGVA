# M1 — Canonical Security Preservation Gate

Per instruction #8: install the contract/record for `CANONICAL_SECURITY >=
strongest verified Parent/v50 behavior`, without wholesale-copying Parent's
`memory_vault.py` (that remains a future semantic-migration wave). This
document records the real Parent/v50 comparison and what Wave M5+ must not
regress.

## Comparison performed (read-only, no file modified)

`memory_security.py` and `security_policy_ir.py` (secret detection/redaction):
**byte-identical** between Parent and v50 (confirmed via `diff --strip-trailing-cr`,
0 differences) — same `SECRET_PATTERNS` registry, same `detect_secrets()`/
`redact_secrets()`/`redact_record()`/`redact_note_content()`. `memory_vault.py`'s
redaction call-sites, `_sanitize_note_id()` and `resolve_vault_path()` sandboxing:
**verbatim identical** both sides. `config.py`: neither side scans committed
config for embedded secrets (`NEITHER_HAS_IT`, equivalent).

## Three real, disclosed Parent-only findings the future migration must not lose

1. **Obsidian-CLI-probe hardening** (`memory_vault.py`) — Parent stopped probing
   the bare `obsidian` GUI-launcher name (a documented incident: probing it can
   hang/spawn a real GUI window) and added a real-version-string check rejecting
   exit-0-but-error-shaped output:
   ```python
   _OBSIDIAN_CLI_CANDIDATES = ["obsidian-cli"]  # never the bare `obsidian` GUI launcher name
   _VERSION_REJECT_MARKERS = ("not found", "error:", "unknown command", "usage:")
   def _looks_like_a_real_version_string(candidate: str) -> bool:
       lowered = candidate.lower()
       return not any(marker in lowered for marker in _VERSION_REJECT_MARKERS)
   ```
   (Parent `memory_vault.py:754,762-767`, used at `:850`.) v50's
   `_OBSIDIAN_CLI_CANDIDATES = ["obsidian-cli", "obsidian"]` (v50 `:697`) still
   probes the bare GUI name and accepts any `returncode==0` + non-empty output.
   **A real automation-safety regression risk if v50's version is taken as
   canonical without this hardening.**

2. **`detect_secrets()` applied to a wider evidence surface** — three Parent-only
   modules (`l5dgva_ss722_step_citation_matrix.py`, `remote_recovery_v23_late_sections.py`,
   `remote_bounded_local_diagnosis.py`) reuse the same, unchanged
   `memory_security.detect_secrets()` as a hard gate over remote-execution/
   diagnosis evidence text, not just vault notes. Confirmed absent from v50.
   Not a detector change, but wider, real coverage that must not be lost.

3. **`remote_relay.py` autoreconnect-override discrepancy** — a genuine, disclosed
   ambiguity, not a confirmed regression: Parent-root's own `tools/remote/remote_relay.py`
   has no `DV_HARNESS_RELAY_AUTORECONNECT_OK` bypass at all (stricter — its own
   docstring says this copy is a standalone-distribution port for external
   consumers, e.g. HAPS, and is NOT the one governing Parent's own live flow).
   v50's `tools/remote/remote_relay.py` (the one this canonical repo actually
   uses, confirmed unmodified in M1) keeps the override, governed by the
   sanctioned `replay.ps1` exemption. **Both files serve different declared
   purposes on the Parent side** — this is a real fact for whoever does the
   actual Wave M5+ consolidation to decide with, not something M1 resolves or
   silently picks a side on.

## Gate record

```
CANONICAL_SECURITY_FLOOR = PRESERVED
  (no regression introduced during M1 -- v50's memory_vault.py/memory_security.py
   were not modified, and this canonical repo's own tools/remote/remote_relay.py
   still carries the same override behavior v50's copy always had)

PARENT_STRONGER_BEHAVIOR_RECORDED = YES (3 items above)
PARENT_MEMORY_VAULT_WHOLESALE_COPIED = NO
SECOND_CONFIG_ARCHITECTURE_BUILT = NO

FUTURE_SEMANTIC_MIGRATION_OBLIGATION:
  Whichever wave reconciles memory_vault.py (Parent vs v50) MUST carry forward
  item 1's Obsidian-CLI-probe hardening (never regress to probing the bare
  `obsidian` GUI name) and SHOULD extend item 2's detect_secrets() coverage
  pattern to any new remote-diagnosis-evidence module the canonical repo adds.
  Whichever wave reconciles tools/remote/remote_relay.py MUST make an explicit,
  recorded human decision about item 3's override-bypass discrepancy (not
  silently inherit whichever side happens to be copied last).
```

This does not weaken the standing rule that the actual Parent `memory_vault.py`
implementation is not imported during M1 — only its verified-stronger behavior
is recorded here, exactly as instructed.
