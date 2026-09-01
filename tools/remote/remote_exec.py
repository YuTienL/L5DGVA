# -*- coding: utf-8 -*-
"""remote_exec.py -- thin client for the persistent relay (remote_relay.py).

THIS FILE NEVER READS VCPW. It talks only to a loopback relay process that
a human started separately, in their own terminal, using remote_relay.py.
This is the one file of the pair Claude Code is expected to invoke via a
tool call.

Usage:
  python tools/remote/remote_exec.py --status
  python tools/remote/remote_exec.py "pwd"
  python tools/remote/remote_exec.py --timeout 1800 "make WAVE=1"
  python tools/remote/remote_exec.py --cwd /home/svcacct/AI/Agent "pwd"
  python tools/remote/remote_exec.py --reconnect
  python tools/remote/remote_exec.py --put local_file remote_file
  python tools/remote/remote_exec.py --get remote_file local_file

--cwd runs the command in a subshell cd'd to that directory (see
remote_relay.py's RelayServer.handle_request 'run' op) instead of relying on
this relay's persistent shell cwd -- the relay is ONE continuous shell
shared by every caller of this (vchost, vchop) pair, so a bare `cd` or
`module load` issued by one command silently persists into the next
caller's command, even a caller working on something unrelated. Pass --cwd
(and prefer full binary paths over relying on a prior `module load`) on
every call when this relay may be shared with other concurrent work.

DVWORKDIR (env var) sets a default --cwd so you don't have to repeat it on
every call -- set once per terminal/session, e.g. to the Linux-server-side
deployment path of the VIP-based verification environment you are working
on this session (distinct from VCWORKDIR, which is the relay's own shared
shell cwd set once at relay start -- see REMOTE_LOGIN_GUIDE.md's "VCWORKDIR
vs. --project-root" section, and note DVWORKDIR is a third, different
concept from both):
  DVWORKDIR=/home/tmpacct/devuser/UVM/USB python tools/remote/remote_exec.py "make WAVE=1"
An explicit --cwd on the command line always overrides DVWORKDIR.

Requires VCHOST/VCHOP env vars (to locate the same relay info file
remote_relay.py wrote) -- but never VCPW.

See docs/superpowers/specs/2026-08-30-persistent-remote-relay-design.md
(in the v50 project) for the full design.
"""
import argparse, json, os, socket, sys

from remote_relay import info_path, is_msys_mangled_path

# REAL BUG FOUND LIVE (2026-09-02): every one of a long string of --put
# MD5_MISMATCH failures against the real /home/svcacct/AI/Agent deployment
# turned out to have nothing to do with the relay's transfer logic at all
# -- this tool was invoked through Git Bash on Windows, whose MSYS layer
# auto-rewrites a bare /home/... argument into a Windows path like
# "D:/Program Files/Git/home/..." BEFORE Python ever sees it in sys.argv
# (remote_hop.py's own module docstring already documented this exact
# gotcha and its MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' workaround --
# it was simply not applied when invoking this tool). Two rounds of
# unrelated (if still real) hardening in remote_hop.py's put() were
# chased before this was found. Detect the unambiguous case -- a
# Unix-style remote/cwd path argument that arrived looking like a Windows
# drive path -- and fail loudly with the actual fix, instead of silently
# sending a corrupted path to the relay and getting a confusing
# MD5_MISMATCH or remote shell error with no clue why.


def _reject_if_msys_mangled(label, value):
    if is_msys_mangled_path(value):
        print('[remote_exec] %s looks like a Windows path (%r) where a Unix '
              'path on the Linux server was expected.' % (label, value))
        print('[remote_exec] This is almost always Git Bash/MSYS silently rewriting a')
        print('[remote_exec] /home/... argument before Python ever saw it. Re-run with:')
        print('[remote_exec]   MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL=\'*\' python tools/remote/remote_exec.py ...')
        sys.exit(2)


def read_relay_info(vchost, vchop):
    p = info_path(vchost, vchop)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def send_request(host, port, req, timeout=1800):
    with socket.create_connection((host, port), timeout=min(timeout, 30)) as sock:
        sock.sendall((json.dumps(req) + '\n').encode('utf-8'))
        sock.settimeout(timeout)
        data = b''
        while not data.endswith(b'\n'):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode('utf-8'))


def format_result(remote_host, response):
    exit_code = response.get('exit_code')
    status = 'PASS' if response.get('ok') and exit_code == 0 else 'FAIL'
    lines = ['REMOTE_HOST=%s' % remote_host, 'EXIT_CODE=%s' % exit_code, 'STATUS=%s' % status]
    # REAL BUG FIX (2026-09-01, found live): remote_relay.py's handle_request()
    # returns a real 'error' string on put/get/status failures (e.g.
    # 'MD5_MISMATCH', 'BAD_TOKEN') -- this function used to silently drop it,
    # so a failed --put/--get printed only "STATUS=FAIL" with no indication
    # of why, forcing a separate manual send_request() call just to see the
    # real reason. 'run' ops don't set this field (their failure detail is
    # already in stdout via the remote command's own output), so this is a
    # pure addition, never duplicate/conflicting output for the common case.
    error = response.get('error')
    if error:
        lines.append('ERROR=%s' % error)
    body = response.get('stdout', '')
    if body:
        lines.append(body)
    return '\n'.join(lines)


def _down_block(vchop):
    return 'REMOTE_HOST=%s\nEXIT_CODE=\nSTATUS=DOWN' % vchop


def _print_reconnect_instructions(vchost, vchop):
    print('[remote_exec] relay is DOWN and cannot self-reauthenticate (no password')
    print('in this process). Ask the user to run, in their OWN terminal:')
    print('  VCUSER=... VCPW=... VCHOST=%s VCHOP=%s VCWORKDIR=... \\' % (vchost, vchop))
    print('    python tools/remote/remote_relay.py --start')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', nargs='?')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--reconnect', action='store_true')
    ap.add_argument('--put', nargs=2, metavar=('LOCAL', 'REMOTE'))
    ap.add_argument('--get', nargs=2, metavar=('REMOTE', 'LOCAL'))
    ap.add_argument('--timeout', type=int, default=1800)
    ap.add_argument('--cwd', default=None,
        help='Run cmd in a subshell cd\'d to this dir; does not affect the '
             'relay\'s persistent shell cwd for later/other callers. '
             'Defaults to the DVWORKDIR env var if set and --cwd is omitted.')
    a = ap.parse_args()

    if a.put:
        _reject_if_msys_mangled('--put REMOTE', a.put[1])
    if a.get:
        _reject_if_msys_mangled('--get REMOTE', a.get[0])
    _reject_if_msys_mangled('--cwd', a.cwd)
    _reject_if_msys_mangled('DVWORKDIR', os.environ.get('DVWORKDIR', ''))

    vchost = os.environ.get('VCHOST', '')
    vchop = os.environ.get('VCHOP', '')
    if not vchost or not vchop:
        print('[remote_exec] missing VCHOST/VCHOP env vars (set the same values used to start remote_relay.py)')
        return 2

    info = read_relay_info(vchost, vchop)
    if info is None:
        print(_down_block(vchop))
        _print_reconnect_instructions(vchost, vchop)
        return 1

    host, port, token = info['host'], info['port'], info['token']

    if a.reconnect:
        req = {'token': token, 'op': 'reconnect_hop'}
    elif a.status:
        req = {'token': token, 'op': 'status'}
    elif a.put:
        req = {'token': token, 'op': 'put', 'local': a.put[0], 'remote': a.put[1]}
    elif a.get:
        req = {'token': token, 'op': 'get', 'remote': a.get[0], 'local': a.get[1]}
    elif a.cmd:
        req = {'token': token, 'op': 'run', 'cmd': a.cmd, 'timeout': a.timeout}
        cwd = a.cwd or os.environ.get('DVWORKDIR', '')
        if cwd:
            req['cwd'] = cwd
    else:
        print(__doc__)
        return 2

    try:
        resp = send_request(host, port, req, timeout=a.timeout)
    except (ConnectionRefusedError, OSError, socket.timeout):
        print(_down_block(vchop))
        _print_reconnect_instructions(vchost, vchop)
        return 1

    if a.status:
        status = 'READY' if resp.get('ok') else 'DOWN'
        print('REMOTE_HOST=%s\nSTATUS=%s\npid=%s started=%s' % (
            vchop, status, info.get('pid'), info.get('started')))
        return 0 if status == 'READY' else 1

    print(format_result(vchop, resp))
    return 0 if resp.get('ok') and resp.get('exit_code') == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
