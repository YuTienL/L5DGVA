#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Report the `ifdef stack enclosing each VIP class the testbench names.

WHY THIS EXISTS

vlogan reports ONE "not recognized as a type" and stops, so a testbench that
names twenty unavailable VIP classes costs twenty ~90-second rebuilds to find
them. Worse, the set cannot be guessed: of the sixteen AXI sequences behind
`ifdef SVT_ACE5_ENABLE, ten carry the svt_ prefix and four do not -- and two
UNGATED ones also lack the prefix. Guessing produced 6 right, 2 wrong, 10
missed.

A wrong guess in the safe direction just fails to compile. A wrong guess in
the other direction -- an available class wrapped in a guard it does not need
-- compiles fine and that sequence is then silently never configured.

USAGE

    vip_guards.py <VIP_HOME> <names-file>

<names-file> is one class name per line. To produce it from the testbench:

    grep -rhoE '\\bsvt_[a-z][A-Za-z_0-9]*_sequence\\b' $UVM_ROOT_PATH/tb \\
      | sort -u > /tmp/names.txt

Run it against VIP_HOME, not the site install: an encrypted .svp delivery
hides class declarations inside `protected blocks, where a text scan sees
nothing and proves nothing.

OUTPUT

One line per class, naming the guards in force. A guard the build does not
define means the class is not a type. `!GUARD_<FILE>_SV entries are the file's
own include guard and can be ignored.
"""
import io
import os
import re
import sys


def scan(vip_src, names):
    """class name -> (file, line, [guards])"""
    found = {}
    wanted = set(names)
    for fn in sorted(os.listdir(vip_src)):
        if not fn.endswith(('.sv', '.svi', '.svh')):
            continue
        try:
            lines = io.open(os.path.join(vip_src, fn), encoding='utf-8',
                            errors='replace').read().split('\n')
        except IOError:
            continue
        stack = []
        for k, raw in enumerate(lines):
            t = raw.strip()
            m = re.match(r'`(ifdef|ifndef)\s+(\w+)', t)
            if m:
                stack.append(('!' if m.group(1) == 'ifndef' else '') + m.group(2))
                continue
            if t.startswith('`elsif'):
                m = re.match(r'`elsif\s+(\w+)', t)
                if stack:
                    stack[-1] = m.group(1) if m else stack[-1]
                continue
            if t.startswith('`else'):
                if stack:
                    s = stack[-1]
                    stack[-1] = s[1:] if s.startswith('!') else '!' + s
                continue
            if t.startswith('`endif'):
                if stack:
                    stack.pop()
                continue
            m = re.match(r'(?:virtual\s+)?class\s+(\w+)\b', t)
            if m and m.group(1) in wanted and m.group(1) not in found:
                found[m.group(1)] = (fn, k + 1, list(stack))
    return found


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    vip_home, names_file = sys.argv[1], sys.argv[2]
    vip_src = os.path.join(vip_home, 'src', 'sverilog', 'vcs')
    if not os.path.isdir(vip_src):
        print('not a VIP tree: %s (expected %s)' % (vip_home, vip_src))
        return 2

    names = [l.strip() for l in io.open(names_file) if l.strip()]
    found = scan(vip_src, names)

    gated, missing = [], []
    for n in names:
        if n not in found:
            missing.append(n)
            continue
        fn, ln, st = found[n]
        real = [g for g in st if not g.startswith('!GUARD_')]
        if real:
            gated.append((n, fn, ln, real))

    print('%-62s %-7s %s' % ('CLASS', 'LINE', 'GUARDS'))
    for n, fn, ln, st in gated:
        print('%-62s %-7d %s' % (n, ln, ' && '.join(st)))
    print('')
    for n in missing:
        print('NOT FOUND in any plaintext source: %s' % n)
    print('')
    print('checked %d, gated %d, not found %d'
          % (len(names), len(gated), len(missing)))
    print('')
    print('A "gated" class is only a type when its guards are all defined by')
    print('the build. Guard the declaration AND its uses with the same')
    print('condition -- never wrap an ungated class, that compiles and then')
    print('silently does nothing.')
    return 1 if (gated or missing) else 0


if __name__ == '__main__':
    sys.exit(main())
