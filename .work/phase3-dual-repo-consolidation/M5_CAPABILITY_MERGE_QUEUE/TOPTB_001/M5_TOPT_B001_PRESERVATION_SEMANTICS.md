# CAP-M5-TOPTB-001 -- Preservation Semantics

## What is actually preserved (Section 8) -- only what evidence supports

```
existing top TB structure       = YES -- the real on-disk file's content
                                   is returned byte-for-byte as files["soc_
                                   tb_top.sv"]
user-authored top TB content    = YES -- same as above
generated top TB content        = N/A -- not applicable when preserving
manual integration points       = NO -- not detected or preserved as a
                                   distinct concept; the whole file is an
                                   atomic unit (preserved or replaced, never
                                   partially merged)
existing hierarchy              = implicitly, as part of the whole-file
                                   preservation (no hierarchy parsing beyond
                                   the DUT-instantiation regex)
existing module instances       = implicitly, same reason
existing includes               = implicitly (e.g. the DV_UVM hook include),
                                   detected as a fact but not selectively
                                   preserved -- the whole file carries them
existing bind points             = NOT detected or modeled at all -- this
                                   module has no awareness of `bind`
                                   statements
existing interface wiring        = NOT detected or modeled
existing comments/markers        = implicitly preserved (whole-file)
regeneration behavior            = see Idempotency section below
idempotency                      = see Idempotency section below (a real,
                                   disclosed nuance, not previously covered
                                   by Parent's own test suite)
```

**Preservation is whole-file, atomic, never selective merge.** No source
(Parent's own docstring, code, or tests) supports any finer-grained
"preserve region A, regenerate region B" semantics. This matches Parent's
own explicit scope disclosure: "this closes PRESERVE only. EXTEND
(splicing new VIP/UVM integration hooks into a preserved existing top
TB) is a distinct, larger, NOT-yet-implemented follow-on."

## Regeneration / idempotency (Section 9) -- a real finding this wave adds

Parent's own 6 composer-level tests do not exercise a SECOND composition
run against the same `root` after a first run has already written
`generated/soc_composition/<soc_name>/soc_tb_top.sv`. Tracing the real
code path for this case (not assumed):

`discover_existing_top_tb()` walks the WHOLE `root` tree for any file
matching `*tb_top.sv`/`*_top.sv`/`top.sv`, sorted **newest-mtime-first**.
`soc_composition_out_dir()` writes the composed output at exactly
`generated/soc_composition/<soc_name>/soc_tb_top.sv` -- which matches the
`*tb_top.sv` glob. On a first composition where an original hand-authored
top TB existed elsewhere in the tree and was preserved, the written
`soc_tb_top.sv` copy now ALSO exists on disk. Because it was just
written, it has the newest mtime of any candidate. **A second composition
of the same `root` therefore discovers and preserves the PREVIOUS
COMPOSITION'S OWN OUTPUT, not the original hand-authored source file
directly**, unless the caller supplies `existing_top_tb_declared_path`
explicitly (which bypasses discovery entirely) or the original file's
mtime is deliberately kept newer.

```
DO_NOT_OVERWRITE       = the closest real semantic -- an already-composed
                          output is treated as itself a valid preservation
                          candidate on the next run
MERGE_GENERATED_REGION = NOT supported -- no such mechanism exists
PRESERVE_USER_REGION   = NOT supported at sub-file granularity
BACKUP_AND_REGENERATE  = NOT supported -- no backup mechanism exists
```

**Practical consequence, disclosed not hidden**: because the preserved
copy is byte-for-byte identical to whatever was preserved/generated on
the prior run, this is self-consistent (never corrupts or drifts) --
but it means a caller relying on discovery-by-convention across multiple
runs is effectively "pinned" to the first run's real decision after the
first composition, not re-evaluated fresh against the TRUE original
source on every subsequent run, unless `existing_top_tb_declared_path` is
supplied to point at the real original explicitly. This is a genuine,
non-obvious nuance neither Parent's own test suite nor its commit message
covers -- surfaced here as required evidence for Section 9, not treated
as a blocking defect (the behavior is internally consistent and every
disposition is still recorded, never silent).

## First / second / partial / user-modified / invalid top TB (Section 9, explicit cases)

| Case | Verified behavior |
|---|---|
| First generation (no existing top TB) | `NO_EXISTING_TOP_TB_FOUND`, fresh generation -- tested (Parent's `test_no_existing_top_tb_on_disk_falls_back_to_fresh_generation`) |
| Second generation (prior composition output present) | Preserves the prior output (see idempotency finding above) -- NOT independently tested by either source this wave; a real, disclosed gap in test coverage, not in behavior correctness |
| Existing top TB, DUT instantiation matches or is `NOT_COMPARABLE`/`EXISTING_ONLY` | Preserved verbatim -- tested (`test_qualified_existing_top_tb_with_no_dut_instantiation_is_preserved_verbatim`, `test_existing_top_tb_that_does_instantiate_the_declared_dut_is_a_real_match_not_divergent`) |
| User-modified existing top TB | No distinct handling -- any on-disk file matching the naming convention is a candidate; "user-modified" and "originally hand-authored" are not distinguished, both are simply "an existing file found on disk" |
| Invalid/corrupt top TB | `extract_existing_top_tb_facts()` reads with `errors="replace"` (never raises on bad encoding); a syntactically-invalid `.sv` file still yields whatever facts the regex-based extraction can find (possibly all-absent) -- never crashes, never silently fabricates a fact |

```
PRESERVATION_SEMANTICS_DEFINED = YES
```
