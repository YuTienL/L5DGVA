#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Report macros the TESTBENCH STAGE uses but does not define for itself.

WHY THIS EXISTS

Analysis is split: stage 1b reads the DUT (and, through MODEL_ALL.v, the hook
and the pattern pool), stage 1c reads the testbench entry dv_uvm_all.sv. Two
vlogan invocations, and neither inherits the other's preprocessor state.

Anything dv_uvm_all.sv used to get for free -- because MODEL_ALL.v had already
included dv_uvm_hook.svh, which defines the hierarchy macros -- is now
undefined (real example from this template's original USB project; the
macro/file names below are illustrative, not IP_PREFIX-substituted):

    usb_seq_launcher.sv, 309: Undefined macro exists as: 'USB_SYS_TOP'

One such macro costs a ~3 minute build to find. This finds them all at once.

SCOPE MATTERS. Only the dv_uvm_all.sv chain is checked. Files reached from
MODEL_ALL.v -- dv_uvm_hook.svh, the patterns -- are analysed in stage 1b where
the DUT's own macros (CPUWRITE, SMEMMODEL, HOSTWRITE ...) are defined, and
flagging those would be noise.

USAGE

    macro_selfcontained.py <UVM_ROOT_PATH> [makefile] [entry.sv]
"""
import io
import os
import re
import sys

KNOWN_PREFIX = ('uvm_', 'UVM_', 'SVT_', 'svt_', 'VCS', 'SYNOPSYS')
DIRECTIVES = {'define', 'include', 'ifdef', 'ifndef', 'else', 'elsif', 'endif',
              'undef', 'default_nettype', 'timescale', 'line', 'resetall',
              'celldefine', 'endcelldefine', 'protected', 'endprotected',
              '__FILE__', '__LINE__'}
SUBDIRS = ('top', 'env', 'seq', 'tests', 'agents', 'patterns')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    tb = os.path.join(sys.argv[1], 'tb')
    mkfile = sys.argv[2] if len(sys.argv) > 2 else None
    entry = sys.argv[3] if len(sys.argv) > 3 else 'top/dv_uvm_all.sv'
    if not os.path.isdir(tb):
        print('no tb/ under %s' % sys.argv[1])
        return 2

    def find(name):
        for d in SUBDIRS:
            p = os.path.join(tb, d, name)
            if os.path.exists(p):
                return p
        return None

    defined, used, seen, guarded_by = set(), {}, set(), {}

    def walk(path):
        if path in seen:
            return
        seen.add(path)
        try:
            txt = io.open(path, encoding='utf-8', errors='replace').read()
        except IOError:
            return
        rel = os.path.relpath(path, tb).replace(os.sep, '/')
        defined.update(re.findall(r'`define\s+(\w+)', txt))
        # Block comments too, not just //. This template's original USB
        # project's <ip>_seq_launcher.sv documented `<TARGET_IP>_BRINGUP(0)
        # inside a /* */ block; counting that reported a macro the file does
        # not actually use.
        txt = re.sub(r'/\*.*?\*/', '', txt, flags=re.S)
        # A USE OF `X INSIDE `ifdef X IS NOT A MISSING MACRO -- that branch is
        # only compiled when X exists. Both false positives this check ever
        # produced (real examples, this template's original USB project) were
        # this shape: <ip>_reg_map.sv:102-103 did
        # `elsif <TARGET_IP>_BASE_ADDR / <ip>0_apb_base = `<TARGET_IP>_BASE_ADDR,
        # and <ip>_event_bridge.sv:92-93 guarded `FRONTMODEL with
        # `ifdef <TARGET_IP>_UVM_BRIDGE_FRONTMODEL. Track the positive guards
        # in scope.
        guards = []
        for line in txt.split('\n'):
            code = line.split('//')[0]
            g = re.match(r'\s*`(ifdef|ifndef|elsif|else|endif)\b\s*(\w+)?', code)
            if g:
                d, nm = g.group(1), g.group(2)
                if d == 'ifdef':
                    guards.append([nm])
                elif d == 'ifndef':
                    guards.append([None])
                elif d == 'elsif' and guards:
                    guards[-1] = [nm]
                elif d == 'else' and guards:
                    guards[-1] = [None]
                elif d == 'endif' and guards:
                    guards.pop()
                continue
            active = set(n for gs in guards for n in gs if n)
            # `NAME`` is macro paste: the fragment before `` is not a macro
            for m in re.finditer(r'`(\w+)', code):
                n = m.group(1)
                if n in DIRECTIVES or n.startswith(KNOWN_PREFIX):
                    continue
                if n in active:
                    continue
                if code[m.end():m.end() + 2] == '``':
                    continue
                # ...and the other side of a paste: `TOP.ss_cpu_m_``sig names
                # the macro's parameter, not a macro.
                if code[max(0, m.start() - 1):m.start()] == '`':
                    continue
                used.setdefault(n, rel)
                # Remember what guarded it, so an unreachable use can be
                # reported as unreachable rather than as a missing macro.
                guarded_by.setdefault(n, sorted(active))
        # Strip comments first. dv_uvm_all.sv:23 documents the hook with a
        # commented-out `include "dv_uvm_hook.svh"; following it pulled the
        # entire DUT-stage chain in and produced four confident false
        # positives (SMEMMODEL, FRONTMODEL, SS_VOUT_MODEL, <TARGET_IP>_BASE_ADDR).
        code_only = '\n'.join(l.split('//')[0] for l in txt.split('\n'))
        for name in re.findall(r'`include\s+"([^"]+)"', code_only):
            p2 = find(name)
            if p2:
                walk(p2)

    start = os.path.join(tb, entry)
    if not os.path.exists(start):
        print('entry not found: %s' % start)
        return 2
    walk(start)

    cmdline = set()
    if mkfile and os.path.exists(mkfile):
        mk = io.open(mkfile, encoding='utf-8', errors='replace').read()
        cmdline = set(re.findall(r'\+define\+(\w+)', mk))

    missing = sorted((n, f) for n, f in used.items()
                     if n not in defined and n not in cmdline)

    print('entry                          : %s' % entry)
    print('files in that chain            : %d' % len(seen))
    print('macros it defines              : %d' % len(defined))
    print('macros supplied by the Makefile: %d' % len(cmdline))
    print('')
    if not missing:
        print('The testbench stage defines every macro it uses.')
        return 0
    # A use whose only guard is itself never defined is DEAD CODE, not a
    # missing macro. Saying so is the difference between "add an include" and
    # "this feature cannot be switched on".
    real, dead = [], []
    for n, f in missing:
        gs = [g for g in guarded_by.get(n, [])
              if g not in defined and g not in cmdline]
        (dead if gs else real).append((n, f, gs))

    if real:
        print('%-34s %s' % ('MACRO', 'FIRST USED IN'))
        for n, f, _ in real:
            print('%-34s %s' % (n, f))
        print('')
        print('total : %d' % len(real))
        print('')
    else:
        print('Every macro the testbench stage uses is defined or reachable.')
        print('')

    if dead:
        print('UNREACHABLE -- used only inside a guard nothing defines, so the')
        print('macro is never expanded. This is dead code, not a missing')
        print('include: the feature has no way to be switched on.')
        print('')
        for n, f, gs in dead:
            print('  %-28s %-34s guard: %s' % (n, f, ', '.join(gs)))
        print('')
    if real:
        print('Each is either defined by the DUT include chain -- which stage 1c')
        print('does not see -- or by the VIP. Include the defining header from')
        print('dv_uvm_all.sv; the project headers are guarded.')
    # Dead code is worth reporting but does not fail the check: nothing it
    # names can reach an analysis error.
    return 1 if real else 0


if __name__ == '__main__':
    sys.exit(main())
