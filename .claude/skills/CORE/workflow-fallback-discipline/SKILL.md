---
name: workflow-fallback-discipline
description: When a Workflow tool step fails repeatedly with an infrastructure-level error (not a task-logic error), diagnose whether the failure is scoped to that specific dispatch mechanism, then fall back to a direct Agent-tool dispatch with an equivalent self-contained prompt rather than retrying the same call indefinitely or abandoning the work.
allowed-tools: Read Grep Glob
---
# Workflow Fallback Discipline

This skill answers a narrow, coordinator-level question: what should the session
DO when a `Workflow` tool step keeps failing, given that a `Workflow` step and a
plain `Agent` dispatch are two different mechanisms for the same underlying
action (running a subagent to completion and getting its result back)?

## The real incident this was distilled from

2026-09-03, this project. A `Workflow` script's final step (`integrate-and-commit`,
`model: 'claude-opus-5'`) failed four times in a row, every time with:

```
API Error: 500 Internal server error. This is a server-side issue, usually
temporary -- try again in a moment.
```

Two diagnostic facts made this actionable rather than just "retry until it
works":

1. **Every failure was near-instant (~3.2-3.4s) and consumed 0 tokens.** The
   step never actually started doing work -- it failed at dispatch, not
   mid-task. A task-logic failure (a bug in the prompt, a real error the
   subagent hit) would show real token/tool-call usage before failing; this
   didn't.
2. **A separate `Agent`-tool dispatch, launched around the same time, running
   on the same model, was progressing normally** (real tool calls, real token
   usage, eventually completed successfully). This ruled out a blanket
   service outage -- the failure was scoped to something about that specific
   `Workflow` step's dispatch, not to the API in general.

Three retries of the identical `Workflow` step (via `resumeFromRunId`, so the
already-completed sibling steps replayed from cache each time at zero cost)
all failed the same way. At that point the correct move was not a fourth
identical retry -- it was switching mechanism: the same task was re-issued as
a plain `Agent` tool call, with a self-contained prompt covering everything
the failed `Workflow` step was supposed to do (re-stating the two completed
sibling steps' real results inline, since a fresh `Agent` dispatch has no
access to the `Workflow` run's own cached state). It succeeded on the first
attempt.

## The general rule

When a `Workflow` step fails with a **server/infrastructure-shaped** error
(HTTP 5xx, "temporary", "try again"), not a **task-logic-shaped** one (an
assertion in the subagent's own work, a real tool error it reported):

1. **Check whether the failure is instant and near-zero-cost** (little to no
   token usage, failure within a few seconds of dispatch). This is the
   signature of a dispatch-level failure, not a subagent that started working
   and then hit a problem.
2. **Check for an independent, concurrently-running dispatch on the same
   model** (another `Agent` call, another `Workflow` step) that IS
   progressing normally. If one exists, the failure is scoped to the specific
   failing call, not a general outage -- do not wait out a "service status"
   check, switch mechanism instead. If no such independent success exists,
   this diagnostic step can't rule out a general outage; a brief genuine wait
   before switching mechanism is reasonable in that case.
3. **Retry the identical call at most 2-3 times** (a `Workflow` step supports
   this cheaply via `resumeFromRunId`, replaying completed sibling steps from
   cache). Do not retry indefinitely -- a repeated identical failure with the
   same near-instant, zero-cost signature across 3+ attempts is itself
   evidence the retry isn't going to start succeeding on its own.
4. **Fall back to a plain `Agent` tool dispatch** for that one failing step,
   with a prompt that is fully self-contained: restate whatever the failed
   step needed from its sibling steps' real results (a fresh `Agent` call has
   no access to the `Workflow` run's cached context), and restate the same
   concrete task/scope/verification bar the `Workflow` step itself specified.
   Do not weaken the task's requirements just because the delivery mechanism
   changed.
5. **Never silently drop the work.** The failure is a dispatch-mechanism
   problem, not a signal that the task itself was wrong or unnecessary -- the
   fallback dispatch should complete the exact same real deliverable (files
   changed, commits made, tests passing) the `Workflow` step was meant to
   produce.

## What this skill does NOT cover

- A `Workflow` step failing with a task-logic error (the subagent's own
  report says `BLOCKED`, or a real assertion/test failure) -- that is a
  normal subagent-driven-development escalation (see
  `superpowers:subagent-driven-development`'s own BLOCKED handling), not an
  infrastructure fallback.
- Switching mechanism preemptively, before the failure signature above is
  actually observed -- `Workflow` is still the right tool for genuinely
  multi-step, multi-agent orchestration (parallel fan-out, phase sequencing,
  cached resume); this skill is about recovering from an infra-level failure
  in one specific step, not a reason to prefer `Agent` calls generally.
