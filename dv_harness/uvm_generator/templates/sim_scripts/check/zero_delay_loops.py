#!/usr/bin/env python
"""Find loops that can spin without advancing simulation time.

Usage:  zero_delay_loops.py <UVM_ROOT_PATH>          # e.g. uvm
        zero_delay_loops.py <UVM_ROOT_PATH> -v       # list tier 3 too

A loop whose exit depends on something only time can change, and which contains
no time-consuming statement, freezes the simulator: wall clock burns, $time
does not move, and NOTHING is printed. Job 98669 spent several rounds being
diagnosed as a hang, a stall, an I/O block and a slow run before the shape was
recognised, so this check exists to find the shape statically.

Three tiers, because "contains a #" is not the same as "always delays":

  1  no #, @, wait() and no call at all in the body.  A guaranteed spin if the
     exit condition is set from outside.
  2  no #, @, wait() but the body calls something.  The call MAY consume time;
     this needs a human to say which.
  3  a #, @ or wait() exists but EVERY one of them is inside a conditional.
     The loop delays on some paths and not others -- which is the shape of
     this template's original USB project's own <TARGET_IP>_FW_SERVICE_FOREVER,
     where `if (wake > $time) #(wake - $time);` does nothing at all when a
     deadline has already passed.

Tier 3 is reported only with -v because the guarded form is often correct;
what it needs is a reader who can say the guard cannot be false for ever.
"""

import os
import re
import sys

LOOP = re.compile(r'\b(forever|while|do)\b')
# Time-consuming primitives. `wait fork` and `@` in a sensitivity list of an
# always block are not loop bodies, so they do not reach here.
DELAY = re.compile(r'(#\s*[\(\d`]|@\s*[\(*a-zA-Z]|\bwait\s*\()')
# A call: an identifier followed by ( that is not a keyword or a system task.
CALL = re.compile(r'(?<![\w`$])(?!if|while|for|case|repeat|return|begin|forever|do|else|and|or|not)'
                  r'[A-Za-z_]\w*\s*\(')
MACRO_CALL = re.compile(r'`[A-Za-z_]\w*\s*\(')
KEYWORDS = {'if', 'while', 'for', 'case', 'casez', 'casex', 'repeat', 'return',
            'begin', 'forever', 'do', 'else', 'wait', 'disable', 'fork'}


def strip_noise(text):
    """Remove block comments, line comments and string literals."""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    out = []
    for ln in text.split('\n'):
        ln = re.sub(r'//.*', '', ln)
        ln = re.sub(r'"[^"\n]*"', '""', ln)
        out.append(ln)
    return '\n'.join(out)


def body_of(lines, i):
    """Return (body_text, end_index) for the loop whose header is on line i.

    Walks begin/end depth. A single-statement body (no begin) is the remainder
    of the line plus following lines up to the first ';' at depth 0.
    """
    rest = lines[i]
    j = i
    # Find the start: either a begin, or a single statement.
    depth = 0
    started = False
    buf = []
    while j < len(lines) and j < i + 400:
        seg = lines[j] if j > i else rest
        buf.append(seg)
        opens = len(re.findall(r'\bbegin\b', seg))
        closes = len(re.findall(r'\bend\b(?!module|task|function|case|generate|interface|package|class)', seg))
        if opens:
            started = True
        depth += opens - closes
        if started and depth <= 0:
            return '\n'.join(buf), j
        if not started and j > i and ';' in seg:
            return '\n'.join(buf), j
        if not started and j == i and ';' in seg.split(')', 1)[-1]:
            return '\n'.join(buf), j
        j += 1
    return '\n'.join(buf), min(j, len(lines) - 1)


def conditional_lines(body):
    """Line indices inside the body that sit under an if/else/case."""
    marked = set()
    depth_stack = []
    for k, ln in enumerate(body.split('\n')):
        if re.search(r'\b(if|else|case|casez|casex)\b', ln):
            depth_stack.append(k)
        if depth_stack:
            marked.add(k)
    return marked


# A loop that changes its own exit condition inside the body is making
# progress on its own and cannot spin waiting for the world. Without this the
# scanner reported a string-trim `while (n > 0 ...) n = n - 1;` as a guaranteed
# spin -- the check has to distinguish "waiting for something else" from
# "counting down", and only the first is a hazard.
SELF_ADVANCING_FN = re.compile(r'\$(fgets|fscanf|fread|value\$plusargs|sscanf)')


def makes_progress(cond, body):
    if SELF_ADVANCING_FN.search(cond):
        return True
    for var in set(re.findall(r'[A-Za-z_]\w*', cond)):
        if var in KEYWORDS:
            continue
        # assigned in the body: `var = `, `var <= `, `var++`, `var += `
        if re.search(r'\b%s\s*(=[^=]|<=[^=]|\+\+|--|\+=|-=)' % re.escape(var),
                     body):
            return True
    return False


def scan(path):
    raw = open(path, encoding='utf-8', errors='replace').read()
    text = strip_noise(raw)
    lines = text.split('\n')
    hits = []
    for i, ln in enumerate(lines):
        m = LOOP.search(ln)
        if not m:
            continue
        kind = m.group(1)
        # `do` is only a loop when a while follows; skip the common false hit.
        if kind == 'do' and not re.search(r'\bdo\b\s*(begin|\w)', ln):
            continue
        body, _ = body_of(lines, i)
        cond = ln[m.end():]
        if kind != 'forever' and makes_progress(cond, body):
            continue
        has_delay = bool(DELAY.search(body))
        calls = [c for c in re.findall(r'([A-Za-z_]\w*)\s*\(', body)
                 if c not in KEYWORDS]
        has_call = bool(calls) or bool(MACRO_CALL.search(body))

        if not has_delay and not has_call:
            tier = 1
        elif not has_delay:
            tier = 2
        else:
            # Every delay inside a conditional?
            cond = conditional_lines(body)
            blines = body.split('\n')
            unguarded = any(DELAY.search(bl) and k not in cond
                            for k, bl in enumerate(blines))
            tier = 3 if not unguarded else 0
        if tier:
            hits.append((i + 1, kind, tier, ln.strip()[:70],
                         sorted(set(calls))[:4]))
    return hits


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    root = argv[1]
    verbose = '-v' in argv
    files = []
    for base, _, names in os.walk(os.path.join(root, 'tb')):
        for n in names:
            if n.endswith(('.sv', '.svh', '.txt')):
                files.append(os.path.join(base, n))

    counts = {1: 0, 2: 0, 3: 0}
    for f in sorted(files):
        hits = scan(f)
        show = [h for h in hits if h[2] in (1, 2) or verbose]
        if show:
            print(os.path.relpath(f, root))
        for line, kind, tier, src, calls in show:
            counts[tier] += 1
            label = {1: 'SPIN  ', 2: 'REVIEW', 3: 'guarded'}[tier]
            print('    %-7s %s:%d  %s' % (label, kind, line, src))
            if tier == 2 and calls:
                print('              calls: %s' % ', '.join(calls))
        for _, _, tier, _, _ in hits:
            if tier == 3 and not verbose:
                counts[3] += 1
        if show:
            print('')

    print('%d files scanned' % len(files))
    print('  tier 1 SPIN   (no delay, no call)        : %d' % counts[1])
    print('  tier 2 REVIEW (no delay, calls something): %d' % counts[2])
    print('  tier 3 guarded (every delay under an if) : %d  %s'
          % (counts[3], '' if verbose else '(-v to list)'))
    return 1 if counts[1] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
