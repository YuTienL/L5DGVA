#!/bin/sh
# =============================================================================
# lsf_regress.sh -- run a pattern suite as LSF jobs, one job per pattern
#
# Called by `make regress LSF=1`. Everything arrives through the environment
# because the Makefile already knows these values and passing twenty of them
# as positional arguments is how quoting bugs get in.
#
# WHY A SCRIPT AND NOT A MAKE RECIPE
# ----------------------------------
# Submitting is the easy part. What follows -- polling, deciding a job has
# hung, killing it, and reporting a verdict per pattern -- is a loop with
# state, and a make recipe is a bad place for that: every line is its own
# shell, and $ has to be escaped twice.
#
# WHAT ONE JOB IS
# ---------------
# One pattern at one seed, running `make sim`, which runs the SHARED simv from
# its OWN directory (run/<job>/). The elaboration happens once, before any job
# is submitted, on the submit host. Jobs never build.
#
# THE THREE WAYS A JOB CAN FAIL TO END
# ------------------------------------
#   1  it finishes and reports a verdict            -> read the log
#   2  it runs forever                              -> LSF -W kills it
#   3  it is alive but making no progress           -> the idle check kills it
#
# 2 and 3 are different. The `vcs` queue carries NO RUNLIMIT (bqueues -l vcs
# prints none), so without -W nothing at all bounds a job -- it holds a licence
# and a host until someone notices. 3 is the case -W cannot see quickly: a
# simulation stuck in a loop still consumes its full runtime limit before
# being killed, while its log stops growing within seconds. Watching the log
# catches it in minutes rather than hours.
# =============================================================================
set -u

# --- inputs, all supplied by the Makefile ------------------------------------
: "${PATTERNS:=}"
: "${SUITE:=all}"
: "${SEED:=1}"
: "${SIM_ROOT:=}"
: "${LOGDIR:=}"
: "${REPORTDIR:=}"
: "${MAKE_PASS:=}"
: "${MAKE_BIN:=make}"

: "${LSF_QUEUE:=vcs}"
: "${LSF_TIMEOUT:=60}"          # minutes, becomes bsub -W
: "${LSF_JOBS:=8}"              # how many may run at once
: "${LSF_SETUP:=}"              # a file to source inside the job
: "${LSF_RES:=}"                # extra bsub -R
: "${LSF_POLL:=20}"             # seconds between status refreshes
# Minutes without the pattern reporting progress before it is called hung.
# Measured against the pattern's own "[pattern] ..." markers, so raise it for
# a pattern with one legitimately long step rather than lowering the bar to
# some side effect that happens to keep moving.
: "${LSF_IDLE:=10}"
: "${LSF_HANG_KILL:=1}"         # kill a job the idle check calls hung
: "${LSF_PREFLIGHT:=1}"         # verify the environment on a host first
# IP_PREFIX/TARGET_IP follow the same vocabulary as the Makefile; override
# for a different protocol, or leave the default (this template's original
# USB proving-ground project) to run standalone unmodified.
: "${IP_PREFIX:=usb_}"
: "${TARGET_IP:=USB}"
IP_PREFIX_STEM="${IP_PREFIX%_}"
: "${LSF_GROUP:=/${IP_PREFIX_STEM}reg}"

# Report on a regression that is already running or has already finished,
# instead of submitting a new one.
#
# The jobs outlive the thing that submitted them -- they are LSF jobs, not
# children of this shell -- but the polling loop does not. A dropped
# connection, a closed terminal or a timeout therefore leaves four jobs
# running perfectly well and nobody to write the summary. Without this the
# only way to get the table back is to run the whole suite again.
: "${LSF_SUMMARY_ONLY:=0}"

if [ -z "$PATTERNS" ]; then echo "lsf_regress: no patterns"; exit 1; fi
if [ -z "$SIM_ROOT" ]; then echo "lsf_regress: SIM_ROOT unset"; exit 1; fi

GROUP="$LSF_GROUP/$SUITE"
PREFIX="${IP_PREFIX_STEM}reg.$SUITE"
LSFLOG="$LOGDIR/lsf"
mkdir -p "$LSFLOG"

# The state file carries one line per job: pattern jobid.
# A file rather than a shell variable so a crashed harness can still be
# cleaned up by hand -- `make lsf_kill` reads the same file.
STATE="$LSFLOG/${SUITE}_${SEED}.jobs"

if [ "$LSF_SUMMARY_ONLY" = "1" ]; then
  if [ ! -s "$STATE" ]; then
    echo "No regression to report on: $STATE is empty or absent."
    echo "It is written when a regression is submitted, so either none has"
    echo "been run for suite '$SUITE' at seed $SEED, or it was cleaned away."
    exit 1
  fi
  echo "=== reporting on the regression recorded in $STATE ==="
  echo "    nothing is submitted; jobs still running are shown as they are"
  # A REPORT MUST NOT HAVE SIDE EFFECTS.
  #
  # This mode reuses the poll loop, and that loop kills jobs it judges hung.
  # So without this, asking "how is it going" could end the thing being asked
  # about -- and it would do so using a stall clock that starts when the
  # report starts, not when the job did. Reporting is read-only.
  LSF_HANG_KILL=0
else
  : > "$STATE"
fi

hr() { echo "-------------------------------------------------------------------------------"; }

# -----------------------------------------------------------------------------
# When this regression started. Everything that reads a log compares against
# it, because a log FILE at the expected path is not evidence of a log from
# THIS run: the path is <pattern>_<seed>, so a rerun at the same seed finds
# the previous one sitting there.
#
# Both things that read logs got this wrong on the first real run:
#
#   the idle check   a job three seconds old was reported "idle 239m" and
#                    killed -- 239 minutes being the age of the log from a
#                    run four hours earlier
#   the summary      that same killed job was recorded PASSED, because the
#                    old log said so
#
# A verdict from a stale log is worse than no verdict, so a log older than
# this is treated as absent.
# -----------------------------------------------------------------------------
#
# In summary-only mode this must be when the regression was SUBMITTED, not
# now. The state file is written at submission, so its mtime is that moment.
# Taking the current time instead would make every log older than T0 and
# report the whole suite as having produced no result -- turning a report on a
# finished regression into a report that it never ran.
if [ "$LSF_SUMMARY_ONLY" = "1" ]; then
  T0=$(stat -c %Y "$STATE" 2>/dev/null || echo 0)
else
  T0=$(date +%s)
fi

# -----------------------------------------------------------------------------
# What the testbench itself reported, taken from its own epilogue:
#
#     [command.txt] FINAL CHECK @ 13294.388 ns
#       UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0
#       VERDICT: PASSED
#
# Worth a column each. PASS/FAIL alone cannot distinguish a run that did the
# work cleanly from one that passed with warnings, nor a pattern that
# simulated 13 us from one that gave up after 200 ns -- and those are the two
# questions actually asked of a regression table.
#
# Sets L_SIM, L_FATAL, L_ERR, L_WARN.
# -----------------------------------------------------------------------------
log_facts() {
  L_SIM="."; L_FATAL="."; L_ERR="."; L_WARN="."
  [ -f "$1" ] || return 0
  _f=$(grep -m1 "FINAL CHECK @" "$1" 2>/dev/null)
  [ -n "$_f" ] && L_SIM=$(echo "$_f" | sed -n 's/.*@ *\([0-9.]*\) *\([a-z]*\).*/\1\2/p')
  _c=$(grep -m1 "UVM_FATAL *=" "$1" 2>/dev/null)
  if [ -n "$_c" ]; then
    L_FATAL=$(echo "$_c" | sed -n 's/.*UVM_FATAL *= *\([0-9]*\).*/\1/p')
    L_ERR=$(echo   "$_c" | sed -n 's/.*UVM_ERROR *= *\([0-9]*\).*/\1/p')
    L_WARN=$(echo  "$_c" | sed -n 's/.*UVM_WARNING *= *\([0-9]*\).*/\1/p')
  fi
  [ -n "$L_SIM" ]   || L_SIM="."
  [ -n "$L_FATAL" ] || L_FATAL="."
  [ -n "$L_ERR" ]   || L_ERR="."
  [ -n "$L_WARN" ]  || L_WARN="."
}

# Is this pattern's log from the current run?
log_is_current() {
  [ -f "$1" ] || return 1
  _m=$(stat -L -c %Y "$1" 2>/dev/null || echo 0)
  [ "$_m" -ge "$T0" ]
}

# -----------------------------------------------------------------------------
# The job script.
#
# ENVIRONMENT. bsub copies the submitting shell's environment to the execution
# host, so a `make regress` launched from a set-up shell already carries
# VIP_HOME, DUT_ROOT_PATH, PATH and the licence variables. That covers the
# normal case, and it is why LSF_SETUP is empty by default.
#
# It is not sufficient in two situations, which is why LSF_SETUP exists:
#   - submitting from a shell that never sourced the site setup. The failure
#     lands on the execution host as "vcs: not found", far from the cause.
#   - a setup that defines shell state rather than variables. Only variables
#     are copied.
#
# This site's setup is csh (source version.csh, then env.csh), so when
# LSF_SETUP names a .csh the wrapper is written as csh. Mixing them silently
# is the trap: `.` on a csh file under sh produces a cascade of syntax errors
# and then runs make anyway, with the environment half set.
# -----------------------------------------------------------------------------
#
# The job runs `make run`, NEVER `make sim`. sim has $(SIMV) as a prerequisite,
# so with sim each job decides for itself whether the build is current -- and
# four jobs that all decide "no" run four concurrent elaborations into one
# output directory. That happened; the symptom was a page of
#   rm: cannot remove '.../output/csrc/objs/rts.191046.info': Stale file handle
# and a simv that had taken nineteen minutes to build was destroyed by the very
# patterns that were supposed to be running on it.
#
# NOTE FOR ANYONE EDITING THE HEREDOCS BELOW: they are UNQUOTED, because $SEED
# and $MAKE_PASS have to expand here. That also makes backticks and $(...)
# active. A comment written inside one of them with `word` in it does not
# become a comment in the generated file -- the surrounding shell runs `word`
# first, which is why this explanation lives out here instead of in there.
WRAPPER="$LSFLOG/${SUITE}_${SEED}.job"

case "$LSF_SETUP" in
  *.csh)
    cat > "$WRAPPER" <<CSHEOF
#!/bin/csh -f
source $LSF_SETUP
cd $SIM_ROOT
$MAKE_BIN run PATTERN=\$1 SEED=$SEED $MAKE_PASS
CSHEOF
    ;;
  *)
    cat > "$WRAPPER" <<SHEOF
#!/bin/sh
if [ -n "$LSF_SETUP" ]; then . "$LSF_SETUP"; fi
cd $SIM_ROOT
exec $MAKE_BIN run PATTERN=\$1 SEED=$SEED $MAKE_PASS
SHEOF
    ;;
esac
chmod +x "$WRAPPER"

# -----------------------------------------------------------------------------
# Preflight.
#
# One tiny job that proves, on a real execution host, the three things every
# other job assumes: the tools resolve, the VIP is readable, and simv exists
# on shared storage. Thirty jobs failing identically for one of these reasons
# costs far more than the half minute this takes, and the error they produce
# points at the pattern rather than at the environment.
# -----------------------------------------------------------------------------
if [ "$LSF_PREFLIGHT" = "1" ] && [ "$LSF_SUMMARY_ONLY" != "1" ]; then
  echo "=== preflight on queue $LSF_QUEUE ==="
  PRE="$LSFLOG/preflight.out"
  rm -f "$PRE"

  # -K blocks until the job finishes, which is what makes this a gate rather
  # than a race against the submissions below. $VIP_HOME is escaped so the
  # submitting shell leaves it alone and the EXECUTION host expands it --
  # that is the whole point of the check.
  bsub -q "$LSF_QUEUE" -W 5 -K -J "$PREFIX.preflight" -o "$PRE" \
       ${LSF_RES:+-R "$LSF_RES"} \
       "hostname; which vcs || echo NO_VCS; \
        test -x $SIM_ROOT/output/simv && echo SIMV_OK || echo NO_SIMV; \
        test -d \$VIP_HOME && echo VIP_OK || echo NO_VIP" >/dev/null 2>&1

  # ANCHORED. LSF writes the job's own command line into the output file
  # before the output, so an unanchored search for NO_VCS matched the text of
  # the test rather than its result -- and the preflight failed every time,
  # reporting all three problems at once on a host where nothing was wrong.
  #
  # All three "failing" together is itself the tell: a real environment fault
  # takes out one of them, not the tools AND the build AND the VIP.
  if [ -f "$PRE" ]; then
    if grep -qE '^(NO_VCS|NO_SIMV|NO_VIP)$' "$PRE" 2>/dev/null; then
      echo "PREFLIGHT FAILED. The execution host cannot see something it needs:"
      grep -E '^(NO_VCS|NO_SIMV|NO_VIP|SIMV_OK|VIP_OK|icr[0-9]+)$' "$PRE" \
        | sed 's/^/    /'
      echo ""
      echo "  NO_VCS   the tool setup did not reach the job."
      echo "           Submit from a set-up shell, or pass the setup explicitly:"
      echo "               make regress LSF=1 LSF_SETUP=/path/to/env.csh"
      echo "  NO_SIMV  $SIM_ROOT/output/simv is not visible from the host."
      echo "           The build tree must be on shared storage; the vcs queue"
      echo "           runs on other machines than the submit host."
      echo "  NO_VIP   VIP_HOME is unset or unreadable there."
      exit 1
    fi
    echo "preflight ok:"
    grep -E '^(SIMV_OK|VIP_OK|icr[0-9]+)$' "$PRE" | sed 's/^/    /' | head -4
  fi
  hr
fi

# -----------------------------------------------------------------------------
# Concurrency.
#
# An LSF job group with a limit is the right control: the jobs are all
# submitted at once and LSF releases them as slots free, so the queue does the
# scheduling rather than this script sleeping in a loop. bgadd fails harmlessly
# if the group already exists, and if job groups are not enabled at this site
# the submissions below still work -- they just run at whatever width the
# queue allows, which is reported rather than hidden.
# -----------------------------------------------------------------------------
# GRP_OPT holds the flag itself, empty when there is no group. It is NOT a
# 0/1 flag consumed by ${VAR:+...}: that expands whenever the variable is
# non-empty, and the string "0" is non-empty -- so a failed bgadd would still
# have passed -g and every submission would have been rejected.
GRP_OPT=""
if [ "$LSF_SUMMARY_ONLY" = "1" ]; then
  :
elif bgadd -L "$LSF_JOBS" "$GROUP" >/dev/null 2>&1 \
   || bgmod -L "$LSF_JOBS" "$GROUP" >/dev/null 2>&1; then
  GRP_OPT="-g $GROUP"
else
  echo "note: job group $GROUP unavailable, so LSF_JOBS=$LSF_JOBS is not"
  echo "      enforced. Jobs run at whatever width queue $LSF_QUEUE allows."
fi

# --- submit ------------------------------------------------------------------
if [ "$LSF_SUMMARY_ONLY" = "1" ]; then
  echo "  (submission skipped)"
else
echo "=== LSF regression ==="
echo "  suite    $SUITE   seed $SEED"
echo "  queue    $LSF_QUEUE"
echo "  limit    $LSF_JOBS concurrent, $LSF_TIMEOUT min per job"
echo "  simv     $SIM_ROOT/output/simv   (shared, built once)"
echo "  logs     $LOGDIR"
hr

n_sub=0
for p in $PATTERNS; do
  out="$LSFLOG/${p}_${SEED}.lsf"
  rm -f "$out"
  jid=$(bsub -q "$LSF_QUEUE" \
             -W "$LSF_TIMEOUT" \
             -J "$PREFIX.$p" \
             $GRP_OPT \
             ${LSF_RES:+-R "$LSF_RES"} \
             -o "$out" \
             "$WRAPPER" "$p" 2>&1 | sed -n 's/^Job <\([0-9]*\)>.*/\1/p')
  if [ -n "$jid" ]; then
    echo "$p $jid" >> "$STATE"
    n_sub=$((n_sub + 1))
    printf '  submitted %-28s job %s\n' "$p" "$jid"
  else
    printf '  SUBMIT FAILED %-24s\n' "$p"
  fi
done
hr
echo "$n_sub job(s) submitted. Polling every ${LSF_POLL}s."
echo "Kill them all with:  make lsf_kill SUITE=$SUITE"
hr
fi

# -----------------------------------------------------------------------------
# Poll.
#
# bjobs -a includes finished jobs, so one query covers both the running set
# and the verdicts, without needing bhist. -noheader and -o keep the format
# fixed rather than depending on the site's default bjobs columns.
#
# The idle check reads each pattern's own log. A job that is RUN but whose log
# has not grown for LSF_IDLE minutes is not progressing: simulation writes
# continuously, so a still log means stuck, not quiet.
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Which fields does this bjobs accept?
#
# Probed once rather than assumed. A single unrecognised field makes bjobs
# reject the WHOLE query, so one wrong guess here would leave every column
# blank for the entire regression -- and the earlier `delimiter=|` attempt
# showed this bjobs does reject what it does not like rather than ignoring it.
#
# pend_time is the one in question: it is how long the job waited in the
# queue, which is the difference between "the farm is busy" and "this pattern
# is slow", and those call for completely different responses.
# -----------------------------------------------------------------------------
# Tried richest first and degraded, so a cluster missing one field loses that
# column instead of every column.
JF_FULL="stat run_time pend_time exec_host exit_code queue cpu_used max_mem"
JF_MID="stat run_time pend_time exec_host exit_code"
JF_BASE="stat run_time exec_host exit_code"

bjobs_ok() {
  case "$(bjobs -a -noheader -o "$1 delimiter='|'" 2>&1 | head -1)" in
    *nvalid*|*nknown*|*not\ a\ valid*|*Illegal*|*llegal*) return 1 ;;
    *) return 0 ;;
  esac
}

if bjobs_ok "$JF_FULL";   then JFIELDS="$JF_FULL"; JF_LEVEL=full
elif bjobs_ok "$JF_MID";  then JFIELDS="$JF_MID";  JF_LEVEL=mid
                               echo "note: bjobs has no cpu_used/max_mem here"
else                           JFIELDS="$JF_BASE"; JF_LEVEL=base
                               echo "note: bjobs has no pend_time here, queue wait not reported"
fi

# -----------------------------------------------------------------------------
# Ask LSF about one job.
#
# The delimiter is not decoration. Without it bjobs separates fields with
# spaces and run_time is itself several words -- "5 second(s)", and
# "1 hour(s) 5 minute(s)" when a job has been going a while. Field N is
# therefore not column N, and any awk that assumes it is silently reports the
# wrong host as soon as jobs get long enough to matter. Confirmed on this
# cluster: bjobs -o "... delimiter='|'" is accepted, so parse on that.
#
# Sets J_STAT, J_RT, J_HOST, J_EXIT.
# -----------------------------------------------------------------------------
job_query() {
  _l=$(bjobs -a -noheader -o "$JFIELDS delimiter='|'" "$1" 2>/dev/null | head -1)
  J_STAT=$(echo "$_l" | cut -d'|' -f1)
  J_RT=$(echo   "$_l" | cut -d'|' -f2)
  J_WAIT=""; J_QUEUE="."; J_CPU="."; J_MEM="."
  case "$JF_LEVEL" in
    full)
      J_WAIT=$(echo  "$_l" | cut -d'|' -f3)
      J_HOST=$(echo  "$_l" | cut -d'|' -f4)
      J_EXIT=$(echo  "$_l" | cut -d'|' -f5)
      J_QUEUE=$(echo "$_l" | cut -d'|' -f6)
      J_CPU=$(echo   "$_l" | cut -d'|' -f7)
      J_MEM=$(echo   "$_l" | cut -d'|' -f8) ;;
    mid)
      J_WAIT=$(echo "$_l" | cut -d'|' -f3)
      J_HOST=$(echo "$_l" | cut -d'|' -f4)
      J_EXIT=$(echo "$_l" | cut -d'|' -f5) ;;
    *)
      J_HOST=$(echo "$_l" | cut -d'|' -f3)
      J_EXIT=$(echo "$_l" | cut -d'|' -f4) ;;
  esac
  [ -n "$J_QUEUE" ] && [ "$J_QUEUE" != "-" ] || J_QUEUE="."
  [ -n "$J_CPU" ]   && [ "$J_CPU"   != "-" ] || J_CPU="."
  [ -n "$J_MEM" ]   && [ "$J_MEM"   != "-" ] || J_MEM="."
  J_CPU=$(secs "$J_CPU")
  [ -n "$J_STAT" ] || J_STAT="?"
  # LSF prints - for a field it has no value for; blank or a dot reads better.
  [ "$J_EXIT" = "-" ] && J_EXIT=""
  [ -n "$J_HOST" ] && [ "$J_HOST" != "-" ] || J_HOST="."
  [ -n "$J_RT"   ] && [ "$J_RT"   != "-" ] || J_RT="."
  [ -n "$J_WAIT" ] && [ "$J_WAIT" != "-" ] || J_WAIT="."
  J_RT=$(secs "$J_RT")
  J_WAIT=$(secs "$J_WAIT")
}

# LSF says "5 second(s)" and "1 hour(s) 5 minute(s)" -- readable in isolation,
# useless in a column. Reduce to one compact token so the numbers line up and
# a slow pattern is visible at a glance.
secs() {
  case "$1" in
    .|"") echo "."; return ;;
  esac
  echo "$1" | awk '
    { t = 0
      if (NF == 1) {
        # A bare number, which is how cpu_used comes back on some clusters.
        # The paired loop below would skip it entirely and print 0s -- a
        # plausible-looking value that is simply wrong, which is worse than
        # a blank.
        t = $1 + 0
      } else {
        for (i = 1; i < NF; i += 2) {
          n = $i + 0
          if ($(i+1) ~ /hour/)     t += n * 3600
          else if ($(i+1) ~ /min/) t += n * 60
          else t += n
        }
      }
      if (t >= 3600) printf "%dh%02dm", t/3600, (t%3600)/60
      else if (t >= 60) printf "%dm%02ds", t/60, t%60
      else printf "%ds", t
    }'
}

# -----------------------------------------------------------------------------
# How long since the PATTERN last reported progress, in seconds. -1 means it
# has not reported any yet, which is normal for a job that just started.
#
# The signal is the pattern's own marker -- the "[pattern] ..." lines it
# prints as it moves through its script:
#
#     [pattern] STAGE 2 : APB access path self check @ 11979.000 ns
#     [pattern] STAGE 3 : clock verification @ 12746.000 ns
#     [pattern] base setup complete, entering the pattern body @ 12819.000 ns
#     [pattern] 64 randomized APB write and read pairs
#
# TWO EARLIER SIGNALS WERE TRIED AND BOTH WERE PROXIES FOR THIS ONE.
#
# Log growth was first. It killed apb_selftest after fifteen minutes:
#     apb_selftest  EXIT/143  RUN 15m02s  CPU 20m45s   killed as hung
# CPU time greater than wall clock -- the job was working and saying nothing,
# because at UVM_LOW a pattern prints nothing between transactions.
#
# So the check moved to cpu_used, and that missed the opposite case. When
# apb_selftest really did wedge, the log showed why:
#     @   12819 ns  [launcher] running '<ip>_apb_wr_rd_seq' on 'apb'
#     @  649527 ns  [manage_objections] Timed out due to bus inactivity
#     @ 1289527 ns  ... the same, every 640000 ns
# The pattern had made no progress since 12819 ns. Clocks were still running,
# so CPU advanced; the AXI VIP complained every 640 us, so the log grew. Both
# signals said "alive" about a simulation that had stopped doing anything.
#
# The marker has neither blind spot, because it is not a proxy: it is the
# pattern stating where it has got to. It also makes the report say something
# useful -- "stuck at: 64 randomized APB write and read pairs" points at the
# problem, where "log idle" only says that something is wrong.
#
# What it costs: a pattern whose single step legitimately takes longer than
# LSF_IDLE is reported as hung. That is a real trade, and the right response
# is to raise LSF_IDLE rather than to go back to guessing from side effects.
# LSF_TIMEOUT (-W) remains the outer bound in every case.
#
# CPU is still read, but only to describe the stall rather than to gate it:
# stuck-and-burning-CPU is a spin, stuck-and-idle is a deadlock, and they lead
# to different places. Sets P_NOTE for the report.
#
# State per job in a file rather than a variable: the poll loop runs in a
# `while read` pipeline, so assignments inside it would not survive.
# -----------------------------------------------------------------------------
progress_age() {
  _jid=$1; _log=$2
  _f="$LSFLOG/.prog.$_jid"
  _now=$(date +%s)

  # The last marker the pattern printed. A full scan rather than a tail, so a
  # long quiet spell cannot push the marker out of the window and make a
  # stalled job look like it changed.
  _mark=$(grep '\[pattern\]' "$_log" 2>/dev/null | tail -1)
  P_LAST=$(echo "$_mark" | sed -e 's/.*\[pattern\] *//' -e 's/ *@.*//' | cut -c1-40)

  _cpu=$(bjobs -a -noheader -o "cpu_used" "$_jid" 2>/dev/null | head -1)
  _cpu=$(echo "$_cpu" | tr -cd '0-9')
  [ -n "$_cpu" ] || _cpu=0

  if [ -z "$_mark" ]; then
    # Nothing yet. Not a stall -- the pattern has not started reporting.
    P_NOTE="starting"
    echo -1
    return
  fi

  if [ ! -f "$_f" ]; then
    printf '%s\t%s\t%s\n' "$_now" "$_cpu" "$_mark" > "$_f"
    P_NOTE="$P_LAST"
    echo 0
    return
  fi

  _since=$(cut -f1 "$_f")
  _pcpu=$(cut -f2 "$_f")
  _pmark=$(cut -f3- "$_f")

  if [ "$_mark" != "$_pmark" ]; then
    printf '%s\t%s\t%s\n' "$_now" "$_cpu" "$_mark" > "$_f"
    P_NOTE="$P_LAST"
    echo 0
  else
    # Stalled. Say whether it is spinning or idle -- different causes.
    if [ "$_cpu" -gt "$_pcpu" ] 2>/dev/null; then
      P_NOTE="at: $P_LAST (cpu still rising)"
    else
      P_NOTE="at: $P_LAST (no cpu)"
    fi
    echo $(( _now - _since ))
  fi
}

# Set by progress_age; declared here so `set -u` cannot trip on a path that
# reads them before it has run.
P_LAST=""
P_NOTE=""

killed_list=""
while : ; do
  running=0; pending=0; done_n=0
  echo ""
  echo "=== $(date '+%H:%M:%S')  suite $SUITE ==="
  printf '  %-24s %-8s %-7s %-8s %-8s %-9s %s\n' \
         PATTERN JOBID STAT WAIT RUN HOST NOTE

  while read -r p jid; do
    [ -n "$jid" ] || continue
    job_query "$jid"
    stat="$J_STAT"; rt="$J_RT"; host="$J_HOST"; wt="$J_WAIT"
    note=""

    case "$stat" in
      RUN)
        running=$((running + 1))
        log="$LOGDIR/${p}_${SEED}.log"
        # Report mode does not evaluate stall at all. progress_age keeps its
        # state in .prog.<jobid>, and a report running beside the real harness
        # would write those files too -- moving the harness's own stall clock
        # and making it slower to notice a job that really had wedged.
        if [ "$LSF_SUMMARY_ONLY" = "1" ]; then
          note=$(grep '\[pattern\]' "$log" 2>/dev/null | tail -1 \
                 | sed -e 's/.*\[pattern\] *//' -e 's/ *@.*//' | cut -c1-40)
          printf '  %-24s %-8s %-7s %-8s %-8s %-9s %s\n' \
                 "$p" "$jid" "$stat" "$wt" "$rt" "$host" "$note"
          continue
        fi
        stall=$(progress_age "$jid" "$log")
        if [ "$stall" -lt 0 ]; then
          note="$P_NOTE"
        elif [ "$stall" -gt $((LSF_IDLE * 60)) ]; then
          # The marker is part of the message on purpose. "no progress for
          # 22m at: 64 randomized APB write and read pairs" names the step it
          # stopped on; "log idle 22m" only says something is wrong.
          note="HUNG? $((stall / 60))m $P_NOTE"
          # LSF_HANG_KILL is forced to 0 in report mode, so this is a
          # statement about the job rather than an action on it.
          if [ "$LSF_HANG_KILL" = "1" ]; then
            bkill "$jid" >/dev/null 2>&1
            note="$note -- killed"
            killed_list="$killed_list $p($P_LAST)"
          fi
        else
          note="$P_NOTE"
        fi
        ;;
      PEND|PSUSP|USUSP|SSUSP|WAIT)
        pending=$((pending + 1)); note="queued" ;;
      DONE|EXIT|TERM|ZOMBI)
        done_n=$((done_n + 1)) ;;
      *)
        # "?" means bjobs has no record of the job, and what that means
        # depends on when you ask.
        #
        # While a regression is running it is almost certainly a transient
        # query failure, and counting it as finished would let one hiccup end
        # the whole run early and read verdicts from logs still being written.
        # So it counts as unfinished and is retried.
        #
        # Reporting on a past regression it means the opposite: LSF keeps
        # finished jobs only for CLEAN_PERIOD and has since forgotten this
        # one. Retrying would wait for news that can never arrive. A job LSF
        # has forgotten has certainly ended, and the log -- which is the
        # authority for the verdict anyway -- is still there.
        if [ "$LSF_SUMMARY_ONLY" = "1" ]; then
          done_n=$((done_n + 1)); stat="GONE"; note="aged out of LSF"
        else
          pending=$((pending + 1)); note="state unknown, retrying"
        fi ;;
    esac

    printf '  %-24s %-8s %-7s %-8s %-8s %-9s %s\n' \
           "$p" "$jid" "$stat" "$wt" "$rt" "$host" "$note"
  done < "$STATE"

  echo "  running $running   pending $pending   finished $done_n"
  [ $((running + pending)) -eq 0 ] && break
  sleep "$LSF_POLL"
done

# -----------------------------------------------------------------------------
# Summary.
#
# Two verdicts per pattern, and they answer different questions:
#   LSF     did the job run to completion, or was it killed / did it exit
#   PATTERN what the testbench itself decided
# A job can be DONE with a FAILED pattern, and a TERM job has no verdict at
# all. Collapsing them into one column loses exactly the distinction that
# says whether to look at the design or at the farm.
# -----------------------------------------------------------------------------
# Everything from here to the end is captured, so the same text the user reads
# on screen is what lands in job_summary.txt. Building the file separately from
# the display is how the two drift apart.
#
# REDIRECTION, NOT `| tee`. A pipeline runs its left side in a subshell, so the
# counters below would be lost by the time the exit status is evaluated -- and
# under `set -u` that is not a wrong answer, it is `fail: unbound variable`
# after the whole regression has already run. Redirect, then cat.
SUMMARY="$LOGDIR/job_summary.txt"
{
hr
echo "=== regression summary: suite $SUITE, seed $SEED ==="
echo "    queue $LSF_QUEUE   timeout ${LSF_TIMEOUT}min   $(date '+%Y-%m-%d %H:%M:%S')"
# WAIT and RUN are separate columns because they answer different questions.
# WAIT is the farm's doing -- a long wait everywhere means the queue is busy
# and says nothing about the testbench. RUN is this pattern's own cost. A
# suite that took an hour looks identical in total either way, and only the
# split tells you whether to ask for more slots or to look at the pattern.
#
# RESULT is likewise separate from LSF. They disagree in both directions: a
# job can be DONE with a FAILED pattern, and a killed job has no result at
# all. Merging them would lose exactly the distinction that says whether to
# look at the design or at the farm.
FMT='  %-22s %-7s %-8s %-6s %-7s %-7s %-7s %-8s %-7s %-11s %-3s %-3s %-4s %-6s %s\n'
# shellcheck disable=SC2059
printf "$FMT" PATTERN JOBID LSF QUEUE WAIT RUN CPU MAXMEM HOST SIMTIME FTL ERR WARN RESULT LOG
printf '  %s\n' "--------------------------------------------------------------------------------------------------------------------------------"

pass=0; fail=0; nolog=0; killed=0
while read -r p jid; do
  [ -n "$jid" ] || continue
  job_query "$jid"
  stat="$J_STAT"; rt="$J_RT"; host="$J_HOST"; wt="$J_WAIT"
  [ -n "$J_EXIT" ] && stat="$stat/$J_EXIT"

  log="$LOGDIR/${p}_${SEED}.log"
  if ! log_is_current "$log"; then
    # Absent, or left over from an earlier run at this seed. Either way this
    # run produced no verdict, and reporting the old one as though it were
    # today's is how a job that was killed gets recorded as having passed.
    verdict="-"; nolog=$((nolog + 1))
    L_SIM="."; L_FATAL="."; L_ERR="."; L_WARN="."
  else
    log_facts "$log"
    if grep -q "VERDICT: PASSED" "$log" 2>/dev/null; then
      verdict="PASS"; pass=$((pass + 1))
    else
      verdict="FAIL"; fail=$((fail + 1))
    fi
  fi
  case "$J_STAT" in TERM|EXIT) killed=$((killed + 1)) ;; esac

  # shellcheck disable=SC2059
  printf "$FMT" "$p" "$jid" "$stat" "$J_QUEUE" "$wt" "$rt" "$J_CPU" "$J_MEM" \
         "$host" "$L_SIM" "$L_FATAL" "$L_ERR" "$L_WARN" "$verdict" "$log"
done < "$STATE"

hr
echo "  PASS $pass   FAIL $fail   no result $nolog   LSF exit/term $killed   of $(wc -l < "$STATE")"
[ -n "$killed_list" ] && echo "  killed as hung:$killed_list"
echo ""
echo "  columns"
echo "    LSF      the job's outcome and exit code. Separate from RESULT on"
echo "             purpose: a DONE job can hold a FAILED pattern, and a killed"
echo "             one has no result at all"
echo "    WAIT     time queued. High everywhere means the farm is busy and"
echo "             says nothing about the testbench"
echo "    RUN      wall clock on the execution host"
echo "    CPU      cpu seconds used. Far below RUN means the job spent its"
echo "             time waiting on something, not simulating"
echo "    MAXMEM   peak memory, for sizing future -lsfrum requests"
echo "    SIMTIME  simulated time at FINAL CHECK. A pattern that stops early"
echo "             can still report PASS, and this is where that shows"
echo "    FTL/ERR/WARN  UVM_FATAL / UVM_ERROR / UVM_WARNING as the testbench"
echo "             counted them"
echo "    RESULT   the testbench's own verdict"
echo "    LOG      that pattern's transcript. A full path per row, because the"
echo "             first thing done with a FAIL is to open it, and a template"
echo "             at the bottom of the table has to be assembled by hand"
echo ""
echo "  reports $REPORTDIR/<pattern>_$SEED/   (VIP traffic, PA, run dir)"
echo "  lsf     $LSFLOG"
hr
} > "$SUMMARY"
cat "$SUMMARY"

# total_summary.txt sits at the top of the sim tree because that is where
# someone looks who did not run this and does not know the layout. Written
# from the same text as the on-screen table rather than rebuilt, so the two
# cannot disagree.
TOTAL="$SIM_ROOT/total_summary.txt"
cp "$SUMMARY" "$TOTAL" 2>/dev/null || true
echo "  summary $SUMMARY"
echo "          $TOTAL"

[ "$fail" -eq 0 ] && [ "$nolog" -eq 0 ]
