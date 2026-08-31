#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Report every class used as a type before it is defined in the include chain.

WHY THIS EXISTS

The testbench is one file to vlogan -- dv_uvm_all.sv -- and ~60 sources arrive
through `include. Get the order wrong and the compiler says

    token 'usb_reg_sequencer' should be a valid type

one name at a time, ~90 seconds apart. Three such errors were found that way
before this script found the rest in one pass.

Two different defects look identical in the compiler output and need opposite
fixes:

  a plain ordering mistake  -> move the `include earlier
  a genuine cycle           -> `typedef class X;`  (moving it cannot help)

usb_top_env <-> usb_seq_launcher_seq is a real cycle: the env builds the
launcher, and the launcher $casts its parent back to the env.

USAGE

    include_order.py <UVM_ROOT_PATH>            # defaults to tb/top/dv_uvm_all.sv
    include_order.py <UVM_ROOT_PATH> <entry.sv>

Forward typedefs already present are honoured, so a declared cycle is not
reported again.
"""
import io
import os
import re
import sys

INC = re.compile(r'^\s*`include\s+"([^"]+)"')
CDEF = re.compile(r'^\s*(?:virtual\s+)?class\s+(\w+)')
CTYP = re.compile(r'^\s+(\w+)\s+\w+\s*(?:\[[^\]]*\])?\s*;')
FWD = re.compile(r'^\s*typedef\s+class\s+(\w+)\s*;')
SUBDIRS = ('top', 'env', 'seq', 'tests', 'agents', 'patterns')


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    tb = os.path.join(sys.argv[1], 'tb')
    entry = sys.argv[2] if len(sys.argv) == 3 else os.path.join('top',
                                                                'dv_uvm_all.sv')
    if not os.path.isdir(tb):
        print('no tb/ under %s' % sys.argv[1])
        return 2

    def find(name):
        for d in SUBDIRS:
            p = os.path.join(tb, d, name)
            if os.path.exists(p):
                return p
        return None

    defined, used, fwd, seen = {}, [], set(), set()
    seq = [0]

    def walk(path):
        if path in seen:
            return
        seen.add(path)
        try:
            lines = io.open(path, encoding='utf-8',
                            errors='replace').read().split('\n')
        except IOError:
            return
        rel = os.path.relpath(path, tb).replace(os.sep, '/')
        for k, l in enumerate(lines):
            m = INC.match(l)
            if m:
                p2 = find(m.group(1))
                if p2:
                    walk(p2)
                continue
            m = FWD.match(l)
            if m:
                fwd.add(m.group(1))
                continue
            m = CDEF.match(l)
            if m:
                seq[0] += 1
                defined.setdefault(m.group(1), (rel, seq[0]))
                continue
            m = CTYP.match(l)
            if m:
                seq[0] += 1
                used.append((m.group(1), rel, k + 1, seq[0]))

    start = os.path.join(tb, entry)
    if not os.path.exists(start):
        print('entry not found: %s' % start)
        return 2
    walk(start)

    problems = []
    for cls, rel, ln, s in used:
        if cls not in defined:
            continue                       # a VIP or uvm type, not ours
        dfile, dseq = defined[cls]
        if dseq > s and cls not in fwd:
            problems.append((cls, rel, ln, dfile))

    print('classes defined in the chain : %d' % len(defined))
    print('forward typedefs present     : %d  %s'
          % (len(fwd), ', '.join(sorted(fwd)) or '-'))
    print('')
    if not problems:
        print('No class is used as a type before it is defined.')
        return 0
    print('%-26s %-34s %-6s %s' % ('CLASS', 'USED IN', 'LINE', 'DEFINED IN'))
    for cls, rel, ln, dfile in problems:
        print('%-26s %-34s %-6d %s' % (cls, rel, ln, dfile))
    print('')
    print('total : %d' % len(problems))
    print('')
    print('Move the `include earlier when the dependency is one-way. When both')
    print('files name each other it is a cycle and only a forward typedef')
    print('helps -- reordering will just move the error.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
