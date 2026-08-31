# -----------------------------------------------------------------------------
# Target-IP UVM verification environment -- main Makefile
#
# This Makefile is a protocol-agnostic template (originally proven out on a
# USB project, now generalized -- see TARGET_IP/IP_PREFIX below). It is meant
# to be the starting point for ANY VIP-based IP-level UVM environment this
# harness generates: USB, PCIe, Ethernet, MIPI, CAN-FD, AMBA4, etc.
#
# Four user-set paths, all required:
#   VIP_HOME       complete VIP tree, the target protocol + APB + AXI in one
#                  delivery
#   DUT_ROOT_PATH  RTL tree; MACRO MODEL ENV DUMMY_TOP RTLCAT vcs.opt
#                  must be siblings, or vcs.opt's relative paths break
#   UVM_ROOT_PATH  this environment: tb/ filelist/ docs/ vplan/
#   SIM_ROOT_PATH  build products; everything but scripts/ is generated
#
#   make compile                 build simv (FLOW=onestep by default)
#   make sim PATTERN=<name>      run one pattern
#   make regress SUITE=sanity    run a suite against one elaboration
#   make check                   static checks, seconds not minutes
#   make help                    every target and variable
# -----------------------------------------------------------------------------

SHELL := /bin/bash

# -----------------------------------------------------------------------------
# Protocol-target parameterization.
#
# TARGET_IP   -- upper-case protocol name (USB, PCIE, ETH, MIPI_CSI, CAN_FD,
#                AMBA4, ...). Matches the vocabulary of Step 1's "Settle the
#                target" table in IP_UVM_DV_Gen.md.
# IP_PREFIX   -- lower-case file/class-name prefix, WITH a trailing
#                underscore (usb_, pcie_, eth_, ...), same as IP_PREFIX in
#                that same table.
# IP_PREFIX_STEM -- IP_PREFIX with the trailing underscore stripped, for the
#                bare-name cases (a filelist named <ip>.f rather than
#                <ip>_something).
#
# Override on the command line (make TARGET_IP=PCIE IP_PREFIX=pcie_ ...) or
# in the environment; the defaults below reproduce this template's original
# USB proving-ground project so the file still runs standalone unmodified.
# -----------------------------------------------------------------------------
TARGET_IP      ?= USB
IP_PREFIX      ?= usb_
IP_PREFIX_STEM := $(patsubst %_,%,$(IP_PREFIX))

# -----------------------------------------------------------------------------
# Required environment variables
#
# VIP_HOME corresponds to the examples' design_dir, and it is the ONLY source
# of VIP paths in this build. See the DESIGNWARE_HOME block below for why
# DESIGNWARE_HOME must not be one.
# -----------------------------------------------------------------------------
ifeq ($(filter help clean distclean,$(MAKECMDGOALS)),)
  ifndef VIP_HOME
        $(error VIP_HOME is not set. Point it at the VIP install tree root, e.g. /proj/.../VIP)
  endif
  ifndef VCS_HOME
        $(error VCS_HOME is not set)
  endif
  ifndef UVM_HOME
        $(error UVM_HOME is not set. Usually $$VCS_HOME/etc/uvm-1.2 or uvm-1.1d)
  endif
endif

# DESIGNWARE_HOME must reach the tools: the VIP resolves its own runtime
# resources through it, and simv exits immediately without it.
# It does NOT select the compile-time sources -- those come from the install
# path baked into $(VIP_HOME)/include/sverilog/svt_source_defines.svi.
DESIGNWARE_HOME ?= $(VIP_HOME)
export DESIGNWARE_HOME

# -----------------------------------------------------------------------------
# Directories. Everything below SIM_ROOT_PATH except scripts/ is a build
# product and is removed by distclean.
# -----------------------------------------------------------------------------
MK_DIR        := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
ifeq ($(notdir $(MK_DIR)),scripts)
  SIM_ROOT_PATH ?= $(abspath $(MK_DIR)/..)
else
  SIM_ROOT_PATH ?= $(MK_DIR)
endif

# UVM_ROOT_PATH is a separate tree and cannot be derived in general -- but the
# delivered package puts uvm/ and sim/ side by side, so that case is worth
# handling rather than making every user set a variable to describe a layout
# they already have. An explicit setting always wins.
UVM_AUTO      := $(abspath $(SIM_ROOT_PATH)/../uvm)
ifneq ($(wildcard $(UVM_AUTO)/tb/patterns),)
  UVM_ROOT_PATH ?= $(UVM_AUTO)
else
  UVM_ROOT_PATH ?=
endif

# Which filelist to read from DUT_ROOT_PATH. The RTL tree ships more than one
# (vcs.opt for simulation, fab.opt for the fab flow) and they are not
# interchangeable.
DUT_OPT       ?= vcs.opt

# VIP runtime library architecture. The VIP tree ships linux64, linux,
# aarch64 and suse64, and picking the wrong one fails at link time with an
# unhelpful message about missing symbols.
VIP_LIB_ARCH  ?= linux64

# Exported so the filelists can address everything absolutely. vlogan runs in
# $(DUT_ROOT_PATH), so a relative path inside a filelist would resolve against
# the RTL tree and silently pick up the wrong file, or nothing at all.
export UVM_ROOT_PATH
export SIM_ROOT_PATH

# Read by vlogan and vcs whatever directory they run in. Stage 1b runs from
# DUT_ROOT_PATH, so without this it silently uses a different library from
# the other two stages -- see the setup target.
SYNOPSYS_SIM_SETUP := $(SIM_ROOT_PATH)/synopsys_sim.setup
export SYNOPSYS_SIM_SETUP

# --- UVM environment tree, read only during a run ----------------------------
TBDIR       := $(UVM_ROOT_PATH)/tb
FILELISTDIR := $(UVM_ROOT_PATH)/filelist
FILELIST    := $(FILELISTDIR)/$(IP_PREFIX_STEM).f

# Stimulus data delivered by the DUT/protocol team: device TRBs and payload
# files.
#
# Deliberately NOT under SIM_ROOT_PATH. That tree is generated and
# make distclean does rm -rf on it; these files cannot be regenerated.
#
# Passed to the testbench as an absolute path, because $readmemh resolves a
# relative path against the simulation working directory.
HEX_DIR     ?= $(UVM_ROOT_PATH)/hex

# --- simulation tree, everything below is generated --------------------------
# One subdirectory per kind of artifact, so a pattern's waveform and its log
# are findable without knowing the run layout.
# sim / regress / compile / verdi
SIM_SCRIPTS := $(SIM_ROOT_PATH)/scripts
# one FSDB per pattern
FSDBDIR     := $(SIM_ROOT_PATH)/fsdb
# one log per pattern per seed
LOGDIR      := $(SIM_ROOT_PATH)/log
# simv and its daidir
OUTDIR      := $(SIM_ROOT_PATH)/output
# code and functional databases, one per job, merged by `make cov`
COVDIR      := $(SIM_ROOT_PATH)/coverage
# VIP traffic reports, PA xml and performance reports, one directory per job
REPORTDIR   := $(SIM_ROOT_PATH)/report
# the working directory of a running simv, one per job
RUNDIR      := $(SIM_ROOT_PATH)/run
# vlogan library
WORKDIR     := $(SIM_ROOT_PATH)/work

# Retained as an alias so the internal rules stay readable.
SIMDIR      := $(SIM_ROOT_PATH)

# include/, src/ and lib/ come from VIP_HOME only. VIP_HOME's own
# svt_source_defines.svi also hardcodes its install path; no flag changes that.
VIP_INC     := $(VIP_HOME)/include
VIP_SRC     := $(VIP_HOME)/src
VIP_LIB     := $(VIP_HOME)/lib/$(VIP_LIB_ARCH)

# -----------------------------------------------------------------------------
# TOPMOD is the testbench top. EXTRA_TOPS names modules that are referenced
# by module name without being instantiated, so VCS drops them unless they
# are elaborated as tops of their own.
# -----------------------------------------------------------------------------
TOPMOD      := sysn063

# Additional elaboration tops.
#
# These are modules the DUT declares with no ports, never instantiates, and
# then references BY MODULE NAME:
#
#     mr74145_syslog.void_var = mr74145_syslog.error(0);     MODEL_ALL.v:8359
#
# The idiom resolves only while the module is itself elaborated. In the RTL
# team's SINGLE-stage flow that happens for free: `vcs -f vcs.opt` sees the
# sources, finds every uninstantiated module, and makes each one a top -- so
# they pass no -top at all.
#
# This is a TWO-stage flow. vcs receives a library and no source files, so it
# cannot infer tops and fails with Error-[NTMES] if none is named. Naming only
# sysn063 excludes these three and produces 158 XMR errors inside the DUT's
# own MODEL_ALL.v. Naming them explicitly is the two-stage equivalent of what
# their flow does implicitly.
#
# If a fourth appears, the symptom is the same: Error-[XMRE] naming a token
# that is a module rather than an instance.
# Only this one. MODEL_ALL.v includes three *_syslog_defs.v files, but only
# mr74145_syslog.v is actually expanded into the design -- naming the other
# two produced Error-[TMENF-ILL], "not found in library". The error evidence
# agreed: all 158 XMR failures named mr74145_syslog and nothing else.
EXTRA_TOPS  := mr74145_syslog

# -----------------------------------------------------------------------------
# DUT_ROOT_PATH must hold MACRO MODEL ENV DUMMY_TOP RTLCAT and vcs.opt as
# siblings; vcs.opt uses relative paths that resolve nowhere else.
# -----------------------------------------------------------------------------
DUT_ROOT_PATH ?=
export DUT_ROOT_PATH

# -----------------------------------------------------------------------------
# User overridable
# -----------------------------------------------------------------------------
#
# Runtime variables (no rebuild needed)
# -------------------------------------
# tb/patterns/<PATTERN>.txt, selected with +PATTERN
PATTERN   ?= smoke
override PATTERN := $(strip $(PATTERN))
# the only uvm_test; variation comes from PATTERN
TEST      ?= $(IP_PREFIX)base_test
override TEST := $(strip $(TEST))
SEED      ?= 1
WAVE      ?= 0
override WAVE := $(strip $(WAVE))
VERB      ?= UVM_LOW
override VERB := $(strip $(VERB))

# ---------------------------------------------------------------------------
# VERB_COMP / VERB_LEVEL -- raise verbosity on ONE component, at run time.
#
# VERB above is global, and UVM_HIGH globally on this environment produces a
# log nobody reads. This is the targeted form:
#
#   make sim PATTERN=<pattern_name> VERB_COMP=link
#   make sim PATTERN=<pattern_name> VERB_COMP=uvm_test_top.env.$(IP_PREFIX)host_agent_1.link
#
# WHY IT EARNS A KNOB. The VIP's link state machine is often encrypted --
# e.g. this template's original USB VIP shipped only
# `extern task device_attached` in its compiled state-machine class -- so
# reading what it decided is not an option. Raising its verbosity makes
# it print its own timer names, configured values and waits, and it is a
# PLUSARG, so it costs one simulation and no rebuild. That is how the 100 ms
# tattdb was found after three rounds of reasoning about it had failed.
#
# The shorthands exist because the full path is long enough to mistype, and a
# mistyped component name is silently accepted by UVM -- nothing matches, the
# run looks normal, and the absent output reads as "the VIP said nothing".
VERB_LEVEL ?= UVM_FULL
override VERB_LEVEL := $(strip $(VERB_LEVEL))
VERB_COMP  ?=
override VERB_COMP := $(strip $(VERB_COMP))

# Shorthands: link / link1 / phys / mon
ifeq ($(VERB_COMP),link)
  override VERB_COMP := uvm_test_top.env.$(IP_PREFIX)host_agent_0.link
else ifeq ($(VERB_COMP),link1)
  override VERB_COMP := uvm_test_top.env.$(IP_PREFIX)host_agent_1.link
else ifeq ($(VERB_COMP),phys)
  override VERB_COMP := uvm_test_top.env.$(IP_PREFIX)host_agent_0.phys_lane*
else ifeq ($(VERB_COMP),mon)
  override VERB_COMP := uvm_test_top.env.$(IP_PREFIX)mon_agent_0.link_mon
endif

#
# TOTAL_RUNTIME -- stop after this many NANOSECONDS of simulated time.
#
# 0 is the default and means OFF: the pattern runs to its own end, exactly as
# before. Set it when you want a bounded run -- most often a waveform, since
# WAVE=1 dumping from time zero costs about 94 MB per simulated millisecond
# (measured, trap 95) and an unbounded run fills the disk long before it fills
# the screen.
#
# It is a RUN TIME plusarg. Changing it costs one simulation, not a rebuild.
# Some useful landmarks for this DUT, so a bound can be chosen on purpose
# rather than guessed (example landmarks below are from this template's
# original USB proving-ground project -- replace with the current DUT's own
# measured bring-up landmarks):
#
#     ~14 us   the stage-wrapper checker begins
#    ~156 us   phy0_sram_init_done arrives (W7)
#    ~203 us   PHYCLOCK0 running, the clock-survey checker runs (W8)
#    ~313 us   the device's first link-training/attach attempt
#
# A truncated run reports Failed on purpose. See <ip>_base_test.sv, where the
# reasoning is written out: an environment in which ending early produces a
# pass has already cost this project two investigations.
#
TOTAL_RUNTIME ?= 0
override TOTAL_RUNTIME := $(strip $(TOTAL_RUNTIME))

#
# DUT specification variables (rebuild required)
# ----------------------------------------------
# SPEED selects what the target-IP VIP is configured for. It also determines
# the minimum timescale precision, see the consistency checks below.
#
# The enum values below are this template's original USB proving-ground
# project's speed/mode set -- adapt them to whatever speed/mode axis
# TARGET_IP's own VIP actually exposes (a protocol with no such axis, e.g. a
# pure bus target, can drop this knob entirely):
#
#   usb20       USB 2.0 only, HS/FS/LS -- the device is asked for HS, so the
#               chirp handshake runs
#   usb20fs     USB 2.0 at Full Speed. The host is FS, so it never drives the
#               HS reset handshake and the device never chirps. Use this to
#               work on enumeration and transfers while the chirp path is
#               blocked; it is not a substitute for usb20 in a signoff run.
#   gen1        SuperSpeed Gen1, 5 GT/s
#   gen2        SuperSpeed Gen2, 10 GT/s, this is SSP
#   ss_capable  SS together with USB 2.0 fallback, closest to the real DUT
SPEED     ?= ss_capable
override SPEED := $(strip $(SPEED))

# Per port speed.
#
# Real example from this template's original project, kept as a worked
# illustration of the pattern (re-derive the equivalent facts from the
# current DUT's own RTL -- do not assume these hierarchical names or
# addresses carry over): the DUT allowed a per-instance array such as
# u_<ip>top[1:0], one array instantiation with one parameter list, so the
# COMPILE TIME configuration of the two ports was necessarily identical, but
# the speed was a RUN TIME choice made by a per-instance config register, and
# each instance had its own register block.
#
# So SPEED0 and SPEED1 configure the two VIP host agents independently. They
# default to SPEED, which keeps the common case a single knob.
#
#   make sim SPEED0=gen1 SPEED1=gen2
#
# !! THE PATTERN STILL HAS TO COOPERATE !!
# A sanity pattern configures ONE port. Driving the two at different speeds
# needs a pattern that writes both register blocks, through the per-instance
# config register macro for instance 0 and instance 1 rather than a literal.
#
# Follow Step 3's "three independent sources" address-map method (the
# decoder, the BFM access histogram, then the register doc as corroboration
# only) to establish IP0_BASE / IP1_BASE for the current DUT -- do not copy
# the addresses from a prior project. See tb/env/$(IP_PREFIX)reg_defs.svh for
# the derivation and the corroborating sources once established. Override
# with IP0_BASE= / IP1_BASE= if that turns out wrong.
SPEED0    ?= $(SPEED)
override SPEED0 := $(strip $(SPEED0))
SPEED1    ?= $(SPEED)
override SPEED1 := $(strip $(SPEED1))

# Which target-IP ports to enable. The DUT has two identical instances.
#   0 | 1 | both
PORTS     ?= both
override PORTS := $(strip $(PORTS))

# How long the DUT's high-speed SerDes/PHY is allowed to take to come up.
# (This whole knob only applies to a protocol whose PHY model has a
# fast/normal simulation-time switch; a protocol without one can drop it.)
#
#   fast    +define+<PHY_VENDOR_MACRO>_SHORT_RESET  (protocol/vendor specific)
#   normal  silicon-accurate timing
#
# REAL TRAP, WORTH KEEPING AS A WORKED EXAMPLE (from this template's
# original USB proving-ground project -- reconfirm every fact below against
# the CURRENT project's own PHY vendor and databook before relying on it):
#
# !! THAT PROJECT'S SWITCH AFFECTED ITS SUPERSPEED PHY ONLY, AND THAT WAS NOT
# !! A LIMITATION OF THE SWITCH -- ITS LOWER-SPEED PATH HAD NOTHING TO SWITCH.
# Its top-level PHY wrapper held two PHY sub-blocks, one per speed grade, and
# both were active: a real "ERROR in PLL model" that cost an hour came out of
# the one NOT under discussion. So always confirm which PHY sub-block(s) a
# timing knob actually affects by measurement, never by assumption. Its PHY
# vendor's own databook also listed simulation-time parameters intended for
# that PHY's standalone test environment, which were absent from the model
# actually delivered into the SoC -- check what is actually wired into your
# SoC net, not what the databook lists as available in general.
#
# THAT PROJECT'S DEFAULT WAS fast BECAUSE normal WAS NOT SIMULATABLE THERE.
# Its PHY databook stated:
#
#   "The maximum time from phy_reset de-assertion to de-assertion of
#    txX_ack/rxX_ack can be as high as 5ms in fast simulation mode and as
#    high as 18 ms in normal simulation mode."
#
# Its runs ended around 300 us; 18 ms is sixty times that, so in normal mode
# the link could not come up no matter what else was right. The databook
# named what is slow: "power-state transitions, receiver-detect, and RX
# adaptation" -- receiver detect being the link-training step immediately
# before the polling state, which is where the link sat.
#
# The general lesson: BEFORE trusting a PHY_SIM-style fast/normal knob,
# measure the actual real-time cost of "normal" against your own run length,
# using your current PHY vendor's own databook -- a fast-mode-only
# measurement is not a timing claim, and a knob whose "accurate" setting
# silently cannot complete inside your run length needs to be flagged, not
# defaulted to.
PHY_SIM   ?= fast
override PHY_SIM := $(strip $(PHY_SIM))
ifeq ($(filter $(PHY_SIM),fast normal),)
  $(error PHY_SIM=$(PHY_SIM) is not usable. Use fast or normal)
endif

# How long the VIP holds its high-speed link-training state machine in its
# initial "disabled/off" state, in microseconds, before entering its
# receiver-detect step. (Only applicable to a protocol whose VIP models an
# explicit link-training state machine with a configurable pre-detect delay;
# a protocol without one can drop this knob.) Sets the VIP's own
# disabled-to-receiver-detect delay parameter.
#
# WHY THIS IS A KNOB AND NOT A CONSTANT (real worked example, from this
# template's original USB proving-ground project -- reconfirm every number
# below against the current DUT and VIP before relying on it):
# The VIP defaulted this to 0, so its link-training state machine reached
# receiver-detect at 143 ns while the DUT PHY was not a link partner until
# its SRAM had loaded -- measured at 171814 ns in that project's enumeration
# pattern. The host therefore completed receiver detection against nothing
# and parked in its polling state, where it stayed, because that state's
# timeout was 360 ms and no run there was that long.
#
# But the right value DEPENDS ON THE PATTERN, which is why it cannot simply
# be hard coded. The DUT PHY becomes ready at whatever point the pattern
# reaches its own bring-up/wrapper stage, and every pattern has a different
# preamble. A value calibrated on one pattern is wrong for the others, and
# wrong in the silent direction -- the VIP starts early, and the log looks
# exactly like a dead link.
#
# So: settable here, and checked at run time. A stage-completion checker
# should compare its own completion time against this value and say so if
# the VIP has already started. A miscalibration then announces itself
# instead of being mistaken for the fault it was meant to cure.
#
# In the original project, 400 was calibrated against ONE measured case
# (171814 ns, above) and it was too short: measured across several
# high-speed runs (PHY_SIM=fast) with a longer bring-up preamble (SRAM init +
# PHY-ready handshake + PLL probe + clock survey -- the whole preamble, not
# just the final wait step), completion did not finish until 517.9-518.4 us.
# The stage checker's own run-time check ("the VIP entered receiver-detect
# ... BEFORE this PHY was ready") computed the minimum itself each time: 618.
# The VIP was parked in its polling state the whole run, indistinguishable in
# the log from a dead link, on every one of those runs.
#
# The default below clears that measured minimum with margin. It is STILL a
# per-pattern value, not a constant -- see "WHY THIS IS A KNOB" above: the
# calibration above only exercised one preamble shape, and a pattern with a
# longer one (a deferred-config bring-up sequence, or multiple ports whose
# bring-up serialises behind one shared register bus) can still need a
# higher value. Raise it for that pattern; the only cost is simulated time
# before the link starts. The run-time check names the exact number required
# when this default is not enough, so a miscalibration announces itself
# instead of reading as a dead link.

# ---------------------------------------------------------------------------
# RETIRED KNOBS. Setting one of these is now an error rather than a no-op.
#
# They passed per-field VIP timing in by +define+, which is a compile-time
# mechanism and so could not follow a mode only knowable at run time.
# <ip>_top_cfg (the DUT-configuration-reading class, named per IP_PREFIX)
# reads the DUT's own scale-down control field and applies the matching field
# set from a vendor-mapping doc instead.
#
# The guard exists because silence is the expensive failure here: a script
# still passing VIP_TUCH_US=2 would build and run and simply ignore it, and
# the log would carry no trace of the setting having been dropped. $(origin)
# distinguishes a value the operator supplied from this file own default.
# ---------------------------------------------------------------------------
RETIRED_VIP_KNOBS := VIP_ATTDB_US VIP_TDRST_US VIP_TUCH_US VIP_TUCHEND_US VIP_TWTREV_US VIP_TWTRSTHS_US VIP_TUCHSUSP_US VIP_SS_ERDY_US VIP_SS_LACT_US VIP_SS_T2SUSP_US VIP_SS_TIMERS
$(foreach v,$(RETIRED_VIP_KNOBS),  $(if $(filter command\ line environment,$(origin $(v))),    $(error $(v) was retired on 2026-08-11. VIP timing now follows the DUT: $(IP_PREFIX)top_cfg reads the DUT's scale-down control field and applies the matching set. The values it used are written to run/<job>/$(IP_PREFIX)cfg_port<N>.rpt.)))

# ---------------------------------------------------------------------------
# IP_SCALED_MODE -- 1 scaled (default), 0 full spec. (Named generically here,
# not $(TARGET_IP)_SCALED_MODE, because a Make variable's own NAME must stay
# a fixed literal token to remain overridable from the command line -- see
# the genericization report for this template.)
#
# Drives BOTH sides of the scale-down agreement, and that is the whole point:
#
#   <ip>_top_cfg::want_scaled()     build_phase, selects the VIP timing set
#                                   from the vendor scale-down mapping doc
#   IP_SCALED_MODE_APPLY(port)      soc_int.svh, after GLOBAL_INIT: writes
#                                   the scale-down control field into the DUT
#                                   and reads it back
#
# EMITTED UNCONDITIONALLY, even at the default. Both readers fall back to 1 on
# their own if the plusarg is absent, and two independent defaults is exactly
# the shape of the defect this replaces -- change one and the two sides
# disagree in silence. Putting it on the command line means neither ever falls
# back, and the run line records which mode the run was.
#
# 1 is the default because, in this template's original USB project, every
# pattern wrote the scale-down field to its scaled encoding; one exception
# turned it off deliberately partway through a pattern and is the reason
# IP_SCALED_MODE_APPLY reads back rather than assuming. Re-verify this
# default's rationale against the current DUT's own patterns.
IP_SCALED_MODE ?= 1
override IP_SCALED_MODE := $(strip $(IP_SCALED_MODE))
ifeq ($(filter $(IP_SCALED_MODE),0 1),)
  $(error IP_SCALED_MODE must be 0 or 1, got '$(IP_SCALED_MODE)')
endif

VIP_RXDET_DELAY_US ?= 700
override VIP_RXDET_DELAY_US := $(strip $(VIP_RXDET_DELAY_US))
# SS LTSSM timeouts are no longer set by +define+.
#
# VIP_SS_TIMERS=fast used to override 13 of them here with a blanket
# /100 (LFPS /1000). That was a compile-time choice, so it could not
# follow a scale-down mode that is only readable at run time, and the
# single divisor was wrong anyway: the vendor mapping factors range from
# about 1x to 100000x across the same protocol.
#
# <ip>_top_cfg now applies the SS field set as configuration assignments,
# selected by a DUT scale-down control field. The distinction those
# comments made is still true and is kept in <ip>_scaledown_timers.svh:
# these are FAILURE DEADLINES, not waits. Shortening them does not make a
# link train; it makes a failing one report inside a short run.
SS_TIMER_DEFINES :=


# CONNECT is GONE. It gated whether the target-IP VIP was wired to the DUT at
# all, and it defaulted to 0 -- a testbench whose protocol connection was
# optional and off. The stated reason was "blocked on item A2", whether the
# SS PHY produces serial waveforms; that was answered on 2026-08-08
# (CLAUDE.md trap 1: Rx.Detect and Polling.LFPS observed), so the block had
# already lapsed. The wiring in dv_uvm_hook.svh and <ip>_uvm_bind.sv is now
# unconditional.
LANE_FLIP ?= 0
override LANE_FLIP := $(strip $(LANE_FLIP))
# Type-C plug orientation, per port (0=Normal, 1=Flipped; default 0
# reproduces the pre-existing hardcoded behavior). Drives BOTH the DUT-side
# TCA_TCPC write ($(TARGET_IP)_STAGE_TCA) and the testbench-side lane wiring
# (<ip>_uvm_bind.sv's lane_swap_rt) from one value -- see <ip>_orientation_flip
# in dv_uvm_hook.svh. Replaces the old global LANE_SWAP (removed 2026-08-20 --
# <ip>_uvm_bind.sv no longer reads that plusarg name at all, so it was dead).
# LANE_SWAP0/LANE_SWAP1 below remain independent, optional overrides for the
# testbench wiring ONLY, for a blind debug trial that deliberately desyncs
# it from the DUT-side write.
ORIENTATION0 ?= 0
override ORIENTATION0 := $(strip $(ORIENTATION0))
ORIENTATION1 ?= 0
override ORIENTATION1 := $(strip $(ORIENTATION1))
# Empty by default -- forwarded only if the user actually sets one, so an
# unset override cannot silently pin the wiring to 0 regardless of
# ORIENTATION0/1. See lane_swap_rt's LANE_SWAP0/LANE_SWAP1 read in
# <ip>_uvm_bind.sv.
LANE_SWAP0 ?=
override LANE_SWAP0 := $(strip $(LANE_SWAP0))
LANE_SWAP1 ?=
override LANE_SWAP1 := $(strip $(LANE_SWAP1))
# LANE_FLIP0/LANE_FLIP1: per-port override of LANE_FLIP (found missing by
# audit workflow w8pin83zg, 2026-08-23 -- lane_flip_rt in <ip>_uvm_bind.sv was
# a single scalar applied to both ports, so LANE_FLIP=1 to trial-fix one
# port's suspected mis-wiring silently flipped the other port too). Empty by
# default, same reasoning as LANE_SWAP0/1 above.
LANE_FLIP0 ?=
override LANE_FLIP0 := $(strip $(LANE_FLIP0))
LANE_FLIP1 ?=
override LANE_FLIP1 := $(strip $(LANE_FLIP1))
# force ss_cpu_m_*, blocked on RBC/TZC encoding
AXI_FORCE ?= 0
override AXI_FORCE := $(strip $(AXI_FORCE))

# Counted from THIS machine, which is right for a local build and wrong for an
# LSF one: the job is scheduled onto a farm host with only LSF_NCORE slots
# reserved, so a -j taken from the submit host would oversubscribe someone
# else's machine. The LSF section below lowers it when the build is submitted.
NPROC     ?= $(shell n=$$(nproc 2>/dev/null || echo 4); echo $$(( n > 3 ? n - 2 : 1 )))

# -----------------------------------------------------------------------------
# LSF mode, declared HERE rather than with the rest of the LSF settings further
# down, because NPROC is baked into PARTCOMP and ONESTEP_FLAGS by `:=` long
# before that point. Setting it later changes nothing and looks like it works.
#
# (The order checker does not catch this one: NPROC *is* defined before its
# uses, so nothing is undefined -- it is the OVERRIDE that arrives too late.
# Same failure as a value that expands to empty, without the empty value.)
#
# 0 local, 1 batch (-lsfon), int interactive (-lsfint).
# -----------------------------------------------------------------------------
LSF         ?= 1
override LSF := $(strip $(LSF))
LSF_COMPILE ?= $(LSF)
LSF_NCORE   ?= 8
lsf_on = $(filter 1 on int,$(1))

# The helper scripts. Resolved here rather than beside the rest of the LSF
# settings because the tree-integrity check further up reports them missing,
# and a name used before it is set is simply empty -- the check would then
# claim they are absent every time LSF=1.
#
# Both layouts are searched: sim/Makefile is a symlink to scripts/Makefile, so
# MK_DIR is the sim root when make is run from there and scripts/ when it is
# not.
lsf_script = $(firstword $(wildcard $(MK_DIR)/$(1) $(MK_DIR)/scripts/$(1) \
                                    $(SIM_SCRIPTS)/$(1)))
LSF_SCRIPT  := $(call lsf_script,lsf_regress.sh)
LSF_RUN_SH  := $(call lsf_script,lsf_run.sh)
LSF_WAIT_SH := $(call lsf_script,lsf_wait.sh)

# Keep -j inside the reservation. NPROC counts the SUBMIT host's cores (30 on
# host-b) while -lsfncore reserves 8 on the execution host, so a submitted build
# would otherwise run 30 compile processes in 8 reserved slots. The queue's
# hosts have MAX 24, so this also avoids requesting more than can ever be
# scheduled. An explicit NPROC= on the command line still wins -- make does not
# let a makefile assignment override one.
ifneq ($(call lsf_on,$(LSF_COMPILE)),)
  NPROC := $(LSF_NCORE)
endif

# -----------------------------------------------------------------------------
# Timescale. Unconditional, not SPEED-selected: the per-port speed plusargs
# are resolved at RUN TIME now (+$(TARGET_IP)0_SPEED=/+$(TARGET_IP)1_SPEED=,
# <ip>_dev_init.svh), so at compile time there is no way to know whether a
# Gen2 port will be
# selected. 1ps/100fs is what Gen2's 12.5ps quarter-UI needs and is the only
# setting that supports every runtime speed choice; still user-overridable
# via TIMESCALE= on the command line, and the checks below still refuse an
# override that is too coarse for what SPEED/SPEED0/SPEED1 actually request.
# -----------------------------------------------------------------------------
TIMESCALE ?= 1ps/100fs

# =============================================================================
# Consistency checks
#
# These run on every invocation except help and clean. The point is to fail
# immediately with an actionable message instead of producing a build that
# compiles but cannot possibly work.
#
# Several of these guard against SILENT failures, where the simulation runs
# to completion and prints "Passed" while having verified nothing.
# =============================================================================
CHECK_GOALS := $(filter-out help clean distclean list_patterns,$(MAKECMDGOALS))

ifneq ($(CHECK_GOALS)$(if $(MAKECMDGOALS),,x),)

  # --- VIP_HOME must be the COMPLETE VIP tree ---------------------------------
  #
  # VIP_HOME is set by the user, and the obvious choice is wrong. This project
  # needs three protocols in one tree:
  #
  #   <target>   svt_$(IP_PREFIX_STEM)_agent   host and monitor agents (verify
  #                                            this actual class/file name
  #                                            against TARGET_IP's real VIP --
  #                                            it is not guaranteed to equal
  #                                            IP_PREFIX_STEM for every VIP)
  #   APB        svt_apb_system_env            every register access goes
  #                                            through it
  #   AXI        svt_axi_system_env            replaces the CPU on ss_cpu_m_*
  #
  # A protocol-only VIP delivery contains none of the AMBA sources, and the
  # failure mode is a wall of unresolved class errors from
  # svt_apb_system_env, several thousand lines into the vlogan log. Check for
  # it here instead.
  #
  # Test with the APB system env, since a protocol-only tree is the common
  # mistake.
  ifeq ($(wildcard $(VIP_HOME)/src/sverilog/vcs/svt_apb_system_env.sv),)
    $(error VIP_HOME='$(VIP_HOME)' has no AMBA VIP. \
            src/sverilog/vcs/svt_apb_system_env.sv is missing, which means this \
            is a $(TARGET_IP)-only delivery. This project needs $(TARGET_IP), APB \
            and AXI in one tree. Point VIP_HOME at the full VIP installation)
  endif
  ifeq ($(wildcard $(VIP_HOME)/src/sverilog/vcs/svt_$(IP_PREFIX_STEM)_agent.sv),)
    $(error VIP_HOME='$(VIP_HOME)' has no $(TARGET_IP) VIP. \
            src/sverilog/vcs/svt_$(IP_PREFIX_STEM)_agent.sv is missing)
  endif
  ifeq ($(wildcard $(VIP_HOME)/src/sverilog/vcs/svt_axi_system_env.sv),)
    $(error VIP_HOME='$(VIP_HOME)' has no AXI VIP. \
            src/sverilog/vcs/svt_axi_system_env.sv is missing)
  endif

  # --- enumerated values ------------------------------------------------------
  #
  # The SPEED/SPEED0/SPEED1 enum values below (usb20, usb20fs, gen1, gen2,
  # ss_capable) are this template's original USB proving-ground project's own
  # protocol-specific speed/mode set -- see the SPEED variable comment above.
  # Replace them with TARGET_IP's own speed/mode axis, or drop this whole
  # enumerated-values block for a protocol with none.
  ifeq ($(filter $(SPEED),usb20 usb20fs gen1 gen2 ss_capable),)
    $(error SPEED='$(SPEED)' is invalid. Use usb20, usb20fs, gen1, gen2 or ss_capable)
  endif
  ifeq ($(filter $(SPEED0),usb20 usb20fs gen1 gen2 ss_capable),)
    $(error SPEED0='$(SPEED0)' is invalid. Use usb20, usb20fs, gen1, gen2 or ss_capable)
  endif
  ifeq ($(filter $(SPEED1),usb20 usb20fs gen1 gen2 ss_capable),)
    $(error SPEED1='$(SPEED1)' is invalid. Use usb20, usb20fs, gen1, gen2 or ss_capable)
  endif

  # Real worked example, kept verbatim in spirit: this template's original
  # project had no such thing as USB Gen3 -- its DUT topped out at Gen2x2
  # (USB 3.2 dual lane), and Gen3 is USB4 terminology that IP did not
  # implement. Catching the word here saved a confusing search through the
  # VIP. The general lesson: guard against enum values that are adjacent-
  # sounding but belong to a DIFFERENT, unimplemented protocol generation --
  # re-derive the equivalent invalid-value list for TARGET_IP's own VIP.
  ifneq ($(filter gen3 gen4 usb4,$(SPEED) $(SPEED0) $(SPEED1)),)
    $(error There is no USB Gen3 in this template's original project. DWC_usb31             supports Gen1 and Gen2, and Gen2x2 for dual lane. Gen3 belongs to             USB4, a different protocol that IP did not implement. Re-check this             guard's validity for the current TARGET_IP/DUT)
  endif

  # The timescale has to satisfy the FASTER of the two ports, because it is a
  # build wide property. A gen2 port under a timescale chosen for gen1 fails to
  # train, silently.
  ifneq ($(filter gen2,$(SPEED0) $(SPEED1)),)
    ifeq ($(filter $(TIMESCALE),1ps/100fs 1ps/10fs 1ps/1fs 1fs/1fs),)
      $(error one of SPEED0='$(SPEED0)' SPEED1='$(SPEED1)' is gen2, which needs               sub-picosecond precision, but TIMESCALE='$(TIMESCALE)'. The 4x               clock half period is 12.5ps and would be quantized. Use               1ps/100fs or finer)
    endif
  endif
  ifeq ($(filter $(PORTS),0 1 both),)
    $(error PORTS='$(PORTS)' is invalid. Use 0, 1 or both)
  endif

  # --- SPEED against TIMESCALE ------------------------------------------------
  #
  # Gen2 needs a 12.5ps half period. At 1ps precision that quantizes to 12 or
  # 13ps, the recovered clock drifts, and link training fails with no error
  # message from the simulator. Refuse the combination rather than let someone
  # spend a day debugging it.
  ifeq ($(SPEED),gen2)
    ifeq ($(filter $(TIMESCALE),1ps/100fs 1ps/10fs 1ps/1fs 1fs/1fs),)
      $(error SPEED=gen2 needs sub-picosecond precision but TIMESCALE='$(TIMESCALE)'. \
              The 4x clock half period is 12.5ps and would be quantized, which makes \
              link training fail silently. Use 1ps/100fs or finer, or SPEED=gen1)
    endif
  endif
  # ss_capable includes SuperSpeed, so a nanosecond scale is too coarse. Must
  # check SPEED0/SPEED1 too, not just the bare SPEED default -- SPEED=usb20
  # SPEED0=ss_capable SPEED1=usb20 previously passed this check silently
  # because only $(SPEED) was tested, same shape as the gen2 check above.
  ifneq ($(filter ss_capable,$(SPEED) $(SPEED0) $(SPEED1)),)
    ifneq ($(filter $(TIMESCALE),1ns/10ps 1ns/100ps 1ns/1ns),)
      $(error one of SPEED='$(SPEED)' SPEED0='$(SPEED0)' SPEED1='$(SPEED1)' is \
              ss_capable, which includes SuperSpeed, but TIMESCALE='$(TIMESCALE)' is \
              too coarse for the serial layer. Use 1ps/1ps or finer, or usb20)
    endif
  endif

  # --- unresolved prerequisites ----------------------------------------------
  #
  # These are not wrong, but they depend on facts nobody has confirmed yet.
  # Warn rather than block, so experimenting is still possible.
  ifeq ($(AXI_FORCE),1)
    $(info NOTE: AXI_FORCE=1 drives ss_cpu_m_*. The awuser/aruser RBC and TZC \
           encoding is still unknown and defaults to zero, so the fabric may \
           reject the transactions. See item P2-1 in docs/dut-request.md)
  endif

  # --- pattern exists ---------------------------------------------------------
  # One suite per directory, and the directory comes from the REGISTRY
  # (tb/patterns/pattern_list.txt), not a hardcoded list. MEASURED
  # 2026-08-22: after the directory taxonomy migration (basic/sanity/<protocol> ->
  # infra/enumeration/speed/link/power/performance/transfer/uvc/rate_switch/
  # user_define), this exact wildcard search -- still only checking the
  # three old names -- rejected every single PATTERN= outright with no job
  # ever submitted. Same hardcoded-directory-list defect as the SUITE= logic
  # and pattern_rules.py (rule 115), a third place it had been copied into.
  # common/ holds the shared sections a pattern includes and contains no
  # pattern of its own, so it is deliberately not looked up here -- a .svh
  # there must never be selectable with PATTERN=, and it is not registered
  # in pattern_list.txt in the first place.
  PATTERN_DIR := $(strip $(shell awk '/^[[:space:]]*(\#|$$)/{next} $$1=="$(PATTERN)"{print $$2; exit}' \
                    $(TBDIR)/patterns/pattern_list.txt 2>/dev/null))
  ifeq ($(strip $(PATTERN_DIR)),)
    PATTERN_FILE :=
  else ifeq ($(PATTERN_DIR),.)
    PATTERN_FILE := $(wildcard $(TBDIR)/patterns/$(PATTERN).txt)
  else
    PATTERN_FILE := $(wildcard $(TBDIR)/patterns/$(PATTERN_DIR)/$(PATTERN).txt)
  endif
  ifeq ($(strip $(PATTERN_FILE)),)
    $(error PATTERN='$(PATTERN)' is not registered in tb/patterns/pattern_list.txt, \
            or its file is missing from the directory the registry names. \
            Run 'make list_patterns' to see what exists)
  endif

  # --- the four roots must be set and must look right -------------------------
  ifeq ($(strip $(UVM_ROOT_PATH)),)
    $(error UVM_ROOT_PATH is not set. Point it at the UVM environment tree,             the directory that holds tb/ filelist/ docs/ and vplan/:             make compile UVM_ROOT_PATH=/proj/.../$(IP_PREFIX_STEM)_uvm)
  endif
  ifeq ($(strip $(DUT_ROOT_PATH)),)
    $(error DUT_ROOT_PATH is not set. Point it at the RTL tree, the directory             that holds MACRO MODEL ENV DUMMY_TOP RTLCAT and vcs.opt side by             side: make compile DUT_ROOT_PATH=/proj/.../lan063)
  endif

  # vcs.opt refers to ./ENV ./MODEL ./MACRO ./DUMMY_TOP ./RTLCAT, so all five
  # must be direct children of DUT_ROOT_PATH. Report what is missing instead of
  # letting vlogan produce a wall of errors several thousand lines in.
  DUT_DIRS := $(strip     $(if $(wildcard $(DUT_ROOT_PATH)/ENV),,ENV)     $(if $(wildcard $(DUT_ROOT_PATH)/MODEL),,MODEL)     $(if $(wildcard $(DUT_ROOT_PATH)/MACRO),,MACRO)     $(if $(wildcard $(DUT_ROOT_PATH)/DUMMY_TOP),,DUMMY_TOP)     $(if $(wildcard $(DUT_ROOT_PATH)/RTLCAT),,RTLCAT))
  ifneq ($(DUT_DIRS),)
    $(error DUT_ROOT_PATH='$(DUT_ROOT_PATH)' is missing: $(DUT_DIRS).             vcs.opt requires MACRO MODEL ENV DUMMY_TOP RTLCAT and vcs.opt to             be direct children of it. Do not move files to satisfy this; point             DUT_ROOT_PATH at the tree where they already sit that way)
  endif
  ifeq ($(wildcard $(DUT_ROOT_PATH)/$(DUT_OPT)),)
    $(error DUT_ROOT_PATH='$(DUT_ROOT_PATH)' has no $(DUT_OPT) beside the five             source directories. That file is the DUT filelist and the build             cannot proceed without it)
  endif

  # UVM_ROOT_PATH must contain the testbench this project authored.
  ifeq ($(wildcard $(TBDIR)/top/dv_uvm_all.sv),)
    $(error UVM_ROOT_PATH='$(UVM_ROOT_PATH)' does not look like the UVM             environment tree. Expected tb/top/dv_uvm_all.sv below it)
  endif
  ifeq ($(wildcard $(FILELIST)),)
    $(error Filelist not found: $(FILELIST). Expected it under             UVM_ROOT_PATH/filelist)
  endif

  # ---------------------------------------------------------------------------
  # Tree integrity, checked before every build or run.
  #
  # Everything named here is something a later stage assumes without saying so.
  # When one is absent the failure arrives thousands of lines into a vlogan log,
  # or -- worse -- as a link error after seven minutes of elaboration.
  #
  # Reported ALL AT ONCE rather than one per invocation. A check that stops at
  # the first problem turns a broken checkout into as many rebuild cycles as
  # there are missing pieces, which is the same one-error-per-90-seconds loop
  # the static checkers were written to end.
  #
  # $(wildcard) on a directory returns the directory, so it doubles as an
  # existence test; on a glob it returns the matches, so an empty tb/env is
  # caught as well as a missing one.
  # ---------------------------------------------------------------------------
  TREE_MISSING := $(strip \
    $(if $(wildcard $(VIP_INC)/sverilog),,VIP_HOME/include/sverilog) \
    $(if $(wildcard $(VIP_SRC)/sverilog/vcs),,VIP_HOME/src/sverilog/vcs) \
    $(if $(wildcard $(VIP_LIB)),,VIP_HOME/lib/$(VIP_LIB_ARCH)) \
    $(if $(wildcard $(FILELISTDIR)/dv_uvm_files.f),,filelist/dv_uvm_files.f) \
    $(foreach d,top env seq tests agents patterns, \
      $(if $(wildcard $(TBDIR)/$(d)/*),,tb/$(d))))

  ifneq ($(TREE_MISSING),)
    $(error Incomplete tree. Missing or empty: $(TREE_MISSING).             VIP_HOME=$(VIP_HOME)  UVM_ROOT_PATH=$(UVM_ROOT_PATH).             VIP_HOME must be the COMPLETE VIP tree with include/ src/ lib/;             a $(TARGET_IP)-only delivery leaves the APB and AXI classes undefined)
  endif

  # The helper scripts, checked only when a goal actually needs them -- their
  # absence is harmless for a local build and fatal for an LSF one.
  ifneq ($(filter regress,$(MAKECMDGOALS)),)
    ifeq ($(LSF),1)
      LSF_MISSING := $(strip \
        $(if $(LSF_SCRIPT),,lsf_regress.sh) $(if $(LSF_WAIT_SH),,lsf_wait.sh))
      ifneq ($(LSF_MISSING),)
        $(error LSF=1 needs $(LSF_MISSING), not found beside the Makefile                 in $(MK_DIR) or $(SIM_SCRIPTS))
      endif
    endif
  endif

  # The hex files are optional in the sense that a pattern which does not do a
  # data transfer never touches them. But a missing directory only shows up as
  # a $readmemh warning buried in the run log, so say it here instead.
  #
  # HEX_DIR= (empty) is how to say the stimulus data is genuinely not needed
  # any more. Without that escape hatch the only choices when hex/ goes away
  # are to keep a directory nobody uses or to see this warning on every build
  # forever -- and a warning that always fires is one nobody reads, which is
  # exactly how the silent-zero-TRB failure below gets missed when it is real.
  ifneq ($(strip $(HEX_DIR)),)
  ifeq ($(wildcard $(HEX_DIR)/$(TARGET_IP)_TRB),)
    $(warning ---------------------------------------------------------------)
    $(warning HEX_DIR = $(HEX_DIR))
    $(warning $(TARGET_IP)_TRB not found below it.)
    $(warning )
    $(warning Patterns that arm a device transfer read their transfer)
    $(warning descriptors from there. Without it, the descriptor-arm/load)
    $(warning tasks load nothing and the device transfers with whatever was)
    $(warning already in memory, which usually still passes. See)
    $(warning docs/dut-request.md section D.)
    $(warning )
    $(warning If the stimulus data is genuinely no longer needed, say so with)
    $(warning HEX_DIR= and this stops being reported.)
    $(warning ---------------------------------------------------------------)
  endif
  endif

  # SIM_ROOT_PATH is created rather than checked, but it must not collide with
  # either of the read only trees. A stray -o or urg -dir would then write into
  # the RTL tree or the environment tree.
  ifeq ($(SIM_ROOT_PATH),$(DUT_ROOT_PATH))
    $(error SIM_ROOT_PATH must not be the same as DUT_ROOT_PATH. Everything             below SIM_ROOT_PATH is generated and gets removed by make distclean)
  endif
  ifeq ($(SIM_ROOT_PATH),$(UVM_ROOT_PATH))
    $(error SIM_ROOT_PATH must not be the same as UVM_ROOT_PATH. Everything             below SIM_ROOT_PATH is generated and gets removed by make distclean)
  endif

endif

# =============================================================================
# Compile flags
#
# The groups below mirror the variables in the example Makefiles, keeping the
# =============================================================================

# --- vcs_bitmode ---
VCS_BITMODE := -full64

# --- vcsuvmflags / vcselabuvmflags (example :184-185) ---
# UVM arrives through -ntb_opts uvm; +incdir+$(UVM_HOME)/src is not needed
NTB_UVM     := -ntb_opts uvm

# -----------------------------------------------------------------------------
# Vera/NTB compatibility, from the VIP examples. Missing any of these
# produces elaboration errors inside the VIP.
# -----------------------------------------------------------------------------
NTB_COMMON  := -ntb_opts use_sigprop -ntb_vipext .ov -ntb_define NTB \
               +define+NTB +define+SYNOPSYS_SV

# --- incdir (example :436 vcs_incdir_options, expanded at :776) ---
# All three include directories are needed: verilog, svtb, sverilog
VIP_INCDIRS := +incdir+$(VIP_INC)/sverilog \
               +incdir+$(VIP_INC)/svtb \
               +incdir+$(VIP_INC)/verilog \
               +incdir+$(VIP_SRC)/sverilog/vcs \
               +incdir+$(VIP_SRC)/verilog/vcs

# --- ntb_incdir (Vera paths, example :776) ---
NTB_INCDIRS := -ntb_incdir $(VIP_INC)/vera+$(VIP_SRC)/vera+$(TBDIR)/env+$(TBDIR)/top

# --- TB incdir ---
TB_INCDIRS  := +incdir+$(TBDIR)/top \
               +incdir+$(TBDIR)/env \
               +incdir+$(TBDIR)/seq \
               +incdir+$(TBDIR)/tests \
               +incdir+$(TBDIR)/agents \
               +incdir+$(TBDIR)/patterns

# -----------------------------------------------------------------------------
# VIP interface widths are COMPILE-TIME macros and the defaults are too
# narrow for this DUT. Setting only the run-time field in the configuration
# leaves the VIP compiled at the default and nothing warns.
#   SVT_APB_PWDATA_WIDTH        default 8,  needs 32
#   SVT_AXI_MAX_ADDR_USER_WIDTH default 4,  needs 9 (awuser[8:0]), set 16
# paddr needs nothing: SVT_APB_PADDR_WIDTH already defaults to 32.
# Must stay ABOVE SIM_BUILD_OPTS, which uses := and expands this now.
# -----------------------------------------------------------------------------
VIP_WIDTHS := +define+SVT_APB_PWDATA_WIDTH=32 \
              +define+SVT_AXI_MAX_ADDR_USER_WIDTH=16

# This block must stay ABOVE SIM_BUILD_OPTS: that uses := and expands
# $(VIP_WIDTHS) immediately, so a later definition silently yields nothing.
# --- sim_build_options ---
# The intersection of the three examples, plus this project's adjustments:
#   <target> basic_sys : +define+UVM_DISABLE_AUTO_ITEM_RECORDING
#                   +define+UVM_PACKER_MAX_BYTES=24000
#                   +define+SVT_USB_INCLUDE_SSIC   <- example VIP-specific
#                   compile-time feature switch (not set here, this DUT has
#                   no SSIC); TARGET_IP's own VIP will have its own such
#                   switches, if any -- check the VIP's example Makefile
#   axi/apb       : (their system envs arrive through modellist)
SIM_BUILD_OPTS := +define+SVT \
                  +define+SVT_UVM_TECHNOLOGY \
                  +define+UVM_DISABLE_AUTO_ITEM_RECORDING \
                  +define+UVM_PACKER_MAX_BYTES=24000 \
                  $(VIP_WIDTHS)

# --- Project defines ---
# Pattern selection. The include happens during preprocessing, so this is a
# compile time choice. Stage skipping inside a pattern is a runtime plusarg.
# DV_UVM turns on the hook block in MODEL/MODEL_ALL.v and the body of
# tb/top/dv_uvm_all.sv. Without it the SoC testbench runs the original
# command.txt unchanged.
#
# PATTERN is deliberately NOT a compile time define. The whole pattern pool
# is compiled in as tasks and selected at run time with +PATTERN=<name>, so
# one elaboration serves every pattern.
# See tb/patterns/dv_uvm_pattern_pool.svh.
DEFINES := +define+DV_UVM

# dv_uvm_all.sv pins its own `timescale unconditionally to 1ps/100fs (it
# DECLARES ITS OWN and so ignores -timescale=) -- no SPEED-keyed +define+
# needed to select it any more. See the header comment there for why: with
# the per-port speed plusargs resolved at run time, compile time cannot know
# whether a Gen2 port will be selected, so the file always builds at the
# precision Gen2 needs.

# -----------------------------------------------------------------------------
# Speed selection. Must agree with the timescale check above and with the
# speed block in tb/top/<ip>_uvm_bind.sv.
# -----------------------------------------------------------------------------
DMA_MON ?= 1
override DMA_MON := $(strip $(DMA_MON))
ifeq ($(DMA_MON),1)
  DEFINES += +define+$(TARGET_IP)_UVM_DMA_MON
endif

# P3 checker (<ip>_dma_evt_axi_checker.sv): evt_count_r advances with no
# corresponding AXI write ever appearing. DEFAULT OFF, unlike DMA_MON above:
# its evt_count_r hierarchical path was re-derived from RTL source text and
# has not yet been fsdbreport-confirmed against a live simv -- see that
# file's own PATH CONFIDENCE header before setting this to 1.
EVT_AXI_CHECK ?= 0
override EVT_AXI_CHECK := $(strip $(EVT_AXI_CHECK))
ifeq ($(EVT_AXI_CHECK),1)
  DEFINES += +define+$(TARGET_IP)_UVM_DMA_EVT_AXI_CHECK
endif

# ORIENTATION0/ORIENTATION1/LANE_FLIP are RUN_FLAGS (run time plusargs, no
# rebuild) -- see the block next to AXI_FORCE below and
# lane_swap_rt/lane_flip_rt in <ip>_uvm_bind.sv.

# DUT specification, consumed by <ip>_base_test to configure the VIP.
#
# IP0_SPEED_*/IP1_SPEED_*/<TARGET_IP>_PORT0_ONLY/<TARGET_IP>_PORT1_ONLY/
# <TARGET_IP>_SPEED_* are GONE from here: SPEED0/SPEED1/PORTS are now
# forwarded as run time plusargs (+$(TARGET_IP)0_SPEED=/+$(TARGET_IP)1_SPEED=/
# +$(TARGET_IP)_PORTS=, near IP0_BASE_RT below) and resolved independently
# by each consumer (<ip>_ep_check.sv build_speed(), <ip>_dev_init.svh's
# <ip>0_speed_rt/<ip>1_speed_rt, <ip>_stages.svh's <ip>_ports_rt,
# <ip>_top_cfg.sv, <ip>_vip_seq_dispatch.svh's <ip>_soak_apply(),
# <ip>_ep_suite.txt's isochronous family selection) via $value$plusargs --
# no rebuild to try a different per-port speed or port combination. The
# last two were the final consumers of the bare +define+<TARGET_IP>_SPEED_$(SPEED);
# once they moved to the plusarg, nothing read the define, so it is removed
# rather than left as dead flags on every vlogan/vcs command line.

# HS_WINDOW_US -- force the DUT's hs_handshake_time to this many microseconds.
#
# THIS OVERRIDES DUT BEHAVIOUR. It is 0 (off) by default and must be asked for
# explicitly, because a run that uses it is not measuring the DUT as built.
#
# The reason it exists: the VIP host drives ~4.12 us per chirp K/J bit whatever
# cfg.tdchbit says (750 ns configured, confirmed in the run-time config report,
# and the VIP even starts a tdchbit_timer with it). Three K-J pairs is 24.7 us
# and the scaled window is 10 us, so the handshake cannot complete and the
# device falls back to Full Speed. There is no register that widens the window
# -- see the block comment on $(TARGET_IP)_HS_WINDOW_FORCE in <ip>_stages.svh
# for the two inputs and why neither helps.
#
# RUN TIME, NOT A +define+: <ip>_stages.svh resolves +HS_WINDOW_US once via
# $value$plusargs (module-scope storage, because `force`'s right-hand side
# must be static) and <ip>_scaledown_timers.svh reads the same plusarg
# independently for the VIP's twtfs -- its model of the same DUT timer -- so
# no rebuild is needed to change or disable it. Setting one side without the
# other puts the two back out of step, which is the class of defect this
# whole scale-down exercise is about; the plusarg name is what keeps them the
# same value, not a shared compile-time macro.
#
# 40 us is the smallest round value that fits 3 pairs at 4.12 us plus the
# measured 4.85 us twtdch, with margin. Forwarded to RUN_FLAGS below, near
# IP0_BASE_RT -- RUN_FLAGS is `:=` and is not defined yet at this point in
# the file.
HS_WINDOW_US ?= 0
override HS_WINDOW_US := $(strip $(HS_WINDOW_US))

# PHY_SIM. Two defines, and they are not interchangeable.
#
# EVERYTHING INSIDE THIS ifeq/else BLOCK IS A REAL, VERBATIM WORKED EXAMPLE
# FROM THIS TEMPLATE'S ORIGINAL USB PROVING-GROUND PROJECT, kept as a
# reference for the CLASS of PHY-vendor-macro investigation it documents
# (mismatched reference-clock defines, undefined macros silently reaching
# vlogan as empty values, a submission-path shell-quoting trap). The
# specific macro names (DWC_USBC31SSPPHY_*) are that project's own PHY
# vendor's RTL macros and will NOT apply to a different TARGET_IP/PHY --
# replace this whole block with the equivalent investigation for the
# current DUT's own PHY vendor and databook; do not carry these exact
# defines into a non-USB environment.
#
#   DWC_USBC31SSPPHY_SHORT_RESET  the PHY RTL's own macro. Goes to stage 1b,
#                                 which is where the PHY is analysed.
#   $(TARGET_IP)_UVM_PHY_SIM_FAST/_NORMAL  informational only now --
#                                 <ip>_top_cfg.sv and soc_int.svh `ifdef on
#                                 them to print which mode the build was made
#                                 for. <ip>_stages.svh no longer ifdefs on
#                                 either name: its own poll bounds
#                                 ($(TARGET_IP)_SRAM_INIT_TRIES,
#                                 $(TARGET_IP)_TCA_ACK_TRIES,
#                                 $(TARGET_IP)_SS_PIPE_READY_US) are
#                                 +PHY_SIM_TRIES/+PHY_SIM_READY_US run time
#                                 plusargs, default to the FAST figures, and
#                                 do NOT follow this switch by themselves.
#
# Both land in VLOGAN_FLAGS, which every analysis stage uses, and FLAGSIG
# signs VLOGAN_FLAGS -- so changing PHY_SIM re-analyses rather than silently
# reusing a library built the other way. That mattered: this is exactly the
# defect trap 77 describes, and a define that never reaches vlogan leaves a
# run looking completely normal while doing nothing.
ifeq ($(PHY_SIM),fast)
  DEFINES += +define+DWC_USBC31SSPPHY_SHORT_RESET
  # Added 2026-08-20, same ifeq($(PHY_SIM),fast) branch as SHORT_RESET so
  # both reach vlogan the same proven way (trap 77): the DE's own reference
  # compile options set 5 USB3-PHY defines, and only SHORT_RESET was present
  # here. REF_20M was undefined, so the SS PHY's PLL fell through to the
  # `else` branch of dwc_usbc31sspphy_upcs_x1_ns_pipe_defines.v's ifdef chain
  # and was configured with 100MHz-reference constants
  # (MPLLA_MULTIPLIER_SSC_OFF=25, BANDWIDTH=27, REF_RANGE=3) while the SS
  # PHY's actual reference clock is the confirmed 20.01MHz phyrefclk net
  # (trap 91, SS_VOUT_USB.v:16783/:15140) -- a 5x mismatch in a value the SS
  # PHY databook (section 5.3.3, Table 5-4) states MUST be defined as a
  # compile macro. Structurally the same defect class as trap 91's femtoPHY
  # div_ncy fix, on the sibling SS PHY. FW_FAST_SIM is a separate, real gap:
  # the databook's own compile-option compatibility table marks it N/N (not
  # implied by SHORT_RESET, unlike most FAST_* rows), and its RTL site
  # (dwc_usbc31sspphy_phy_x1_ns_pcs_raw_mem_rst.v) changes 4854 of 8194
  # calibration/adaptation firmware RAM values versus the non-fast branch.
  # Added 2026-08-21 (P5, RX frequency investigation): the RTL/DE team
  # reproduced this project's exact phy_rx0_clk_pma misreading (351.7 MHz
  # instead of 250 MHz) on their own setup by removing these two defines --
  # an independent, externally-validated correlation, not this project's own
  # inference. The scoping note that used to justify omitting them (below,
  # superseded) was written for the P4 TX/beacon-side LFPS-oscillator
  # investigation and does not hold for this RX-frequency question, which is
  # exactly the "RX-only VCO force logic" effect that note itself named.
  # dut-request.md's P5 section also records that the specific RTL site once
  # cited as the mechanism for this project's own compiled design
  # (force_freq_tune0/1) turned out to be inside a module never instantiated
  # here (dwc_usbc31sspphy_phy_x1_ns) -- so treat this as an empirically
  # strong, externally-corroborated fix to try and measure, not a fix with a
  # confirmed mechanism in this specific design.
  DEFINES += +define+DWC_USBC31SSPPHY_SIM_MODE
  DEFINES += +define+DWC_USBC31SSPPHY_SIM_GTECH
  # ADDED 2026-08-21, same day as SIM_MODE above: SIM_MODE unlocks
  # synchronizer/metastability-modeling code paths (SS_VOUT_USB_PHY.v, 8
  # sites) that use DWC_USBC31SSPPHY_RANDOM/_RANDOM_SEED as bare macro
  # VALUES, not just `ifdef guards -- first build attempt with SIM_MODE
  # alone failed with Error-[UM] Undefined macro at :11850. RANDOM is used
  # inside `always`-block non-blocking assignments (d_s1 <= `..._RANDOM;).
  # $random was tried first (matching the RTL's own "d_s1 is either
  # randomized" comment), then 1'b0 -- both were confirmed correct by
  # `make -n` dry-run but STILL arrived at the real (non-dry-run, bsub/LSF
  # path) vlogan invocation as an empty value (log/analyze_dut.log's own
  # echo showed "+define+DWC_USBC31SSPPHY_RANDOM= \" with nothing after the
  # "="). The apostrophe in 1'b0 is suspected (not confirmed) to be
  # interpreted as an unmatched shell quote somewhere in the DUT's build
  # entry point's actual submission path (this template's own equivalent is
  # ip_run.sh), which the dry-run does not reproduce. Using a BARE
  # DECIMAL LITERAL instead avoids every special character tried so far
  # ($, \, '). This makes the synchronizer's metastability injection
  # deterministic (always 0) rather than genuinely random -- a real loss of
  # coverage for whatever this synchronizer model was meant to stress -- but
  # is orthogonal to the RX CDR frequency question this Makefile change
  # exists to unlock. RANDOM_SEED is used in a module-level
  # `integer rnd_seed = ..._RANDOM_SEED * SEED;` initializer (:13313); no
  # documented default value was found in the local databook, 1 is a
  # placeholder pending confirmation.
  DEFINES += +define+DWC_USBC31SSPPHY_RANDOM=0
  DEFINES += +define+DWC_USBC31SSPPHY_RANDOM_SEED=1
  DEFINES += +define+DWC_USBC31SSPPHY_REF_20M
  DEFINES += +define+DWC_FW_FAST_SIM
  DEFINES += +define+$(TARGET_IP)_UVM_PHY_SIM_FAST
else
  DEFINES += +define+$(TARGET_IP)_UVM_PHY_SIM_NORMAL
  $(info [cfg] PHY_SIM=normal: <ip>_stages.svh's poll bounds are run time \
plusargs now and default to the FAST figures regardless of this switch -- add \
PLUSARGS="+PHY_SIM_TRIES=25000 +PHY_SIM_READY_US=22000" or the testbench will \
time out waiting on a PHY that was not sped up.)
endif

# One define, read by two files that are analysed in different stages:
# <ip>_top_cfg.sv sets the VIP's ss_disabled_to_rx_detect_delay from it (stage
# 1c) and <ip>_stages.svh checks the DUT against it (stage 1b, through the
# dv_uvm_hook.svh chain). A +define+ is what reaches both -- a `define in
# either file would not, because a vlogan invocation does not inherit another
# one's preprocessor state.
# This template's original USB 2.0 attach/reset/chirp and SS LTSSM knobs were
# removed here on 2026-08-11. They were per-field guesses passed in by
# +define+, which is a COMPILE TIME mechanism and therefore could not follow
# a mode that is only knowable at run time. <ip>_top_cfg now reads the DUT's
# scale-down control field and applies the matching field set from a vendor
# scale-down mapping doc. Measured cost of the guessing they replaced:
# VIP_TUCH_US was 100 us against a mapping value of 300 ns.
DEFINES += +define+$(TARGET_IP)_UVM_RXDET_DELAY_US=$(VIP_RXDET_DELAY_US)

# Read by <ip>_top_cfg.sv (stage 1c) and printed in the [cfg] banner by
# soc_int.svh (stage 1b), so it has to be a +define+ for the same reason.

# The SuperSpeed set, overriding the VIP's own `SVT_REPLACEABLE_DEFINE values.
# Empty when VIP_SS_TIMERS=spec. Assigned above, and referenced here rather
# than the other way round -- trap 77 was exactly this ordering, silently
# expanding to nothing.
DEFINES += $(SS_TIMER_DEFINES)

# --- SoC defines (carried over from DUT/vcs.opt) ---
#
# SSVOUTMODEL_EN AND SMEMMODEL_EN ARE GONE, and neither may come back. Both
# models are now unconditional in MODEL_ALL.v, so the two macros every pattern
# uses -- `SS_VOUT_MODEL.ss_vout_init_flow and `SMEMMODEL.FILLMEM -- resolve
# from DUT_ROOT_PATH alone. A missing model is then an elaboration error
# naming the hierarchy, which is the whole point: a define that gates an
# instantiation turns "the model is not there" into silence.
#
# What each was hiding, measured 2026-08-14:
#   SSVOUTMODEL_EN  the module body was never in the DUT tree at all -- only
#                   the guarded instantiation was. The running simv carried
#                   ss_vout_model from an earlier build that partition compile
#                   kept reusing, so a full rebuild would have dropped it. It
#                   clears the AXI arbiter pause registers (POR 0xF = every
#                   master paused), whose absence shows up only as DMA counts
#                   of zero.
#   SMEMMODEL_EN    three guards in MODEL_ALL.v -- the instantiation at :749,
#                   the TZC_INIT call inside GLOBAL_INIT at :1127, and the
#                   whole module at :5301. TZC_INIT's own definition was
#                   already outside the guard, so only the call was optional.
SOC_DEFINES := +define+RTL +define+GSIAPB +define+MISC_NOCHECK
# +define+HAPS is NOT set, so the else branch applies: xtestmode exists and
#
# Parity is deliberately not enabled. Confirmed with the RTL owner:
# APB4_PARITY_PORT_EN / AXI4_PARITY_PORT_EN stay undefined.

# -----------------------------------------------------------------------------
# Register base addresses. Compile-time defines, overridable at run time.
#   IP0 0x1270_0000   IP1 0x1280_0000   (apbsplit_rep nibble 7 and 8, this
#   template's original project's real example -- re-derive per Step 3's
#   three-independent-source address-map method for the current DUT)
#
# (Named IP0_BASE/IP1_BASE, not $(TARGET_IP)0_BASE/..., because a Make
# variable's own NAME must stay a fixed literal token to remain overridable
# from the command line -- see the genericization report.)
# -----------------------------------------------------------------------------
IP0_BASE ?=
override IP0_BASE := $(strip $(IP0_BASE))
IP1_BASE ?=
override IP1_BASE := $(strip $(IP1_BASE))
GTOP_BASE ?=
override GTOP_BASE := $(strip $(GTOP_BASE))

# 0x40100000 -> 32\'h40100000. The backslash survives make and reaches the
# shell as a literal quote, which is what VCS needs to see.
sv_hex = $(if $(filter 0x%,$(1)),32\'h$(patsubst 0x%,%,$(1)),$(1))

ifneq ($(IP0_BASE),)
  DEFINES += +define+$(TARGET_IP)0_BASE_ADDR=$(call sv_hex,$(IP0_BASE))
endif
ifneq ($(IP1_BASE),)
  DEFINES += +define+$(TARGET_IP)1_BASE_ADDR=$(call sv_hex,$(IP1_BASE))
endif
ifneq ($(GTOP_BASE),)
  DEFINES += +define+GTOP_BASE_ADDR=$(call sv_hex,$(GTOP_BASE))
endif

# -----------------------------------------------------------------------------
# Synopsys Protocol Analyzer, run-time gate. Needs VERDI_HOME (checked once,
# unconditionally, below -- see "debug-access capability, always built in").
#
# PA=1 at `make run` time passes +$(IP_PREFIX)pa (PA_RUN_OPTS below); PA=0
# (default) omits it. <ip>_top_cfg.sv:835 returns early unless +$(IP_PREFIX)pa
# is present, so this alone decides whether the target-IP VIP records --
# APB/AXI record unconditionally regardless (<ip>_apb_cfg.sv:67,
# <ip>_axi_cfg.sv:96, enable_xml_gen=1 with no gate), which is a VIP-side
# asymmetry, not this variable's doing.
# -----------------------------------------------------------------------------
PA ?= 0
override PA := $(strip $(PA))

# -----------------------------------------------------------------------------
# VIP traffic reporting and analysis. All three on by default; each can be
# turned off from the command line, which is what a regression usually wants.
#
#   VIP_REPORT  text traffic reports from each VIP at end of test.
#               AXI enable_reporting + display_perf_summary_report,
#               the target-IP VIP's enable_prot/link_reporting.
#               The target-IP VIP's are int levels, not flags (this was true
#               for this template's original USB VIP; verify for TARGET_IP's
#               own VIP): 1 reports the top-level transaction, >1 adds the
#               object's implementation contents, which floods a regression
#               log.
#               RUN TIME ONLY (<ip>_vip_report_rt(), <ip>_top_cfg.sv), default
#               ON -- VIP_REPORT=0 adds +vip_report_off to RUN_FLAGS below and
#               costs no rebuild.
#   VIP_PA      PA / transaction record generation inside the VIPs. Independent
#               of PA above: that one links the Verdi backend, this one decides
#               whether the VIPs emit records at all.
#   VIP_STATUS  end-of-test status and performance summaries read from the
#               VIPs' own status objects.
#               RUN TIME ONLY (<ip>_vip_status_rt(), <ip>_top_cfg.sv), default
#               ON -- VIP_STATUS=0 adds +vip_status_off to RUN_FLAGS below and
#               costs no rebuild.
#
#   make regress SUITE=sanity VIP_REPORT=0 VIP_PA=0
# -----------------------------------------------------------------------------
VIP_REPORT ?= 1
VIP_PA     ?= 1
VIP_STATUS ?= 1
override VIP_REPORT := $(strip $(VIP_REPORT))
override VIP_PA     := $(strip $(VIP_PA))
override VIP_STATUS := $(strip $(VIP_STATUS))

# PA detail per protocol layer, see <ip>_top_cfg.sv::set_pa_gen.
#   prot 0 off, 1 transfers, 2 transfers and transactions
#   link 0 off, 1 packets, 2 plus link commands, 3 plus symbol sets, 4 plus LTSSM
#   phys 0 off, 1 LFPS signalling
#   payload 0 off, 1 the transferred bytes
#
# PA_PAYLOAD is new. enable_payload_pa_gen (svt_<protocol>_agent_configuration.sv:722,
# real example: svt_usb_agent_configuration.sv in this template's original
# project) was never set by this environment because it is not in the VIP
# example the other three came from. For a DEVICE DUT it is the most
# informative of the four: it is the stream that says whether a descriptor
# actually came back.
PA_PROT    ?= 2
PA_LINK    ?= 1
PA_PHYS    ?= 0
PA_PAYLOAD ?= 1

ifeq ($(VIP_PA),1)
  DEFINES += +define+$(TARGET_IP)_UVM_PA_PROT=$(strip $(PA_PROT))
  DEFINES += +define+$(TARGET_IP)_UVM_PA_LINK=$(strip $(PA_LINK))
  DEFINES += +define+$(TARGET_IP)_UVM_PA_PHYS=$(strip $(PA_PHYS))
  DEFINES += +define+$(TARGET_IP)_UVM_PA_PAYLOAD=$(strip $(PA_PAYLOAD))
endif
# VIP_REPORT and VIP_STATUS no longer add a DEFINES+= here -- both consumer
# sites read a runtime plusarg instead (<ip>_top_cfg.sv), set from RUN_FLAGS
# near IP0_BASE_RT below.

# -----------------------------------------------------------------------------
# Debug-access capability (FSDB + Protocol Analyzer PLI), always built in.
#
# PA and WAVE used to each gate their own compile-time +define+/-debug_access
# set, so switching either forced a full rebuild (FLAGSIG mismatch -- measured
# cost 15-25 min). Both are actually decided at RUN time already: wave.txt's
# every choice (+fsdb_off/+fsdb_full/+fsdb_file/+fsdb_start/+fsdb_stop) is a
# plusarg, never an `ifdef, and PA_RUN_OPTS below is +$(IP_PREFIX)pa, also a
# plusarg (<ip>_top_cfg.sv:835 reads it at run time). The compile-time half was the
# only part still keyed off WAVE/PA -- so build it in unconditionally, once,
# and let every `make run` choose WAVE=/PA= freely against the same simv.
#
# COST: every simv now carries -debug_access, whatever that adds to
# elaboration time and simv size, even for a run that asks for neither. That
# is the trade this buys back: no more 15-25 min rebuild for a WAVE/PA change.
#
# DEGRADE, DO NOT ERROR, when VERDI_HOME is unset -- same reasoning PA's own
# check already used before this change: a machine without Verdi should not
# fail every build for a capability nobody asked for yet. The one remaining
# case where a rebuild is unavoidable: a simv built while VERDI_HOME was unset
# has none of this compiled in, so WAVE=1/PA=1 at run time against THAT simv
# will hit an undefined $fsdb* system task, not a graceful no-op -- rebuild
# once VERDI_HOME is set to recover.
NOVAS_PLATFORM ?= LINUX64
ifndef VERDI_HOME
  $(warning VERDI_HOME is not set, so FSDB dumping and Protocol Analyzer \
            recording are DISABLED for this build -- WAVE=1/full or PA=1 at \
            run time against this simv will not work; rebuild after setting \
            VERDI_HOME to recover.)
  PA_DEFINES  :=
  PA_OPTIONS  :=
  WAVE_DEFINES :=
  WAVE_OPTIONS :=
  # Fallback baseline: post-processing debug from an FSDB (VCS "Recommended
  # Debug Settings for a New Project"), the same floor every build had before
  # this section existed. PA_OPTIONS' -debug_access+pp+dmptf+thread is the
  # normal case below and supersedes this; this arm only fires when there is
  # no PA_OPTIONS to supersede it.
  DEBUG_ACCESS := -debug_access
else
  PA_DEFINES   := +define+SVT_FSDB_ENABLE +define+WAVES_FSDB +define+WAVES=\"fsdb\"
  PA_OPTIONS   := +plusarg_save -debug_access+pp+dmptf+thread \
                  -debug_region=cell+encrypt -notice
  PA_OPTIONS   += -P $(VERDI_HOME)/share/PLI/VCS/$(NOVAS_PLATFORM)/novas.tab \
                  $(VERDI_HOME)/share/PLI/VCS/$(NOVAS_PLATFORM)/pli.a
  # WAVE_DEFINES/WAVE_OPTIONS stay empty: PA_DEFINES/PA_OPTIONS already carry
  # the identical set (both consumption sites below add both variables), and
  # populating both produced a harmless but noisy VCS duplicate-define
  # warning. One source of truth, not a fold-when-both-are-on special case.
  WAVE_DEFINES :=
  WAVE_OPTIONS :=
  # DEBUG_ACCESS stays empty here: PA_OPTIONS' -debug_access+pp+dmptf+thread
  # already covers the plain -debug_access case, and passing both to the same
  # vcs invocation was the plain -debug_access + -debug_access+pp+dmptf+thread
  # collision this variable used to avoid by being compile-time PA/WAVE gated.
  # That gate is gone now that PA_OPTIONS is unconditional (see above), so this
  # is the same avoidance expressed against VERDI_HOME instead.
  DEBUG_ACCESS :=
endif

# +$(IP_PREFIX)pa is the RUN time gate <ip>_top_cfg.sv:835 reads (PA=1 at
# `make run`, independent of whether this build has the capability compiled
# in at all -- see the VERDI_HOME degrade case above, which leaves PA_OPTIONS
# empty and makes this plusarg a no-op rather than a crash).
ifeq ($(PA),1)
  PA_RUN_OPTS := +svt_enable_pa=fsdb +$(IP_PREFIX)pa
else
  PA_RUN_OPTS :=
endif

# -----------------------------------------------------------------------------
# Coverage. COV adds VCS code coverage, FCOV the VIP functional coverage.
# Both change the command line and therefore force a full rebuild.
# -----------------------------------------------------------------------------
COV      ?= 0
override COV := $(strip $(COV))
FCOV     ?= 0
override FCOV := $(strip $(FCOV))
COV_HIER ?= $(TOPMOD).u_lan063.u_ss_vout

# Metric set. The recommendation is line+cond+fsm for procedural designs and
# line+branch+tgl with -cm_line contassign for assign heavy ones. This SoC is
# both, so all five are collected.
CM_OPTS   := line+cond+fsm+tgl+branch

# -cm_seqnoconst is recommended for every new project: it drops constant
# expressions and flags unreachable statements, which otherwise sit in the
# report forever as uncovered noise.
CM_EXTRA  := -cm_seqnoconst -cm_line contassign
CM_DIR   := $(COVDIR)/simv.vdb

# -----------------------------------------------------------------------------
# Coverage scope, written to cov_hier.cfg as +tree/-tree lines applied in
# order. Default instruments the subsystem holding both target-IP instances
# and carves out the two vendor PHYs (real example hierarchy below is this
# template's original USB project -- re-derive the equivalent instance paths
# from the current DUT's own RTL).
# -----------------------------------------------------------------------------
COV_SCOPE   ?= $(TOPMOD).u_lan063.u_ss_vout
COV_EXCLUDE ?= $(TOPMOD).u_lan063.u_ss_vout.u_$(IP_PREFIX_STEM)top*.u_udc_usb31_top.u_udc_usb31_phy \
               $(TOPMOD).u_lan063.u_ss_vout.u_$(IP_PREFIX_STEM)top*.u_udc_usb31_top.u_udc_usb2_phy

ifeq ($(COV),1)
  COV_ELAB := -cm $(CM_OPTS) $(CM_EXTRA) -cm_dir $(CM_DIR) -cm_hier $(SIM_ROOT_PATH)/cov_hier.cfg
  # COV_RUN is RECURSIVE (=), not immediate (:=), because PAT_NAME and PAT_COV
  # are defined ~250 lines below this point. With := it expanded to nothing and
  # every coverage run was launched with a bare `-cm_name` and no name after it.
  # Recursive is also the right semantics here: both derive from PATTERN and
  # SEED, which change per invocation, and this is only used inside a recipe.
  #
  # Compile time -cm_dir names the database the elaboration builds; run time
  # -cm_dir sends THIS run's test data somewhere else (cov_ref.pdf, "Using
  # -cm_dir and -dbname Options", and the worked example at cov_ref.txt:1587-89
  # which compiles once and runs test1.vdb / test2.vdb separately). One
  # database per job is what lets jobs run at the same time without writing
  # over each other; `make cov` merges them afterwards with urg.
  #
  # It is also required rather than optional here: the manual notes that
  # invoking the executable from a different location needs -cm_dir, and each
  # job now runs from its own directory.
  COV_RUN   = -cm $(CM_OPTS) -cm_dir $(PAT_COV) -cm_name $(PAT_NAME)
else
  COV_ELAB :=
  COV_RUN  :=
endif

# !! Functional coverage is enabled BY DEFAULT in VCS !!
#
# The covergroups inside the target-IP, APB and AXI VIPs collect data whether
# or not this project asks for them, and they are not free. So FCOV=0 has to
# switch them off explicitly at run time, per "Recommended Coverage Settings
# for a New Project" section 1.4:
#
#   simv -covg_disable_cg   disables covergroup coverage
#   simv -assert nocovdb    disables cover property coverage
#
# FCOV=1 sets a define that tb/tests/<ip>_base_test.sv reads to call
# <ip>_top_cfg::enable_check_coverage(), and asks for the faster immediate
# assertion implementation.
#
# WHAT FCOV=1 ACTUALLY BUYS
# This template's original USB VIP shipped 19 checker files as a real
# example. They run regardless and fail the test regardless. What FCOV adds
# is the record of WHICH checks were exercised: twelve configuration fields,
# all defaulting to 0 except the three *_chk_fail_cov which default to 1. So
# by default a failing check is covered and a passing one is not, which
# cannot answer "was this check ever reached".
#
# It is a compile time define, not a plusarg, because the covergroups are
# built during build_phase.
# -----------------------------------------------------------------------------
# <TARGET_IP>_HEX_DIR is the one define whose value is a STRING, and it is
# therefore the one that cannot go on the command line.
#
# It used to be     DEFINES += +define+USB_HEX_DIR=\"$(HEX_DIR)\"
# which works locally and fails under LSF. The site's vcs wrapper re-submits
# the command through bsub, and the quotes do not survive that extra shell:
# vcs then sees a bare path where it expected a string literal and reports
#
#     full expansion of macro (USB_HEX_DIR), error at line 1
#     =>/home/.../uvm/hex
#
# Adding another layer of backslashes would fix this build and break the local
# one. A filelist is read by vcs itself, with no shell anywhere in between, so
# the quotes mean exactly what they say in both cases. Generated rather than
# checked in because the value is a path only known at build time -- the same
# reason cov_hier.cfg is generated.
# -----------------------------------------------------------------------------
# The file is written by `setup`, which every stage already depends on.
#
# HEX_DIR is named again in a comment inside the flag signature: DEFINES now
# carries only the path of this file, so without that the signature would be
# identical before and after HEX_DIR changed, and the rebuild that a changed
# stimulus path needs would never happen.
HEXDEF_F := $(SIM_ROOT_PATH)/hexdir.f
DEFINES  += -f $(HEXDEF_F)
FLAG_EXTRA += HEX_DIR=$(HEX_DIR)

ifeq ($(FCOV),1)
  DEFINES   += +define+$(TARGET_IP)_UVM_FCOV
  FCOV_ELAB := -assert fast_immediate
  FCOV_RUN  :=
else
  FCOV_ELAB :=
  FCOV_RUN  := -covg_disable_cg -assert nocovdb
endif

# -----------------------------------------------------------------------------
# Partition compile. Autopartitioning is the default with -partcomp and
# handles the cross-partition cases itself, so no +optconfigfile here.
# Any command-line change is treated as a global rebuild.
# -----------------------------------------------------------------------------
PARTCOMP_NOXMR ?= 0
override PARTCOMP_NOXMR := $(strip $(PARTCOMP_NOXMR))
PARTCOMP_EN    ?= 1
override PARTCOMP_EN := $(strip $(PARTCOMP_EN))

# UNR cannot run with partition compile, see the UNR section below, so the
# whole block has to be switchable rather than hard coded.
ifeq ($(PARTCOMP_EN),1)
# Autopartitioning, which is what -partcomp does on its own. Per "Guidelines
# for Using the Partition Compile Flow" section 1.1 it is the DEFAULT mode,
# it partitions design and testbench without being told how, and it
# "automatically takes care of the cross-partition limitations across
# partitions and re-adjusts the partitioning to avoid any cross-partition
# errors".
#
# No +optconfigfile. Manual partitioning (section 1.2) exists to isolate a
# block under active development; there is none here, and hand-written rules
# would have to track the RTL hierarchy by hand. A rule whose instance path
# does not resolve is only a warning (PC-PRNU), so a stale one leaves you with
# partitioning nobody intended and no error to say so.
PARTCOMP := -partcomp -fastpartcomp=j$(NPROC)
ifeq ($(PARTCOMP_NOXMR),1)
  PARTCOMP += -partcomp=noxmrconfig
endif
else
PARTCOMP :=
endif

# -----------------------------------------------------------------------------
# Unreachability analysis. Reports coverage bins no stimulus can reach, so
# they can be excluded rather than chased. Needs a separate licence and
# does not support partition compile, hence its own elaboration.
# -----------------------------------------------------------------------------
UNR_TOP ?= lan063
UNR_CFG ?= $(SIM_ROOT_PATH)/unr_config.txt
UNR_EL  ?=

# --- KDB (for Verdi) ---
# -kdb is needed in BOTH stages. Passing it only to vcs leaves Verdi with
# incomplete design information. -lca is a prerequisite for -kdb.
KDB := -kdb

# =============================================================================
# The three stage commands
# =============================================================================

# --- SLED transaction recording (example :449-452, :635-639) ---
#
# libsvtsled.so / libamba_sled.so are linked only when SLED=1. They wrap a SLED
# core library that VIP_HOME/lib does not ship, so linking them otherwise fails
# at ld -- after elaboration reports 0 errors, so the symptom is "no simv".
# The define below is what makes the VIP emit records; off by default.
#
# The example ties LD_LIBRARY_PATH to the same switch, but the other way
# round: it CLEARS LD_LIBRARY_PATH when SLED is off (:635-639), because a
# stale entry is a common cause of the wrong VIP library being picked up. We
# only ADD to it when SLED is on -- this environment does not own the user's
# shell, and clearing it would break unrelated tools.
#
#   make sim PATTERN=<n> SLED=1
#
# !! THIS BLOCK MUST STAY ABOVE VLOGAN_FLAGS !!
# VLOGAN_FLAGS is a := assignment, so $(SIM_BUILD_OPTS) is expanded at that
# line. Appending to SIM_BUILD_OPTS after it has no effect on vlogan, and the
# define would silently never reach the analysis stage -- the VIP would
# compile without recording and the run would look normal.
#
# Changing it forces a rebuild, like every other compile-time switch.
SLED ?= 0
override SLED := $(strip $(SLED))
ifeq ($(SLED),1)
  ifeq ($(wildcard $(VIP_LIB)/libsvtsled.so),)
    $(error SLED=1 but $(VIP_LIB)/libsvtsled.so does not exist. Check \
            VIP_LIB_ARCH='$(VIP_LIB_ARCH)' against what is under $(VIP_HOME)/lib)
  endif
  SIM_BUILD_OPTS += +define+SVT_USB_SLED_RECORD_ENABLE
  SLED_ENV       := LD_LIBRARY_PATH=$(VIP_LIB):$$LD_LIBRARY_PATH
else
  SLED_ENV       :=
endif

# DIAGNOSTIC ONLY (real example from this template's original USB project,
# dut-request.md P3/P5 STALL-vs-ACCEPT comparison, 2026-08-27): forced a
# specific USB SET_SEL request through its programming guide's default STALL
# behavior instead of an ACCEPT override (<ip>_dev_init.svh, `ifdef
# $(TARGET_IP)_DIAG_SET_SEL_FORCE_STALL`), to compare against the ACCEPT
# path's stall on the identical config. Default 0 -- normal builds are
# unaffected. This exact knob is USB-specific (SET_SEL is a real USB3
# descriptor request); keep the PATTERN -- an opt-in, default-off
# diagnostic define for an A/B comparison against a real, disputed DUT
# behavior -- and replace the specifics for TARGET_IP's own equivalent
# investigation, if any. Strip this block and the `ifdef` it feeds once the
# comparison is done.
DIAG_SET_SEL_FORCE_STALL ?= 0
override DIAG_SET_SEL_FORCE_STALL := $(strip $(DIAG_SET_SEL_FORCE_STALL))
ifeq ($(DIAG_SET_SEL_FORCE_STALL),1)
  SIM_BUILD_OPTS += +define+$(TARGET_IP)_DIAG_SET_SEL_FORCE_STALL
endif

# -kdb belongs on THIS line too. VCS User Guide, "Generating Verdi KDB":
#   "In case of VCS three-step flow, add the -kdb option in all the
#    vlogan/vhdlan/vcs command lines."
# This IS the three-step flow (vlogan UVM, vlogan design, vcs). It was
# missing here and present on the other two, which is exactly what
#   Warning-[KDB-OPTIONS] Kdb options of library "DEFAULT" are inconsistent
# reports. A partial KDB leaves Verdi with an incomplete design.
# UVM_PACKER_MAX_BYTES must match what the VIP is compiled with. The UVM
# package sizes uvm_pack_bitstream_t from it, and a mismatch is a run-time
# UVM_FATAL from svt_configuration, not a compile error:
#   set to 24000 but uvm_pack_bitstream_t only contains 4096 bytes
VLOGAN_UVM_FLAGS := $(VCS_BITMODE) $(KDB) $(NTB_UVM) -ntb_opts vera_compat \
                    +define+UVM_DISABLE_AUTO_ITEM_RECORDING \
                    +define+UVM_PACKER_MAX_BYTES=24000

# No -j here. It applies to native code generation, which happens at
# elaboration, so it belongs on the vcs line only; vlogan ignores it.
VLOGAN_FLAGS := $(VCS_BITMODE) -sverilog $(KDB) \
                -timescale=$(TIMESCALE) \
                $(NTB_UVM) $(NTB_COMMON) \
                $(SIM_BUILD_OPTS) $(SOC_DEFINES) $(DEFINES) \
                $(PA_DEFINES) $(WAVE_DEFINES) \
                $(VIP_INCDIRS) $(NTB_INCDIRS) $(TB_INCDIRS)

# +error+10000 is carried over from DUT/runver_precomp.
# -Xcheck_p1800_2009=char is NOT: it makes the VIP fail elaboration with 14
# Error-[CNST-RONV] across APB, AXI and the target-IP VIP. Synopsys's own
# example for this VIP does not pass it either. It belongs to the RTL flow,
# not to this one.
# -debug_access level, per "Recommended Debug Settings for a New Project":
#   -debug_access+all   interactive debug. Expensive on a design this size.
#   -debug_access       post-processing debug from an FSDB. What we do.
# DEBUG_ACCESS itself is set above, keyed on VERDI_HOME rather than on PA/WAVE
# -- see the ifndef VERDI_HOME block. It used to be decided here, keyed on
# compile-time PA/WAVE, which is exactly the rebuild-on-toggle coupling that
# block exists to remove; leaving this second assignment would silently
# overwrite that one (textually last wins) and reintroduce it.

# Three parallelism knobs, all from NPROC, none a substitute for another:
#   -j                     native code generation (this line only)
#   -fastpartcomp=jN       parallel partition build, inside $(PARTCOMP)
#   -hsopt=j               vcselab for GLS designs; not used, this is RTL
# !! NO +define+ ON THIS LINE. !!
# PA_DEFINES and WAVE_DEFINES used to be here as well as in VLOGAN_FLAGS, and
# in the four-step flow that is fatal:
#   Error-[PRS_OPT] Illegal use of parse only options
#     There is no source file specified ... hence VCS is running in UUM mode.
#     In UUM mode, the parse only option '+define+SVT_FSDB_ENABLE
#     +define+WAVES_FSDB +define+WAVES=fsdb' can only be used with vlogan.
# The vcs invocation here elaborates from the analysed library and is given no
# source files, so every +define+ is rejected. They are already on the vlogan
# line, which is where a define belongs and where it has any effect.
#
# This had never fired because WAVE=1 and PA=1 had only ever been used with
# the one-step flow, where vcs does get source files and a +define+ is legal.
# Turning on the four-step flow is what exposed it -- the same way it exposed
# the stale HOOK_SOURCES dependency. Incremental flows do not create these
# defects, they reveal the ones that were always there.
VCS_FLAGS := $(VCS_BITMODE) -sverilog $(KDB) -lca \
             $(DEBUG_ACCESS) \
             $(NTB_UVM) -ntb_opts use_sigprop \
             $(PARTCOMP) -j$(NPROC) \
             -Mdir=$(OUTDIR)/csrc \
             $(PA_OPTIONS) \
             $(WAVE_OPTIONS) \
             $(COV_ELAB) $(FCOV_ELAB) \
             +error+10000

# The VIP common runtime library (example :625)
ifeq ($(SLED),1)
  VCS_FLAGS += $(wildcard $(VIP_LIB)/libsvtsled.so) \
               $(wildcard $(VIP_LIB)/libamba_sled.so)
endif

# The example passes vcs_sled_options to BOTH stages (:769 and :971), so the
# define goes to elaboration as well. It is set further up, above VLOGAN_FLAGS
# -- see the SLED block there for why the position matters.
# SVT_USB_SLED_RECORD_ENABLE is the real Synopsys VIP macro name for this
# template's original USB VIP; substitute the equivalent SLED-enable macro
# name from TARGET_IP's own VIP (its naming is set by Synopsys per protocol,
# not by IP_PREFIX).
ifeq ($(SLED),1)
  VCS_FLAGS += +define+SVT_USB_SLED_RECORD_ENABLE
endif

# -----------------------------------------------------------------------------
# Per job artifact names.
#
# A JOB is one pattern at one seed. Everything a run produces is named or
# located by it, which is what allows several runs to proceed at once against
# the single shared simv.
#
#   run/<job>/                working directory of that simv process
#   report/<job>/             VIP traffic reports, PA xml, performance reports
#   coverage/<job>.vdb        that run's coverage database
#   log/<job>.log             transcript
#   fsdb/<job>.fsdb           waveform
#
# THIS BLOCK MUST STAY ABOVE RUN_FLAGS. RUN_FLAGS is `:=`, so a later
# `RUN_FLAGS += ... $(PAT_FSDB)` expands PAT_FSDB at that moment, not when the
# recipe runs. With the definitions below it, +fsdb_file= was passed EMPTY and
# every run fell back to the default novas.fsdb in the current directory --
# which is both a lost waveform and, with jobs in parallel, a collision.
# -----------------------------------------------------------------------------
# RUNTAG -- appended to JOB so two runs of the same pattern do not overwrite
# each other. RUN TIME ONLY: it touches no `+define+`, so changing it does not
# rebuild anything.
#
# WHY IT EXISTS. run/<pattern>_<seed>/ is reused on every invocation, so a
# build in progress leaves the PREVIOUS run's sim.log sitting there under the
# name the next analysis will read. That cost two wrong conclusions in one
# night -- one of them, "the tdrst hypothesis is dead", was published and had
# to be retracted after tdrst turned out to move expected_reset_end_time by
# exactly the amount it was raised. Timestamps cannot separate the two, because
# both the log and the simv are replaced every round.
#
# A staleness guard in the check script is a mitigation. Not colliding in the
# first place is the fix.
#
#   make run PATTERN=<pattern> RUNTAG=hs      -> run/<pattern>_1_hs/
#   make run PATTERN=<pattern> RUNTAG=fs      -> run/<pattern>_1_fs/
#
# Unset keeps the historical name exactly, so nothing that assumes it breaks.
# It is NOT auto-incremented on purpose: with WAVE=1 each run leaves a 300-500
# MB FSDB, and a name that silently grows a new directory every invocation
# fills the disk without anyone choosing to.
RUNTAG     ?=
override RUNTAG := $(strip $(RUNTAG))
ifeq ($(RUNTAG),)
  JOB      := $(PATTERN)_$(SEED)
else
  JOB      := $(PATTERN)_$(SEED)_$(RUNTAG)
endif
PAT_NAME   := $(JOB)
PAT_RUN    := $(RUNDIR)/$(JOB)
PAT_REPORT := $(REPORTDIR)/$(JOB)
PAT_FSDB   := $(FSDBDIR)/$(JOB).fsdb

# ---------------------------------------------------------------------------
# THERE WAS AN FSDB_LOCAL HERE. IT WAS REMOVED, AND THE REASONING IS WORTH
# KEEPING BECAUSE THE MISTAKE IS EASY TO REPEAT.
#
# It wrote the waveform to the execution host's /tmp and copied it back at the
# end, on the theory that FSDBDIR is NFS and a dumping run was I/O bound. The
# evidence was real: 94 MB/min, 1.3 GB in fourteen minutes, simv at 20-53 %
# CPU.
#
# But that measurement came from a broken configuration, not from NFS. The
# server's wave.txt was the RTL owner's original, which dumps the whole SoC
# and ignores +fsdb_off. Once the DV_UVM version was installed and the scope
# became the target-IP blocks, the rate fell to about 20 MB/min and simv ran at
# 103-112 % CPU -- above 100 % means the process is computing, not waiting on
# I/O, so there was nothing left for a faster disk to fix.
#
# The A/B that would have proved it was abandoned deliberately: each arm has
# to run until the enumeration timeout expires, which is hours, and both arms
# had already reported >100 % CPU. Paying hours of machine time and a VIP
# licence to refine a number that cannot change the decision is not
# thoroughness.
#
# And the cost was concrete. The copy back runs on normal exit, not on
# SIGKILL, so a hard-killed run left its waveform on a compute node's /tmp --
# somewhere nobody looks and nothing cleans. Seven runs were hard-killed on
# the day this was written. The option would have lost the waveform from
# exactly the runs that most needed one.
#
# If a dump ever does become I/O bound again, measure before reaching for
# this: CPU efficiency under 100 % is the symptom, and check the wave.txt in
# DUT_ROOT_PATH first, because that is where it came from last time.
# ---------------------------------------------------------------------------
PAT_COV    := $(COVDIR)/$(JOB).vdb
SIMV       := $(OUTDIR)/simv

# The transcript lives in the pattern's OWN directory, not in a shared log/
# with the pattern name encoded into the filename.
#
# WRITTEN INTO run/<job>/, NOT report/<job>/. It used to go straight into the
# report directory, which made it the one file there that was not a symlink --
# report/<job>/ is a view of the run assembled from links, and having a single
# real file in it meant "what is a link and what is not" depended on knowing
# this exception. Everything the simulation produces now lands in the run
# directory and the report links to it, with no special case.
#
# Two links point at it, for two different questions:
#   report/<job>/sim.log  "everything about this one run"
#   log/<job>.log         "which pattern failed", answered by one grep over
#                         log/*.log rather than a walk over thirty directories
# Symlinks both, so no copy can go stale.
PAT_LOG      := $(PAT_RUN)/sim.log
PAT_LOG_LINK := $(LOGDIR)/$(JOB).log

# --- Run time (example sim_run_options / vcs_run_options) ---
# +vcs+flush+log / +vcs+flush+fopen: VCS user guide, "Options for Flushing
# Certain Output Text File Buffers" -- raises the flush frequency of the -l
# log file and of every $fopen'd text file (transaction_trace, novas_dump.log
# etc). Unconditional, not gated behind a switch, so a background watcher
# polling sim.log for FINAL_CHECK/SvtTestEpilog is not reading a buffer that
# is minutes stale. +vcs+flush+dump (FSDB) deliberately left out -- WAVE=1
# already stresses NFS I/O (trap 95) and nothing here needs faster FSDB
# flush. Cost (extra I/O from more frequent small writes) not yet measured
# against a long regression; revisit if it shows up.
RUN_FLAGS := +PATTERN=$(PATTERN) \
             +UVM_TESTNAME=$(TEST) \
             +UVM_VERBOSITY=$(VERB) \
             +ntb_random_seed=$(SEED) \
             +ntb_solver_array_size_warn=100000 \
             +vcs+flush+log +vcs+flush+fopen \
             $(PA_RUN_OPTS) $(COV_RUN) $(FCOV_RUN)

# TOTAL_RUNTIME. Emitted only when it is set, so the default run line is
# byte for byte what it was and a plusarg the test would ignore anyway does
# not appear in every log.
ifneq ($(TOTAL_RUNTIME),0)
  RUN_FLAGS += +$(TARGET_IP)_TOTAL_RUNTIME_NS=$(TOTAL_RUNTIME)
endif

# Waveform scope. wave.txt dumps the target-IP blocks by default; these two
# select the other scopes. WAVE=0 turns dumping off entirely, which is what a
# regression wants.
ifeq ($(WAVE),0)
  RUN_FLAGS += +fsdb_off
endif
ifeq ($(WAVE),full)
  RUN_FLAGS += +fsdb_full
endif
# wave.txt reads this to name the file, so each pattern keeps its own.
ifneq ($(filter $(WAVE),1 full),)
  RUN_FLAGS += +fsdb_file=$(PAT_FSDB)
endif

# <ip>_base_test writes every UVM and VIP report here as well as to sim.log.
#
# Left in the run directory on purpose, alongside everything else the
# simulation produces. report/<job>/ is a view built from symlinks after the
# run, not a second place to write to, so a file that is being written should
# be under PAT_RUN and reachable from the report directory by link.
# collect_reports makes that link.
#
# UVM_LOG_FILE=off disables the second copy.
UVM_LOG_FILE ?= $(PAT_RUN)/uvm.log
ifneq ($(strip $(UVM_LOG_FILE)),)
  RUN_FLAGS += +UVM_LOG_FILE=$(strip $(UVM_LOG_FILE))
endif

# ---------------------------------------------------------------------------
# FSDB_START / FSDB_STOP -- record only the window being debugged
#
# wave.txt reads both (DV_UVM HOOK 1b and 1c). Unset means record everything,
# which is what it did before.
#
# This is the useful control for link bring-up: LTSSM activity is between
# roughly 14 us and 250 us of a run that goes on much longer, so
#
#   make sim PATTERN=<pattern> WAVE=1 FSDB_START=10000 FSDB_STOP=300000
#
# records the part being debugged and skips the rest.
#
# A size cap was tried too and removed: `$fsdbDumpLimit` does not exist in
# this Verdi. The documented mechanism is `$fsdbAutoSwitchDumpfile`, which
# rotates files rather than stopping and needs a naming decision. The window
# bounds the size for the case that matters, so it is not urgent.
# ---------------------------------------------------------------------------
FSDB_START ?=
FSDB_STOP  ?=
ifneq ($(strip $(FSDB_START)),)
  RUN_FLAGS += +fsdb_start=$(strip $(FSDB_START))
endif
ifneq ($(strip $(FSDB_STOP)),)
  RUN_FLAGS += +fsdb_stop=$(strip $(FSDB_STOP))
endif

# VIP_REPORT / VIP_STATUS (declared above with the other VIP_* switches).
# Both default ON at run time (<ip>_top_cfg.sv: <ip>_vip_report_rt() /
# <ip>_vip_status_rt()), so only the OFF case needs a plusarg -- same "default
# on, one override flag" shape as +fsdb_off.
ifeq ($(VIP_REPORT),0)
  RUN_FLAGS += +vip_report_off
endif
ifeq ($(VIP_STATUS),0)
  RUN_FLAGS += +vip_status_off
endif

# Run time register bases. These override the compile time defines and need
# no rebuild, which is what makes them useful while hunting for the value.
# Bare hex, no 0x prefix: $value$plusargs %h does not accept one.
# (Named IP0_BASE_RT/IP1_BASE_RT, not $(TARGET_IP)0_BASE_RT/..., because a
# Make variable's own NAME must stay a fixed literal token to remain
# overridable from the command line -- see the genericization report.)
IP0_BASE_RT ?=
IP1_BASE_RT ?=
GTOP_BASE_RT ?=
ifneq ($(IP0_BASE_RT),)
  RUN_FLAGS += +$(TARGET_IP)0_BASE_ADDR=$(IP0_BASE_RT)
endif
ifneq ($(IP1_BASE_RT),)
  RUN_FLAGS += +$(TARGET_IP)1_BASE_ADDR=$(IP1_BASE_RT)
endif
ifneq ($(GTOP_BASE_RT),)
  RUN_FLAGS += +GTOP_BASE_ADDR=$(GTOP_BASE_RT)
endif

# SPEED0/SPEED1/PORTS (declared above at line 292/294/299). Run time only,
# no rebuild -- replaces an older +define+<ip>0_SPEED_*/+define+<ip>1_SPEED_*/
# +define+<ip>_PORT0_ONLY/+define+<ip>_PORT1_ONLY compile-time scheme.
# Resolved independently by each consumer via $value$plusargs on these exact
# names (<ip>_ep_check.sv build_speed(), <ip>_dev_init.svh's
# <ip>0_speed_rt/<ip>1_speed_rt, <ip>_stages.svh's <ip>_ports_rt,
# <ip>_top_cfg.sv, <ip>_uvm_bind.sv's SS UI clock). Always present, like
# IP_SCALED_MODE below -- every build has a speed and a port set, there is no
# "off" state to gate on.
RUN_FLAGS += +$(TARGET_IP)0_SPEED=$(SPEED0)
RUN_FLAGS += +$(TARGET_IP)1_SPEED=$(SPEED1)
RUN_FLAGS += +$(TARGET_IP)_PORTS=$(PORTS)

# HS_WINDOW_US (declared above, with the other testbench-override switches).
# Run time only, no rebuild -- see <ip>_stages.svh's <ip>_HS_WINDOW_FORCE.
ifneq ($(HS_WINDOW_US),0)
  RUN_FLAGS += +HS_WINDOW_US=$(HS_WINDOW_US)
endif

# AXI_FORCE (declared above at line 450). Run time only, no rebuild -- see
# <ip>_probe_if.sv's axi_force_rt, which resolves the identical plusarg name.
ifeq ($(AXI_FORCE),1)
  RUN_FLAGS += +AXI_FORCE=1
endif

# LANE_FLIP (declared above). Run time only, no rebuild -- see
# lane_flip_rt in <ip>_uvm_bind.sv, which resolves this identical plusarg name.
ifeq ($(LANE_FLIP),1)
  RUN_FLAGS += +LANE_FLIP=1
endif

# ORIENTATION0/ORIENTATION1 (declared above). Always present, like
# IP0_SPEED/IP1_SPEED above -- 0 (Normal) is a real, valid value, not an
# "off" state to gate on. Read independently by dv_uvm_hook.svh (DUT-side
# TCA_TCPC write) and <ip>_uvm_bind.sv (testbench-side lane wiring).
RUN_FLAGS += +ORIENTATION0=$(ORIENTATION0)
RUN_FLAGS += +ORIENTATION1=$(ORIENTATION1)
# LANE_SWAP0/LANE_SWAP1 (declared above). Empty by default and forwarded
# only when the user actually sets one -- an always-forwarded +LANE_SWAP0=0
# would silently pin the wiring to Normal regardless of ORIENTATION0/1,
# defeating the single-source-of-truth this pair exists for.
ifneq ($(LANE_SWAP0),)
  RUN_FLAGS += +LANE_SWAP0=$(LANE_SWAP0)
endif
ifneq ($(LANE_SWAP1),)
  RUN_FLAGS += +LANE_SWAP1=$(LANE_SWAP1)
endif
# LANE_FLIP0/LANE_FLIP1 (declared above). Same empty-by-default forwarding
# rule as LANE_SWAP0/1 -- an always-forwarded +LANE_FLIP0=0 would silently
# pin port0 to unflipped regardless of the shared LANE_FLIP default.
ifneq ($(LANE_FLIP0),)
  RUN_FLAGS += +LANE_FLIP0=$(LANE_FLIP0)
endif
ifneq ($(LANE_FLIP1),)
  RUN_FLAGS += +LANE_FLIP1=$(LANE_FLIP1)
endif

# Anything the user wants to hand the simulation, verbatim. Deliberately last
# so it can override what the switches above set.
#
#   make sim PATTERN=smoke PLUSARGS="+UVM_VERBOSITY=UVM_HIGH +$(IP_PREFIX)pa"
#
# This exists because the first experiment switch in this environment was
# written as a `+define+`, and a define changes the analysis flags,
# invalidates every stamp, and costs a full rebuild each time it moves. A
# switch that exists to be A/B compared belongs at run time, where both arms
# share one simv. (That particular switch is gone -- the thing it was gating
# turned out to be correct -- but the lesson and the variable stay.)
PLUSARGS ?=
# Always present, never defaulted-to in the RTL. See the note at the knob.
RUN_FLAGS += +$(TARGET_IP)_SCALED_MODE=$(IP_SCALED_MODE)

# Component-scoped verbosity. Emitted only when asked for, and ECHOED, because
# a component path that matches nothing is accepted in silence -- the run looks
# normal and the missing output reads as the VIP having nothing to say.
ifneq ($(VERB_COMP),)
  RUN_FLAGS += +uvm_set_verbosity=$(VERB_COMP),_ALL_,$(VERB_LEVEL),run
  $(info [cfg] VERB_COMP=$(VERB_COMP) at $(VERB_LEVEL) -- if that component \
does not exist, UVM ignores it silently and the log will look untouched.)
endif

# sync_ts_ratio_check_tx_passive: root-caused (dut-request.md), demoted by
# default -- same "default on, one override flag" shape as VIP_REPORT/
# VIP_STATUS above. It is a mechanical side effect of sync_after_ts_check_count
# (the RX-side fix) sharing cfg.host_cfg[p] with this TX-passive checker, not a
# DUT defect: the DUT's receive path has no documented cadence requirement on
# SYNC-after-TS spacing (checked against the programming guide and databook),
# and the check self-clears the instant U0 is reached. DEMOTE_SYNC_TS_RATIO=0
# restores it as UVM_ERROR, e.g. to re-verify the root cause itself.
DEMOTE_SYNC_TS_RATIO ?= 1
ifeq ($(DEMOTE_SYNC_TS_RATIO),1)
  RUN_FLAGS += +$(TARGET_IP)_DEMOTE_ID=sync_ts_ratio_check_tx_passive
endif

# expected_recovery_check (CREDIT_HP_TIMER_1's checker, dut-request.md P12):
# OPT-IN ONLY, default 0 -- unlike sync_ts_ratio above, this one's root cause
# is NOT yet confirmed benign, only narrowed (dv-workflow ww4aipu1d,
# 2026-08-27): the checker pairs with deliberate VIP link-error-injection
# sequences this project never calls (expected_recovery_entry defaults 0,
# set 1 only inside *_link_errors_* sequences), so it flags any genuine
# self-healing LTSSM Recovery entry as a failure -- confirmed self-healing
# for the one occurrence measured (port0, 2775.68ns recovery, no repeat, no
# other error). Two prior timer raises (200us, 350us) were each defeated by
# a longer run, so raising the number again is not the fix -- this demotes
# the checker's severity instead, but stays default-off since the DUT-side
# credit-return tail this masks is still open, not closed.
DEMOTE_CREDIT_HP_TIMER ?= 0
ifeq ($(DEMOTE_CREDIT_HP_TIMER),1)
  RUN_FLAGS += +$(TARGET_IP)_DEMOTE_ID=expected_recovery_check
endif

# non_streamable_ep_received_unexpected_non_successive_erdy /
# received_erdy_while_dps_unacked (Gen2+Gen2 dual-port, dut-request.md P16):
# CLOSED as VIP-side, demoted by default -- same shape as sync_ts_ratio above.
# Directly confirmed twice (fsdbreport on the DUT's own EIM/AXE/TXE sequencing,
# two independent reproductions at t~=749781ns): the DUT issues exactly one
# correctly-timed ERDY per transfer, no double-issue, no premature clear, for
# two genuinely separate, legitimate control transfers ~5.9us apart on the same
# endpoint (EP0 IN). The VIP's own published Class Reference
# (class_svt_usb_endpoint_status.html, not encrypted) documents the checker's
# underlying state, packet_activity_pending, as clearing -- for an IN endpoint,
# VIP as Host -- only once the Host VIP itself sends an ACK with NumP==0 for
# the prior transfer's DP burst: a fact about the Host VIP's own ACK pacing,
# not anything the DUT emits or withholds. DEMOTE_P16_ERDY_DPS=0 restores both
# as UVM_ERROR, e.g. to re-verify against a future VIP version.
DEMOTE_P16_ERDY_DPS ?= 1
ifeq ($(DEMOTE_P16_ERDY_DPS),1)
  RUN_FLAGS += +$(TARGET_IP)_DEMOTE_ID=non_streamable_ep_received_unexpected_non_successive_erdy
  RUN_FLAGS += +$(TARGET_IP)_DEMOTE_ID=received_erdy_while_dps_unacked
endif

RUN_FLAGS += $(PLUSARGS)

# =============================================================================
.PHONY: help dirs setup analyze_uvm analyze_dut analyze_tb analyze elab \
        compile sim debug verdi \
        run regress regress_summary collect_reports \
        job_summary record_result record_suite \
        pattern_pool ADD_PAT RM_PAT \
        lsf_kill lsf_status lsf_queues lsf_report \
        list_patterns cov cov_merge cov_gui unr check clean distclean

# -----------------------------------------------------------------------------
# Static checks: include order, VIP class availability, VIP enum members, and
# Makefile expansion order. Seconds rather than the minutes a rebuild costs,
# and they report every instance instead of the one the compiler stops on.
#
# sim/Makefile is a symlink to scripts/Makefile, so MK_DIR resolves to sim/
# when make is run from there. Accept both layouts.
# -----------------------------------------------------------------------------
ifneq ($(wildcard $(MK_DIR)/check/include_order.py),)
  CHECKDIR := $(MK_DIR)/check
else
  CHECKDIR := $(MK_DIR)/scripts/check
endif

# EVERY CHECKER UNDER check/ IS INVOKED HERE, AND FIVE OF THEM WERE NOT UNTIL
# 2026-08-16. pattern_rules.py, make_order.py, macro_selfcontained.py,
# zero_delay_loops.py and reg_audit.py existed, worked, and were reachable by
# no target at all -- so the branch architecture was "enforced" by a tool
# nothing ran, and `make check` silently covered three of eight checks while
# the help text advertised more.
#
# ADVISORY, like the four that were already here: every line ends in `|| true`
# so one failure does not hide the rest. That is a deliberate carry-over of the
# existing convention, NOT a judgement that these cannot fail a build --
# pattern_rules.py in particular returns non-zero on a real architecture
# violation, and promoting it to a hard failure is a policy change worth making
# separately and on purpose.
check:
	@echo "=== include order ==="
	@python3 $(CHECKDIR)/include_order.py $(UVM_ROOT_PATH) || true
	@echo ""
	@echo "=== pattern framework rules (blocking + branch_a0/a1 + branch_fw + branch_b0/b1) ==="
	@python3 $(CHECKDIR)/pattern_rules.py $(UVM_ROOT_PATH) || true
	@echo ""
	@echo "=== Makefile expansion order (:= and prerequisites using a later variable) ==="
	@python3 $(CHECKDIR)/make_order.py $(MK_DIR)/Makefile || true
	@echo ""
	@echo "=== testbench-stage macros defined or reachable ==="
	@python3 $(CHECKDIR)/macro_selfcontained.py $(UVM_ROOT_PATH) $(MK_DIR)/Makefile || true
	@echo ""
	@echo "=== zero-delay loops (a forever with no delay stops simulated time) ==="
	@python3 $(CHECKDIR)/zero_delay_loops.py $(UVM_ROOT_PATH) || true
	@echo ""
	@echo "=== register field audit ==="
	@python3 $(CHECKDIR)/reg_audit.py $(TBDIR) || true
	@echo ""
	@echo "=== VIP class availability (ifdef guards) ==="
	@grep -rhoE '\bsvt_[a-z][A-Za-z_0-9]*_sequence\b' $(TBDIR) \
	   | sort -u > $(SIMDIR)/.check_names.txt
	@python3 $(CHECKDIR)/vip_guards.py $(VIP_HOME) $(SIMDIR)/.check_names.txt || true
	@echo ""
	@echo "=== VIP enum and constant members ==="
	@grep -rhoE '\bsvt_\w+::[A-Z][A-Z0-9_]*' $(TBDIR) \
	   | sort -u > $(SIMDIR)/.check_refs.txt
	@python3 $(CHECKDIR)/vip_members.py $(VIP_HOME) $(SIMDIR)/.check_refs.txt || true
	@rm -f $(SIMDIR)/.check_names.txt $(SIMDIR)/.check_refs.txt
	@echo ""
	@echo "=== VIP paths (hard rule: include/ src/ lib/ from VIP_HOME only) ==="
	@echo "VIP_HOME = $(VIP_HOME)"
	@bad=0; \
	for p in $(VIP_INC) $(VIP_SRC) $(VIP_LIB); do \
	  case "$$p" in \
	    $(VIP_HOME)/*) ;; \
	    *) echo "  ESCAPES VIP_HOME: $$p"; bad=1 ;; \
	  esac; \
	done; \
	if [ "$$bad" = "0" ]; then \
	  echo "  every path this Makefile emits is under VIP_HOME"; \
	fi
	@# What VIP_HOME's own files then pull in is a separate question, and the
	@# analysis log is the only place it shows. Report it rather than let it
	@# stay invisible.
	@if [ -f $(LOGDIR)/analyze.log ]; then \
	  out=$$(grep -c "Parsing.*$(VIP_HOME)" $(LOGDIR)/analyze.log || true); \
	  esc=$$(grep "Parsing included file" $(LOGDIR)/analyze.log \
	         | grep -c "svt" | head -1); \
	  ext=$$(grep "Parsing included file" $(LOGDIR)/analyze.log \
	         | grep "svt" | grep -vc "$(VIP_HOME)" || true); \
	  echo "  last analysis parsed $$out VIP files from VIP_HOME,"; \
	  echo "                       $$ext from elsewhere"; \
	  if [ "$$ext" != "0" ]; then \
	    echo ""; \
	    echo "  Those come from inside VIP_HOME, not from this Makefile:"; \
	    echo "    $(VIP_INC)/sverilog/svt_source_defines.svi"; \
	    echo "  is one line that hardcodes the install path the VIP was"; \
	    echo "  installed from. To make the rule absolute, edit that line, or"; \
	    echo "  re-run the VIP installer with design_dir = VIP_HOME."; \
	  fi; \
	else \
	  echo "  (no analyze.log yet -- run make compile to measure the rest)"; \
	fi

help:
	@echo ""
	@echo "$(TARGET_IP) IP-level UVM verification environment"
	@echo "========================="
	@echo ""
	@echo "Target:"
	@echo "  setup            generate synopsys_sim.setup and the directories"
	@echo "  analyze_uvm      stage 1a: vlogan analyses the UVM library"
	@echo "  analyze_dut      stage 1b: vlogan analyses the DUT   (FLOW=fourstep)"
	@echo "  analyze_tb       stage 1c: vlogan analyses the testbench"
	@echo "                   (a tb edit re-runs 1c only, not the DUT)"
	@echo "  analyze          alias for analyze_tb"
	@echo "  elab             stage 2 : vcs elaborates, produces simv"
	@echo "  compile          build simv, per FLOW (now: $(FLOW))"
	@echo "  sim   PATTERN=<n> run one pattern"
	@echo "  debug PATTERN=<n> run with +fsdb, then open Verdi"
	@echo "  verdi PATTERN=<n> open Verdi on an existing FSDB, signals from waves.tcl"
	@echo "  run   PATTERN=<n> run one pattern, never builds (what LSF jobs use)"
	@echo "  regress          run every pattern in the suite,"
	@echo "                   JOBS=<n> locally, or LSF=1 on the farm"
	@echo "  lsf_status       jobs still alive for SUITE"
	@echo "  lsf_report       the summary table for a regression already run,"
	@echo "                   without submitting anything. The jobs outlive the"
	@echo "                   shell that launched them; the polling loop does not"
	@echo "  lsf_kill         kill every job this suite submitted"
	@echo "  lsf_queues       queue limits and hosts for LSF_QUEUE"
	@echo "  ADD_PAT PAT_NAME=<f>.txt PAT_DIR=<d>   register a pattern"
	@echo "  RM_PAT  PAT_NAME=<f>.txt PAT_DIR=<d>   un-register it (keeps the file)"
	@echo "  regress_summary  reprint the last regression's verdicts"
	@echo "  collect_reports  gather a run's VIP reports by hand after a crash"
	@echo "  cov              urg report, per-test correlation"
	@echo "  cov_merge        merge vdbs, COV_DIRS=<list>"
	@echo "  cov_gui          Verdi coverage GUI"
	@echo "  check            static checks: include order, VIP class"
	@echo "                   availability, VIP enum members. Seconds, not"
	@echo "                   minutes -- run it before a long build"
	@echo "  clean / distclean"
	@echo ""
	@echo "Variables (* = changing it forces a rebuild, partcomp treats any command line change as global):"
	@echo "  FLOW=onestep|fourstep  build arrangement   (now: $(FLOW))"
	@echo "                   onestep  : one vcs call, simplest, no incremental"
	@echo "                   fourstep : vlogan x3 + vcs, incremental, per-file"
	@echo "                              compilation units"
	@echo "  PATTERN=<name>   pattern to run     (now: $(PATTERN))"
	@echo "  SEED=<n>         random seed       (now: $(SEED))"
	@echo "  WAVE=0|1|full    FSDB: off | target-IP blocks | whole SoC  (now: $(WAVE))"
	@echo "                   run-time only, no rebuild -- unless this simv was"
	@echo "                   built with VERDI_HOME unset, see the Makefile note"
	@echo "                   at the debug-access block"
	@echo "  FSDB_START=<ns>  record only a window, e.g. FSDB_START=10000"
	@echo "  FSDB_STOP=<ns>   FSDB_STOP=300000 covers link bring-up"
	@echo "  PA=0|1           Protocol Analyzer, needs VERDI_HOME (now: $(PA))"
	@echo "                   run-time only, same caveat as WAVE above"
	@echo "* COV=0|1          VCS code coverage                   (now: $(COV))"
	@echo "* FCOV=0|1         VIP functional coverage, ON by default in VCS (now: $(FCOV))"
	@echo "* DMA_MON=0|1      passive monitor on $(IP_PREFIX)m_*      (now: $(DMA_MON))"
	@echo "* EVT_AXI_CHECK=0|1 evt_count_r-vs-AXI-write P3 checker (now: $(EVT_AXI_CHECK)), default off, path unconfirmed"
	@echo "* SLED=0|1         VIP SLED transaction recording      (now: $(SLED))"
	@echo "  COV_SCOPE=<list> code coverage scope   (now: $(COV_SCOPE))"
	@echo "  COV_EXCLUDE=<l>  carved back out"
	@echo "  WAVES_SETUP=<f>  Verdi signal setup tcl (now: $(WAVES_SETUP))"
	@echo "  IP0_BASE=0x..    instance0 APB base, rebuild (now: $(IP0_BASE))"
	@echo "  IP1_BASE=0x..    instance1 APB base, rebuild (now: $(IP1_BASE))"
	@echo "  GTOP_BASE=0x..   gtop greg base, rebuild(now: $(GTOP_BASE))"
	@echo "  IP0_BASE_RT=<hex>  same, run time, no rebuild, bare hex"
	@echo "  VERB=<level>     UVM verbosity     (now: $(VERB))"
	@echo "  SPEED=<s>        usb20|gen1|gen2|ss_capable (this template's example"
	@echo "                   enum -- replace with TARGET_IP's own) (now: $(SPEED))"
	@echo "  PORTS=0|1|both   which target-IP ports       (now: $(PORTS))"
	@echo "  AXI_FORCE=0|1    AXI master takeover, run time (now: $(AXI_FORCE))"
	@echo "  SUITE=<name>     all, list, or one of: $(SUITE_NAMES)  (now: $(SUITE))"
	@echo "                   list = the patterns in regression.list"
	@echo "  RECORD=0|1       a PASS adds the pattern to regression.list,"
	@echo "                   a FAIL removes it            (now: $(RECORD))"
	@echo "  REGRESSION_LIST=<f>  (now: $(REGRESSION_LIST))"
	@echo "  JOBS=<n>         patterns run at once during regress (now: $(JOBS))"
	@echo "                   one shared simv, one run directory each."
	@echo "                   Distinct from NPROC, which parallelises the BUILD"
	@echo "  NPROC=<n>        build parallelism (now: $(NPROC))"
	@echo ""
	@echo "LSF:"
	@echo "  LSF=0|1|int      0 local, 1 batch, int interactive (now: $(LSF))"
	@echo "                   sets the three below at once"
	@echo "  LSF_COMPILE=..   vlogan and vcs           (now: $(LSF_COMPILE))"
	@echo "  LSF_SIM=..       simv runs                (now: $(LSF_SIM))"
	@echo "  LSF_VERDI=int|1  Verdi mode. Always on -- this site's Verdi refuses"
	@echo "                   to start without -lsfon/-lsfint (now: $(LSF_VERDI))"
	@echo "  LSF_QUEUE=<q>    queue for vcs/vlogan/simv  (now: $(LSF_QUEUE))"
	@echo "  LSF_VERDI_QUEUE=<q>  queue for Verdi        (now: $(LSF_VERDI_QUEUE))"
	@echo "  LSF_NCORE=<n>    cores reserved per job     (now: $(LSF_NCORE))"
	@echo "                   also caps -j, so it sets build speed: a local"
	@echo "                   -j30 elaboration takes ~7min, the same build at"
	@echo "                   -lsfncore 8 takes ~20. The queue's hosts have 24"
	@echo "                   slots, so raise it when the farm is quiet"
	@echo "  LSF_MEM=<n>      memory rusage, -lsfrum     (now: $(LSF_MEM))"
	@echo "  LSF_COMP_TIMEOUT=<m>  minutes, simv jobs only (now: $(LSF_COMP_TIMEOUT))"
	@echo "  LSF_QUEUE=<q>    queue                    (now: $(LSF_QUEUE))"
	@echo "  LSF_JOBS=<n>     concurrent jobs          (now: $(LSF_JOBS))"
	@echo "  LSF_TIMEOUT=<m>  minutes per job, bsub -W (now: $(LSF_TIMEOUT))"
	@echo "                   the vcs queue has no RUNLIMIT of its own, so this"
	@echo "                   is the only thing bounding a hung job"
	@echo "  LSF_IDLE=<m>     minutes of no log growth before a job is called"
	@echo "                   hung                     (now: $(LSF_IDLE))"
	@echo "  LSF_HANG_KILL=0|1  kill it when that happens (now: $(LSF_HANG_KILL))"
	@echo "  LSF_POLL=<s>     status refresh interval  (now: $(LSF_POLL))"
	@echo "  LSF_SETUP=<file> sourced inside each job. Leave empty to inherit"
	@echo "                   the submitting shell's environment, which is the"
	@echo "                   normal case                (now: $(LSF_SETUP))"
	@echo "  LSF_RES=<str>    extra bsub -R             (now: $(LSF_RES))"
	@echo "  LSF_PREFLIGHT=0|1  check tools/simv on a host before submitting"
	@echo "  TIMESCALE=<t>    time unit/precision     (now: $(TIMESCALE))"
	@echo ""
	@echo "Where a run's output goes (<job> = <pattern>_<seed>):"
	@echo "  log/<job>.log            transcript"
	@echo "  report/<job>/            VIP traffic reports, PA xml, performance"
	@echo "  coverage/<job>.vdb       that run's database; make cov merges them"
	@echo "  fsdb/<job>.fsdb          waveform"
	@echo "  run/<job>/               the simv working directory, debris only"
	@echo "  output/simv              ONE elaboration, shared by every job"
	@echo ""
	@echo "Paths (user supplied, all four required):"
	@echo "  VIP_HOME        complete VIP tree, $(TARGET_IP)+APB+AXI in one delivery"
	@echo "                  (now: $(VIP_HOME))"
	@echo "  DUT_ROOT_PATH   RTL tree; MACRO MODEL ENV DUMMY_TOP RTLCAT vcs.opt as siblings"
	@echo "                  (now: $(DUT_ROOT_PATH))"
	@echo "  UVM_ROOT_PATH   UVM environment tree: tb/ filelist/ docs/ vplan/"
	@echo "                  (now: $(UVM_ROOT_PATH))"
	@echo "  SIM_ROOT_PATH   product tree: scripts/ fsdb/ log/ output/ coverage/"
	@echo "                  (now: $(SIM_ROOT_PATH))"
	@echo ""
	@echo "EDA variables: VCS_HOME  UVM_HOME  VERDI_HOME (required when WAVE or PA is on)"
	@echo "Optional: DUT_OPT=$(DUT_OPT)  VIP_LIB_ARCH=$(VIP_LIB_ARCH)"
	@echo ""
	@echo "Note: register access -- including command.txt and GLOBAL_INIT \`CPUWRITE*"
	@echo "      is routed entirely to UVM APB sequences, unconditionally. There is"
	@echo "      no GSI fallback and no switch to turn it off. The run must still"
	@echo "      pass +UVM_TESTNAME."
	@echo ""

dirs:
	@mkdir -p $(SIM_ROOT_PATH) $(SIM_SCRIPTS) $(FSDBDIR) $(LOGDIR) \
	          $(OUTDIR) $(COVDIR) $(REPORTDIR) $(RUNDIR) $(WORKDIR)

# -----------------------------------------------------------------------------
# synopsys_sim.setup maps the logical library. SYNOPSYS_SIM_SETUP is
# exported so every stage reads the same file wherever it runs -- a bare
# name is looked for in the current directory, and stage 1b does not run in
# SIMDIR.
# -----------------------------------------------------------------------------
setup: dirs
	@printf 'WORK > DEFAULT\nDEFAULT : $(WORKDIR)\n' > $(SIM_ROOT_PATH)/synopsys_sim.setup
	@mkdir -p $(WORKDIR)
	@# The one string-valued define, kept off the command line -- see the
	@# $(TARGET_IP)_HEX_DIR block for why. Rewritten every time so it tracks
	@# HEX_DIR.
	@#
	@# The backslashes are required INSIDE the filelist too. Tested directly:
	@#   +define+X="path"    ->  Error-[SE], macro expands to a bare path
	@#   +define+X=\"path\"  ->  analysed clean
	@# So the escaping was never the problem -- the extra shell the site's vcs
	@# wrapper adds was eating it. printf '%s' rather than echo, because echo
	@# is allowed to interpret backslashes and here they must survive verbatim.
	@#
	@# $(TARGET_IP)_HEX_DIR is defined either way. The testbench concatenates
	@# it into file names unconditionally, so leaving it undefined turns a
	@# data question into a compile error in <ip>_trb_defs.svh. With HEX_DIR
	@# empty it becomes the empty string, and $readmemh then fails to find a
	@# relative path -- which is the intended outcome when the answer is
	@# "these patterns no longer load stimulus".
	@printf '%s\n' '+define+$(TARGET_IP)_HEX_DIR=\"$(strip $(HEX_DIR))\"' > $(HEXDEF_F)
	@if [ -z "$(strip $(HEX_DIR))" ]; then \
	   echo "note: HEX_DIR is empty, so $(TARGET_IP)_HEX_DIR compiles to \"\" and no"; \
	   echo "      stimulus files will be found. Set HEX_DIR to re-enable."; \
	 fi

# These must stay ABOVE the stage rules below. A prerequisite list is
# expanded when the rule is READ, so a name defined later expands to
# nothing and the rule silently has no dependencies.


# What makes each stage re-run. vlogan has no notion of a stale library, so
# this is entirely the Makefile's job.
#   DUT_SOURCES  vcs.opt lists the RTL, it is not the RTL. Without this a DUT
#                update that leaves vcs.opt alone is never re-analysed.
#   FLAGSIG      the analysis flags. Without this a new +define+ never reaches
#                vlogan and the run looks normal while doing nothing.
#                Rewritten only when the flags change.
# -----------------------------------------------------------------------------
# FLOW -- which build arrangement to use
#
#   onestep   (default) one vcs call. No library, no stage ordering. No
#             incremental analysis, and all files share one $unit scope.
#   fourstep  vlogan UVM / DUT / testbench, then vcs. Incremental, and each
#             file gets its own compilation unit.
#
# Both produce the same $(SIMV). Run fourstep before trusting a clean onestep
# build: one shared $unit can hide a missing `include.
# -----------------------------------------------------------------------------
# DEFAULT IS FOURSTEP. Only that flow has incremental analysis, and only
# that flow gives each file its own compilation unit -- one shared $unit
# hides a missing `include. onestep was the default while the three-step
# split was being debugged, and stayed after the reason lapsed.
FLOW ?= fourstep
override FLOW := $(strip $(FLOW))
ifeq ($(filter $(FLOW),onestep fourstep),)
  $(error FLOW='$(FLOW)' is not valid. Use FLOW=onestep or FLOW=fourstep)
endif

# Switching flows clears the other flow's products first. SYNOPSYS_SIM_SETUP is
# exported for every stage, so a one-step vcs also sees the library fourstep
# populated, and a module present in both is a silent wrong-version hazard.
# Make cannot see this, so the flow in use is recorded. Staying on one flow
# rewrites nothing and keeps incremental analysis.
FLOWTAG := $(SIMDIR)/.flow

$(FLOWTAG): FORCE
	@mkdir -p $(SIMDIR)
	@if [ "$$(cat $@ 2>/dev/null)" != "$(FLOW)" ]; then \
	   echo "=== flow is now '$(FLOW)' (was '$$(cat $@ 2>/dev/null || echo none)')"; \
	   echo "    removing the other flow's products so nothing stale is linked"; \
	   rm -rf $(SIMDIR)/.uvm.stamp $(SIMDIR)/.dut.stamp $(SIMDIR)/.analyze.stamp \
	          $(WORKDIR) $(OUTDIR)/csrc $(SIMV) $(SIMV).daidir; \
	   echo "$(FLOW)" > $@; \
	 fi

# Three things were missing here, all of them silent:
#
#   subdirectories   this template's original project's real example:
#                    RTLCAT/USB_FPGA/include_ctrl/udc_DWC_usb31_params.svh is
#                    the DUT's configuration. A new delivery that changes it
#                    and nothing else was elaborated from the old analysis.
#                    Re-check the current DUT's own RTLCAT layout for the
#                    equivalent nested configuration subdirectory.
#   .sv and .svh     outside RTLCAT only *.v was matched.
#   command.txt      a DUT deliverable, `include-d by MODEL_ALL.v, sitting in
#   wave.txt         DUT_ROOT_PATH itself and matched by nothing at all.
#
# Make's $(wildcard) has no ** so the levels are written out. Three deep covers
# every include directory in the delivered tree; if a fourth ever appears the
# symptom is a stale elaboration, not an error, so check here first.
DUT_SOURCES := $(wildcard $(DUT_ROOT_PATH)/command.txt $(DUT_ROOT_PATH)/wave.txt \
                          $(DUT_ROOT_PATH)/RTLCAT/*.v $(DUT_ROOT_PATH)/RTLCAT/*.sv \
                          $(DUT_ROOT_PATH)/RTLCAT/*.svh \
                          $(DUT_ROOT_PATH)/RTLCAT/*/*.v $(DUT_ROOT_PATH)/RTLCAT/*/*.sv \
                          $(DUT_ROOT_PATH)/RTLCAT/*/*.svh \
                          $(DUT_ROOT_PATH)/RTLCAT/*/*/*.v $(DUT_ROOT_PATH)/RTLCAT/*/*/*.sv \
                          $(DUT_ROOT_PATH)/RTLCAT/*/*/*.svh \
                          $(DUT_ROOT_PATH)/MODEL/*.v $(DUT_ROOT_PATH)/MODEL/*.sv \
                          $(DUT_ROOT_PATH)/MODEL/*.svh $(DUT_ROOT_PATH)/MODEL/*/*.v \
                          $(DUT_ROOT_PATH)/MODEL/*/*/*.v \
                          $(DUT_ROOT_PATH)/MACRO/*.v $(DUT_ROOT_PATH)/MACRO/*.sv \
                          $(DUT_ROOT_PATH)/MACRO/*/*.v \
                          $(DUT_ROOT_PATH)/ENV/*.v $(DUT_ROOT_PATH)/ENV/*.sv \
                          $(DUT_ROOT_PATH)/DUMMY_TOP/*.v $(DUT_ROOT_PATH)/DUMMY_TOP/*.sv)

FLAGSIG := $(SIMDIR)/.flags

.PHONY: FORCE
FORCE:

# FLOW is part of the signature. .flags is deliberately not in the flow-change
# cleanup list: make may build it first, and deleting it there loses it.
# The same problem one stage later: vcs generates a C makefile under
# output/csrc and reuses it. Dropping a library from the vcs command line
# therefore does not drop it from the link -- the stale generated makefile
# still names it, ld fails, and elaboration reports 0 errors.
ELABSIG := $(SIMDIR)/.elabflags

# -----------------------------------------------------------------------------
# A signature must contain only what changes the RESULT, never what changes
# how the build was executed.
#
# -j and -fastpartcomp=jN are both derived from NPROC, which is the machine's
# core count -- and under LSF it is lowered to the reservation. So the same
# sources produced two different signatures depending on where the build ran,
# and each move invalidated the other's output.
#
# That is not theoretical. A regression job inherited LSF_COMPILE=0, NPROC went
# from 8 back to 30, the signature changed, and the job answered by deleting
# the generated C and starting its own elaboration -- four of them at once,
# into the directory holding the simv they were meant to run.
#
# Filtered as whole words, so only the flags themselves are dropped.
# -----------------------------------------------------------------------------
sig_of = $(filter-out -j% -fastpartcomp=j%,$(1))

$(ELABSIG): FORCE
	@mkdir -p $(SIMDIR)
	@printf '%s\n' 'FLOW=$(FLOW) $(FLAG_EXTRA) $(call sig_of,$(VCS_FLAGS) $(ONESTEP_FLAGS))' > $@.new
	@cmp -s $@.new $@ 2>/dev/null || { mv $@.new $@; \
	   rm -rf $(OUTDIR)/csrc $(SIMV).daidir; \
	   echo "elaboration flags changed -- generated C removed"; }
	@rm -f $@.new

$(FLAGSIG): FORCE
	@mkdir -p $(SIMDIR)
	@printf '%s\n' 'FLOW=$(FLOW) $(FLAG_EXTRA) $(call sig_of,$(VLOGAN_UVM_FLAGS) $(VLOGAN_FLAGS))' > $@.new
	@cmp -s $@.new $@ 2>/dev/null || { mv $@.new $@; \
	   echo "analysis flags changed -- re-analysing"; }
	@rm -f $@.new

# -----------------------------------------------------------------------------
# Stage 1a: analyse the UVM library
#
# Example :773. Kept separate from 1b because the UVM library rarely changes,
# so a testbench-only edit does not re-analyse it.
# -----------------------------------------------------------------------------
$(SIMDIR)/.uvm.stamp: $(FLAGSIG) $(FLOWTAG) | setup
	@echo "=== [1a] vlogan: UVM library ==="
	cd $(SIMDIR) && vlogan $(call LSF_TOOL_OPT,$(LSF_COMPILE),$(IP_PREFIX_STEM)c.1a) \
	    $(VLOGAN_UVM_FLAGS) -l $(LOGDIR)/analyze_uvm.log
	@$(call LSF_WAIT,$(LSF_COMPILE),$(IP_PREFIX_STEM)c.1a,$(LOGDIR)/analyze_uvm.log)
	@touch $@

analyze_uvm: $(SIMDIR)/.uvm.stamp

# -----------------------------------------------------------------------------
# Stage 1b: analyse design + VIP + TB
# Example :776
# -----------------------------------------------------------------------------
# vlogan sees one file, dv_uvm_all.sv; everything else arrives by `include.
# Depending on the filelist alone means an edit to any source does not
# re-analyse, and the next build silently elaborates the previous version.
# Pattern .txt files count too -- MODEL_ALL.v `include-s the selected one.
TB_SOURCES := $(wildcard $(TBDIR)/*.sv $(TBDIR)/*.svh \
                         $(TBDIR)/*/*.sv $(TBDIR)/*/*.svh \
                         $(TBDIR)/*/*/*.sv $(TBDIR)/*/*/*.svh \
                         $(TBDIR)/patterns/*/*.txt \
                         $(TBDIR)/patterns/*.svh $(TBDIR)/patterns/*/*.svh)

# THE DUT STAGE COMPILES TESTBENCH SOURCE, AND THIS LIST HAS TO SAY SO.
#
# `MODEL_ALL.v:336` does `include "dv_uvm_hook.svh"`, and that header pulls in
# <ip>_stages.svh, <ip>_dev_init.svh, <ip>_reg_defs.svh, <ip>_hier_defs.svh,
# <ip>_trb_defs.svh, <ip>_mem_util.svh, the five *_tasks.svh files, soc_int.svh and
# dv_uvm_pattern_pool.svh -- which in turn includes the selected pattern .txt.
# All of that is analysed HERE, in stage 1b, not in the testbench stage.
#
# This rule used to carry the comment "Deliberately independent of
# TB_SOURCES", and that was wrong in a way nothing could see. Editing
# <ip>_stages.svh changed no prerequisite of any stamp, so vlogan never re-ran
# and the build silently elaborated the previous version. Measured 2026-08-09:
# two consecutive deploys of <ip>_stages.svh -- the CSftRst switch, then its
# removal -- were both discarded, while <ip>_enumeration_seq.sv from the same
# deploy took effect because it belongs to the dv_uvm_all.sv chain in stage
# 1c. The symptom was a run whose [body] line numbers were new and whose
# [stage] behaviour was old, with stage timestamps identical to the nanosecond
# across a rebuild that had changed the CTRL stage.
#
# It had been invisible until now because every earlier build was full: the
# FLOW switch clears all three stamps, and before that the flow was onestep,
# which has no incremental analysis at all. Turning on the incremental flow is
# what exposed it.
#
# HOOK_SOURCES is the include closure of dv_uvm_hook.svh, listed by directory
# rather than by name so a new header does not have to be added here as well.
# If a future include reaches outside these directories, the symptom will be
# this same silent staleness -- check here first.
# patterns/*/*.svh IS common/: soc_int.svh, soc_run.svh and the bodies. Leaving
# it out is the silent staleness this comment describes, not a cosmetic gap.
HOOK_SOURCES := $(wildcard $(TBDIR)/top/*.svh $(TBDIR)/top/*.sv \
                           $(TBDIR)/env/$(IP_PREFIX)hier_defs.svh \
                           $(TBDIR)/env/$(IP_PREFIX)reg_defs.svh \
                           $(TBDIR)/patterns/*.svh \
                           $(TBDIR)/patterns/*/*.svh \
                           $(TBDIR)/patterns/*/*.txt)

# Stage 1b: the DUT. vcs.opt uses relative paths, so vlogan runs in
# DUT_ROOT_PATH; $(IP_PREFIX_STEM).f comes first for the +incdir+/+define+
# MODEL_ALL.v needs.
# Sources that must exist at FILE SCOPE in stage 1b.
#
# dv_uvm_hook.svh is included by MODEL_ALL.v:336, which is INSIDE
# `module sysn063()` (:157). A module body can instantiate but cannot define,
# so the interface and the interconnect module have to be analysed as their
# own files in this stage. There is no include point outside a module anywhere
# in MODEL_ALL.v -- :311, :336, :338, :345, :349 and :352 are all within it.
#
# svt_$(IP_PREFIX_STEM)_if.uvm.svi (real Synopsys VIP file, verify the exact
# name against TARGET_IP's own VIP) is ALSO analysed in stage 1c, from
# dv_uvm_all.sv:83. Defining the same interface in two vlogan units of one
# library is accepted: probed 2026-08-10 with a trivial interface, both
# units rc=0, no "already defined" and no overwrite warning.
#
# NOT added to $(IP_PREFIX_STEM).f. That file carries +incdir+ and +define+
# only, and dv_uvm_files.f owns the testbench source list; a file named in
# both produces duplicate module definitions. These belong to stage 1b
# alone, so they go on the stage 1b command line alone.
IC_SOURCES := $(TBDIR)/top/$(IP_PREFIX)20_serial_ic.sv

$(SIMDIR)/.dut.stamp: $(FILELIST) $(DUT_ROOT_PATH)/$(DUT_OPT) $(DUT_SOURCES) \
                      $(HOOK_SOURCES) $(IC_SOURCES) \
                      $(FLAGSIG) $(FLOWTAG) $(SIMDIR)/.uvm.stamp
	@echo "=== [1b] vlogan: DUT (NPROC=$(NPROC)) ==="
	cd $(DUT_ROOT_PATH) && vlogan $(call LSF_TOOL_OPT,$(LSF_COMPILE),$(IP_PREFIX_STEM)c.1b) \
	    $(VLOGAN_FLAGS) \
	    -f $(FILELIST) \
	    $(IC_SOURCES) \
	    -f $(DUT_ROOT_PATH)/$(DUT_OPT) \
	    -l $(LOGDIR)/analyze_dut.log
	@$(call LSF_WAIT,$(LSF_COMPILE),$(IP_PREFIX_STEM)c.1b,$(LOGDIR)/analyze_dut.log)
	@touch $@

analyze_dut: $(SIMDIR)/.dut.stamp

# Stage 1c: the testbench. dv_uvm_files.f is named here rather than from a hook
# inside vcs.opt, so the read-only DUT tree needs no edit. Runs from SIMDIR so
# nothing is written into that tree. $(IP_PREFIX_STEM).f is passed again for
# its defines.
$(SIMDIR)/.analyze.stamp: $(FILELIST) $(FILELISTDIR)/dv_uvm_files.f \
                          $(TB_SOURCES) $(FLAGSIG) $(SIMDIR)/.dut.stamp
	@echo "=== [1c] vlogan: testbench ==="
	cd $(SIMDIR) && vlogan $(call LSF_TOOL_OPT,$(LSF_COMPILE),$(IP_PREFIX_STEM)c.1c) \
	    $(VLOGAN_FLAGS) \
	    -f $(FILELIST) \
	    -f $(FILELISTDIR)/dv_uvm_files.f \
	    -l $(LOGDIR)/analyze_tb.log
	@$(call LSF_WAIT,$(LSF_COMPILE),$(IP_PREFIX_STEM)c.1c,$(LOGDIR)/analyze_tb.log)
	@touch $@

analyze_tb: $(SIMDIR)/.analyze.stamp

analyze: $(SIMDIR)/.analyze.stamp

# -----------------------------------------------------------------------------
# Stage 2: elaborate
# Example :779
# -----------------------------------------------------------------------------
ifeq ($(FLOW),fourstep)

# THE PRODUCTS ARE REMOVED BEFORE ELABORATING, AND NOT AS TIDINESS.
# vcselab reuses output/partitionlib and output/simv.daidir. Partition compile
# forces a global rebuild when the COMMAND LINE changes -- it does not notice
# that stage 1b re-analysed the DUT into a different library with the same
# flags, which is what editing HOOK_SOURCES does (MODEL_ALL.v:336). The old
# partition then fails to stitch onto the new modules:
#   Assertion failed "cflatNodesRead == cflatNodes" at hsflatmastersort.cc:287
# after 0.567 s of CPU, reported by LSF as nothing but "exit code 255".
#
# The recipe only runs when a stamp or flag already moved -- when the partition
# had to be rebuilt anyway -- so the incremental benefit given up is one that
# could not have been claimed correctly. Cost: ~900 s rather than ~560 s.
# The analysis stamps are left alone, so 1a/1b/1c are not re-run.
$(SIMV): $(SIMDIR)/.analyze.stamp $(ELABSIG)
	@echo "=== [2] vcs elaborate (partition compile, NPROC=$(NPROC)) ==="
	rm -rf $(OUTDIR)/csrc $(OUTDIR)/simv.daidir $(OUTDIR)/partitionlib $(SIMV)
	cd $(SIMDIR) && vcs $(call LSF_TOOL_OPT,$(LSF_COMPILE),$(IP_PREFIX_STEM)c.elab) \
	    $(VCS_FLAGS) $(TOPMOD) $(EXTRA_TOPS) -o $(SIMV) -l $(LOGDIR)/compile.log
	@$(call LSF_WAIT,$(LSF_COMPILE),$(IP_PREFIX_STEM)c.elab,$(SIMV))
	@# Match how the tools actually report, not the word "error" anywhere.
	@# `grep -i error` counted +error+10000 from our own flags and 155 lines of
	@# "This warning will be upgraded to error in future releases", and printed
	@# "errors : 156" on a build that produced a working simv.
	@# Elaboration, the generated C build and the link each fail differently,
	@# so all three forms are matched.
	@grep -E "^Warning-" $(LOGDIR)/compile.log > $(LOGDIR)/compile_w.log || true
	@grep -E "^Error-|Assertion failed|collect2: error|ld returned [0-9]+ exit" 	      $(LOGDIR)/compile.log > $(LOGDIR)/compile_e.log || true
	@echo "warnings: $$(wc -l < $(LOGDIR)/compile_w.log)"
	@echo "errors  : $$(wc -l < $(LOGDIR)/compile_e.log)"

else

# FLOW=onestep: one vcs call, no vlogan and no library.
# UVM comes from source, not -ntb_opts uvm; passing both links two UVM
# libraries. -top is required -- a one-step vcs reads a bare module name as a
# filename.
ONESTEP_UVM := -CFLAGS -DVCS +incdir+$(UVM_HOME)/src $(UVM_HOME)/src/dpi/uvm_dpi.cc

ONESTEP_FLAGS := $(VCS_BITMODE) -sverilog $(KDB) -lca \
                 -timescale=$(TIMESCALE) \
                 $(ONESTEP_UVM) $(NTB_COMMON) \
                 $(SIM_BUILD_OPTS) $(SOC_DEFINES) $(DEFINES) \
                 $(PA_DEFINES) $(WAVE_DEFINES) \
                 $(VIP_INCDIRS) $(TB_INCDIRS) \
                 $(DEBUG_ACCESS) $(PA_OPTIONS) $(WAVE_OPTIONS) \
                 $(COV_ELAB) $(FCOV_ELAB) \
                 +error+10000 \
                 -Mdir=$(OUTDIR)/csrc \
                 -j$(NPROC)

# IC_SOURCES BELONGS HERE TOO, AND LEAVING IT OFF WAS SILENT.
# <ip>_20_serial_ic.sv defines <ip>_20_serial_ic_wrapper, which
# dv_uvm_hook.svh instantiates inside sysn063. The four-step flow lists it
# in stage 1b; this rule did not, so a one-step build had the instantiation
# and not the module:
#   Error-[CFCILFBI] Cell 'usb_20_serial_ic_wrapper' cannot be found in
#   liblist for binding instance 'sysn063.u0_ic'
# Hidden until now because the instantiation sat behind `ifdef
# $(TARGET_IP)_UVM_CONNECT with CONNECT defaulting to 0 -- the module was
# never asked for, so its absence could not be noticed.
$(SIMV): $(FILELIST) $(FILELISTDIR)/dv_uvm_files.f $(DUT_ROOT_PATH)/$(DUT_OPT) \
         $(DUT_SOURCES) $(TB_SOURCES) $(IC_SOURCES) \
         $(FLAGSIG) $(ELABSIG) $(FLOWTAG) | setup
	@echo "=== one-step vcs (FLOW=onestep, NPROC=$(NPROC)) ==="
	@# vcs.opt uses paths relative to DUT_ROOT_PATH, so vcs runs there.
	cd $(DUT_ROOT_PATH) && vcs $(call LSF_TOOL_OPT,$(LSF_COMPILE),$(IP_PREFIX_STEM)c.onestep) \
	    $(ONESTEP_FLAGS) \
	    -f $(FILELIST) \
	    $(IC_SOURCES) \
	    -f $(DUT_ROOT_PATH)/$(DUT_OPT) \
	    -f $(FILELISTDIR)/dv_uvm_files.f \
	    -top $(TOPMOD) $(addprefix -top ,$(EXTRA_TOPS)) \
	    -o $(SIMV) -l $(LOGDIR)/compile.log
	@$(call LSF_WAIT,$(LSF_COMPILE),$(IP_PREFIX_STEM)c.onestep,$(SIMV))
	@# Match how the tools actually report, not the word "error" anywhere.
	@# `grep -i error` counted +error+10000 from our own flags and 155 lines of
	@# "This warning will be upgraded to error in future releases", and printed
	@# "errors : 156" on a build that produced a working simv.
	@# Elaboration, the generated C build and the link each fail differently,
	@# so all three forms are matched.
	@grep -E "^Warning-" $(LOGDIR)/compile.log > $(LOGDIR)/compile_w.log || true
	@grep -E "^Error-|Assertion failed|collect2: error|ld returned [0-9]+ exit" 	      $(LOGDIR)/compile.log > $(LOGDIR)/compile_e.log || true
	@echo "warnings: $$(wc -l < $(LOGDIR)/compile_w.log)"
	@echo "errors  : $$(wc -l < $(LOGDIR)/compile_e.log)"

endif

elab: $(SIMV)
compile: elab


# -----------------------------------------------------------------------------
# Stage 3: run
# Example :783
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# One pattern at one seed.
#
# The run happens in its OWN directory, $(PAT_RUN), and that is what makes
# several of them safe to run at once. simv itself is shared -- it is opened
# read-only, so one elaboration serves every job -- but a running simv writes
# a set of files into whatever directory it was started from, and those files
# are named after the UVM component that produced them, not after the pattern:
#
#     env.apb_env.master.apb_svt.xml
#     env.apb_env.master.monitor.transaction_trace
#     env.axi_env.system_monitor.axi_system_transaction_summary_report
#     ucli.key, novas_dump.log
#
# Two patterns started from the same directory therefore write the same
# filenames. Sequentially that means only the last pattern's traffic reports
# survive; in parallel they interleave inside one file. Neither reports an
# error. Giving each job its own directory fixes both at once, and it covers
# artifacts nobody has enumerated yet -- which a per-file rename would not.
#
# Absolute paths are used for -l, +fsdb_file and -cm_dir so the cwd change
# does not move them. SYNOPSYS_SIM_SETUP is already exported as a full path.
#
# The reports are then moved out of the scratch directory into
# $(PAT_REPORT), leaving the run directory holding only simulator debris.
# -----------------------------------------------------------------------------
# sim builds if it has to, then runs. The two are separate targets because a
# regression job must never be able to build: `run` has no $(SIMV) prerequisite,
# so a job whose variables differ slightly from the build's cannot decide to
# re-elaborate. With jobs spread over the farm that would be N simultaneous
# elaborations into one output directory.
#
# The recursive call rather than `sim: $(SIMV) run` is deliberate: prerequisites
# of one target have no ordering between them under -j, so `run` could start
# before the elaboration finished.
sim: $(SIMV)
	@$(MAKE) --no-print-directory run

run: dirs
	@if [ ! -x $(SIMV) ]; then \
	  echo "No simv at $(SIMV)."; \
	  echo "The run target never builds one -- that is its purpose. Build it:"; \
	  echo "    make compile"; \
	  exit 1; \
	fi
	@echo "=== running pattern $(PATTERN) (seed=$(SEED)) ==="
	@echo "    run    $(PAT_RUN)"
	@echo "    log    $(PAT_LOG)"
	@echo "    report $(PAT_REPORT)"
	@if [ "$(WAVE)" != "0" ]; then echo "    fsdb   $(PAT_FSDB)"; fi
	@if [ "$(COV)" = "1" ]; then echo "    cov    $(PAT_COV)"; fi
	@# BOTH directories, not just the run one. report/<job>/ is a view built
	@# from symlinks into run/<job>/, so wiping only the run directory leaves
	@# every link in the report pointing at something that no longer exists --
	@# a broken link looks like a file until you open it, which is worse than
	@# an obviously stale one. Physical copies used to hide this; links do not.
	@#
	@# Safe here because this runs before simv starts, so sim.log -- which is
	@# written into the report directory directly -- does not exist yet.
	@#
	@# One consequence worth knowing: report/<job>/ always shows the LATEST
	@# run of that pattern and seed. Earlier runs are not archived. Use a
	@# different SEED to keep two side by side.
	@rm -rf $(PAT_RUN) $(PAT_REPORT) && mkdir -p $(PAT_RUN) $(PAT_REPORT)
	@# BOTH links are made before the run, not after, so a job that dies early
	@# still leaves a reachable transcript at the two places anything looks for
	@# it. collect_reports would make the report one, but collect_reports only
	@# runs on a clean exit -- and seven runs were hard-killed on 2026-08-09,
	@# every one of them a run whose log someone then wanted.
	@#
	@# A symlink created before its target exists is dangling, not broken: as
	@# soon as simv opens the file with -l it resolves. That is fine here and
	@# is the price of having the link exist for a run that never finishes.
	@ln -sfn $(PAT_LOG) $(PAT_LOG_LINK)          2>/dev/null || true
	@ln -sfn $(PAT_LOG) $(PAT_REPORT)/sim.log    2>/dev/null || true
	cd $(PAT_RUN) && $(SLED_ENV) \
	    $(call LSFW,$(LSF_SIM),$(IP_PREFIX_STEM)run.$(PATTERN),$(LSF_TIMEOUT),$(PAT_RUN)/lsf.out) \
	    $(SIMV) $(RUN_FLAGS) -l $(PAT_LOG)
	@$(MAKE) --no-print-directory collect_reports
	@$(MAKE) --no-print-directory job_summary
	@$(MAKE) --no-print-directory record_result
	@echo "--- result ---"
	@grep "SvtTestEpilog" $(PAT_LOG) \
	    || echo "SvtTestEpilog not found; the run may have aborted"

# -----------------------------------------------------------------------------
# One job's summary, written into that job's own report directory.
#
# Per job rather than one shared file, because under `make regress JOBS=8`
# eight of these finish at unpredictable moments and a single shared file
# would interleave. The aggregate lives in $(JOB_SUMMARY) and is written once,
# at the end, by regress_summary.
#
# IN_REGRESS is what tells the two apart. A single `make sim` also refreshes
# the top-level file, because for a single run that IS the whole result and
# looking in a per-pattern directory for it would be silly.
# -----------------------------------------------------------------------------
IN_REGRESS ?= 0

# -----------------------------------------------------------------------------
# RECORD=1: this pattern's result updates regression.list.
#
#   PASS -> present in the list
#   FAIL -> absent from the list
#
# Idempotent, so re-running a passing pattern does not duplicate the line, and
# re-running a failing one that was never listed is not an error.
#
# NOT DONE FROM INSIDE A REGRESSION JOB. Under `make regress JOBS=8` eight of
# these finish at unpredictable moments, and read-modify-write on one file from
# eight machines loses entries silently -- the file would end up holding
# whichever job wrote last rather than the union of the results. A regression
# updates the list once, afterwards, from the collected verdicts.
#
# The write is via a temp file and mv, so an interrupted update cannot leave a
# half-written list behind. mv within a directory is atomic.
# -----------------------------------------------------------------------------
record_result:
ifeq ($(RECORD),1)
	@if [ "$(IN_REGRESS)" = "1" ]; then \
	   :; \
	 elif [ ! -f $(PAT_LOG) ]; then \
	   echo "    RECORD: no log, list unchanged"; \
	 else \
	   t=$$(mktemp $(REGRESSION_LIST).XXXXXX 2>/dev/null || echo $(REGRESSION_LIST).tmp); \
	   touch $(REGRESSION_LIST); \
	   grep -vxF '$(PATTERN)' $(REGRESSION_LIST) > $$t 2>/dev/null || true; \
	   if grep -q "VERDICT: PASSED" $(PAT_LOG) 2>/dev/null; then \
	     echo '$(PATTERN)' >> $$t; \
	     mv $$t $(REGRESSION_LIST); \
	     echo "    RECORD: $(PATTERN) PASSED, kept in $(REGRESSION_LIST)"; \
	   else \
	     mv $$t $(REGRESSION_LIST); \
	     echo "    RECORD: $(PATTERN) FAILED, removed from $(REGRESSION_LIST)"; \
	   fi; \
	 fi
else
	@:
endif

# Update the list from a whole suite's verdicts, once, after everything has
# finished. This is what a regression uses instead of record_result.
record_suite:
	@touch $(REGRESSION_LIST)
	@t=$$(mktemp $(REGRESSION_LIST).XXXXXX 2>/dev/null || echo $(REGRESSION_LIST).tmp); \
	 cp $(REGRESSION_LIST) $$t; \
	 add=0; del=0; \
	 for p in $(PATTERNS); do \
	   l=$(LOGDIR)/$${p}_$(SEED).log; \
	   grep -vxF "$$p" $$t > $$t.2 2>/dev/null || true; mv $$t.2 $$t; \
	   if [ -f $$l ] && grep -q "VERDICT: PASSED" $$l 2>/dev/null; then \
	     echo "$$p" >> $$t; add=$$((add+1)); \
	   else \
	     del=$$((del+1)); \
	   fi; \
	 done; \
	 sort -u $$t -o $$t; \
	 mv $$t $(REGRESSION_LIST); \
	 echo "  RECORD: $(REGRESSION_LIST) now lists $$(grep -cve '^[[:space:]]*$$' -e '^\#' $(REGRESSION_LIST)) pattern(s)"; \
	 echo "          $$add passing kept, $$del failing or missing removed"

job_summary:
	@mkdir -p $(PAT_REPORT)
	@{ echo "pattern   $(PATTERN)"; \
	   echo "seed      $(SEED)"; \
	   echo "date      $$(date '+%Y-%m-%d %H:%M:%S')"; \
	   echo "host      $$(hostname)"; \
	   echo "speed     $(SPEED0)/$(SPEED1)   ports $(PORTS)"; \
	   echo "log       $(PAT_LOG)"; \
	   echo "run dir   $(PAT_RUN)"; \
	   if [ -f $(PAT_LOG) ]; then \
	     if grep -q "VERDICT: PASSED" $(PAT_LOG) 2>/dev/null; then \
	       echo "verdict   PASSED"; else echo "verdict   FAILED"; fi; \
	     echo "uvm       $$(grep -c 'UVM_ERROR' $(PAT_LOG) 2>/dev/null) error line(s)"; \
	     grep "SvtTestEpilog" $(PAT_LOG) 2>/dev/null | head -2; \
	   else \
	     echo "verdict   NO LOG"; \
	   fi; \
	   echo "reports:"; \
	   ls -1 $(PAT_REPORT) 2>/dev/null | grep -v job_summary | sed 's/^/  /'; \
	 } > $(PAT_REPORT)/job_summary.txt
	@if [ "$(IN_REGRESS)" != "1" ]; then \
	   mkdir -p $(LOGDIR); cp $(PAT_REPORT)/job_summary.txt $(JOB_SUMMARY); \
	   echo "    summary $(JOB_SUMMARY)"; \
	 else \
	   echo "    summary $(PAT_REPORT)/job_summary.txt"; \
	 fi

# -----------------------------------------------------------------------------
# Move this job's VIP output out of its run directory into report/<job>/.
#
# Run as a separate target rather than inline so a run that dies still has its
# reports collected by hand:  make collect_reports PATTERN=x SEED=y
#
# The trailing `|| true` on the find is deliberate. A pattern that generates no
# AXI traffic produces no AXI report, and an empty result is not a failure.
# -----------------------------------------------------------------------------
collect_reports:
	@mkdir -p $(PAT_REPORT)
	@# LINKED, NOT MOVED. report/<job>/ is a view of the run assembled from
	@# symlinks -- that is what the rundir, wave.fsdb and coverage.vdb links
	@# below already do, and the VIP files were the one thing being physically
	@# relocated. Moving them meant the run directory no longer held the run's
	@# own output, and a reader following rundir found it half emptied.
	@#
	@# Linking also survives a kill better: the files stay where the simulator
	@# put them whatever happens, and this step only adds the pointers.
	@#
	@# uvm.log is named explicitly because it is not one of the VIP patterns
	@# and it is the file most worth finding next to sim.log.
	@if [ -d $(PAT_RUN) ]; then \
	  find $(PAT_RUN) -maxdepth 1 -type f \
	       \( -name '*.xml' -o -name '*transaction_trace' \
	          -o -name '*_report' -o -name '*xfer_trace' \
	          -o -name 'uvm.log' -o -name 'sim.log' -o -name '*.txt' \) \
	       -exec ln -sfn {} $(PAT_REPORT)/ \; 2>/dev/null || true; \
	  n=$$(ls -1 $(PAT_REPORT) 2>/dev/null | wc -l); \
	  echo "    linked $$n report file(s) into $(PAT_REPORT)"; \
	fi
	@# One directory per pattern that holds everything about that run.
	@#
	@# Links rather than copies. The transcript stays in log/ because that is
	@# what regress_summary greps across the whole suite, and a waveform is
	@# large enough that a second copy is a real cost -- but neither should be
	@# somewhere you have to already know about to find.
	@#
	@# What stays behind in run/<job>/ is what simv drops on its own:
	@# ucli.key, novas_dump.log and anything a VIP writes unprompted. It is
	@# linked as `rundir` rather than emptied, because "the simulator produced
	@# a file nobody enumerated" is exactly the case worth being able to look at.
	@ln -sfn $(PAT_RUN) $(PAT_REPORT)/rundir  2>/dev/null || true
	@if [ -f $(PAT_FSDB) ]; then \
	   ln -sfn $(PAT_FSDB) $(PAT_REPORT)/wave.fsdb 2>/dev/null || true; fi
	@if [ -d $(PAT_COV) ]; then \
	   ln -sfn $(PAT_COV) $(PAT_REPORT)/coverage.vdb 2>/dev/null || true; fi

debug:
	@$(MAKE) sim PATTERN=$(PATTERN) SEED=$(SEED) WAVE=1
	@$(MAKE) verdi PATTERN=$(PATTERN)

# -----------------------------------------------------------------------------
# Verdi signal setup. WAVES_SETUP points at a real Tcl script, loaded with
# -play (aka -script): "Source a TCL script; stop on first error" (verdi -h).
#
# FIXED 2026-08-25: this used to say `-sswr $(WAVES_SETUP)`. -sswr's own
# documented meaning is "Load waveform restore file(s) (*.rc)" -- a
# DIFFERENT, non-Tcl internal restore grammar. Verdi opened with -sswr on a
# real Tcl file (proc/set/foreach/wvCreateGroup/wvSetMarker, exactly what
# waves.tcl and every debug .tcl in this tree contain) parses every line
# through that grammar instead and reports "Unrecognized keyword" on every
# single statement -- confirmed live in a screenshot, not inferred. This means
# `make verdi`/`make debug` had never actually loaded a signal group through
# this path; missing it silently degraded to "Verdi opens with no signals
# preloaded" exactly as the old comment above described, which is why it went
# unnoticed. Never revert this to -sswr for a script that uses any Tcl control
# flow or the wv* group/marker API.
# -----------------------------------------------------------------------------
WAVES_SETUP ?= $(MK_DIR)/waves.tcl
ifneq ($(strip $(WAVES_SETUP)),)
  ifneq ($(wildcard $(WAVES_SETUP)),)
    WAVES_TCL := -play $(WAVES_SETUP)
  else
    WAVES_TCL :=
  endif
else
  WAVES_TCL :=
endif

# Report a missing setup file only when a viewer is actually being opened.
# A $(warning) here is evaluated on every invocation, so `make list_patterns`
# and `make help` were emitting a Verdi warning they have nothing to do with.
ifneq ($(filter verdi debug,$(MAKECMDGOALS)),)
  ifeq ($(strip $(WAVES_TCL)),)
    ifneq ($(strip $(WAVES_SETUP)),)
      $(warning waves.tcl not found at '$(WAVES_SETUP)'; Verdi will open with no signals preloaded. \
                Set WAVES_SETUP=<file>, or WAVES_SETUP= to silence this.)
    endif
  endif
endif

verdi:
	@if [ ! -f $(PAT_FSDB) ]; then \
	  echo "No FSDB for pattern $(PATTERN) at $(PAT_FSDB)"; \
	  echo "Run it with a waveform first:"; \
	  echo "    make sim PATTERN=$(PATTERN) WAVE=1"; \
	  exit 1; \
	fi
	@# Verdi at this site REFUSES to start without an LSF option:
	@#     Error! Verdi only can be lauch by LSF.
	@#     Please use LSF options by append -lsfon or -lsfint
	@# so LSF_VERDI is a choice of mode, not of whether. int is the default
	@# because Verdi is a GUI: -lsfint keeps the terminal and the X connection,
	@# and -lsfon would put a window on a batch slot where nothing can see it.
	@#
	@# -dbdir points at simv.daidir, so Verdi reads the KDB that -kdb produced
	@# during elaboration rather than re-parsing the sources.
	verdi $(call LSF_TOOL_OPT,$(LSF_VERDI),$(IP_PREFIX_STEM)verdi.$(PATTERN),$(LSF_VERDI_QUEUE)) \
	      -dbdir $(SIMV).daidir -ssf $(PAT_FSDB) $(WAVES_TCL) -nologo

# -----------------------------------------------------------------------------
# Regression runs every pattern in a suite against one elaboration.
# The suite is a directory under tb/patterns, not a list of uvm_tests:
# test variation comes from the pattern pool, selected at run time.
# -----------------------------------------------------------------------------
SUITE ?= all
override SUITE := $(strip $(SUITE))

# -----------------------------------------------------------------------------
# UVM_ROOT_PATH must be the tree that CONTAINS tb/, not tb/ itself.
#
# Pointing it one level too deep is easy and, without this check, silent:
# TBDIR becomes <...>/tb/tb, every glob below returns nothing, and
# `make list_patterns` reports basic(0) sanity(0) <protocol>(0) as though the
# suites were simply empty. Detect it by looking for patterns/ one level up.
# -----------------------------------------------------------------------------
ifeq ($(wildcard $(TBDIR)/patterns),)
  ifneq ($(wildcard $(UVM_ROOT_PATH)/patterns),)
    $(error UVM_ROOT_PATH='$(UVM_ROOT_PATH)' is one level too deep. It must be             the directory CONTAINING tb/, so drop the trailing /tb:             UVM_ROOT_PATH=$(patsubst %/tb,%,$(UVM_ROOT_PATH)))
  endif
endif

# -----------------------------------------------------------------------------
# Pattern registration.
#
# tb/patterns/pattern_list.txt is the registry, and dv_uvm_pattern_pool.svh is
# GENERATED from it. Registering used to mean two hand edits inside a 400 line
# file -- a task wrapper in the right section and a case arm in the right
# place, which have to agree, and where the wrapper has to match the pattern's
# style or the build fails pointing at the include rather than the mistake.
#
# The list rather than a glob of the directory, for two reasons:
#   - un-registering stays non-destructive; the .txt is left where it is
#   - every registered pattern is compiled in, and a syntax error in any one
#     of them breaks the whole build, so there has to be somewhere to park a
#     pattern that is not finished
#
# Style is DETECTED, not declared: a .txt containing `task automatic pat_`
# brings its own task and is included at file scope, otherwise it is a bare
# body and gets a wrapper. Checked against the tree as it stood, that rule
# reproduces all 39 existing registrations exactly.
# -----------------------------------------------------------------------------
PATTERN_LIST := $(TBDIR)/patterns/pattern_list.txt
PATTERN_POOL := $(TBDIR)/patterns/dv_uvm_pattern_pool.svh
GEN_POOL     := $(firstword $(wildcard $(MK_DIR)/gen_pattern_pool.py \
                                       $(MK_DIR)/scripts/gen_pattern_pool.py \
                                       $(SIM_SCRIPTS)/gen_pattern_pool.py))

# Regenerated whenever the list changes. The generator rewrites the file only
# when its content differs, so an unchanged list does not move the timestamp
# and re-elaborate the design for nothing.
$(PATTERN_POOL): $(PATTERN_LIST) $(GEN_POOL)
	@python $(GEN_POOL) $(PATTERN_LIST) $(TBDIR)/patterns $(PATTERN_POOL)

pattern_pool: $(PATTERN_POOL)

# -----------------------------------------------------------------------------
# Register / un-register a pattern.
#
#   make ADD_PAT PAT_NAME=yyy.txt PAT_DIR=../uvm/tb/patterns/xxx
#   make RM_PAT  PAT_NAME=yyy.txt PAT_DIR=../uvm/tb/patterns/xxx
#
# PAT_DIR is accepted either as a path (as above) or as a bare suite name
# (e.g. PAT_DIR=$(IP_PREFIX_STEM)). Only the last component matters, because the registry stores
# the directory relative to tb/patterns/ -- accepting the full path just means
# a user can paste what they see in their shell.
#
# Both verify the file exists FIRST. Registering a name whose file is absent
# would produce a build that fails in the generator, and un-registering a name
# that was never there would silently do nothing and look like success.
# -----------------------------------------------------------------------------
PAT_NAME ?=
PAT_DIR  ?= .
# Strip any leading path and the .txt, so all four spellings work:
#   yyy.txt / yyy / patterns/xxx/yyy.txt / ../uvm/tb/patterns/xxx
pat_base = $(basename $(notdir $(strip $(PAT_NAME))))
pat_sub  = $(notdir $(patsubst %/,%,$(strip $(PAT_DIR))))
# The registry stores the directory; the suite is what `make regress SUITE=`
# takes. They are the same word except at the top level, where the directory
# is "." and the suite is "basic" -- so printing the directory there tells the
# user to run `make regress SUITE=.`, which is not a suite.
pat_suite = $(if $(filter .,$(pat_sub)),basic,$(pat_sub))
pat_file = $(TBDIR)/patterns/$(if $(filter .,$(pat_sub)),,$(pat_sub)/)$(pat_base).txt

# Both are TRANSACTIONAL. The registry is edited, the pool is regenerated, and
# if that fails the registry is put back exactly as it was. Without the
# rollback a rejected registration -- a task name colliding with another
# pattern's, say -- would leave a list that no longer generates, and the next
# person to run make would meet a broken build they did not cause.
ADD_PAT:
	@if [ -z "$(pat_base)" ]; then \
	   echo "FAILED: no pattern named."; \
	   echo "  usage: make ADD_PAT PAT_NAME=<name>.txt PAT_DIR=<dir>"; \
	   exit 1; fi
	@if [ ! -f "$(pat_file)" ]; then \
	   echo "FAILED: $(pat_base) was not registered."; \
	   echo "  reason : no such file"; \
	   echo "  looked : $(pat_file)"; \
	   echo "  from   : PAT_NAME=$(PAT_NAME)  PAT_DIR=$(PAT_DIR)"; \
	   echo "  Put the command.txt there first, then register it."; \
	   exit 1; fi
	@touch $(PATTERN_LIST)
	@if awk '/^[[:space:]]*(\#|$$)/{next} $$1=="$(pat_base)"{f=1} END{exit !f}' \
	     $(PATTERN_LIST); then \
	   echo "OK: $(pat_base) was already registered, nothing to change."; \
	   exit 0; \
	 fi; \
	 cp $(PATTERN_LIST) $(PATTERN_LIST).bak; \
	 printf '%-20s %-8s %s\n' '$(pat_base)' '$(pat_sub)' '' >> $(PATTERN_LIST); \
	 if $(MAKE) --no-print-directory $(PATTERN_POOL); then \
	   rm -f $(PATTERN_LIST).bak; \
	   echo ""; \
	   echo "OK: $(pat_base) registered."; \
	   echo "  file     $(pat_file)"; \
	   echo "  suite    $(pat_suite)   (make regress SUITE=$(pat_suite))"; \
	   echo "  registry $(PATTERN_LIST), now $$(awk '/^[[:space:]]*(\#|$$)/{next}{n++}END{print n+0}' $(PATTERN_LIST)) pattern(s)"; \
	   echo "  run it   make sim PATTERN=$(pat_base)"; \
	   echo "  The next build re-elaborates: the pattern pool changed."; \
	 else \
	   mv $(PATTERN_LIST).bak $(PATTERN_LIST); \
	   $(MAKE) --no-print-directory $(PATTERN_POOL) >/dev/null 2>&1 || true; \
	   echo ""; \
	   echo "FAILED: $(pat_base) was NOT registered."; \
	   echo "  reason : the pattern pool would not generate -- see above."; \
	   echo "  $(PATTERN_LIST) has been put back as it was."; \
	   exit 1; \
	 fi

RM_PAT:
	@if [ -z "$(pat_base)" ]; then \
	   echo "FAILED: no pattern named."; \
	   echo "  usage: make RM_PAT PAT_NAME=<name>.txt PAT_DIR=<dir>"; \
	   exit 1; fi
	@if [ ! -f "$(pat_file)" ]; then \
	   echo "FAILED: nothing was changed."; \
	   echo "  reason : no such file"; \
	   echo "  looked : $(pat_file)"; \
	   echo "  from   : PAT_NAME=$(PAT_NAME)  PAT_DIR=$(PAT_DIR)"; \
	   echo "  Un-registering a name whose file is absent would hide a typo:"; \
	   echo "  it would report success having done nothing."; \
	   exit 1; fi
	@touch $(PATTERN_LIST)
	@if ! awk '/^[[:space:]]*(\#|$$)/{next} $$1=="$(pat_base)"{f=1} END{exit !f}' \
	       $(PATTERN_LIST); then \
	   echo "OK: $(pat_base) was not registered, nothing to change."; \
	   exit 0; \
	 fi; \
	 cp $(PATTERN_LIST) $(PATTERN_LIST).bak; \
	 t=$$(mktemp $(PATTERN_LIST).XXXXXX); \
	 awk '/^[[:space:]]*(\#|$$)/{print; next} $$1!="$(pat_base)"{print}' \
	     $(PATTERN_LIST) > $$t && mv $$t $(PATTERN_LIST); \
	 if $(MAKE) --no-print-directory $(PATTERN_POOL); then \
	   rm -f $(PATTERN_LIST).bak; \
	   rl=""; \
	   if [ -f $(REGRESSION_LIST) ] && grep -qxF '$(pat_base)' $(REGRESSION_LIST); then \
	     u=$$(mktemp $(REGRESSION_LIST).XXXXXX); \
	     grep -vxF '$(pat_base)' $(REGRESSION_LIST) > $$u; mv $$u $(REGRESSION_LIST); \
	     rl="yes"; \
	   fi; \
	   echo ""; \
	   echo "OK: $(pat_base) un-registered."; \
	   echo "  registry $(PATTERN_LIST), now $$(awk '/^[[:space:]]*(\#|$$)/{next}{n++}END{print n+0}' $(PATTERN_LIST)) pattern(s)"; \
	   if [ -n "$$rl" ]; then \
	     echo "  also removed from $(REGRESSION_LIST) -- a pattern that is no"; \
	     echo "           longer built cannot pass, and SUITE=list would have"; \
	     echo "           failed on a name that does not exist any more"; \
	   else \
	     echo "  $(REGRESSION_LIST) did not list it, so it is unchanged"; \
	   fi; \
	   echo "  kept     $(pat_file)   (un-registering is not a delete)"; \
	   echo "  The next build re-elaborates: the pattern pool changed."; \
	 else \
	   mv $(PATTERN_LIST).bak $(PATTERN_LIST); \
	   $(MAKE) --no-print-directory $(PATTERN_POOL) >/dev/null 2>&1 || true; \
	   echo ""; \
	   echo "FAILED: $(pat_base) was NOT un-registered."; \
	   echo "  reason : the pattern pool would not generate -- see above."; \
	   echo "  $(PATTERN_LIST) has been put back as it was."; \
	   exit 1; \
	 fi

# Suite membership comes from the REGISTRY, not from globbing the directory.
# A .txt that is present but unregistered is deliberately not compiled in, so
# listing it in a suite would produce a run that fails with "no pattern named"
# -- the parking mechanism has to be invisible to the suites, not half honoured.
#
# The directory column doubles as the suite name; "." is the top level.
pat_in_dir = $(shell awk '/^[[:space:]]*(\#|$$)/{next} $$2=="$(1)"{print $$1}' \
                     $(PATTERN_LIST) 2>/dev/null)

# SUITE_NAMES IS COMPUTED FROM THE REGISTRY, NOT HARDCODED. MEASURED
# 2026-08-22: this template's original project had a previous
# PATTERNS_BASIC/SANITY/<PROTOCOL> trio (below, now removed) where
# PATTERNS_BASIC filtered on dir=="." while every basic/ pattern's own
# registry line actually says "basic" -- so SUITE=basic ran ZERO patterns,
# silently, and nobody had noticed. The same three-name assumption would
# have broken outright the moment that project's directory taxonomy
# migration (basic/sanity/<protocol> -> infra/enumeration/speed/link/power/
# performance/transfer/uvc/rate_switch/user_define) landed. Deriving the
# valid suite names from whatever directories pattern_list.txt actually uses
# fixes both: the stale "basic" filter and any future category rename, with
# no matching Makefile edit ever required again.
SUITE_NAMES := $(sort $(shell awk '/^[[:space:]]*(\#|$$)/{next} {print $$2}' \
                     $(PATTERN_LIST) 2>/dev/null))
PATTERNS_ALL := $(shell awk '/^[[:space:]]*(\#|$$)/{next} {print $$1}' \
                     $(PATTERN_LIST) 2>/dev/null)

# -----------------------------------------------------------------------------
# regression.list -- the patterns known to pass.
#
# A plain text file, one pattern per line, # for comments. It lives in
# UVM_ROOT_PATH rather than under sim/, because sim/ is build product and
# `make distclean` removes it -- a list that took a week of runs to build up
# must not be deleted by a clean.
#
# Two ways to maintain it, and they are meant to be used together:
#
#   by hand      it is a text file; edit it
#   by RECORD=1  a run that PASSES adds its pattern, a run that FAILS removes
#                it. So the list tracks what actually works rather than what
#                worked once.
#
# The removal half is the point. A list that only ever grows becomes a list of
# things that passed at some time in the past, and a regression built from it
# fails every night for a reason nobody entered deliberately. Removing on
# failure keeps `SUITE=list` meaning "this should be green".
#
# RECORD is off by default: a run made while debugging is not a statement
# about whether the pattern works.
# -----------------------------------------------------------------------------
REGRESSION_LIST ?= $(UVM_ROOT_PATH)/regression.list
RECORD ?= 0
override RECORD := $(strip $(RECORD))

# Strip comments and blanks. $(file) would be neater but needs make 4.2.
# The \# is required. An unescaped # ends the line as far as make is
# concerned, so the $(shell ...) call loses its closing paren and the whole
# Makefile fails to parse with
#   *** unterminated call to function `shell': missing `)'
# which names neither the sed nor the #. Three awk programs in this file were
# fixed for exactly this and this one was missed, because it is a sed.
PATTERNS_LIST = $(shell sed -e 's/\#.*//' -e '/^[[:space:]]*$$/d' \
                        $(REGRESSION_LIST) 2>/dev/null)

ifeq ($(SUITE),list)
  PATTERNS := $(PATTERNS_LIST)
  ifeq ($(strip $(PATTERNS)),)
    $(error SUITE=list but $(REGRESSION_LIST) is empty or absent.             Build it up with: make sim RECORD=1 PATTERN=<name>)
  endif
else ifeq ($(SUITE),all)
  PATTERNS := $(PATTERNS_ALL)
else ifneq ($(filter $(SUITE),$(SUITE_NAMES)),)
  PATTERNS := $(call pat_in_dir,$(SUITE))
else
  $(error SUITE='$(SUITE)' is invalid. Use all, list, or one of: $(SUITE_NAMES))
endif

# A duplicate basename would run one pattern and shadow another.
# $(sort) removes duplicates, so a shorter sorted list means a collision.
# Done in make rather than the shell: the shell version needed a newline
# inside a tr argument, which does not survive being written into a Makefile.
ifneq ($(words $(PATTERNS_ALL)),$(words $(sort $(PATTERNS_ALL))))
  $(error Pattern name collision across suites. +PATTERN= selects by basename,           so one would shadow the other. Names seen: $(PATTERNS_ALL))
endif

list_patterns:
	@$(foreach d,$(SUITE_NAMES),echo "$(d) ($(words $(call pat_in_dir,$(d)))):"; $(foreach p,$(call pat_in_dir,$(d)),echo "    $(p)";) )echo ""
	@echo "make regress SUITE=all|list|<name>   (now: $(SUITE); registered suites: $(SUITE_NAMES))"

# -----------------------------------------------------------------------------
# How many patterns run at once. 1 keeps the old serial behaviour.
#
# The elaborated simv is SHARED by every job: it is built once as a
# prerequisite below, then opened read-only by each run. What must not be
# shared is the working directory, and each job now has its own -- see the
# sim target for the list of files that made this necessary.
#
# Pick JOBS from the machine, not from the pattern count. Each job is a full
# simv process holding the whole SoC, so memory is the limit before CPU is.
# -----------------------------------------------------------------------------
JOBS ?= 1
override JOBS := $(strip $(JOBS))

REGRESS_JOBS := $(addprefix run-,$(PATTERNS))

# `|| true` so one failing pattern does not abandon the rest of the suite.
# The verdict comes from the summary below, not from make's exit status.
# `run`, not `sim`: the elaboration already happened in the regress target.
run-%:
	@$(MAKE) --no-print-directory run PATTERN=$* SEED=$(SEED) IN_REGRESS=1 || true

# -----------------------------------------------------------------------------
# LSF.
#
# LSF=1 spreads the suite over the farm instead of over local cores. The
# elaboration still happens once, here, on the submit host -- $(SIMV) is a
# prerequisite of regress either way -- and the jobs share it read-only.
#
# The queue's own limits are not a safety net: `bqueues -l vcs` shows no
# RUNLIMIT, so a hung simulation would hold a host and a licence indefinitely.
# LSF_TIMEOUT is what bounds it, and it is passed on every single bsub.
# -----------------------------------------------------------------------------
# LSF, LSF_COMPILE, LSF_NCORE and lsf_on are declared much earlier, next to
# NPROC -- see the note there for why they cannot wait until here.
LSF_QUEUE    ?= vcs
# Which activities go to the farm. Each defaults to LSF so `LSF=1` moves
# everything at once, and each can be set on its own when that is not wanted --
# compiling on the farm while simulating locally, say.
#
# LSF_VERDI is the exception and defaults to OFF whatever LSF is set to.
# Verdi is a GUI: on the farm it needs an interactive slot and a working X
# connection back, and when either is missing the failure is a window that
# never appears. Opting in is the right default for that.
LSF_SIM      ?= $(LSF)
# Not derived from LSF: Verdi refuses to start without -lsfon or -lsfint at
# this site, so it is always on and this only chooses the mode. int keeps the
# GUI attached to your terminal and display.
LSF_VERDI    ?= int
# Verdi has its own queue here (/eda/sunplus/bin/.queue_list maps Verdi and
# Verdi64 to `verdi`). Set it to $(LSF_QUEUE) to send it to the batch queue
# instead.
LSF_VERDI_QUEUE ?= verdi
# Minutes, for the bsub path only -- the site wrappers do their own submission
# and take no timeout from us.
LSF_COMP_TIMEOUT ?= 180
# Default scales with WAVE: FSDB dumping (WAVE=1 or WAVE=full) adds enough
# I/O overhead to justify a longer bound than a plain WAVE=0 run -- still
# just a default, LSF_TIMEOUT=<n> on the command line overrides either way.
ifeq ($(WAVE)$(COV)$(FCOV),000)
  LSF_TIMEOUT ?= 120
else
  LSF_TIMEOUT ?= 180
endif
LSF_JOBS     ?= 8
LSF_SETUP    ?=
LSF_RES      ?=
LSF_POLL     ?= 20
LSF_IDLE     ?= 10
LSF_HANG_KILL?= 1
LSF_PREFLIGHT?= 1
override LSF_QUEUE := $(strip $(LSF_QUEUE))

# MK_DIR is the directory of the Makefile AS INVOKED, and sim/Makefile is a
# symlink to scripts/Makefile -- so running `make` from sim/ makes MK_DIR the
# sim root, not scripts/. Both layouts are in use, so look in both rather than
# picking one and being wrong half the time.
# -----------------------------------------------------------------------------
# -lsfon returns as soon as the job is ACCEPTED, not when it finishes. Without
# this, `make compile LSF=1` returned in 2.7s reporting zero errors while the
# job was still queued -- and the job then failed. Every stage that submits
# must wait for its own job before make treats the stage as done.
#
# The third argument is the file that stage is supposed to have produced. The
# wait is not over until it is visible HERE, which is a different question from
# the job having exited -- the job wrote it on another host through NFS.
#
#   $(call LSF_WAIT,<mode>,<jobname>,<artifact>)
# -----------------------------------------------------------------------------
LSF_WAIT = $(if $(call lsf_on,$(1)), \
             sh $(LSF_WAIT_SH) $(2) $(LSF_COMP_TIMEOUT) $(3),true)

# -----------------------------------------------------------------------------
# LSF for the EDA tools: their own options, not a bsub wrapper around them.
#
# vcs, vlogan, verdi and urg here are not the Synopsys binaries. They are
# /eda/sunplus/bin/* Perl wrappers written by the site's CAD team, and they
# implement LSF themselves:
#
#   -lsfon         background (batch) mode
#   -lsfint        interactive mode
#   -lsfname <n>   the LSF job name
#   -lsfwait <n>   hold until job <n> has ended
#   -lsfq <q>      queue; without it which_queue() picks one per tool from
#                  /eda/sunplus/bin/.queue_list, defaulting to `normal`
#   -lsfncore <n>  cores to reserve
#   -lsfrum <n>    memory rusage
#                                        (/eda/sunplus/bin/vcs:49-60)
#
# Submitting these through our own bsub would nest one submission inside
# another, so the wrapper's options are used directly. Our bsub wrapper is
# kept for simv, which is a binary this project links and which no site
# wrapper knows about.
#
# The options go FIRST, matching how the tools document themselves
# ("verdi -lsfint -dbdir ...") and the wrapper's own note that they belong in
# the first argument.
#
#   $(call LSF_TOOL_OPT,<mode>,<jobname>)
# -----------------------------------------------------------------------------

# The third argument overrides the queue for one call. It exists because this
# site runs Verdi on its own queue (.queue_list maps Verdi -> verdi), and
# sending a GUI to the batch queue is not the same thing at all. Empty falls
# back to LSF_QUEUE, which the user sets.
LSF_TOOL_OPT = $(strip \
  $(if $(filter int,$(1)),-lsfint,$(if $(filter 1 on,$(1)),-lsfon,)) \
  $(if $(call lsf_on,$(1)), \
      -lsfq $(if $(3),$(3),$(LSF_QUEUE)) -lsfname $(2) \
      $(if $(LSF_NCORE),-lsfncore $(LSF_NCORE),) \
      $(if $(LSF_MEM),-lsfrum $(LSF_MEM),),))

# For simv only. simv has no site wrapper, so this is a real bsub.
#
# detach is passed through so LSF_SIM=detach reaches lsf_run.sh's detach arm.
# Without this line the value falls through the $(filter 1,...) test to `off`
# and the simulation runs locally -- which is silent and looks like success
# until you notice it never went to the farm.
#
# WHEN TO USE WHICH, because the difference has already cost a run:
#   LSF_SIM=1        bsub -K, blocks and returns the job's exit status. Right
#                    for a person at a terminal, and required for any stage a
#                    later stage depends on.
#   LSF_SIM=detach   plain bsub, returns a job ID. Required when the
#                    submitting shell may die first -- a telnet session with a
#                    per-command timeout, which is how this project reaches
#                    the farm. -K ties the job to that shell, and job 93426
#                    was reaped as TERM_OWNER at 00:03:04 for exactly that
#                    reason after eight minutes of healthy running.
#   LSF_SIM=0        already inside an LSF allocation; do not submit again.
lsf_mode = $(if $(filter int,$(1)),int,\
             $(if $(filter detach,$(1)),detach,\
               $(if $(filter 1,$(1)),batch,off)))
LSFW = $(if $(filter off,$(call lsf_mode,$(1))),, \
         sh $(LSF_RUN_SH) $(call lsf_mode,$(1)) $(LSF_QUEUE) $(2) $(3) $(4) --)

# Run time settings the job needs. Build settings are deliberately absent:
# the job runs `make run`, which cannot build, so anything that would only
# affect a build has no business travelling with it.
# LSF_SIM=0 is not optional. The job IS the LSF allocation; leaving it on
# would make the `make run` inside it bsub a second job and wait for that,
# holding one slot to queue for another.
MAKE_PASS = IN_REGRESS=1 LSF_SIM=0 LSF_COMPILE=0 \
            WAVE=$(WAVE) COV=$(COV) FCOV=$(FCOV) VERB=$(VERB) \
            SIM_ROOT_PATH=$(SIM_ROOT_PATH) UVM_ROOT_PATH=$(UVM_ROOT_PATH) \
            VIP_HOME=$(VIP_HOME) DUT_ROOT_PATH=$(DUT_ROOT_PATH)

regress: $(SIMV)
ifeq ($(LSF),1)
	@if [ -z "$(LSF_SCRIPT)" ]; then \
	  echo "lsf_regress.sh not found next to the Makefile."; \
	  echo "Looked in: $(MK_DIR) $(MK_DIR)/scripts $(SIM_SCRIPTS)"; \
	  exit 1; \
	fi
	@PATTERNS='$(PATTERNS)' SUITE='$(SUITE)' SEED='$(SEED)' \
	 SIM_ROOT='$(SIM_ROOT_PATH)' LOGDIR='$(LOGDIR)' REPORTDIR='$(REPORTDIR)' \
	 MAKE_BIN='$(MAKE)' MAKE_PASS='$(MAKE_PASS)' \
	 LSF_QUEUE='$(LSF_QUEUE)' LSF_TIMEOUT='$(LSF_TIMEOUT)' \
	 LSF_JOBS='$(LSF_JOBS)' LSF_SETUP='$(LSF_SETUP)' LSF_RES='$(LSF_RES)' \
	 LSF_POLL='$(LSF_POLL)' LSF_IDLE='$(LSF_IDLE)' \
	 LSF_HANG_KILL='$(LSF_HANG_KILL)' LSF_PREFLIGHT='$(LSF_PREFLIGHT)' \
	 sh $(LSF_SCRIPT); rc=$$?; \
	 if [ "$(RECORD)" = "1" ]; then \
	   $(MAKE) --no-print-directory record_suite; \
	 fi; \
	 exit $$rc
else
	@echo "=== Regression: SUITE=$(SUITE), $(words $(PATTERNS)) patterns, $(JOBS) at a time ==="
	@echo "    one elaboration, shared: $(SIMV)"
	@$(MAKE) --no-print-directory -j$(JOBS) $(REGRESS_JOBS)
	@$(MAKE) --no-print-directory regress_summary
endif

# -----------------------------------------------------------------------------
# Kill everything this suite submitted.
#
# By job name rather than by job group, because a group whose creation failed
# would silently match nothing while the jobs kept running.
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Report on a regression that is already running or has finished, without
# submitting anything.
#
# The jobs are LSF jobs, not children of the shell that submitted them, so
# they survive a dropped connection or a closed terminal -- but the polling
# loop does not. This is how to get the table back afterwards, instead of
# running the whole suite again to find out what happened.
#
# For a long suite, submitting under nohup avoids needing this at all:
#     nohup make regress LSF=1 SUITE=sanity > regress.out 2>&1 &
# -----------------------------------------------------------------------------
lsf_report:
	@PATTERNS='$(PATTERNS)' SUITE='$(SUITE)' SEED='$(SEED)' \
	 SIM_ROOT='$(SIM_ROOT_PATH)' LOGDIR='$(LOGDIR)' REPORTDIR='$(REPORTDIR)' \
	 LSF_QUEUE='$(LSF_QUEUE)' LSF_TIMEOUT='$(LSF_TIMEOUT)' \
	 LSF_SUMMARY_ONLY=1 \
	 sh $(LSF_SCRIPT)

lsf_kill:
	@echo "killing $(IP_PREFIX_STEM)reg.$(SUITE).* on queue $(LSF_QUEUE)"
	@bkill -J '$(IP_PREFIX_STEM)reg.$(SUITE).*' 2>&1 | head -20 || true
	@bjobs -J '$(IP_PREFIX_STEM)reg.$(SUITE).*' 2>&1 | head -5 || true

# Detail for jobs still alive, without attaching to a running regression.
lsf_status:
	@bjobs -o "jobid stat queue exec_host job_name run_time" \
	       -J '$(IP_PREFIX_STEM)reg.$(SUITE).*' 2>&1 | head -60 \
	  || echo "no jobs for suite $(SUITE)"

# bhosts has no -q on this LSF (10.1 rejects it), so take the host list out of
# bqueues -l and ask bhosts about those names.
lsf_queues:
	@bqueues $(LSF_QUEUE) 2>&1
	@echo ""
	@bqueues -l $(LSF_QUEUE) 2>&1 | grep -iE "RUNLIMIT|MEMLIMIT|HOSTS|USERS" || true
	@echo ""
	@h=$$(bqueues -l $(LSF_QUEUE) 2>/dev/null \
	      | sed -n 's/^HOSTS: *//p' | tr -d '/' | head -1); \
	 if [ -n "$$h" ]; then bhosts $$h 2>&1 | head -15; fi
	@echo ""
	@bqueues -l $(LSF_QUEUE) 2>/dev/null | grep -qi RUNLIMIT \
	  || echo "note: queue $(LSF_QUEUE) sets no RUNLIMIT, so LSF_TIMEOUT=$(LSF_TIMEOUT)min is the only bound on a hung job"

# -----------------------------------------------------------------------------
# The summary, on screen and in a file.
#
# JOB_SUMMARY is written by every run, single or regression, and overwritten
# each time rather than appended: it answers "what happened just now", and a
# file that accumulates every run since the tree was created answers a
# different and much less useful question. The per-pattern logs are the
# history.
#
# Separate target so a summary can be reproduced without re-running anything.
# -----------------------------------------------------------------------------
JOB_SUMMARY   := $(LOGDIR)/job_summary.txt
TOTAL_SUMMARY := $(SIM_ROOT_PATH)/total_summary.txt

# The local counterpart of the LSF summary, with the same columns so the two
# read alike. There is no queue here, so WAIT has nothing to report; RUN comes
# from the log's own first and last modification, which is the only wall-clock
# figure available once the run has ended.
regress_summary:
	@mkdir -p $(LOGDIR)
	@{ echo ""; \
	   echo "=== summary: SUITE=$(SUITE)  SEED=$(SEED)  $$(date '+%Y-%m-%d %H:%M:%S') ==="; \
	   printf '  %-22s %-11s %-4s %-4s %-5s %-7s %s\n' \
	          PATTERN SIMTIME FTL ERR WARN RESULT LOG; \
	   pass=0; fail=0; miss=0; \
	   for p in $(PATTERNS); do \
	     l=$(LOGDIR)/$${p}_$(SEED).log; \
	     if [ ! -f $$l ]; then \
	       printf '  %-22s %-11s %-4s %-4s %-5s %-7s %s\n' \
	              $$p . . . . - "(none)"; miss=$$((miss+1)); \
	     else \
	       t=$$(sed -n 's/.*FINAL CHECK @ *\([0-9.]*\) *\([a-z]*\).*/\1\2/p' $$l | head -1); \
	       c=$$(grep -m1 "UVM_FATAL *=" $$l 2>/dev/null); \
	       ft=$$(echo "$$c" | sed -n 's/.*UVM_FATAL *= *\([0-9]*\).*/\1/p'); \
	       er=$$(echo "$$c" | sed -n 's/.*UVM_ERROR *= *\([0-9]*\).*/\1/p'); \
	       wr=$$(echo "$$c" | sed -n 's/.*UVM_WARNING *= *\([0-9]*\).*/\1/p'); \
	       if grep -q "VERDICT: PASSED" $$l 2>/dev/null; then \
	         r=PASS; pass=$$((pass+1)); else r=FAIL; fail=$$((fail+1)); fi; \
	       printf '  %-22s %-11s %-4s %-4s %-5s %-7s %s\n' \
	              $$p "$${t:-.}" "$${ft:-.}" "$${er:-.}" "$${wr:-.}" $$r $$l; \
	     fi; \
	   done; \
	   echo ""; \
	   echo "  PASS $$pass   FAIL $$fail   no result $$miss   of $(words $(PATTERNS))"; \
	   echo "  logs    $(LOGDIR)"; \
	   echo "  reports $(REPORTDIR)/<pattern>_$(SEED)"; \
	 } | tee $(JOB_SUMMARY)
	@cp $(JOB_SUMMARY) $(TOTAL_SUMMARY) 2>/dev/null || true
	@echo "  summary $(JOB_SUMMARY)"
	@echo "          $(TOTAL_SUMMARY)"
ifeq ($(RECORD),1)
	@$(MAKE) --no-print-directory record_suite
endif

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Code coverage instrumentation scope.
#
# Generated rather than checked in, because COV_HIER is a variable. Without a
# -cm_hier file VCS instruments the entire SoC, which on this design is slow
# and mostly measures blocks nobody is verifying.
#
# The default scope is u_ss_vout, the subsystem that contains both target-IP
# instances. Widen it with COV_HIER when the DUT boundary changes:
#   make sim COV=1 COV_HIER=sysn063.u_lan063
#
# +tree instruments the named instance and everything below it.
# -----------------------------------------------------------------------------
$(SIM_ROOT_PATH)/cov_hier.cfg:
	@mkdir -p $(SIM_ROOT_PATH)
	@printf '%s\n' $(foreach s,$(COV_SCOPE),'+tree $(s)') > $@
	@printf '%s\n' $(foreach s,$(COV_EXCLUDE),'-tree $(s)') >> $@
	@echo "generated $@"
	@cat $@

ifeq ($(COV),1)
$(SIMV): $(SIM_ROOT_PATH)/cov_hier.cfg
endif

# -----------------------------------------------------------------------------
# Coverage report.
#
# Merges the elaboration's database with every job's database. Both kinds of
# coverage are in there:
#   code       from -cm, present when COV=1
#   functional from the VIP covergroups, present when FCOV=1
# urg reports them together, so a run with neither enabled produces an empty
# report rather than an error, which is confusing. Say so instead.
#
# Two sorts of database are named here, and both are needed:
#   $(CM_DIR)            built by elaboration, holds the design structure
#   $(COVDIR)/<job>.vdb  written by each run, holds that run's test data
# The manual's own parallel example merges exactly this way
# (cov_ref.txt:1591). Reporting on the per-job databases alone gives coverage
# with nothing to attribute it to.
#
# COV_VDBS uses `=`, so the wildcard is evaluated when the recipe runs rather
# than when the Makefile is read -- the databases do not exist yet at read time.
# -----------------------------------------------------------------------------
COV_VDBS = $(wildcard $(COVDIR)/*.vdb)

cov:
	@if [ ! -d $(CM_DIR) ] && [ -z "$(COV_VDBS)" ]; then \
	  echo "No coverage database under $(COVDIR)"; \
	  echo "Coverage is off by default. Re-run with:"; \
	  echo "    make sim     COV=1 FCOV=1 PATTERN=$(PATTERN)"; \
	  echo "    make regress COV=1 FCOV=1 SUITE=$(SUITE) JOBS=$(JOBS)"; \
	  exit 1; \
	fi
	@echo "=== Coverage merge: $(words $(COV_VDBS)) job database(s) ==="
	urg -dir $(CM_DIR) $(COV_VDBS) \
	    -format both -show tests -report $(COVDIR)/urgReport \
	    $(if $(UNR_EL),-elfile $(UNR_EL),)
	@echo "report: $(COVDIR)/urgReport/dashboard.html"

# -----------------------------------------------------------------------------
# Merge several coverage databases into one.
#
# The normal case needs no merge: every pattern writes into $(CM_DIR) under its
# own -cm_name. This is for the case that does -- databases that cannot share a
# directory, e.g. the same suite at different SPEED settings, or runs from
# separate grid machines.
#
#   make cov_merge COV_DIRS="/a/simv.vdb /b/simv.vdb"
#
# -dbname is what makes it a merged DATABASE and not only a report; per the
# Coverage Technology User Guide it also gathers each run's test record into
# test.xml, which is what keeps -show tests meaningful afterwards.
# -----------------------------------------------------------------------------
COV_DIRS  ?= $(CM_DIR)
CM_MERGED := $(COVDIR)/merged.vdb

cov_merge:
	@if [ -z "$(strip $(COV_DIRS))" ]; then \
	  echo "COV_DIRS is empty. Pass the databases to merge:"; \
	  echo "    make cov_merge COV_DIRS=/a/simv.vdb /b/simv.vdb"; \
	  exit 1; \
	fi
	@echo "=== Merging $(words $(COV_DIRS)) database(s) ==="
	urg $(foreach d,$(COV_DIRS),-dir $(d)) -dbname $(CM_MERGED) \
	    -format both -show tests -report $(COVDIR)/urgMerged \
	    $(if $(UNR_EL),-elfile $(UNR_EL),)
	@echo "merged db : $(CM_MERGED)"
	@echo "report    : $(COVDIR)/urgMerged/dashboard.html"

# Verdi coverage GUI. Same database, interactive instead of a static
# report. Syntax from "Recommended Coverage Settings for a New Project".
# Opens the merged database when one exists, otherwise the single run.
# Coverage Technology User Guide: "verdi -cov -covdir <dir>".
cov_gui:
	@if [ -d $(CM_MERGED) ]; then \
	  echo "opening merged database $(CM_MERGED)"; \
	  verdi -cov -covdir $(CM_MERGED) -nologo & \
	elif [ -d $(CM_DIR) ]; then \
	  echo "opening $(CM_DIR)"; \
	  verdi -cov -covdir $(CM_DIR) -nologo & \
	else \
	  echo "No coverage database. Run: make sim COV=1 FCOV=1"; exit 1; \
	fi

# -----------------------------------------------------------------------------
# Unreachability analysis. Separate build, see the UNR block above.
# -----------------------------------------------------------------------------
$(UNR_CFG):
	@mkdir -p $(SIM_ROOT_PATH)
	@# -top is mandatory in the config file for the non UUM flow.
	@echo "-top $(UNR_TOP)" > $@
	@echo "generated $@ targeting $(UNR_TOP)"

unr: $(UNR_CFG)
	@if [ "$(PARTCOMP_EN)" = "1" ]; then \
	  echo "UNR does not support partition compile."; \
	  echo "It is the only entry in the UNR guide Limitations chapter."; \
	  echo "Rebuild without it:"; \
	  echo "    make unr PARTCOMP_EN=0 COV=1"; \
	  exit 1; \
	fi
	@if [ "$(COV)" != "1" ]; then \
	  echo "UNR needs a coverage instrumented build. Add COV=1."; \
	  exit 1; \
	fi
	@echo "=== UNR elaborate (top=$(UNR_TOP), no partition compile) ==="
	cd $(SIM_ROOT_PATH) && vcs $(VCS_FLAGS) -unr=$(UNR_CFG) $(UNR_TOP) \
	    -o $(OUTDIR)/unrSimv -l $(LOGDIR)/unr_compile.log
	@echo "=== UNR analyse ==="
	cd $(SIM_ROOT_PATH) && $(OUTDIR)/unrSimv -unr=$(UNR_CFG) \
	    -save_elfile=$(COVDIR)/unreachables.el -l $(LOGDIR)/unr_run.log
	@echo ""
	@echo "exclusion file: $(COVDIR)/unreachables.el"
	@echo "apply it with:  make cov UNR_EL=$(COVDIR)/unreachables.el"

# clean removes run artifacts but keeps the compilation database, so the
# next sim does not pay for a full elaboration.
clean:
	rm -rf $(LOGDIR)/*.log $(FSDBDIR)/*.fsdb $(COVDIR)/* \
	       $(REPORTDIR)/* $(RUNDIR)/*

# distclean removes everything generated. Guarded, because SIM_ROOT_PATH is
# user supplied and an empty or misspelled value would make this an rm -rf
# on the wrong tree.
distclean:
	@if [ -z "$(strip $(SIM_ROOT_PATH))" ] || [ "$(SIM_ROOT_PATH)" = "/" ]; then \
	  echo "SIM_ROOT_PATH is empty or /, refusing to remove anything"; exit 1; \
	fi
	rm -rf $(SIM_ROOT_PATH)/* \
	       $(SIM_ROOT_PATH)/.uvm.stamp $(SIM_ROOT_PATH)/.dut.stamp \
	       $(SIM_ROOT_PATH)/.analyze.stamp $(SIM_ROOT_PATH)/.flags \
	       $(SIM_ROOT_PATH)/.flow
