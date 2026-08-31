#!/bin/sh
# =============================================================================
# lsf_wait.sh -- block until a named LSF job finishes, and exit with its status
#
#   sh lsf_wait.sh <job_name> <timeout_minutes> [artifact]
#
# <artifact> is a file the job is expected to have produced. When given, this
# does not return until that file is actually visible here -- see the DONE
# branch for why that is a separate question from the job having finished.
#
# WHY THIS IS NEEDED
# ------------------
# The site's vcs wrapper submits with -lsfon and returns immediately:
#
#     $ make compile LSF=1
#     Job <93283> is submitted to queue <vcs>.
#     warnings: 159
#     errors  : 0
#     real  0m2.684s
#
# Two and a half seconds for an elaboration that takes seven minutes. The
# counts printed there came from the PREVIOUS build's compile.log, and the
# job itself went on to fail. Nothing in that output says so.
#
# That is the failure this guards: make has to know the build finished, and
# whether it worked, before anything depends on simv.
#
# HOW THE JOB IS IDENTIFIED
# -------------------------
# By name, taking the highest job id that carries it. Job ids increase, so the
# highest is the one just submitted. A stale job of the same name from an
# earlier run can still be listed -- LSF keeps finished jobs for CLEAN_PERIOD
# -- but it necessarily has a lower id.
#
# Reading the id from the submit message would be exact, but it costs a pipe
# around the tool command, and `cmd | tee` returns tee's status, which would
# quietly turn a failed local compile into a successful one. Not worth it.
# =============================================================================
set -u

NAME=${1:-}
TIMEOUT_MIN=${2:-180}
ARTIFACT=${3:-}
POLL=15

# How long to keep looking for the artifact after the job says DONE.
# Bounded on purpose -- see wait_for_artifact.
ART_WAIT=${ART_WAIT:-60}

if [ -z "$NAME" ]; then
  echo "lsf_wait: no job name" >&2
  exit 2
fi

# -----------------------------------------------------------------------------
# "The job finished" and "its output is visible here" are two different facts.
#
# The job ran on another host and wrote through NFS; the status flips on the
# LSF master as soon as the process exits. Observed directly: an elaboration
# reported DONE while `ls output/simv` said no such file, and the file's own
# timestamp turned out to be that very second.
#
# A fixed sleep is the wrong answer to this. NFS attribute cache lifetimes are
# tens of seconds and configurable, so any constant is either too short --
# failing intermittently, which is the worst kind -- or pure waiting. Wait for
# the CONDITION and return the moment it holds.
#
# BOUNDED, though. An unbounded wait on a file that will never appear is a
# hang whose only symptom is silence, and it would replace a clear failure
# with no failure at all. On expiry this says exactly what it was waiting for
# and fails; it never returns success on a guess.
#
# `ls` on the parent directory each round is not decoration -- it is what
# invalidates the cached directory entry, so a plain `test -e` alone can keep
# answering from the same stale cache.
# -----------------------------------------------------------------------------
wait_for_artifact() {
  [ -n "$ARTIFACT" ] || return 0

  _end=$(( $(date +%s) + ART_WAIT ))
  while : ; do
    ls "$(dirname "$ARTIFACT")" >/dev/null 2>&1
    [ -e "$ARTIFACT" ] && return 0
    if [ "$(date +%s)" -ge "$_end" ]; then
      echo "[lsf] job $NAME reported DONE but $ARTIFACT never appeared" >&2
      echo "      (waited ${ART_WAIT}s for it to become visible here)." >&2
      echo "      The job succeeded and produced nothing at that path, or" >&2
      echo "      the path is not on storage shared with the execution host." >&2
      return 1
    fi
    sleep 2
  done
}

newest_id() {
  bjobs -a -noheader -o "jobid" -J "$NAME" 2>/dev/null \
    | sed 's/[^0-9]//g' | grep -v '^$' | sort -n | tail -1
}

# The job may not be registered the instant the wrapper returns.
jid=""
i=0
while [ $i -lt 20 ]; do
  jid=$(newest_id)
  [ -n "$jid" ] && break
  sleep 2
  i=$((i + 1))
done

if [ -z "$jid" ]; then
  echo "lsf_wait: no LSF job named '$NAME' appeared within 40s." >&2
  echo "          The submission probably failed. Check the output above." >&2
  exit 1
fi

echo "[lsf] waiting for $NAME (job $jid), limit ${TIMEOUT_MIN}min"

deadline=$(( $(date +%s) + TIMEOUT_MIN * 60 ))
last=""
while : ; do
  line=$(bjobs -a -noheader -o "stat exit_code delimiter='|'" "$jid" 2>/dev/null | head -1)
  stat=$(echo "$line" | cut -d'|' -f1)
  code=$(echo "$line" | cut -d'|' -f2)
  [ -n "$stat" ] || stat="?"

  case "$stat" in
    PEND|RUN|PSUSP|USUSP|SSUSP|WAIT|"?")
      if [ "$stat" != "$last" ]; then
        echo "[lsf]   $stat"
        last="$stat"
      fi
      ;;
    DONE)
      wait_for_artifact || exit 1
      echo "[lsf] job $jid finished ok"
      exit 0
      ;;
    *)
      # EXIT, TERM, ZOMBI and the rest all mean the build did not complete.
      echo "[lsf] job $jid ended $stat${code:+ (exit $code)}" >&2
      exit 1
      ;;
  esac

  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "[lsf] job $jid still $stat after ${TIMEOUT_MIN}min -- killing it" >&2
    bkill "$jid" >/dev/null 2>&1
    exit 1
  fi
  sleep "$POLL"
done
