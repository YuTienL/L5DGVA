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
  python tools/remote/remote_exec.py --reconnect
  python tools/remote/remote_exec.py --put local_file remote_file
  python tools/remote/remote_exec.py --get remote_file local_file

Requires VCHOST/VCHOP env vars (to locate the same relay info file
remote_relay.py wrote) -- but never VCPW.

See docs/superpowers/specs/2026-08-30-persistent-remote-relay-design.md
(in the v50 project) for the full design.
"""
import argparse, json, os, socket, sys

from remote_relay import info_path


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
    a = ap.parse_args()

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
