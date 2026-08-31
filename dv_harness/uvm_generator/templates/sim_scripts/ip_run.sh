#!/bin/sh
# Build and run one pattern. Parameterised so the speed sweep does not need a
# new script per combination.
#
# CANONICAL HOME: sim/scripts/usbrun.sh, on the PC, and mirrored to the server
# at the same path. It lived in a scratch directory until 2026-08-11 and was
# pushed to /tmp on each invocation -- which meant this project's only build
# entry point was the one file in the tree that nothing version controlled.
# Every fix made to it was one `rm` in a temp directory away from being lost,
# and the two copies had no way to be compared.
#
# So: edit the PC copy, deploy it like any other source file, and run the
# SERVER copy. Never run a copy in /tmp -- that is how the two diverge, and
# a divergent build script is indistinguishable from a divergent testbench in
# the log it produces.
#
#   PAT=usb20_enumeration SPD=usb20 PHYSIM=fast  sh usbrun.sh
#   PAT=usb3_enumeration  SPD=gen1  PHYSIM=fast  sh usbrun.sh
#   PAT=usb3_enumeration  SPD=gen2  PHYSIM=fast  sh usbrun.sh
#   PAT=usb2_enum SPEED0=usb20 SPEED1=usb20fs PHYSIM=fast  sh usbrun.sh
#
# SPD sets SPEED, i.e. BOTH ports, and is the default for whichever of
# SPEED0/SPEED1 is not given explicitly (mirrors the Makefile's own
# `SPEED0 ?= $(SPEED)` / `SPEED1 ?= $(SPEED)`, sim/scripts/Makefile:292,294).
# Using SPEED0 alone leaves port 1 at the ss_capable default, and its
# SuperSpeed agent then sits in Polling.LFPS for the whole run. That does not
# block port 0, but it fills the log with LTSSM lines from usb_host_agent_1
# that read exactly like a port 0 failure. The first SPEED0=usb20 run had
# that problem -- pass SPEED1 explicitly too when the ports must differ.
#
# NO bkill LOOP. A blanket `for j in $(bjobs...); do bkill $j; done` at the
# top of a script killed four of this project's own simulations, reported as
# TERM_OWNER, and a theory about a site reaper was built on top of it before
# `crontab -l` ended that. Kill by name, by hand, once, when it is actually
# needed.
# The farm queue is vcs and only vcs. A run once landed in queue <verdi> as an
# interactive pseudo-terminal job at 2.2%% CPU efficiency; passing it explicitly
# on every bsub removes the question.
QUEUE=${QUEUE:-vcs}
# S is SIM_ROOT_PATH: the sim/ directory this script's own scripts/
# subdirectory lives under. Auto-derived from this script's own location so
# it works unmodified on any checkout; override with S=... if you invoke this
# script from somewhere unusual (e.g. via a symlink outside the tree).
S=${S:-$(cd "$(dirname "$0")/.." && pwd)}
PAT=${PAT:-usb20_enumeration}
SPD=${SPD:-usb20}
SPEED0=${SPEED0:-$SPD}
SPEED1=${SPEED1:-$SPD}
PHYSIM=${PHYSIM:-fast}
# Partition compile. DEFAULT ON, and the Makefile agrees (PARTCOMP_EN ?= 1).
#
# It was briefly defaulted OFF on 2026-08-09 after it crashed VCS itself:
#   Assertion failed "cflatNodesRead == cflatNodes" at hsflatmastersort.cc:287
#   sortAndRenumberMasterNodesIncrLevel -> hsimCreateCallGraphForLevelize
#   -> hsimDoLevelize -> hsimModByModElab
#   make[1]: *** [PARTCOMP_SIMV] Error 1
# with LSF reporting only "exit code 255". It has not recurred across every
# build since, on sources that have changed a great deal, so the workaround
# outlived the problem it was for.
#
# Without partition compile every elaboration is a full ~930 s, which is a
# real cost on a design this size. The crash arm further down names the
# assertion in one line if it ever comes back, so the failure mode is not the
# misleading "0 errors" that made it expensive the first time.
PARTCOMP=${PARTCOMP:-1}
# Waves. WAVE is a COMPILE-time switch here -- WAVE_DEFINES goes into
# VLOGAN_FLAGS -- so it has to be on both the compile and the run line or the
# build and the run disagree about whether dumping exists.
#
# It was missing, and that undid a fix made an hour earlier. wave.txt's DV_UVM
# branch, which names the file after the pattern and scopes the dump, is
# guarded by WAVES_FSDB. Without WAVE=1 the else branch runs
# $fsdbDumpfile("./FSDB/debug.fsdb"), that directory does not exist, and Verdi
# falls back to novas.fsdb with a whole-SoC dump. So a run launched through
# this script silently produced the old broken artefact while the configured
# one sat unused -- and the fsdb being analysed then came from a DIFFERENT run
# than the sim.log beside it.
# CONNECT is gone from this script and from the Makefile. It gated the USB
# serial wiring -- the trans, the interfaces, the interconnect wrappers -- and
# defaulted to 0, so every USB run had the analogue connection compiled out.
# Two days of symptoms sat downstream of that, including a root cause written
# up as "bind + tran does not conduct" when the trans simply were not there.
# This script worked around it by defaulting to 1; the wiring is now
# unconditional, so there is nothing left to forward.
WAVE=${WAVE:-0}
FSDB_START=${FSDB_START:-}
FSDB_STOP=${FSDB_STOP:-}
WOPT="WAVE=$WAVE"
[ -n "$FSDB_START" ] && WOPT="$WOPT FSDB_START=$FSDB_START"
[ -n "$FSDB_STOP" ]  && WOPT="$WOPT FSDB_STOP=$FSDB_STOP"

# TOTAL_RUNTIME -- run time only, so it goes on the `make run` line and NOT on
# `make compile`. Putting it on compile would be harmless but misleading: it
# would suggest a rebuild is needed to change it, which is the whole thing the
# plusarg exists to avoid.
#
# 0 is off, and off means the pattern decides when it is done. Anything else
# bounds the run and the verdict comes back Failed on purpose -- see
# usb_base_test.sv. That is stated here as well because a bound set in a shell
# variable and read back three hours later in a log is exactly the kind of
# thing that gets mistaken for a DUT that stops early.
TOTAL_RUNTIME=${TOTAL_RUNTIME:-0}
ROPT=""
[ "$TOTAL_RUNTIME" != "0" ] && ROPT="TOTAL_RUNTIME=$TOTAL_RUNTIME"

# USB_SCALED_MODE. Passed explicitly rather than left to the environment,
# because `bsub` does not guarantee which variables reach the job and a mode
# that silently reverts to the default is the failure this knob exists to
# prevent. The Makefile defaults it to 1 and rejects anything but 0 or 1.
USB_SCALED_MODE=${USB_SCALED_MODE:-1}
ROPT="$ROPT USB_SCALED_MODE=$USB_SCALED_MODE"

# Extra run-time plusargs, forwarded explicitly for the same reason as the
# above: the environment is not reliably carried into a bsub job.
#
# The one this exists for is verbosity on a single VIP component:
#   PLUSARGS='+uvm_set_verbosity=uvm_test_top.env.usb_host_agent_0.link,_ALL_,UVM_FULL,run'
# which is how trap 96 got the link state machine to state its own timer
# values, with no rebuild. The VIP's link SM body is encrypted, so making it
# talk is the only way to see what it decided.
#
# NOT folded into ROPT: PLUSARGS can itself contain multiple space-separated
# +...=... tokens (e.g. two +USB_DEMOTE_ID= values), and $ROPT is expanded
# UNQUOTED on the bsub line below so `make`'s other KEY=value tokens split
# into separate argv words as intended -- that same unquoted expansion would
# also split PLUSARGS's own internal spaces, truncating it to its first token
# and silently dropping the rest into dead, unreferenced make variables
# (2026-08-25, found by a dedicated workflow, right after usb_top_env.sv's
# load_demotions() was fixed to accept multiple +USB_DEMOTE_ID/+USB_DEMOTE_MSG
# -- that SV-side fix alone never took effect end to end because of this).
# Kept as its own single quoted argv word via "$@" instead, built just before
# the bsub call below.

# Component-scoped verbosity. VERB_COMP=link is the common case; the Makefile
# expands the shorthand and echoes what it used.
[ -n "$VERB_COMP" ]  && ROPT="$ROPT VERB_COMP=$VERB_COMP"
[ -n "$VERB_LEVEL" ] && ROPT="$ROPT VERB_LEVEL=$VERB_LEVEL"

# HS_WINDOW_US -- forces the DUT's hs_handshake_time wider. COMPILE TIME, so it
# goes on the `make compile` line, not on `make run`. It becomes a +define+ and
# is read by both usb_stages.svh (the force) and usb_scaledown_timers.svh (the
# VIP's matching twtfs), so getting it onto only the run line would produce a
# build with neither and a log that looks completely normal -- the same shape
# as the SLED defect, where a define appended after a `:=` assignment never
# reached analysis and the run recorded nothing while looking healthy.
HS_WINDOW_US=${HS_WINDOW_US:-0}
COPT=""
[ "$HS_WINDOW_US" != "0" ] && COPT="HS_WINDOW_US=$HS_WINDOW_US"

# RUNTAG -- run-time only, so it rides with ROPT and not COPT. It renames
# run/, log/, fsdb/, report/ and coverage/ for this invocation so a second run
# of the same pattern does not overwrite the first. Two analyses were run
# against a previous run's sim.log before this existed.
[ -n "$RUNTAG" ] && ROPT="$ROPT RUNTAG=$RUNTAG"
cd $S || exit 1

echo "=== $PAT  SPEED0=$SPEED0 SPEED1=$SPEED1  PHY_SIM=$PHYSIM   WAVE=$WAVE  PARTCOMP=$PARTCOMP  TOTAL_RUNTIME=$TOTAL_RUNTIME  USB_SCALED_MODE=$USB_SCALED_MODE  HS_WINDOW_US=$HS_WINDOW_US  $(date '+%H:%M:%S') ==="
[ "$HS_WINDOW_US" != "0" ] && echo "*** hs_handshake_time IS FORCED to ${HS_WINDOW_US}us. This run does not measure the DUT as built. ***"
bjobs 2>&1 | head -4

echo ""
echo "=== compile ==="
T0=$(date +%s)
make compile FLOW=fourstep SPEED=$SPD SPEED0=$SPEED0 SPEED1=$SPEED1 PHY_SIM=$PHYSIM PARTCOMP_EN=$PARTCOMP WAVE=$WAVE $COPT LSF=1 LSF_QUEUE=$QUEUE 2>&1 \
  | grep -vE "^cd |^ *-f |^ *-top |^ *-o |^ *-full64" | tail -10

i=0
while [ $i -lt 150 ]; do
  # ANCHOR ON OUR OWN JOB NAMES. This used to be
  #     bjobs -noheader | grep -c 'RUN\|PEND'
  # which counts EVERY job on the account, so any unrelated job kept the loop
  # alive. Measured 2026-08-13: a stale interactive `verdi` job had been RUN
  # since 00:53, elaboration had already reported "finished ok / errors: 0" at
  # 10:51, and this loop then printed "building" every two minutes until it
  # exhausted all 150 iterations -- 50 minutes of waiting for a build that was
  # already on disk, with no LSF job of its own left running.
  #
  # The compile stages are named usbc.* by LSF_TOOL_OPT (usbc.analyze, usbc.1b,
  # usbc.elab), so match that and nothing else. Same family as CLAUDE.md trap
  # 84: an unanchored match reads somebody else's state as your own.
  n=$(bjobs -noheader -J 'usbc.*' 2>/dev/null | grep -c 'RUN\|PEND')
  [ "$n" = "0" ] && break
  [ $((i % 6)) -eq 0 ] && echo "  building $(date '+%H:%M:%S')"
  sleep 20; i=$((i + 1))
done
sleep 5
echo "build wall time: $(( $(date +%s) - T0 ))s"

# A BARE Error-/ERROR/Fatal arm, not only the UVM spellings. The 480 MHz PLL
# defect sat in a log for an hour across four rounds of investigation because
# every filter looked for UVM_ERROR and the line said "ERROR in PLL model".
echo ""
ANEC=$(grep -cE '^Error-' log/analyze_dut.log log/analyze_tb.log 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')
echo "analysis errors: $ANEC"
echo "elab errors:     $(grep -cE '^Error-' log/compile.log 2>/dev/null)"
grep -E "^Error-" -A3 log/compile.log 2>/dev/null | head -20

# A SECOND ARM, IN THE TOOL'S OWN VOCABULARY RATHER THAN OURS.
# On 2026-08-09 VCS crashed inside its partition-compile levelizer and every
# check reported zero errors: the crash says "Assertion failed", not "Error-",
# and the last line of the log is Verdi's "0 error(s)" from a KDB pass that
# genuinely succeeded AFTER the crash. LSF said only "exit code 255". The same
# build had failed this way once before, as job 93379, and was written off as
# undiagnosed.
# So: grep for what a broken tool says, not only for what a broken design says.
# "elaboration failed" BELONGS TO TWO DIFFERENT TOOLS, and on 2026-08-12 that
# threw away a build that had completely succeeded:
#
#   Verdi KDB elaboration failed and the KDB database is not generated:
#     0 error(s), 1 warning(s)
#
# -kdb builds Verdi's SOURCE BROWSING database. It failing means Verdi cannot
# jump to RTL source; it says nothing about simv. That run linked cleanly --
# "simv up to date", a 3.3 MB ELF at 21:16:34, every partitionlib product
# present -- and this arm rejected it, printed "output/simv ... would lie",
# and cost a whole 623-second build plus the answer it was carrying.
#
# The note above already knew Verdi's "0 error(s)" line shares this log. What
# it did not anticipate is that Verdi uses the same WORD for its own failure.
KDB_ONLY='Verdi|KDB'
CRASH=$(grep -E "Assertion failed|elaboration failed|Internal Error|Segmentation" log/compile.log 2>/dev/null \
        | grep -vcE "$KDB_ONLY")

# AND THEN CHECK THE THING ITSELF, because narrowing a pattern only fixes the
# spelling that has already burned us once.
#
# A crash that produced a fresh, linked simv is not a crash. T0 is the build's
# own start time, so "simv newer than T0" cannot be satisfied by a leftover
# from an earlier build -- which is exactly the stale-binary case the arm below
# exists to catch. Content beats vocabulary; CLAUDE.md traps 84 and 85 are the
# same lesson from the matching side and the timestamp side.
if [ "$CRASH" != "0" ] && [ -x output/simv ]; then
  SIMV_T=$(stat -c %Y output/simv 2>/dev/null || echo 0)
  if [ "$SIMV_T" -ge "$T0" ]; then
    echo "TOOL CRASH text matched $CRASH line(s), but output/simv was linked at" \
         "$(date -d @$SIMV_T '+%H:%M:%S') -- after this build started. Treating" \
         "the build as SUCCESSFUL and continuing. The matched lines were:"
    grep -nE "Assertion failed|elaboration failed|Internal Error|Segmentation" log/compile.log \
      | grep -vE "$KDB_ONLY" | head -4
    CRASH=0
  fi
fi

if [ "$CRASH" != "0" ]; then
  echo "TOOL CRASH -- $CRASH matching line(s). This is VCS failing, not the design:"
  grep -nE "Assertion failed|elaboration failed|Internal Error|Segmentation" log/compile.log \
    | grep -vE "$KDB_ONLY" | head -6
  echo "If it names PARTCOMP_SIMV or hsim*, this is the 2026-08-09 levelizer"
  echo "assertion. Partition compile defaults ON, so re-run with PARTCOMP=0 to"
  echo "get past it, then say so -- it had not recurred in months of builds."
fi

# Report the KDB result separately so it is visible without being fatal. It is
# a real loss -- source browsing in Verdi -- just not a build failure.
if grep -qE "KDB.*(failed|not generated)" log/compile.log 2>/dev/null; then
  echo "NOTE: Verdi KDB (source-browsing database) was not generated. Waveforms" \
       "and the simulation are unaffected; only source navigation in Verdi is." \
       "The 1 warning it counts is the ICPSD_W driver-combination set."
fi
# A STALE simv IS NOT A BUILD. This used to test only that output/simv exists,
# and on 2026-08-10 stage 1c failed with 2 errors while a simv from an earlier
# build sat in place -- so the script cheerfully submitted a run of the OLD
# binary. The log then describes code that is not the code under test, which
# is the worst kind of result because it looks valid.
if [ "$ANEC" != "0" ] || [ "$CRASH" != "0" ]; then
  echo "BUILD FAILED -- not running. analysis=$ANEC crash=$CRASH"
  echo "output/simv below, if any, is from an EARLIER build and would lie."
  ls -la --time-style=+%H:%M output/simv 2>&1 | head -1
  exit 1
fi
[ -x output/simv ] || { echo "NO_SIMV"; exit 1; }
ls -la --time-style=+%H:%M output/simv

# STOP HERE WHEN ASKED, SO THE FOUR-STEP FLOW CAN VERIFY BETWEEN BUILD AND RUN.
#
#   push  ->  STOP_AFTER_SIMV=1 usbrun.sh  ->  sync_check.sh  ->  usbrun.sh
#
# The second call finds .flags unchanged and every stamp newer than its sources,
# so make declares simv up to date and goes straight to the bsub.
#
# WITHOUT THIS THERE IS NO PLACE TO PUT THE VERIFY. A bare `make compile` is not
# the same build: this script derives a whole set of +define+ from PAT/SPD/
# PHYSIM, so its .flags differ, FLAGSIG is a prerequisite of .uvm.stamp, and all
# four analysis stages re-run. Measured 2026-08-14: `make compile` produced a
# simv at 03:32 and this script threw it away and rebuilt from stage 1a at
# 10:29. Nothing failed -- 20 minutes were simply spent twice.
if [ "$STOP_AFTER_SIMV" = "1" ]; then
  echo "STOP_AFTER_SIMV=1 -- simv is built and NOT submitted. Verify now, then re-run this script without it."
  exit 0
fi

echo ""
echo "=== run ==="
# DETACHED. Not `make run LSF_SIM=1`, which goes through lsf_run.sh and uses
#   bsub -K   (lsf_run.sh:61)
# -K blocks the submitting shell until the job finishes so that make can read
# the job's exit status. That is right for a foreground build and fatal for a
# long simulation reached over a telnet session: the job's life is tied to the
# shell, so when hop.py hits its 1800 s per-command timeout the shell dies and
# LSF reaps the job as TERM_OWNER.
#
# That is what killed job 93426 at 00:03:04 after eight minutes at a healthy
# 20.7% CPU, and it is the second cause behind the same signature CLAUDE.md
# trap 94 recorded. The blanket bkill loop found then was real, but the note
# also said "a later run with no kill in the script died the same way, so
# something else is also involved". This is that something else.
#
# Plain bsub returns a job ID immediately and the job outlives the shell.
# The cost is that make no longer sees the exit status -- which is fine,
# because nothing here waits on it; progress is read with bjobs and the log.
# PLUSARGS as its own argv word, spaces intact -- see the comment where
# PLUSARGS is read, above. set -- has nothing else in it: this script takes
# no positional arguments of its own, so reusing "$@" here does not collide
# with anything.
set --
[ -n "$PLUSARGS" ] && set -- "PLUSARGS=$PLUSARGS"

mkdir -p run/${PAT}_1
bsub -q $QUEUE -J "usbrun.$PAT" -W 180 -o run/${PAT}_1/lsf.out \
     make run PATTERN=$PAT SPEED=$SPD SPEED0=$SPEED0 SPEED1=$SPEED1 PHY_SIM=$PHYSIM PARTCOMP_EN=$PARTCOMP \
              $WOPT $ROPT "$@" LSF_QUEUE=$QUEUE FLOW=fourstep LSF_SIM=0 2>&1 | tail -3
echo "SUBMITTED DETACHED $(date '+%H:%M:%S') -- follow with bjobs, not this shell"
