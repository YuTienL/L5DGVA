#!/usr/bin/env python
"""Check every pattern .txt against the project's pattern iron rules.

Usage:  pattern_rules.py <UVM_ROOT_PATH>            # e.g. uvm
        pattern_rules.py <UVM_ROOT_PATH> -v         # list PASS lines too

GENERIC TEMPLATE: this checker is protocol-agnostic, generalized from a real
USB proving-ground project. The macro-name prefix it looks for is read from
the TARGET_IP / IP_PREFIX environment variables (same vocabulary as the
Makefile), defaulting to this template's original USB project so it still
runs standalone unmodified:

    TARGET_IP=PCIE IP_PREFIX=pcie_  python pattern_rules.py <UVM_ROOT_PATH>

The macro VOCABULARY itself (BULK/ISOC/INT/CTRL_XFER transfer-type names,
FW_SERVICE/FORK_PORT_BRINGUP bring-up names) is this template's original USB
project's own worked example; a different protocol's real macro set may
differ in shape as well as prefix -- update REF_CALLS/APB_CALLS/USB_CALLS/
USB_EVIDENCE below to match the current environment's actual macros rather
than assuming a prefix swap alone is sufficient.

Reference command.txt files (the designers' originals, outside tb/patterns/)
are NOT checked -- the rules are about what this environment generates.

The rules, and what each check can and cannot see:

  R1/R2  no reference-derived task may be skipped, and none may be hidden
         behind an `ifdef. Detected by finding known reference calls inside a
         conditional block, and by finding them commented out.
  R4     commenting something out during generation requires stopping to ask.
         A commented-out reference call is therefore reported whether or not
         it was asked about -- the checker cannot know, so it surfaces it.
  R6     blocking + branch-A + branch-B shape.
  R7     AXI and the target IP share <ip>_seq_launcher's capacity-1
         semaphore, so a bare fork of two wrapped tasks is sequential
         (trap 50). Real concurrency needs `FORK_SEQ, and every `FORK_SEQ
         needs a `WAIT_SEQ_ALL (trap 40).
  R8     cannot be checked mechanically. Test intent is not in the syntax.
  R9     redundant comment removal is a judgement; what IS checkable is
         commented-out code, which is never a comment worth keeping.

  Purity: branch-A is APB/AXI, branch-B is the target IP. A `CPUWRITE in
  branch-B or a `<TARGET_IP>_BULK_IN in branch-A is the framework applied
  wrongly.
"""

import os
import re
import sys

# Protocol-target parameterization, same vocabulary as the Makefile.
TARGET_IP = os.environ.get('TARGET_IP', 'USB')
IP_PREFIX = os.environ.get('IP_PREFIX', 'usb_')
IP_PREFIX_STEM = IP_PREFIX.rstrip('_')

# Calls that come from the reference command.txt. Finding one of these behind
# an `ifdef or inside a comment is what R1/R2/R4 are about.
REF_CALLS = (
    'SS_VOUT_MODEL.ss_vout_init_flow', 'GMODEL.GLOBAL_INIT',
    'SMEMMODEL.FILLMEM', 'CPUWRITE1B', 'CPUWRITE2B', 'CPUWRITE4B',
    'CPUREAD1B', 'CPUREAD2B', 'CPUREAD4B', 'HOSTWRITE4B', 'HOSTREAD4B',
)

# Branch-B is the target IP only. These reaching branch-B means APB traffic
# was put on the wrong side (trap 51 is the failure this prevents).
#
# LINKUP and ENUM are branch-B's OWN stages, not exceptions to the rule: the
# framework is "branch B = LinkUp, enumeration, traffic". LINKUP polls
# DSTS.CONNECTSPD and ENUM drives the VIP host through the standard requests.
APB_CALLS = re.compile(r'`(CPUWRITE\d?B|CPUREAD\d?B|'
                       + TARGET_IP + r'_STAGE_(?!LINKUP|ENUM)\w+|APB_\w+)')

# Branch-A is APB/AXI only. A wrapped target-IP transfer here is the mirror
# error.
USB_CALLS = re.compile(
    r'`(' + TARGET_IP + r'_ENUMERATE|' + TARGET_IP + r'_TRAFFIC|'
    + TARGET_IP + r'_BULK_\w+|' + TARGET_IP + r'_ISOC\w*|'
    + TARGET_IP + r'_INT_\w+|' + TARGET_IP + r'_CTRL_XFER|'
    + TARGET_IP + r'_RANDOM|' + TARGET_IP + r'_UVC_(?!EP_CFG)\w+)')

# "IS THIS A TARGET-IP PATTERN" IS A SEPARATE QUESTION FROM "DOES IT CALL A
# WRAPPED TARGET-IP TASK", AND CONFLATING THEM MADE THE CHECKER PASS TWO
# BROKEN FILES. This template's original USB project's usb_parallel_bus and
# usb_perf_concurrent drove every transfer through
# `FORK_SEQ("<class name>", ...) -- a sequence class name is a STRING, looked up
# in the factory, so a scan for macro names cannot see it. Both were
# registered in pattern_list.txt, both had join_any and
# `<TARGET_IP>_FW_SERVICE_FOREVER inside branch_a, and both reported PASS
# because every R6 rule was gated on USB_CALLS. A checker that hides a
# violation is worse than no checker.
#
# So the gate also accepts the marks a target-IP pattern cannot avoid
# leaving: the firmware loop, a bring-up call, a stage call, the branch-B
# barrier, and a launcher call naming a target-IP sequence class.
USB_EVIDENCE = re.compile(
    r'`(' + TARGET_IP + r'_FW_SERVICE_FOREVER|' + TARGET_IP + r'_FORK_FW_SERVICE|'
    + TARGET_IP + r'_FORK_PORT_BRINGUP|'
    + TARGET_IP + r'_INIT|' + TARGET_IP + r'_STAGE_\w+|'
    + TARGET_IP + r'_WAIT_CTRL_READY|' + TARGET_IP + r'_WAIT_EP0_READY|'
    + TARGET_IP + r'_BRINGUP\w*)\b'
    r'|`(?:FORK_SEQ|RUN_SEQ\w*)\s*\(\s*"' + re.escape(IP_PREFIX_STEM) + r'[a-z0-9_]*"')

# Branch-B's entry barrier, and the two ways branch-A can raise it.
BARRIER_WAIT = re.compile(r'`' + TARGET_IP + r'_WAIT_CTRL_READY\s*\(')
BARRIER_RAISE = re.compile(r'`' + TARGET_IP + r'_CTRL_DONE\s*\(')
SOC_INIT = re.compile(r'`' + TARGET_IP + r'_SOC_INIT\b')
SOC_RUN_INC = re.compile(r'`include\s+"soc_run\.svh"')
SOC_INT_INC = re.compile(r'`include\s+"soc_int\.svh"')

# The six-branch shape: blocking + branch_a0 + branch_a1 + branch_fw +
# branch_b0 + branch_b1. A0/A1 and FW are launched with join_none and are not
# waited for; B0/B1 are joined with `join`.
FORK_BRINGUP = re.compile(r'`' + TARGET_IP + r'_FORK_PORT_BRINGUP\b')
FORK_FW      = re.compile(r'`' + TARGET_IP + r'_FORK_FW_SERVICE\b')
FW_FOREVER   = re.compile(r'`' + TARGET_IP + r'_FW_SERVICE_FOREVER\b')

# A DECLARED departure from the shape, with its reason on the same line:
#     //SIX-BRANCH-EXC: the rounds arm both ports before either fires
# Twelve patterns coordinate the two ports against each other and that
# coordination IS the test, so a parallel branch_b0/branch_b1 would delete it.
# Six more have no USB content at all. UNDECLARED IS THE VIOLATION -- a
# permanent unexplained FAIL only teaches people to ignore the checker, and a
# silent exemption teaches them nothing at all.
SIX_BRANCH_EXC = re.compile(r'//\s*SIX-BRANCH-EXC:\s*(\S.*)')


def strip_block_comments(text):
    return re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'),
                  text, flags=re.S)


def classify(lines):
    """Return (branch_a_lines, branch_b_lines, blocking_lines) as index lists.

    Regions run from `begin : branch_<label>` to the matching end, by
    begin/end depth. Anything outside a labelled branch is blocking.

    BOTH GENERATIONS OF LABEL ARE RECOGNISED. The six-branch shape names its
    host scripts branch_b0 and branch_b1; the two-branch shape it replaces had
    a single branch_a and branch_b, and twelve patterns keep a single branch_b
    on purpose because coordinating the two ports against each other IS their
    test (this template's original USB project's own worked example:
    usb_dual_port's rounds, usb_concurrent's asymmetric round 3, usb_perf's
    deliberately uncontended per-port measurement). Those are declared with
    SIX_BRANCH_EXC, not by being unrecognisable here.

    branch_a0/branch_a1 are accepted for a pattern whose port bring-up is
    written by hand. Most patterns have no branch_a region at all now: the
    bring-up is launched by `<TARGET_IP>_FORK_PORT_BRINGUP, which forks internally.
    """
    a, b, blocking = [], [], []
    cur, depth = None, 0
    for i, ln in enumerate(lines):
        code = re.sub(r'//.*', '', ln)
        if cur is None:
            m = re.search(r'\bbegin\s*:\s*branch_([ab])[01]?\b', code)
            if m:
                cur = m.group(1)
                depth = 1
                continue
            blocking.append(i)
        else:
            depth += len(re.findall(r'\bbegin\b', code))
            depth -= len(re.findall(r'\bend\b(?!module|task|function|case)', code))
            if depth <= 0:
                cur = None
                continue
            (a if cur == 'a' else b).append(i)
    return a, b, blocking


def check(path, name):
    raw = open(path, encoding='utf-8', errors='replace').read()
    text = strip_block_comments(raw)
    lines = text.splitlines()
    code = '\n'.join(re.sub(r'//.*', '', l) for l in lines)
    a_idx, b_idx, _ = classify(lines)
    a_txt = '\n'.join(re.sub(r'//.*', '', lines[i]) for i in a_idx)
    b_txt = '\n'.join(re.sub(r'//.*', '', lines[i]) for i in b_idx)

    fails, warns, info = [], [], []
    has_fork = bool(a_idx or b_idx)
    has_ip_traffic = bool(USB_CALLS.search(code) or SOC_RUN_INC.search(code)
                   or USB_EVIDENCE.search(code))

    # --- R6 shape: blocking + a0 + a1 + fw + b0 + b1 ----------------------
    m_exc = SIX_BRANCH_EXC.search(raw)     # raw: the reason lives in a comment
    exc_why = m_exc.group(1).strip() if m_exc else ''

    if not SOC_INT_INC.search(code):
        fails.append('R6 no `include "soc_int.svh" (blocking Global section)')

    # A HAND-WRITTEN PER-PORT BRING-UP COUNTS, which is what classify()'s
    # docstring already promised and this line did not deliver. This
    # template's original USB project had five patterns that could not use
    # soc_run.svh for reasons in their own headers -- usb_perf needed
    # usb_perf_tune BETWEEN USB_STAGE_CTRL and USB_STAGE_EP0, which is the
    # wrong side of the hand-back pause; usb3_rate_switch needed DCFG.DEVSPD
    # to DISAGREE with the build, which is the whole test -- and they
    # expressed the bring-up as labelled branch_a0/branch_a1 regions instead.
    #
    # branch_a0 ALONE IS NOT ENOUGH unless declared. That is job 98520's shape:
    # port 1 acquires a silent dependency on port 0's branch having run, and a
    # single-port run of port 1 then has no bring-up at all and says nothing.
    has_a0 = bool(re.search(r'\bbegin\s*:\s*branch_a0\b', code))
    has_a1 = bool(re.search(r'\bbegin\s*:\s*branch_a1\b', code))
    launches_a  = bool(SOC_RUN_INC.search(code) or FORK_BRINGUP.search(code)
                       or (has_a0 and has_a1) or (has_a0 and m_exc))
    # soc_run.svh now forks branch_fw itself (`<TARGET_IP>_FORK_FW_SERVICE,
    # right after both `<TARGET_IP>_FORK_PORT_BRINGUP calls), so including it
    # satisfies this the same way it already satisfies launches_a. A
    # pattern's own explicit call remains valid
    # (<TARGET_IP>_FW_SERVICE_FOREVER guards against the double launch that
    # would otherwise cause) and still counts here.
    launches_fw = bool(FORK_FW.search(code) or SOC_RUN_INC.search(code))
    has_b0 = bool(re.search(r'\bbegin\s*:\s*branch_b0\b', code))
    has_b1 = bool(re.search(r'\bbegin\s*:\s*branch_b1\b', code))

    # ANCHORED TO A WHOLE LINE. `\bjoin\b` matched the word inside
    # $display("... did not join cleanly") and reported three converted
    # patterns as unconverted -- the string-literal false positive this file's
    # own header warns about. The LAST such line is the one that closes the
    # host-script fork; the join_none launches come before it.
    joins = re.findall(r'^\s*(join(?:_any|_none)?)\s*;?\s*$', code, re.M)
    join_kind = joins[-1] if joins else ''

    if has_ip_traffic:
        if not launches_a:
            fails.append('R6 nothing launches branch_a0/branch_a1 -- no '
                         'soc_run.svh include and no `%s_FORK_PORT_BRINGUP' % TARGET_IP)
        if not launches_fw:
            fails.append('R6 no `%s_FORK_FW_SERVICE -- branch_fw is missing, '
                         'so nothing answers EP0 and every control transfer '
                         'times out against a device with no responder' % TARGET_IP)
        if FW_FOREVER.search(a_txt) or FW_FOREVER.search(b_txt):
            fails.append('R6 `%s_FW_SERVICE_FOREVER inside a branch. It is '
                         'branch_fw and is started with `%s_FORK_FW_SERVICE; '
                         'left inside branch_a it never returns, and the '
                         '`join over the host scripts never completes' % (TARGET_IP, TARGET_IP))
        if ('`' + TARGET_IP + '_PAR_ON') not in code and not SOC_RUN_INC.search(code):
            fails.append('R6 nothing reaches `%s_PAR_ON -- soc_run.svh '
                         'carries it for the patterns that include it' % TARGET_IP)

    # --- R6b the host scripts are two branches, joined with `join` --------
    # join_any was safe only while branch_a ended in a forever loop and so
    # never finished. branch_fw is now its own background branch, so A0 and A1
    # complete -- and far earlier than either host script. join_any then ends
    # the pattern the moment A0 returns: job 98520 stopped at 15.32 us with
    # 0 UVM_ERROR and no SvtTestEpilog, which reads exactly like a pass.
    if has_ip_traffic and join_kind == 'join_any':
        if m_exc:
            info.append('join_any, SIX-BRANCH-EXC: %s' % exc_why[:70])
        else:
            fails.append('R6b host-script fork is closed with join_any. A0/A1 '
                         'now finish, so this ends the pattern early and '
                         'silently (job 98520). Use `join over branch_b0 and '
                         'branch_b1, or declare //SIX-BRANCH-EXC: <reason>')

    if has_ip_traffic and not (has_b0 and has_b1):
        missing = ' and '.join(n for n, got in
                               (('branch_b0', has_b0), ('branch_b1', has_b1))
                               if not got)
        if m_exc:
            info.append('no %s, SIX-BRANCH-EXC: %s' % (missing, exc_why[:70]))
        else:
            fails.append('R6b no %s. Each host script needs its own branch '
                         'under `if (`%s_PORT_EN(p)), so a disabled port is '
                         'visibly skipped rather than indistinguishable from '
                         'one that was forgotten -- and so a single-port run '
                         'cannot come to depend on the other port having run. '
                         'If the two ports must be coordinated against each '
                         'other, declare //SIX-BRANCH-EXC: <reason>' % (missing, TARGET_IP))

    # An exception that is declared but not needed is its own defect: it
    # silences a rule nobody is breaking, and the next real violation in this
    # file will be silenced with it.
    if m_exc and has_ip_traffic and has_b0 and has_b1 and join_kind != 'join_any':
        warns.append('R6b //SIX-BRANCH-EXC declared but the file conforms -- '
                     'remove it, or it will hide the next real violation')

    m = re.search(r'`FINAL_CHECK\s*\(\s*("([^"]*)")?\s*\)', code)
    if not m:
        fails.append('R6 no `FINAL_CHECK')
    elif not m.group(2):
        fails.append('R6 `FINAL_CHECK() called with no pattern name')
    elif m.group(2) != name:
        warns.append('R6 `FINAL_CHECK("%s") does not match the file name'
                     % m.group(2))

    # --- ss_vout_init_flow must be branch-A's first act -------------------
    reaches_init = bool(SOC_RUN_INC.search(code) or SOC_INIT.search(code))
    if has_ip_traffic and not reaches_init:
        fails.append('R6 nothing reaches ss_vout_init_flow -- no soc_run.svh '
                     'include and no `%s_SOC_INIT. The AXI arbiters stay '
                     'paused and the setup TRB fetch never completes' % TARGET_IP)
    # "First" means first thing that touches the DUT. A banner $display, a
    # `define, or the `<TARGET_IP>_PAR_OFF that brackets a hierarchical wait
    # are not statements this rule is about -- flagging them was noise.
    #
    # NOT CHECKED WHEN ss_vout_init_flow IS REACHED FROM THE BLOCKING SECTION,
    # because there it is CORRECT and the warning recommended the bug. With the
    # per-port bring-up split into branch_a0 and branch_a1, a
    # `<TARGET_IP>_SOC_INIT inside a branch is run by BOTH of them; it is
    # idempotent through soc_init_done, so the second call is silent and the
    # reader is left with a pattern that looks like it initialises the SoC
    # twice. The four patterns with a hand-written bring-up all place it in
    # the blocking section.
    init_in_branch = bool(SOC_RUN_INC.search(a_txt) or SOC_INIT.search(a_txt))
    if a_idx and reaches_init and init_in_branch:
        first = ''
        for i in a_idx:
            s = re.sub(r'//.*', '', lines[i]).strip()
            if (not s or s.startswith('$display') or s.startswith('`define')
                    or s.startswith('`' + TARGET_IP + '_PAR_') or s in ('begin', 'end')):
                continue
            first = s
            break
        if not (SOC_RUN_INC.search(first) or SOC_INIT.search(first)):
            warns.append('R6 branch_a reaches ss_vout_init_flow but does not '
                         'START with it (found: %s). Move it to the blocking '
                         'section, or make it the first act of the branch'
                         % first[:60])

    # --- barrier ----------------------------------------------------------
    if b_idx and USB_CALLS.search(b_txt) and not BARRIER_WAIT.search(b_txt):
        # <ip>_up_body.svh carries the barrier for the patterns that include it
        if (IP_PREFIX + 'up_body.svh') not in b_txt and (IP_PREFIX + 'link_body.svh') not in b_txt:
            fails.append('R6 branch_b runs target-IP traffic without '
                         '`%s_WAIT_CTRL_READY -- it can start before branch_a '
                         'has written DCTL.RunStop' % TARGET_IP)
    if SOC_INIT.search(code) and not (BARRIER_RAISE.search(code)
                                      or SOC_RUN_INC.search(code)):
        fails.append('R6 `%s_SOC_INIT without `%s_CTRL_DONE -- branch_b '
                     'will wait out its bound and report the port' % (TARGET_IP, TARGET_IP))

    # --- purity -----------------------------------------------------------
    # A register access in branch B is a FAIL unless it carries BRANCH-EXC on
    # its own line or in the three lines above it. That tag means someone
    # established the access cannot move -- an observation whose value is its
    # position in the target-IP sequence, like a DSTS sample taken between
    # two link events. UNTAGGED IS THE VIOLATION; a permanent unexplained
    # FAIL just teaches people to ignore the checker.
    #
    # The tag silences the checker, NOT the run. Iron rule 3 stands: the
    # pattern must also say so at run time.
    par_on = '`' + TARGET_IP + '_PAR_ON'
    par_off = '`' + TARGET_IP + '_PAR_OFF'
    for i in b_idx:
        c = re.sub(r'//.*', '', lines[i])
        m2 = APB_CALLS.search(c)
        if not m2:
            continue
        # The tag covers the whole `<TARGET_IP>_PAR_OFF/`<TARGET_IP>_PAR_ON
        # bracket it sits in, because these accesses come in groups and one
        # reason covers the group. Outside a bracket it covers five lines.
        start = i - 5
        for j in range(i, max(0, i - 60), -1):
            if par_on in lines[j]:
                break
            if par_off in lines[j]:
                start = j - 8
                break
        ctx = '\n'.join(lines[max(0, start):i + 1])
        if 'BRANCH-EXC' in ctx:
            info.append('%d: `%s in branch_b, tagged BRANCH-EXC'
                        % (i + 1, m2.group(1)))
            continue
        fails.append('%d: branch_b is target-IP only, found `%s (trap 51). '
                     'If it cannot move, tag it BRANCH-EXC with the reason '
                     'and warn at run time' % (i + 1, m2.group(1)))
        break
    for i in a_idx:
        c = re.sub(r'//.*', '', lines[i])
        m2 = USB_CALLS.search(c)
        if m2:
            fails.append('%d: branch_a is APB/AXI only, found `%s'
                         % (i + 1, m2.group(1)))
            break

    # --- R7 concurrency ---------------------------------------------------
    n_fork_seq = len(re.findall(r'`FORK_SEQ\b', code))
    n_wait_all = len(re.findall(r'`WAIT_SEQ_ALL(_OK)?\b', code))
    if n_fork_seq and not n_wait_all:
        fails.append('R7 %d `FORK_SEQ with no `WAIT_SEQ_ALL -- the run ends '
                     'mid-transfer and reports Passed (trap 40)' % n_fork_seq)

    # A bare fork whose branches each call a wrapped task is trap 50: both go
    # through <ip>_seq_launcher's capacity-1 semaphore and run sequentially.
    for m3 in re.finditer(r'\bfork\b(.*?)\bjoin\b', code, re.S):
        body = m3.group(1)
        if 'branch_a' in body or 'branch_b' in body:
            continue
        n = len(re.findall(r'`(AXI_\w+|' + TARGET_IP + r'_BULK_\w+|'
                           + TARGET_IP + r'_ISOC\w*|' + TARGET_IP + r'_INT_\w+|'
                           + TARGET_IP + r'_TRAFFIC|' + TARGET_IP + r'_RANDOM)', body))
        if n >= 2 and '`FORK_SEQ' not in body:
            ln = code[:m3.start()].count('\n') + 1
            warns.append('%d: fork of %d wrapped tasks with no `FORK_SEQ -- '
                         'they share one capacity-1 semaphore and run '
                         'sequentially (trap 50)' % (ln, n))

    # --- R1/R2/R4 ---------------------------------------------------------
    depth, guard_start = 0, None
    for i, ln in enumerate(lines):
        if re.match(r'\s*`(ifdef|ifndef)\b', ln):
            depth += 1
            if depth == 1:
                guard_start = i
        elif re.match(r'\s*`endif\b', ln):
            depth = max(0, depth - 1)
            if depth == 0 and guard_start is not None:
                seg = '\n'.join(re.sub(r'//.*', '', l)
                                for l in lines[guard_start:i + 1])
                for c in REF_CALLS:
                    if c in seg:
                        warns.append('%d: reference call %s inside an `ifdef '
                                     '(R2 forbids hiding one behind a guard)'
                                     % (guard_start + 1, c))
                        break
                guard_start = None

    # Only a commented-out CALL counts, not prose that names one. The call
    # form is a backtick macro with an argument list, or `SOMETHING.task;` --
    # requiring that is what stops "// ss_vout_init_flow is the first
    # statement of soc_run.svh" from being reported as a skipped task.
    #
    # A tag says the line has been classified against the reference and is
    # therefore not an unanswered R4 question. UNTAGGED IS THE VIOLATION;
    # this must be an explicit exemption, not the regex happening to miss.
    #   //REF-OFF:      commented out in the reference too -- not ours to run
    #   //SUPERSEDED:   a live line here does the same thing
    #   //BFM:          host-side original, replaced by the VIP
    tagged = 0
    for i, ln in enumerate(lines):
        m4 = re.match(r'\s*//\s*(REF-OFF:|SUPERSEDED:|BFM:)?\s*'
                      r'(`\w+\s*\(|`?\w+(?:\.\w+)+\s*[;(])', ln)
        if not m4:
            continue
        tag, frag = m4.group(1), m4.group(2)
        hit = None
        for c in REF_CALLS:
            leaf = c.split('.')[-1]
            if leaf in frag:
                hit = leaf
                break
        if hit is None:
            continue
        if tag:
            tagged += 1
        else:
            warns.append('%d: reference call %s is commented out and untagged '
                         '(R4 needed a question at the time; classify it as '
                         '//REF-OFF: //SUPERSEDED: or //BFM:)' % (i + 1, hit))
    if tagged:
        info.append('%d commented reference calls, all classified' % tagged)

    return fails, warns, info


# A literal port where the file is supposed to read the branch's own port.
# `<TARGET_IP>_IS_SS(0) inside branch_b1 sends a SuperSpeed-only sequence
# onto whatever port 1 was built as, and CLAUDE.md records that picking the
# wrong isochronous family does NOT fail -- is_applicable returns 0 and the
# sequence quietly does nothing. (IS_SS/DEVSPD are this template's original
# USB project's own speed-check macros; adjust for TARGET_IP's real ones.)
SPEED_READ = re.compile(r'`(' + TARGET_IP + r'_IS_SS|' + TARGET_IP + r'_DEVSPD)\s*\(\s*([01])\s*\)')


# Macros whose FIRST argument is a port, read out of the `define parameter
# lists rather than guessed from the name. A guess is what produced the false
# report on `<TARGET_IP>_DEPCFG_PAR1(1, 0, 0) -- that 1 is a logical endpoint.
_PORT_FIRST = None
_TOPDIR = None

PORT_PARAM = ('port', 'p', IP_PREFIX_STEM + '_port', 'prt')


def port_first_macros():
    global _PORT_FIRST
    if _PORT_FIRST is not None:
        return _PORT_FIRST
    _PORT_FIRST = set()
    if not _TOPDIR or not os.path.isdir(_TOPDIR):
        return _PORT_FIRST
    for f in sorted(os.listdir(_TOPDIR)):
        if not f.endswith('.svh'):
            continue
        src = open(os.path.join(_TOPDIR, f), encoding='utf-8',
                   errors='replace').read()
        for m in re.finditer(r'`define\s+(' + TARGET_IP + r'_[A-Za-z0-9_]+)\s*\(([^)]*)\)',
                             src):
            first = m.group(2).split(',')[0].strip()
            if first.lower() in PORT_PARAM:
                _PORT_FIRST.add(m.group(1))
    return _PORT_FIRST


# A file under common/ reaches its port one of two ways, and the two carry
# opposite obligations. Deciding by SHAPE rather than by filename: what makes a
# file branch-A is that it walks the ports itself.
PORT_LOOP = re.compile(r'for\s*\(.*<=\s*1\s*;.*\)\s*if\s*\(\s*`' + TARGET_IP + r'_PORT_EN')


def check_shared_body(path):
    """A file under patterns/common/, checked against whichever contract it is.

    branch-B body   included once per branch, so it must take
                    `<TARGET_IP>_BODY_PORT. A literal port in it makes
                    branch_b1 drive port 0 -- twice the traffic on one port,
                    none on the other, and a log that looks busy either way.

    branch-A ep_cfg included ONCE and walks both ports itself, because branch A
                    after soc_run.svh is a single thread and a second include
                    would redeclare the block label. `<TARGET_IP>_BODY_PORT is
                    wrong here, not missing.
    """
    raw = open(path, encoding='utf-8', errors='replace').read()
    text = strip_block_comments(raw)
    lines = text.splitlines()
    # Line comments too: this file's own prose names `<TARGET_IP>_BODY_PORT
    # to say it does NOT take one, and matching that read the header as if
    # it were code.
    code = '\n'.join(re.sub(r'//.*', '', l) for l in lines)
    fails, warns, info = [], [], []

    loops_ports = bool(PORT_LOOP.search(code))
    uses_param = '`' + TARGET_IP + '_BODY_PORT' in code

    if loops_ports and uses_param:
        fails.append('R10 walks both ports AND reads `%s_BODY_PORT. One or '
                     'the other: the loop variable is branch A\'s, the macro '
                     'is branch B\'s, and mixing them makes the port depend on '
                     'which include site won' % TARGET_IP)
    elif not loops_ports and not uses_param:
        fails.append('R10 no `%s_BODY_PORT and no per-port loop -- this file '
                     'cannot be included once per port, so branch_b1 would '
                     'drive port 0' % TARGET_IP)

    for i, ln in enumerate(lines):
        c = re.sub(r'//.*', '', ln)
        m = SPEED_READ.search(c)
        if m:
            fails.append('%d: `%s(%s) reads a LITERAL port. The two ports are '
                         'built at independent speeds (SPEED0/SPEED1), so it '
                         'must read the port it is acting on, or it decides a '
                         'SuperSpeed question using the other port\'s answer'
                         % (i + 1, m.group(1), m.group(2)))
            break
        # Only for macros whose FIRST argument really is a port. Scanning every
        # `<TARGET_IP>_*(0, ...) flagged `<TARGET_IP>_DEPCFG_PAR1(1, 0, 0),
        # whose first argument is the logical endpoint number.
        m = re.search(r'`(' + TARGET_IP + r'_[A-Z0-9_]+)\s*\(\s*([01])\s*,', c)
        if m and uses_param and m.group(1) in port_first_macros():
            fails.append('%d: `%s(%s, ...) passes a literal port'
                         % (i + 1, m.group(1), m.group(2)))
            break

    if not fails:
        info.append('branch A, walks both ports' if loops_ports
                    else 'branch B, per port via `%s_BODY_PORT' % TARGET_IP)
    return fails, warns, info


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    root = argv[1]
    verbose = '-v' in argv
    global _TOPDIR
    _TOPDIR = os.path.join(root, 'tb', 'top')
    pdir = os.path.join(root, 'tb', 'patterns')
    if not os.path.isdir(pdir):
        sys.stderr.write('pattern_rules: no %s\n' % pdir)
        return 2

    # SUITE NAMES COME FROM THE REGISTRY, NOT A HARDCODED LIST. MEASURED
    # 2026-08-22, this template's original USB project: after a directory
    # taxonomy migration (basic/sanity/<protocol> -> infra/enumeration/speed/
    # link/power/performance/transfer/uvc/rate_switch/user_define), this
    # loop's old ('basic', 'sanity', '<protocol>') tuple found zero patterns
    # -- the exact same hardcoded-directory-list defect the
    # sim/scripts/Makefile SUITE= logic had (rule 115). Scanning every
    # directory pattern_list.txt actually references removes the class of
    # bug rather than trading one fixed list for another.
    suites = set()
    list_path = os.path.join(pdir, 'pattern_list.txt')
    if os.path.isfile(list_path):
        with open(list_path) as lf:
            for line in lf:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                parts = s.split()
                if len(parts) >= 2:
                    suites.add(parts[1])
    if not suites:
        suites = {'basic', 'sanity', IP_PREFIX_STEM}  # fallback if the registry is unreadable

    files = []
    for suite in sorted(suites):
        d = os.path.join(pdir, suite) if suite not in ('.', '') else pdir
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith('.txt'):
                    files.append((suite, f[:-4], os.path.join(d, f)))

    n_fail = n_warn = 0
    for suite, name, path in files:
        fails, warns, info = check(path, name)
        if fails or warns:
            print('%s/%s' % (suite, name))
            for f in fails:
                print('    FAIL  %s' % f)
            for w in warns:
                print('    warn  %s' % w)
            for x in info:
                print('    info  %s' % x)
            print('')
        elif verbose:
            print('%s/%s  PASS%s' % (suite, name,
                                     '  (%s)' % '; '.join(info) if info else ''))
        n_fail += len(fails)
        n_warn += len(warns)

    # A literal port in one of these defeats branch_b1 for every pattern that
    # includes it -- 23 patterns hang off these files. _body and _ep_cfg are
    # checked against DIFFERENT contracts; check_shared_body decides which from
    # the file's shape.
    cdir = os.path.join(pdir, 'common')
    bodies = []
    if os.path.isdir(cdir):
        bodies = [f for f in sorted(os.listdir(cdir))
                  if re.match(re.escape(IP_PREFIX) + r'.*(_body|_ep_cfg)\.svh$', f)]
    if bodies:
        print('--- shared bodies and endpoint configurations ---')
    n_body_fail = 0
    for f in bodies:
        fails, warns, info = check_shared_body(os.path.join(cdir, f))
        if fails or warns:
            print('common/%s' % f)
            for x in fails:
                print('    FAIL  %s' % x)
            for x in warns:
                print('    warn  %s' % x)
        elif verbose:
            print('common/%s  PASS%s' % (f, '  (%s)' % '; '.join(info)
                                         if info else ''))
        n_body_fail += len(fails)
        n_warn += len(warns)
    if bodies:
        print('%d shared bodies checked: %d FAIL' % (len(bodies), n_body_fail))
        print('')
    n_fail += n_body_fail

    print('%d patterns checked: %d FAIL, %d warn' % (len(files), n_fail, n_warn))
    print('')
    print('R8 (do not break the test intent) is NOT checkable here -- it is')
    print('not in the syntax. R9 is only partly: commented-out code is')
    print('reported, redundant prose is not.')
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
