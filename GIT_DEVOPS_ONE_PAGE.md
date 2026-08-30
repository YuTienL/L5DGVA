> See START_HERE.md for the canonical entry point and current mechanism overview; this page remains accurate for its specific topic.

# Generic DV Workflow + Git/DevOps

```text
Developer / AI
     ↓
 Git Pull / Sync
     ↓
 Branch / Modify
     ↓
 Review / Commit
     ↓
     PUSH
     ↓
 Exact Commit SHA
     ↓
 Linux Server Checkout
     ↓
 Source Environment
     ↓
 BUILD
     ↓
 Target VERIFY
     ↓
 LSF Regression
     ↓
 Monitor / Failure Triage
     ↓
 FSDB / fsdbreport / Verdi
     ↓
 Fix → Commit → Push → Rerun
     ↓
 Regression Report
     ↓
 Signoff
     ↓
 Tag / Release
```

Source identity is part of verification evidence.
