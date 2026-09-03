# -*- coding: utf-8 -*-
"""remote_relay.py -- persistent telnet+ssh relay to a Linux DV server.

RUN THIS FROM YOUR OWN INTERACTIVE TERMINAL. NEVER from inside a Claude
Code (or any AI agent) tool call -- same rule as remote_hop.py, for the
same reason (see remote_hop.py's own module docstring): a password
composed into a Claude-issued command's literal text can end up persisted
in Claude Code's own tool-approval history.

This script performs the telnet(VCHOST)->ssh(VCHOP)->cd(VCWORKDIR)->
source(VCEDAENV) handshake ONCE, using remote_hop.py's own Session class
unchanged, then keeps that authenticated session alive behind a
loopback-only TCP socket so remote_exec.py (the Claude-invoked client, in
the same directory) can issue many commands against it without ever
touching VCPW.

Required environment variables: same four as remote_hop.py --
VCUSER, VCPW, VCHOST, VCHOP.
Optional: VCPORT, VCWORKDIR, VCEDAENV (same meaning as remote_hop.py).

Usage:
  VCUSER=... VCPW=... VCHOST=vchost-b VCHOP=host-b VCWORKDIR=... VCEDAENV=... \\
    python remote_relay.py --start [--idle-timeout 86400] [--bind-port 0]

See docs/superpowers/specs/2026-08-30-persistent-remote-relay-design.md
(in the v50 project) for the full design this implements.
"""
import argparse, json, os, re, secrets, socket, sys, threading, time
from pathlib import Path

from remote_hop import Session, _setup_reminder

DEFAULT_IDLE_TIMEOUT = 86400  # 24h -- was 7200 (2h); a shared, multi-user relay dying from idle mid-session forces a full re-login/re-auth for everyone using it, not just the caller who happened to trigger the idle check.

# One relay = one real telnet+ssh session against one shared shell. Real
# incident (2026-09-02): multiple logical callers hitting the same relay
# concurrently raised a "commands cut in line" (指令互相插隊) concern.
# serve()'s accept loop is single-threaded and already processes one
# connection fully before the next, so byte-level interleaving of a single
# command's send/read cycle was never actually possible -- but that
# correctness property was true only by accident of serve()'s current shape,
# not enforced by RelayServer itself. DEFAULT_LISTEN_BACKLOG (was
# unconditionally 1) queues concurrent connection attempts at the OS level
# instead of refusing them outright when several callers arrive at once, and
# the lock added to RelayServer below makes "exactly one command executes
# against the shared session at a time" an invariant of the class, not of
# whatever loop happens to drive it.
DEFAULT_LISTEN_BACKLOG = 32

# Layer 2 (secondary defense only -- see module docstring's "Defense in
# depth" note): environment markers Claude Code is confirmed to set in
# its own and its subprocesses' environment. An env var is not a security
# primitive (it can be unset or spoofed), but catching the common case --
# an agent invoking this script directly, as actually happened once, see
# the 2026-08-31 incident this guard exists to catch -- is worth it as a
# defense-in-depth layer on top of Layer 1 (never put VCPW where a Claude
# Code process tree can inherit it) and Layer 3/4 below.
AI_AGENT_ENV_MARKERS = (
    'CLAUDECODE',
    'CLAUDE_CODE',
    'CLAUDE_CODE_ENTRYPOINT',
    'CLAUDE_CODE_SESSION_ID',
    'ANTHROPIC_API_KEY',
)

# Layer 4: this relay process holds VCPW (used once, at login) and the
# authenticated session it produced. No command sent through the "run" op
# may attempt to read credential-shaped environment state -- on either
# side of the connection. This is a narrow, targeted deny list for
# credential inspection specifically, not a general destructive-command
# policy (that stays a human/skill-level review responsibility, per the
# design spec's own Security Considerations section -- this list is not a
# substitute for that, it closes one specific hole: a command whose only
# purpose is to read back the very secret this trust boundary exists to
# protect).
_CREDENTIAL_INSPECTION_PATTERNS = (
    re.compile(r'(^|;|&&|\|)\s*env\s*($|;|&&|\|)'),
    re.compile(r'(^|;|&&|\|)\s*printenv(\s|$)'),
    re.compile(r'(^|;|&&|\|)\s*set\s*($|;|&&|\|)'),
    re.compile(r'(^|;|&&|\|)\s*export\s*($|;|&&|\|)'),
    re.compile(r'\$VCPW\b'),
    re.compile(r'\$\{VCPW\}'),
    re.compile(r'os\.environ'),
    re.compile(r'getenv\s*\(\s*[\'"]?VCPW'),
)


# 2026-09-03 amendment (see CLAUDE.md's "Remote Linux Execution" section,
# explicit user decision on this confirmed single-user machine): an explicit
# opt-in override lets the sanctioned local auto-reconnect flow (replay.ps1)
# bypass Layer 2 specifically. This does not weaken the check for any other
# invocation path -- only a caller that explicitly sets this exact variable
# is exempted, and only Layer 2; Layers 1/4 are completely unaffected.
AUTORECONNECT_OVERRIDE_VAR = 'DV_HARNESS_RELAY_AUTORECONNECT_OK'


def running_inside_ai_agent():
    if os.environ.get(AUTORECONNECT_OVERRIDE_VAR) == '1':
        return False
    return any(os.environ.get(marker) for marker in AI_AGENT_ENV_MARKERS)


def is_credential_inspection_command(cmd):
    return any(p.search(cmd) for p in _CREDENTIAL_INSPECTION_PATTERNS)


def info_dir():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~/.local/share')
    return Path(base) / 'dv_agent_harness' / 'relay'


def info_path(vchost, vchop):
    return info_dir() / ('%s-%s.json' % (vchost, vchop))


def bind_loopback(port, backlog=DEFAULT_LISTEN_BACKLOG):
    """Binds a TCP socket to 127.0.0.1 only. A non-loopback bind is a bug,
    not a configuration option -- enforced here, not just documented.
    backlog queues concurrent connection attempts (multiple users/processes
    hitting this relay around the same moment) instead of refusing them."""
    host = '127.0.0.1'
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    assert sock.getsockname()[0] == host, 'relay must never bind non-loopback'
    sock.listen(backlog)
    return sock


def is_msys_mangled_path(value):
    """True if `value` looks like a Windows drive path (C:/..., D:\\...)
    where a Unix path on the Linux server was expected -- the unambiguous
    signature of Git Bash/MSYS silently rewriting a bare /home/... argument
    before Python ever sees it in sys.argv or os.environ (real incident,
    2026-09-02: an entire string of --put MD5_MISMATCH failures turned out
    to be exactly this, nothing to do with the relay's transfer logic)."""
    return bool(value) and bool(re.match(r'^[A-Za-z]:[/\\]', value))


def _shell_quote_for_cd(path):
    """Single-quote a path for both bash and tcsh (the remote shell varies
    by server -- see CLAUDE.md's tcsh-vs-bash notes). Plain literal-string
    single-quote escaping works identically in both."""
    return "'" + path.replace("'", "'\\''") + "'"


class RelayServer:
    """Owns one authenticated Session and answers relay protocol requests.
    handle_request() is pure given a request dict -- no socket I/O -- so it
    is unit-testable with a fake/mock Session and without a real network."""

    def __init__(self, session, token, hop_cmd):
        self.session = session
        self.token = token
        self.hop_cmd = hop_cmd
        self.last_activity = time.time()
        # One relay drives one real shell -- two commands executed against
        # it at the same instant would interleave their sends/reads on the
        # same telnet stream. This lock makes "exactly one command runs
        # against self.session at a time" an invariant of RelayServer
        # itself, independent of whether serve() (or any future caller)
        # happens to be single-threaded.
        self._lock = threading.Lock()

    def handle_request(self, req):
        if not isinstance(req, dict) or req.get('token') != self.token:
            return {'ok': False, 'exit_code': None, 'stdout': '', 'error': 'BAD_TOKEN'}
        with self._lock:
            self.last_activity = time.time()
            op = req.get('op')
            try:
                if op == 'status':
                    out, rc = self.session.run('echo alive', 30)
                    return {'ok': True, 'exit_code': rc, 'stdout': out, 'error': ''}
                if op == 'run':
                    cmd = req.get('cmd', '')
                    if is_credential_inspection_command(cmd):
                        return {'ok': False, 'exit_code': None, 'stdout': '',
                                 'error': 'CREDENTIAL_INSPECTION_DENIED'}
                    # Optional cwd: composed as a subshell (parens) so a cd
                    # done for THIS request never leaks into the shared
                    # shell's persistent cwd for the NEXT caller's command --
                    # closes the exact state-leakage bug already hit live
                    # this session (a `module load` and a `cd` both
                    # persisted across unrelated later commands because the
                    # relay is one continuous shell, not a fresh one per
                    # call). Callers that need every command self-contained
                    # should pass cwd on every request rather than relying
                    # on a prior request's cd.
                    cwd = req.get('cwd')
                    if cwd:
                        if is_credential_inspection_command(cwd):
                            return {'ok': False, 'exit_code': None, 'stdout': '',
                                     'error': 'CREDENTIAL_INSPECTION_DENIED'}
                        cmd = '(cd %s && %s)' % (_shell_quote_for_cd(cwd), cmd)
                    timeout = req.get('timeout', 1800)
                    out, rc = self.session.run(cmd, timeout)
                    return {'ok': True, 'exit_code': rc, 'stdout': out, 'error': ''}
                if op == 'put':
                    ok = self.session.put(req['local'], req['remote'])
                    return {'ok': ok, 'exit_code': 0 if ok else 1, 'stdout': '',
                             'error': '' if ok else 'MD5_MISMATCH'}
                if op == 'get':
                    ok = self.session.get(req['remote'], req['local'])
                    return {'ok': ok, 'exit_code': 0 if ok else 1, 'stdout': '',
                             'error': '' if ok else 'MD5_MISMATCH'}
                if op == 'reconnect_hop':
                    self.session.send(self.hop_cmd)
                    self.session.read_until(r'[>$]\s*$', 45, 'reconnect_hop')
                    return {'ok': True, 'exit_code': 0, 'stdout': '', 'error': ''}
                return {'ok': False, 'exit_code': None, 'stdout': '', 'error': 'UNKNOWN_OP'}
            except Exception as e:
                return {'ok': False, 'exit_code': None, 'stdout': '', 'error': str(e)}

    def idle_seconds(self):
        return time.time() - self.last_activity


def should_idle_exit(server, idle_timeout):
    return server.idle_seconds() > idle_timeout


def _handle_one_connection(conn, server):
    conn.settimeout(1800)
    buf = b''
    while b'\n' not in buf:
        chunk = conn.recv(65536)
        if not chunk:
            return
        buf += chunk
    line, _, _rest = buf.partition(b'\n')
    try:
        req = json.loads(line.decode('utf-8'))
    except Exception:
        resp = {'ok': False, 'exit_code': None, 'stdout': '', 'error': 'BAD_REQUEST'}
    else:
        resp = server.handle_request(req)
    conn.sendall((json.dumps(resp) + '\n').encode('utf-8'))


def serve(server, sock, idle_timeout):
    sock.settimeout(5)
    while True:
        if should_idle_exit(server, idle_timeout):
            print('[remote_relay] idle timeout reached (%ss) -- closing remote session and exiting' % idle_timeout)
            server.session.send('exit')
            server.session.send('exit')
            return
        try:
            conn, _addr = sock.accept()
        except socket.timeout:
            continue
        try:
            _handle_one_connection(conn, server)
        finally:
            conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', action='store_true')
    ap.add_argument('--idle-timeout', type=int, default=DEFAULT_IDLE_TIMEOUT)
    ap.add_argument('--bind-port', type=int, default=0)
    a = ap.parse_args()

    if not a.start:
        print(__doc__)
        return 2

    if running_inside_ai_agent():
        print('SECURITY BLOCK: remote_relay.py may not be started from an '
              'AI-agent environment (detected one of: %s). Run this from '
              'your own interactive terminal instead.' % ', '.join(AI_AGENT_ENV_MARKERS),
              file=sys.stderr)
        return 126

    user = os.environ.get('VCUSER', '')
    pw = os.environ.get('VCPW', '')
    host = os.environ.get('VCHOST', '')
    hop = os.environ.get('VCHOP', '')
    port = int(os.environ.get('VCPORT', '23'))
    workdir = os.environ.get('VCWORKDIR', '')
    edaenv = os.environ.get('VCEDAENV', '')

    missing = [k for k, v in (('VCUSER', user), ('VCPW', pw), ('VCHOST', host), ('VCHOP', hop)) if not v]
    if missing:
        print(_setup_reminder(missing))
        return 2

    if is_msys_mangled_path(workdir):
        print('[relay] VCWORKDIR looks like a Windows path (%r) where a Unix path on '
              'the Linux server was expected -- if you are in Git Bash, re-run with '
              'MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL=\'*\' prefixed.' % workdir)
        return 2

    t = Session(host, port)
    t.read_until(r'login:', 30, '%s login' % host); t.send(user)
    t.read_until(r'assword:', 20, '%s pw' % host); t.send(pw)
    t.read_until(user + '@' + host, 30, '%s shell' % host)
    print('[relay] %s ok' % host)

    hop_cmd = 'ssh -o StrictHostKeyChecking=no -o LogLevel=ERROR -o BatchMode=yes ' + hop
    t.send(hop_cmd)
    t.read_until(user + '@' + hop, 45, 'ssh ' + hop)
    print('[relay] %s ok' % hop)

    if workdir:
        t.send('cd ' + workdir)
        t.read_until(r'[>$]\s*$', 30, 'cd ' + workdir)
        print('[relay] cwd = %s' % workdir)

    if edaenv:
        for f in [x.strip() for x in edaenv.split(',') if x.strip()]:
            t.send('source ' + f)
            t.read_until(r'[>$]\s*$', 60, 'source ' + f)
            print('[relay] sourced %s' % f)

    sock = bind_loopback(a.bind_port)
    bound_port = sock.getsockname()[1]
    token = secrets.token_hex(32)

    info_dir().mkdir(parents=True, exist_ok=True)
    ipath = info_path(host, hop)
    ipath.write_text(json.dumps({
        'host': '127.0.0.1',
        'port': bound_port,
        'token': token,
        'pid': os.getpid(),
        'started': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }), encoding='utf-8')
    print('[relay] listening on 127.0.0.1:%d, info file: %s' % (bound_port, ipath))
    print('[relay] idle-timeout: %ss' % a.idle_timeout)

    server = RelayServer(t, token, hop_cmd)
    try:
        serve(server, sock, a.idle_timeout)
    finally:
        try:
            ipath.unlink()
        except OSError:
            pass
        sock.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
