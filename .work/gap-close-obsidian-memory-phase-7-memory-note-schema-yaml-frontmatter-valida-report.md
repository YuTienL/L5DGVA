# Gap-Close Pass — Phase 7: Memory Note Schema (YAML frontmatter + validation)

**Status: NO_ACTION_NEEDED** (Phase 7 was already READY and is re-confirmed)
**Side finding, out of scope: NEEDS_SEPARATE_EFFORT** — a Phase 13 git-commit flake, §4.1

Scope: verify the fresh audit's `READY` verdict for Phase 7 independently, and close
anything that turned out to be a real, boundable gap. Nothing was found to close.
**No file in this repository was modified by this pass**, so there is no commit.

Mode: `LOCAL_ANALYSIS` — pure local read + local synthetic execution. No server, no VCS,
no simulation.

---

## 1. Re-confirmation of the audit's cited evidence

Every claim in the incoming audit was re-checked against the live files, not taken on trust.

### 1.1 Schema definition is real — `dv_harness/memory_vault.py:122-159`

Confirmed verbatim at the cited lines:

| Symbol | Line | Content |
|---|---|---|
| `MEMORY_NOTE_REQUIRED_FIELDS` | `memory_vault.py:122` | `id, memory_level, protocol, status, confidence, created, updated` |
| `MEMORY_NOTE_OPTIONAL_FIELDS` | `memory_vault.py:140-143` | `subsystem, category, failure, project, rtl_sha, tb_sha, vip_vendor, vip_version, simulator, tags, knowledge_commit_sha` |
| `MEMORY_NOTE_ALL_FIELDS` | `memory_vault.py:145` | union of the two above |
| `MEMORY_NOTE_BODY_SECTIONS` | `memory_vault.py:156-159` | `Symptom, Context, Hypothesis, Evidence, Root Cause, Fix, Verification, Confidence, Reusability, Known Limitations, Related Knowledge` |

Machine-checked field coverage against the spec's own 17-name list
(`id, memory_level, protocol, subsystem, category, failure, status, confidence, project,
rtl_sha, tb_sha, vip_vendor, vip_version, simulator, created, updated, tags`):

```
spec fields missing from schema: []
schema fields beyond spec: ['knowledge_commit_sha']
```

Zero spec fields are absent. The single extra field is the additive Phase-13
git-traceability field, documented in place at `memory_vault.py:129-139`.

### 1.2 Validator is real AND enforced — `memory_vault.py:181-189`

```python
missing = [f for f in MEMORY_NOTE_REQUIRED_FIELDS if frontmatter.get(f) in (None, "")]
return {"schema_status": "PARTIAL" if missing else "COMPLETE", "missing_required": missing}
```

Call sites confirmed by repo-wide grep — the validator is not a dead primitive:

- `memory_vault.py:820-821` — `FileSystemMarkdownAdapter.create()`; result's `schema_status`
  is written into `fm` **before** `render_note_markdown()` at line 827, so it lands on the
  note's own on-disk frontmatter.
- `memory_vault.py:869-870` — `FileSystemMarkdownAdapter.update()`; same pattern, before the
  `p.write_text(...)` at line 871.
- `memory_doctor.py:153-155` — **an additional real consumer the incoming audit did not
  cite**: the vault-wide health audit re-validates every discovered note's frontmatter and
  counts COMPLETE vs. PARTIAL. This strengthens the READY verdict rather than changing it.

These are the only write paths into a note, so no path exists that writes a note without
computing and stamping `schema_status`.

### 1.3 Existing tests pass — re-run, not quoted

```
$ python -m pytest dv_harness_tests/test_memory_vault.py -q
41 passed in 36.01s
```

Phase 7 test bodies re-read at `dv_harness_tests/test_memory_vault.py:145-194` and
`:277-288` — they assert real behavior (PARTIAL classification, round-trip fidelity,
colon/quote escaping, on-disk `schema_status: PARTIAL`), not merely that the module imports.

---

## 2. Independent synthetic verification (this pass's own, not reused)

Written to a throwaway temp vault via `FileSystemMarkdownAdapter(git_enabled=False)`, three
cases, all passing:

**(a) Fully-populated note (`MEM-P7A`, all 17 spec fields):**
```
FULL -> {'schema_status': 'COMPLETE', 'missing_required': []}
  on-disk schema_status: COMPLETE
  vip_version type/value: str '2024.1'      <- correctly quoted, NOT coerced to float 2024.1
  tags: ['usb3', 'link']                    <- real YAML list, round-trips as a list
  all spec fields present on disk: True
  all 11 sections present: True
  wikilinks verbatim: True                  <- [[MEM-OTHER]] / [[F-99]] survive render+parse
  placeholder used: True                    <- undocumented sections -> "_Not yet documented._"
```

**(b) Incomplete note (`MEM-P7B`, `status`/`confidence` omitted):**
```
SPARSE -> {'schema_status': 'PARTIAL', 'missing_required': ['status', 'confidence']}
  on-disk schema_status: PARTIAL | status present: False | confidence present: False
```
The two missing fields are simply absent from the written frontmatter — never fabricated,
never emitted as if valid. This is the phase's explicit "never silently COMPLETE"
requirement, verified on the artifact itself rather than on the return value.

**(c) Transition back to valid (new check, beyond the incoming audit):**
```
AFTER FILL-IN -> {'schema_status': 'COMPLETE', 'missing_required': []}
```
`update()` re-runs the validator over the merged frontmatter, so a note repaired later is
re-stamped COMPLETE. `schema_status` is a live computed property of the note, not a
write-once stamp that goes stale.

---

## 3. The one deviation from the spec's literal wording — assessed, deliberately left as-is

The spec text lists all 17 fields as "required"; the code gates `schema_status` on 7 of them
and treats the other 10 as always-emitted-but-nullable schema members.

**Assessed as a deliberate, better design — not a boundable gap to close.** Reasons:

1. `rtl_sha` / `tb_sha` / `vip_vendor` / `vip_version` / `simulator` / `project` are
   legitimately absent for a note not tied to one specific commit, VIP or simulator
   (e.g. a cross-protocol `debug_lesson`). Making them gate `schema_status` would mark
   every such note PARTIAL forever, or — far worse — pressure a caller to pad the fields
   with placeholder values, which is exactly the "do not pad an `evidence` field to clear
   it" failure mode CLAUDE.md's Engineering Memory Policy already names.
2. The rationale is written down in the source at `memory_vault.py:115-121` and
   `:124-127`, not implicit — the "which protocol / still-trusted / how confident"
   threshold it names is the same reusability bar CLAUDE.md's "Memory is prior knowledge,
   not current evidence" rule sets for anything read back out of Memory.
3. This pass's governing instruction is explicit: keep a more mature existing design rather
   than downgrading it to match spec wording literally. Tightening the required list here
   would be a downgrade, so no change was made.

Recorded here so the discrepancy stays visible rather than silently endorsed.

---

## 4. Test summary

No change was made, so no new test was needed. Suites exercising the Phase 7 schema were
run to confirm current truth:

- `dv_harness_tests/test_memory_vault.py` — **41 passed in 36.01s**
- `dv_harness_tests/test_obsidian_memory_final_integration.py` — **14 passed in 36.49s**
  (covers the integration-level "never silently COMPLETE" assertion at
  `test_obsidian_memory_final_integration.py:366-374`)
- `dv_harness_tests/test_memory_doctor.py` + the integration file together — **31 passed,
  1 failed in 119.20s**; see §4.1. Every Phase 7 assertion passed in all three runs.

### 4.1 One observed failure — NOT Phase 7, and not reproducible

The combined run failed `test_obsidian_memory_final_integration.py::test_case_12_git_metadata`
at line 424:

```
AssertionError: assert None
  where None = {...}.get('knowledge_commit_sha')
  ... {'note_id': 'MEM-D426FE14EC', 'ok': True,
       'path': '06_Agent_Memory\\Engineering\\MEM-D426FE14EC.md',
       'validation': {'missing_required': [], 'schema_status': 'COMPLETE'}}
```

Scope: this is **Phase 13 (Git Integration)**, not Phase 7. Note that the Phase 7 half of the
same result is correct in the failing run itself — `'schema_status': 'COMPLETE'`,
`'missing_required': []`. What was missing is the git commit SHA.

Reproduction attempts:

| Run | Result | Wall time |
|---|---|---|
| `::test_case_12_git_metadata` alone | **1 passed** | 19.85s |
| whole integration file alone | **14 passed** | 36.49s |
| integration file + `test_memory_doctor.py` | **1 failed**, 31 passed | 119.20s |

It does not reproduce in isolation or on the file alone, so it is **load-dependent, not
order-dependent**. The 119s vs. 36s wall time for the run that failed shows the machine was
heavily loaded at the time (this repo currently has several concurrent agent workflows and a
live remote build running).

**Plausible mechanism — stated as a hypothesis, not a proven diagnosis** (this pass did not
prove it and did not modify anything to test it): `_run_git()` at `memory_vault.py:426-430`
runs git with `timeout=10` and swallows *every* exception — including
`subprocess.TimeoutExpired` — returning `None`. `_commit_vault_change()` at `:457-458` then
returns `None`, which is the exact same signal it uses for the legitimate "nothing to commit"
case. So a git call that merely ran slow under load is indistinguishable, to the caller, from
a git call that correctly had nothing to do. That would explain a failure that only appears
when the machine is loaded.

If that hypothesis is right it is a real (if minor) robustness weakness — a timed-out commit is
silently reported as "no commit was needed", so a note could be written with no
`knowledge_commit_sha` and nothing would flag it. Distinguishing timeout/error from
nothing-to-commit would close it. **Deliberately not fixed here**: it is outside this pass's
Phase 7 scope, it touches a file other concurrent workflows may be editing, and the hypothesis
is unproven. Flagged for a separate Phase 13 effort — **NEEDS_SEPARATE_EFFORT** for that item
only. Phase 7 itself is unaffected.

---

## 5. Concurrency check

Per this pass's own instruction to check before touching shared files: `git status --porcelain`
shows `dv_harness/memory_vault.py` and `dv_harness_tests/test_memory_vault.py` **clean** — no
concurrent workflow has them modified, and this pass added nothing to the index. `CLAUDE.md`,
`dv_harness/cli.py`, `dv_harness/memory.py` and `dv_harness/memory_router.py` were not touched.

---

## Verdict

**Phase 7: READY — NO_ACTION_NEEDED.** Schema, validator, render/parse round-trip and the
write-path enforcement are all real, wired into every note-write path plus the vault doctor,
covered by passing tests, and independently reproduced here on synthetic notes. The one
deviation from the spec's literal field list is a documented, defensible design choice that
this pass deliberately preserved.
