#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find `:=` assignments that reference a variable defined later in the file.

WHY THIS EXISTS

`:=` expands immediately. Referencing a variable that is assigned further down
the file yields the empty string, silently:

    SIM_BUILD_OPTS := ... $(VIP_WIDTHS)          line 627
    VIP_WIDTHS     := +define+SVT_APB_PWDATA_WIDTH=32 ...   line 690

Nothing warns. The only visible trace is a double space where the value should
have been, on a command line nobody reads:

    ... +define+UVM_PACKER_MAX_BYTES=24000  +define+RTL ...

This has happened twice in this Makefile. The first time the SLED define never
reached analysis and the run looked entirely normal with no records produced.
The second time the APB VIP was compiled at its default 8-bit data width while
the configuration set 32 at run time, and SVT_AXI_MAX_ADDR_USER_WIDTH stayed at
4 while the DUT needs 9 -- both silent.

USAGE

    make_order.py <Makefile>

Exit status is 1 if anything is reported.

WHAT IT DOES NOT CATCH

`=` (recursive) assignments, which expand at use and are therefore fine, and
variables that come from the environment or the command line.
"""
import io
import re
import sys

ASSIGN = re.compile(r'^\s*(?:override\s+|export\s+)?([A-Za-z_][A-Za-z0-9_]*)'
                    r'\s*(:=|::=|\?=|\+=|=)')
REF = re.compile(r'\$[({]([A-Za-z_][A-Za-z0-9_]*)[)}]')
# Names make defines itself, or that legitimately come from outside.
BUILTIN = {'CURDIR', 'MAKEFILE_LIST', 'MAKECMDGOALS', 'SHELL', 'MAKE',
           'MAKEFLAGS', 'PWD', 'HOME', 'USER', 'PATH', 'VCS_HOME', 'UVM_HOME',
           'VIP_HOME', 'DUT_ROOT_PATH', 'UVM_ROOT_PATH', 'SIM_ROOT_PATH',
           'VERDI_HOME', 'DESIGNWARE_HOME'}


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    lines = io.open(sys.argv[1], encoding='utf-8',
                    errors='replace').read().split('\n')

    first_def = {}
    for i, l in enumerate(lines):
        m = ASSIGN.match(l)
        if m and m.group(1) not in first_def:
            first_def[m.group(1)] = i

    problems = []
    for i, l in enumerate(lines):
        if l.startswith('\t') or l.lstrip().startswith('#'):
            continue                       # recipe lines expand at run time
        m = ASSIGN.match(l)
        if not m or m.group(2) not in (':=', '::='):
            continue
        lhs = m.group(1)
        rhs = l[m.end():]
        for ref in REF.findall(rhs):
            if ref in BUILTIN or ref == lhs:
                continue
            if ref in first_def and first_def[ref] > i:
                problems.append((i + 1, lhs, ref, first_def[ref] + 1))

    # A rule's prerequisite list is expanded when the rule is READ, so a name
    # defined further down expands to nothing and the rule silently has no
    # dependency. This is the same defect as above in a different place, and
    # checking only assignments let it through once: .uvm.stamp listed
    # $(FLAGSIG) and $(FLOWTAG), both defined 80 lines lower, and therefore
    # never re-ran when the analysis flags changed.
    RULE = re.compile(r'^([^\s:#=][^:=]*):(?!=)([^;]*)')
    for i, l in enumerate(lines):
        if l.startswith('\t') or l.lstrip().startswith('#'):
            continue
        m = RULE.match(l)
        if not m:
            continue
        for ref in REF.findall(m.group(2)):
            if ref in BUILTIN:
                continue
            if ref in first_def and first_def[ref] > i:
                problems.append((i + 1, m.group(1).strip()[:20] + ' (prereq)',
                                 ref, first_def[ref] + 1))

    if not problems:
        print('No := assignment or rule prerequisite references a variable '
              'defined later.')
        return 0
    print('%-6s %-22s %-24s %s' % ('LINE', 'ASSIGNS', 'USES (still empty)',
                                   'DEFINED AT'))
    for ln, lhs, ref, dln in problems:
        print('%-6d %-22s %-24s %d' % (ln, lhs, ref, dln))
    print('')
    print('total : %d' % len(problems))
    print('')
    print('Move the definition above its first use, or make the assignment')
    print('recursive with = so it expands when it is read.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
