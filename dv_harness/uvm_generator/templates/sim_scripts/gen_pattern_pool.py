#!/usr/bin/env python
"""Generate dv_uvm_pattern_pool.svh from pattern_list.txt.

WHY THIS IS GENERATED
---------------------
Registering a pattern used to mean two hand edits inside a 400 line file: a
task wrapper in the right section, and a case arm in the right place. Both
have to agree, and the wrapper has to match the pattern's style or the build
fails with a syntax error pointing at the include rather than at the mistake.

SystemVerilog cannot read a list at elaboration -- the arms of a `case` on a
string have to exist at compile time -- so a registry file only helps if
something turns it into code. That is this.

WHY A LIST RATHER THAN GLOBBING THE DIRECTORY
---------------------------------------------
Globbing would need no registry at all, and it was the first design. It was
rejected for two reasons:

  - removing a pattern would mean deleting or moving its file. Unregistering
    should not be destructive.
  - every .txt in the tree would be compiled in, and the pool's own header
    notes that a syntax error in any one pattern breaks the whole build. There
    has to be somewhere to park a pattern that is not finished.

THE ONE THING THAT IS NOT IN THE LIST
-------------------------------------
Whether a pattern brings its own task. The pool carries two styles:

    task automatic pat_x();      <- 4 patterns: a bare body, wrapped here
      `include "x.txt"
    endtask

    `include "sanity/y.txt"      <- 35 patterns: the file declares its own
                                    task, because it has local variables and
                                    SystemVerilog wants those first

Getting that wrong is a syntax error, so it is detected rather than declared:
a file containing `task automatic pat_` is self-declaring. Checked against the
current tree, that rule agrees with all 39 registrations.
"""
import os
import re
import sys

HEADER = """//=========================================================================
// dv_uvm_pattern_pool.svh -- every pattern, compiled in
//
// !! GENERATED FILE, DO NOT EDIT !!
//
// Produced from patterns/pattern_list.txt by sim/scripts/gen_pattern_pool.py.
// Edit the list, not this file; anything written here is lost on the next
// build. To add or remove a pattern:
//
//     make ADD_PAT PAT_NAME=<name>.txt PAT_DIR=<dir>
//     make RM_PAT  PAT_NAME=<name>.txt PAT_DIR=<dir>
//
// All patterns are compiled in, so compile time and memory grow with the
// pool, and a syntax error in any one pattern breaks the whole build. That is
// an acceptable price for turning N elaborations into one -- and it is why
// the list exists, so an unfinished pattern can sit in the tree unregistered.
//
// Task properties
// ---------------
// automatic, so the local declarations inside soc_int.svh become automatic
// locals. The shared pat_rdata and pat_fail stay at module scope in
// dv_uvm_hook.svh and are visible from here.
//=========================================================================
"""


def read_list(path):
    """Registry entries as (name, directory, description)."""
    out = []
    with open(path, encoding='utf-8', errors='replace') as fh:
        for raw in fh:
            line = raw.split('#', 1)[0].strip()
            if not line:
                continue
            parts = line.split(None, 2)
            name = parts[0]
            directory = parts[1] if len(parts) > 1 else '.'
            desc = parts[2] if len(parts) > 2 else ''
            out.append((name, directory, desc))
    return out


TASK_RE = re.compile(r'^task\s+(?:automatic\s+|static\s+)?(\w+)\s*[;(]')


def declared_tasks(path):
    """Every task this file declares, in order of declaration.

    Three things here are deliberately not assumed:

    `automatic` is optional. `task pat_x;` is legal SystemVerilog and would be
    missed by a pattern that insists on the keyword -- the file would then be
    treated as a bare body, wrapped in a task, and produce a task declared
    inside a task.

    The name need not match the file. A file called yyy.txt is free to declare
    `task pat_ABC`. Calling pat_yyy because that is what the file is called
    gives "pat_yyy is not declared", which points at the generated pool rather
    than at the pattern.

    There may be more than one. Eight patterns in this tree declare helper
    tasks beside the entry point, so the first declaration is not necessarily
    the one to call -- see pick_entry.
    """
    out = []
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            stripped = line.lstrip()
            if stripped.startswith('//'):
                continue
            m = TASK_RE.match(stripped)
            if m:
                out.append(m.group(1))
    return out


def pick_entry(name, tasks):
    """Which of a file's tasks is the pattern's entry point.

    In order of confidence:
      pat_<registered name>   the convention, and what all 39 use today
      the first pat_*         a file whose entry is named differently
      the first task at all   a file that does not use the prefix

    The choice is returned with a flag saying whether it was the obvious one,
    so the caller can say out loud when it was not. Silently calling the wrong
    task would compile -- it is a real task -- and run the wrong thing.
    """
    want = 'pat_' + name
    if want in tasks:
        return want, True
    for t in tasks:
        if t.startswith('pat_'):
            return t, False
    return tasks[0], False


def main():
    if len(sys.argv) != 4:
        sys.stderr.write(
            'usage: gen_pattern_pool.py <pattern_list.txt> <patterns_dir> <out.svh>\n')
        return 2
    list_path, pat_dir, out_path = sys.argv[1:4]

    entries = read_list(list_path)
    if not entries:
        sys.stderr.write('gen_pattern_pool: %s registers no patterns\n' % list_path)
        return 1

    wrapped, included, arms, missing = [], [], [], []
    seen = set()
    owner = {}      # task name -> the pattern that declares it
    renamed = []    # entry point whose name is not pat_<pattern>

    for name, directory, desc in entries:
        if name in seen:
            sys.stderr.write('gen_pattern_pool: %s listed twice\n' % name)
            return 1
        seen.add(name)

        rel = name + '.txt' if directory in ('.', '') else '%s/%s.txt' % (directory, name)
        full = os.path.join(pat_dir, rel)
        if not os.path.isfile(full):
            missing.append((name, full))
            continue

        tasks = declared_tasks(full)
        if tasks:
            entry, obvious = pick_entry(name, tasks)
            if not obvious:
                renamed.append((name, rel, entry, tasks))
            included.append((rel, desc))
        else:
            # A bare body: the pool supplies the task, so the entry point is
            # ours to name and matches the pattern by construction.
            entry = 'pat_' + name
            tasks = [entry]
            wrapped.append((name, rel, desc))

        # Every task in the file is compiled in, so a name used by two
        # patterns is a duplicate declaration -- which fails to compile with a
        # message naming the task, not the two files that share it.
        for t in tasks:
            if t in owner and owner[t] != name:
                sys.stderr.write(
                    'gen_pattern_pool: task %s is declared by both %s and %s.\n'
                    '  Both are compiled in, so this will not elaborate. Rename one.\n'
                    % (t, owner[t], name))
                return 1
            owner[t] = name

        arms.append((name, entry))

    if missing:
        for name, full in missing:
            sys.stderr.write('gen_pattern_pool: %s is registered but %s does not exist\n'
                             % (name, full))
        return 1

    # Said out loud rather than handled quietly. The generated call is correct
    # either way, but a pattern whose entry point is not named after it is
    # worth knowing about -- it is the difference between "make sim
    # PATTERN=yyy" and what a reader will find when they open yyy.txt.
    for name, rel, entry, tasks in renamed:
        sys.stderr.write('gen_pattern_pool: note: %s declares %s, not pat_%s.\n'
                         '  PATTERN=%s will call %s. Tasks in the file: %s\n'
                         % (rel, entry, name, name, entry, ', '.join(tasks)))

    body = [HEADER, '']

    if wrapped:
        body.append('// --- patterns whose file is a bare body, wrapped here ---------------------')
        for name, rel, desc in wrapped:
            if desc:
                body.append('/** %s */' % desc)
            body.append('task automatic pat_%s();' % name)
            body.append('  `include "%s"' % rel)
            body.append('endtask')
            body.append('')

    if included:
        body.append('// --- patterns that declare their own task ---------------------------------')
        body.append('//')
        body.append('// Included at file scope. These carry local variables, and SystemVerilog')
        body.append('// needs those declared before the first statement, so each file brings its')
        body.append('// own task rather than being wrapped above.')
        for rel, desc in included:
            if desc:
                body.append('/** %s */' % desc)
            body.append('`include "%s"' % rel)
        body.append('')

    body.append('// --- selector -------------------------------------------------------------')
    body.append('//')
    body.append('// +PATTERN=<name> at run time. Unknown names are reported rather than')
    body.append('// silently defaulting: a typo that ran smoke instead would be recorded as a')
    body.append('// pass for the pattern that never ran.')
    body.append('task automatic dv_uvm_run_pattern();')
    body.append('  string pname;')
    body.append('')
    body.append('  if (!$value$plusargs("PATTERN=%s", pname))')
    body.append('    pname = "smoke";')
    body.append('')
    body.append('  $display("=========================================================");')
    body.append('  $display("[dv_uvm] pattern = %s  @ %0t", pname, $time);')
    body.append('  $display("=========================================================");')
    body.append('')
    body.append('  case (pname)')
    width = max(len(a) for a, _ in arms) + 3
    for name, entry in arms:
        # The arm calls the task the FILE declares, which is not always
        # pat_<name>. Assuming it is produces "pat_x is not declared", pointing
        # at this generated file instead of at the pattern that renamed it.
        body.append('    %-*s %s();' % (width, '"%s":' % name, entry))
    body.append('    default: begin')
    body.append('      $display("[dv_uvm] ERROR: no pattern named \'%s\'.", pname);')
    body.append('      $display("         Registered patterns are listed in");')
    body.append('      $display("         tb/patterns/pattern_list.txt");')
    body.append('      $display("         Add one with: make ADD_PAT PAT_NAME=<f>.txt PAT_DIR=<d>");')
    body.append('      pat_fail = pat_fail + 1;')
    body.append('    end')
    body.append('  endcase')
    body.append('endtask')
    body.append('')

    text = '\n'.join(body)

    # Only rewrite when the content changes, so the file's timestamp does not
    # move on every build -- it is a prerequisite of the elaboration, and
    # touching it would re-elaborate the whole design for nothing.
    if os.path.isfile(out_path):
        with open(out_path, encoding='utf-8', errors='replace') as fh:
            if fh.read() == text:
                print('gen_pattern_pool: %d patterns, unchanged' % len(arms))
                return 0

    with open(out_path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    print('gen_pattern_pool: %d patterns -> %s' % (len(arms), out_path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
