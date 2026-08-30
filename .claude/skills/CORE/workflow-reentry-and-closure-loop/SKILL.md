---
name: workflow-reentry-and-closure-loop
description: Mandatory re-analysis loop after fixes; promotion is blocked until a second detailed workflow pass finds no remaining omissions.
---
# Workflow Re-entry and Closure Loop

Mandatory sequence:

1. Let the current workflow finish its full analysis.
2. Collect **all** discovered problems, defects, omissions, contradictions, and recommendations.
3. Fix **all** discovered problems together; remove obsolete/unrelated comments and stale artifacts.
4. Re-launch the workflow for a new detailed analysis.
5. Check specifically for secondary omissions introduced or revealed by the fixes.
6. If any issue remains, repeat steps 2–5.
7. Only when the detailed re-analysis returns clean may the flow proceed to:
   `push → build → verify → run`.
8. After `run`, apply WAVE=0 semantic postcheck and, if needed, focused WAVE=1/fsdbreport debug.

A first-pass fix is never considered final closure without the second detailed workflow pass.
