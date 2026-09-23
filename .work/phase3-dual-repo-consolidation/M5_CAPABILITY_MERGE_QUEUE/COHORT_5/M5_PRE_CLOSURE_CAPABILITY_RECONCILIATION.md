# M5 Pre-Closure Capability Reconciliation

Per instruction item 18: after `CAP-M5-COV-001`/`CAP-M5-DSI-001`
disposition, perform a complete M5-owned capability reconciliation.

## Structural re-enumeration (post-Cohort-5, `csv.DictReader`, not grep)

```
PRIMARY_OWNER_WAVE == 'M5' rows, post-Cohort-5: 15
  CAP-M4-001, CAP-M5-ENV-001, CAP-M5-VIP-001, CAP-M5-ARCH-001,
  CAP-M5-ARCH-002, CAP-M5-TOPTB-001, CAP-M5-ARCH-003, CAP-M5-COV-001,
  CAP-M5-DSI-001, CAP-ATL-004, CAP-ATL-005, CAP-ATL-006, CAP-ATL-007,
  CAP-ATL-009, CAP-ATL-010
```

(Down from 25 pre-Cohort-5 — the 10 `CAP-ATL-001/002/003/008` +
`CAP-POOL-001/003/004/008/011/012` items were reassigned `M5` -> `M6`
this Cohort, per `M5_COHORT_5_CAPABILITY_INVENTORY.md` Group C.)

## Disposition of all 15 remaining M5-owned rows

| ID | Disposition | Counts as resolved for M5? |
|---|---|---|
| `CAP-M4-001` | CLOSED (pre-existing) | YES |
| `CAP-M5-ENV-001` | CLOSED (Cohort 1) | YES |
| `CAP-M5-VIP-001` | CLOSED (Cohort 3) | YES |
| `CAP-M5-ARCH-001` | CLOSED (Cohort 2) | YES |
| `CAP-M5-ARCH-002` | CLOSED (Cohort 2) | YES |
| `CAP-M5-TOPTB-001` | CLOSED (Cohort 2) | YES |
| `CAP-M5-ARCH-003` | CLOSED (Cohort 2) | YES |
| `CAP-M5-COV-001` | CLOSED (Cohort 5, this wave) | YES |
| `CAP-M5-DSI-001` | SUPERSEDED (Cohort 5, this wave) | YES |
| `CAP-ATL-004` | FOUNDATION_CLOSED (Cohort 4) — `WIRED=NO`, deferred to `CAP-M6-DISPATCH-001` | YES |
| `CAP-ATL-005` | CLOSED (`ALREADY_COVERED`, pre-existing) | YES |
| `CAP-ATL-006` | CLOSED (`ALREADY_COVERED`, pre-existing) | YES |
| `CAP-ATL-007` | FOUNDATION_CLOSED (Cohort 4) — `WIRED=NO`, deferred to `CAP-M6-CLARSVC-001` | YES |
| `CAP-ATL-009` | DEFERRED_WITH_EXPLICIT_FUTURE_OWNER (pre-existing, trigger-based: "M5+ candidate only if a real cross-provider incident occurs") | YES |
| `CAP-ATL-010` | CLOSED (`ALREADY_COVERED`, pre-existing) | YES |

**`UNRESOLVED_M5_CAPABILITIES = 0`.** Every remaining M5-owned row falls
into a resolved-for-M5 bucket (`CLOSED` / `FOUNDATION_CLOSED` /
`SUPERSEDED` / `DEFERRED_WITH_EXPLICIT_FUTURE_OWNER`) per instruction
item 18's own definition. None is bare `OPEN`, `UNKNOWN`, or
`UNASSIGNED`.

## The 10 reassigned items are explicitly NOT part of this reconciliation's `UNRESOLVED_M5_CAPABILITIES` count

`CAP-ATL-001/002/003/008` and `CAP-POOL-001/003/004/008/011/012` no
longer carry `PRIMARY_OWNER_WAVE=M5` as of this Cohort's own reassignment
(see `M5_COHORT_5_CAPABILITY_INVENTORY.md` Group C) — they are now
`M6`-owned, `DEFERRED_WITH_EXPLICIT_OWNER`. This is disclosed here
explicitly rather than achieving a clean `UNRESOLVED_M5_CAPABILITIES = 0`
by simply moving the count out of the M5 column without saying so.

## M5_STATUS remains IN_PROGRESS (instruction item 19)

Per explicit instruction, closing Cohort 5's own capability work does
**not** advance `M5_STATUS` to `READY_FOR_APPROVAL`. That requires a
separate M5 final closure regression against a stable qualified
checkpoint — not run automatically as part of this Cohort, per the same
instruction's own closing line ("Do not start the M5 final full
regression automatically unless the standing Canonical governance
explicitly requires it as part of this same Cohort-5 task" — it does
not; Cohort 5's own regression requirement, item 16, is scoped to THIS
Cohort's own capabilities' focused/caller/preservation tests, which this
Cohort satisfied in full — see `M5_COHORT_5_TEST_EVIDENCE.md` — not a
repo-wide final regression).

```
M5_STATUS = IN_PROGRESS
NEXT_RECOMMENDED_GATE = M5_FINAL_CLOSURE_REGRESSION (awaiting explicit dispatch)
```
