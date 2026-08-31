#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check every svt_<class>::<MEMBER> the testbench uses against the VIP source.

WHY THIS EXISTS

Same reason as vip_guards.py: vlogan reports one Error-[MFNF] and stops. Four
wrong member names cost four ~90-second rebuilds to find, and none of them was
a typo -- each was a plausible name that simply is not what the VIP calls it:

    svt_axi_port_configuration::IN_ORDER        -> ROUND_ROBIN
    svt_usb_types::endpoint_type_enum           -> ep_type_enum
    svt_axi_port_configuration::DATA_WIDTH_256  -> the field is a plain int, 256
    svt_usb_types::ESS_GEN2X1                   -> ESSG2

Enum bodies stay in plaintext even in an encrypted .svp delivery -- only method
bodies are `protected -- so a text scan is reliable for this.

USAGE

    vip_members.py <VIP_HOME> <refs-file>

<refs-file> is one svt_class::MEMBER per line. To produce it:

    grep -rhoE '\\bsvt_\\w+::[A-Z][A-Z0-9_]*' $UVM_ROOT_PATH/tb | sort -u > /tmp/refs.txt

For each member that does not resolve, the candidates from the same file whose
name shares the last underscore-separated word are printed; that has named the
replacement every time so far.
"""
import io
import os
import re
import sys

EXTS = ('.sv', '.svp', '.svi', '.svh')


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    vip_home, refs_file = sys.argv[1], sys.argv[2]
    dirs = [os.path.join(vip_home, 'src', 'sverilog', 'vcs'),
            os.path.join(vip_home, 'include', 'sverilog')]
    dirs = [d for d in dirs if os.path.isdir(d)]
    if not dirs:
        print('not a VIP tree: %s' % vip_home)
        return 2

    cache = {}

    def body(cls):
        if cls not in cache:
            txt = ''
            for d in dirs:
                for e in EXTS:
                    p = os.path.join(d, cls + e)
                    if os.path.exists(p):
                        txt += io.open(p, encoding='utf-8',
                                       errors='replace').read()
            cache[cls] = txt
        return cache[cls]

    def enum_of(txt, mem):
        """Which `typedef enum { ... } NAME;` contains this member?

        Existence alone is not enough. svt_usb_types declares both
            RX, TX      } direction_enum;
            OUT, IN     } ep_direction_enum;
        so `svt_usb_types::IN` exists, passes a name check, and is still the
        wrong type wherever a direction_enum is expected -- which cost 8 errors,
        none of them reported on the offending line.
        """
        out = []
        for blk in re.finditer(r'typedef\s+enum\b[^{]*\{(.*?)\}\s*(\w+)\s*;',
                               txt, re.S):
            if re.search(r'(?<!\w)' + re.escape(mem) + r'(?!\w)', blk.group(1)):
                out.append(blk.group(2))
        return out

    refs = [l.strip() for l in io.open(refs_file) if '::' in l]
    bad, found = [], []
    nofile = set()
    for r in refs:
        cls, mem = r.split('::', 1)
        t = body(cls)
        if not t:
            nofile.add(cls)
            continue
        if not re.search(r'(?<!\w)' + re.escape(mem) + r'(?!\w)', t):
            members = sorted(set(re.findall(r'^\s{2,}([A-Z][A-Z0-9_]{2,})\s*=',
                                            t, re.M)))
            key = mem.split('_')[-1]
            near = [c for c in members if key and key in c]
            bad.append((r, near[:6], len(members)))
        else:
            e = enum_of(t, mem)
            if e:
                found.append((r, e))

    print('references checked : %d' % len(refs))
    if nofile:
        print('no plaintext source found for : %s' % ', '.join(sorted(nofile)))
        print('  (that is not a verdict -- an encrypted delivery may still')
        print('   define them; re-run against a plaintext VIP_HOME)')
    print('')
    for r, near, n in bad:
        print('MISSING  %s' % r)
        print('         %d enum members in that file; closest: %s'
              % (n, ', '.join(near) if near else '(no obvious match -- the '
                 'field may not be an enum at all)'))
    print('')
    print('missing : %d' % len(bad))
    print('')
    print('--- which enum each member actually belongs to ---')
    print('Existence is not correctness: a member can resolve and still be the')
    print('wrong type. Compare each line against the field it is assigned to.')
    print('')
    for r, e in sorted(found):
        mark = '  <-- more than one enum!' if len(e) > 1 else ''
        print('  %-52s %s%s' % (r, ', '.join(e), mark))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
