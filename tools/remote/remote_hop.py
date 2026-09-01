# -*- coding: utf-8 -*-
"""telnet <VCHOST> -> ssh <VCHOP> -> (optional) cd into a work dir -> run commands.

Adapted from D:\\DV\\Task\\USB\\sim\\scripts\\hop.py (a working, previously-proven
telnet+ssh automation tool for this same site's vc-pool/icr-server topology).
That original hardcodes one person's account and machine names (vchost-a/host-d/
devuser) as constants -- fine for a single-project repo only that one person
uses, wrong for a file living next to DV Agent Harness L5, which gets zipped
up and handed to other DE/DV engineers. Every identifying value here comes
from an environment variable instead, so this file itself carries no one's
personal account/target-machine information -- only whoever runs it, with
their own env vars set, is identified, and never in this file's own text.

Nothing installed, no TTY needed: a Unix login over telnet is line-oriented,
so a socket plus minimal IAC handling is enough. telnetlib was removed in
Python 3.13, hence the hand-rolled negotiation (same rationale as the
original hop.py).

The remote login shell is assumed tcsh (matches this site's vc-pool/icr
servers); a POSIX command should be wrapped in `sh -c '...'`.

THE PASSWORD COMES FROM AN ENVIRONMENT VARIABLE (VCPW) -- never written to
disk, never echoed, never a script argument (arguments can end up in shell
history / process listings; an env var set in the SAME interactive shell
that runs this script does not, unless that shell's own history logs env
assignments -- use `unset VCPW` after use if that is a concern on your site).
This file must never be run from inside a Claude Code (or any AI agent)
tool call with the password embedded in the invocation -- run it from your
own interactive terminal only.

Required environment variables:
  VCUSER      the account to log in as (both hops, same account assumed)
  VCPW        the password (used for the telnet hop only; the ssh hop uses
              -o BatchMode=yes and will simply fail if it would need a
              password -- set up key-based auth for the ssh hop separately
              if it is not already trusted from VCHOST)
  VCHOST      the telnet target (e.g. vchost-b)
  VCHOP       the ssh target reached from inside VCHOST (e.g. host-b)
Optional:
  VCPORT      telnet port (default 23)
  VCWORKDIR   one `cd` target to run after the ssh hop, before any commands
              (e.g. /home/tmpacct/devuser/UVM/AI_Agent/USB/WORK). Omit to
              stay wherever the login shell starts.
  VCEDAENV    comma-separated, ORDERED list of EDA-tool environment setup
              files to `source` after the VCWORKDIR cd, before any --put/
              --get or trailing command (e.g. "version.csh,env.csh" or
              "/proj/tools/vcs_setup.csh,/proj/tools/verdi_setup.csh").
              Omit to skip -- nothing is sourced automatically by default,
              same as before this variable existed.

Usage:
  VCUSER=... VCPW=... VCHOST=vchost-b VCHOP=host-b VCWORKDIR=... \\
    python remote_hop.py "<cmd>" ["<cmd>" ...]
  VCUSER=... VCPW=... VCHOST=vchost-b VCHOP=host-b VCWORKDIR=... \\
    python remote_hop.py --put <local> <remote> ["<cmd>" ...]

From Git Bash on Windows, prefix with MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
or MSYS rewrites a bare /tmp/x argument into C:/Users/.../Temp/x before
python ever sees it.

For uploading a whole directory (e.g. the PACKAGE deliverable), do NOT
--put every file individually -- base64-over-telnet is ~400 bytes per round
trip. Instead, on this machine: `tar czf package.tgz -C <parent> PACKAGE`,
then `--put package.tgz <remote>/package.tgz`, then run
`tar xzf <remote>/package.tgz -C <remote-dir>` as one of the trailing
commands.
"""
import base64, hashlib, io, os, re, socket, sys, time

ANSI = re.compile('\x1b' + r'\[[0-9;?]*[ -/]*[@-~]')
USER = os.environ.get('VCUSER', '')
PW = os.environ.get('VCPW', '')
HOST = os.environ.get('VCHOST', '')
HOP = os.environ.get('VCHOP', '')
PORT = int(os.environ.get('VCPORT', '23'))
WORKDIR = os.environ.get('VCWORKDIR', '')
EDAENV = os.environ.get('VCEDAENV', '')
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


class Session:
    def __init__(self, host, port, timeout=30):
        self.s = socket.create_connection((host, port), timeout)
        self.s.settimeout(timeout)

    def _neg(self, data):
        out, i, keep = bytearray(), 0, bytearray()
        while i < len(data):
            c = data[i]
            if c == IAC and i + 1 < len(data):
                cmd = data[i + 1]
                if cmd in (DO, DONT) and i + 2 < len(data):
                    out += bytes([IAC, WONT, data[i + 2]]); i += 3; continue
                if cmd in (WILL, WONT) and i + 2 < len(data):
                    out += bytes([IAC, DONT, data[i + 2]]); i += 3; continue
                if cmd == SB:
                    j = data.find(bytes([IAC, SE]), i)
                    i = (j + 2) if j >= 0 else len(data); continue
                i += 2; continue
            keep.append(c); i += 1
        if out:
            self.s.sendall(bytes(out))
        return bytes(keep)

    def send(self, line):
        self.s.sendall((line + '\n').encode())

    def read_until(self, pattern, timeout, label):
        """Accumulate until `pattern` appears. ANSI is stripped first: the
        prompt is colourised and would otherwise never match."""
        rx, got, end = re.compile(pattern), '', time.time() + timeout
        while time.time() < end:
            self.s.settimeout(max(0.5, end - time.time()))
            try:
                chunk = self.s.recv(8192)
            except socket.timeout:
                continue
            if not chunk:
                break
            got += ANSI.sub('', self._neg(chunk).decode('utf-8', 'replace'))
            if rx.search(got):
                return got
        raise TimeoutError('no %r within %ss at %s\n--- saw ---\n%s'
                           % (pattern, timeout, label, got[-700:]))

    def put(self, local, remote, chunk=400):
        """Copy a file over the telnet session, base64 in small pieces.
        See module docstring: for a directory, tar it locally first."""
        data = io.open(local, 'rb').read()
        b64 = base64.b64encode(data).decode()
        want = hashlib.md5(data).hexdigest()
        tmp = '/tmp/.put.%d.b64' % (int(time.time()) % 100000)

        self.run('rm -f %s' % tmp, 30)
        for i in range(0, len(b64), chunk):
            self.send('echo %s >> %s' % (b64[i:i + chunk], tmp))
            time.sleep(0.015)
        # REAL BUG FIX (2026-09-02, found live -- 7/7 puts failed with
        # MD5_MISMATCH on a relay that had been up a while), ROUND 2: the
        # first fix here (a bare `echo <marker>` + read_until(marker,...))
        # was ITSELF still broken the same way as the [>$]\s*$ pattern it
        # replaced -- a telnet session in cooked mode echoes back the
        # literal characters of a SENT line as soon as they're typed,
        # independent of whether the shell has actually finished executing
        # anything queued before it. Since the sent command
        # ("echo <marker>") contains the marker text verbatim, read_until()
        # could match on that raw echo of the INPUT itself, before the
        # shell had even executed it -- let alone drained the 47+ preceding
        # chunk-writes. run()'s own marker trick avoids exactly this: it
        # sends 'echo <m>$status', whose raw echo does NOT satisfy the
        # search pattern (m + a DIGIT) because '$status' is not yet a
        # digit in the un-executed command text -- only the shell's real
        # output (after variable expansion) is. Reuse run() itself for the
        # flush step instead of hand-rolling a weaker version of the same
        # trick.
        flush_marker = 'PUTFLUSH%dZ' % (int(time.time() * 1000) % 1000000)
        self.run('echo %s' % flush_marker, 60)

        out, rc = self.run('base64 -d %s > %s && md5sum %s && rm -f %s'
                           % (tmp, remote, remote, tmp), 300)
        # Targeted extraction: require the hash to be immediately followed
        # by the exact remote path (md5sum's own output format), instead
        # of grabbing the first 32-hex-char run anywhere in `out` -- immune
        # to any unrelated hex-looking noise elsewhere in the buffer.
        got = re.search(r'([0-9a-f]{32})\s+\S*' + re.escape(os.path.basename(remote)), out)
        if not got:
            got = re.search(r'([0-9a-f]{32})', out)
        ok = bool(got) and got.group(1) == want
        print('[put] %s -> %s  %d bytes  md5 %s'
              % (local, remote, len(data), 'MATCH' if ok else 'MISMATCH'))
        if not ok:
            print('   expected ' + want)
            print('   got      ' + (got.group(1) if got else out[:200]))
        return ok

    def get(self, remote, local):
        """Pull a file back. base64 both ways, md5 both ways."""
        out, rc = self.run('base64 -w 400 %s' % remote, 300)
        want, _ = self.run('md5sum %s' % remote, 60)
        m = re.search(r'([0-9a-f]{32})', want)
        want = m.group(1) if m else ''
        b64 = ''.join(re.findall(r'^[A-Za-z0-9+/=]+$', out, re.M))
        try:
            data = base64.b64decode(b64)
        except Exception as e:
            print('[get] %s -> decode failed: %s' % (remote, e)); return False
        got = hashlib.md5(data).hexdigest()
        ok = (got == want)
        if ok:
            d = os.path.dirname(local)
            if d and not os.path.isdir(d):
                os.makedirs(d)
            io.open(local, 'wb').write(data)
        print('[get] %s -> %s  %d bytes  md5 %s'
              % (remote, local, len(data), 'MATCH' if ok else 'MISMATCH'))
        if not ok:
            print('   remote ' + want + '   decoded ' + got + '   NOT WRITTEN')
        return ok

    def run(self, cmd, timeout=1800):
        """One command, delimited by a marker so its output is unambiguous.

        1800s is a hard ceiling. NEVER run a long build/regression in the
        foreground through this -- launch with nohup ... & and poll with
        separate short invocations, or the transport dying mid-run takes
        the job with it.
        """
        m = 'Z%dZ' % (int(time.time() * 1000) % 1000000)
        self.send(cmd)
        self.send('echo %s$status' % m)
        txt = self.read_until(m + r'\d', timeout, cmd[:50])
        rc = int(re.search(m + r'(\d+)', txt).group(1))
        body = txt[:txt.rfind(m)]
        out = []
        for line in body.splitlines():
            t = line.rstrip()
            if not t:
                continue
            if t.endswith('echo %s$status' % m):
                continue
            if t.endswith('> ' + cmd) or t.strip() == cmd:
                continue
            if re.match(r'^\S+ /.*>\s*$', t):
                continue
            out.append(re.sub(r'^\S+ /\S* > ', '', t))
        return '\n'.join(out), rc


def _setup_reminder(missing):
    """A friendly, copy-pasteable reminder of what to set before running this
    script -- shown instead of (well, in front of) the full docstring so a
    first-time user (this one or anyone else who picks up this generic
    script later) sees the actionable part immediately, not a wall of text.
    Placeholders only; never fills in a real value seen this session."""
    lines = []
    lines.append('missing required env var(s): %s' % ', '.join(missing))
    lines.append('')
    lines.append('Set these in YOUR OWN terminal window first (never inside a Claude')
    lines.append('Code / AI-agent tool call -- see this file\'s module docstring for why):')
    lines.append('')
    lines.append('  Windows (cmd.exe):')
    lines.append('    set VCUSER=devuser')
    lines.append('    set VCPW=<your password>')
    lines.append('    set VCHOST=vcxxx')
    lines.append('    set VCHOP=icryyy')
    lines.append('    set VCWORKDIR=/path/to/your/working/dir   (optional)')
    lines.append('    set VCEDAENV=version.csh,env.csh          (optional, ordered, comma-separated)')
    lines.append('')
    lines.append('  PowerShell:')
    lines.append('    $env:VCUSER   = "devuser"')
    lines.append('    $env:VCPW     = "<your password>"')
    lines.append('    $env:VCHOST   = "vcxxx"')
    lines.append('    $env:VCHOP    = "icryyy"')
    lines.append('    $env:VCWORKDIR = "/path/to/your/working/dir"   # optional')
    lines.append('    $env:VCEDAENV  = "version.csh,env.csh"         # optional')
    lines.append('')
    lines.append('  Git Bash:')
    lines.append('    export VCUSER=devuser')
    lines.append('    export VCPW=\'<your password>\'')
    lines.append('    export VCHOST=vcxxx')
    lines.append('    export VCHOP=icryyy')
    lines.append('    export VCWORKDIR=/path/to/your/working/dir   # optional')
    lines.append('    export VCEDAENV=version.csh,env.csh          # optional')
    lines.append('')
    lines.append('VCUSER/VCHOST/VCHOP/VCWORKDIR replace vchost-b/host-b/devuser with YOUR own')
    lines.append('account and target machines -- this script has none of that baked in.')
    lines.append('Then re-run the same python remote_hop.py "<cmd>" [...] command.')
    return '\n'.join(lines)


def main():
    missing = [k for k in ('VCUSER', 'VCPW', 'VCHOST', 'VCHOP') if not os.environ.get(k)]
    if missing:
        print(_setup_reminder(missing))
        return 2
    if len(sys.argv) < 2:
        print(__doc__); return 2

    t = Session(HOST, PORT)
    t.read_until(r'login:', 30, '%s login' % HOST); t.send(USER)
    t.read_until(r'assword:', 20, '%s pw' % HOST);  t.send(PW)
    t.read_until(USER + '@' + HOST, 30, '%s shell' % HOST)
    print('[hop] %s ok' % HOST)

    t.send('ssh -o StrictHostKeyChecking=no -o LogLevel=ERROR ' + HOP)
    t.read_until(USER + '@' + HOP, 45, 'ssh ' + HOP)
    print('[hop] %s ok' % HOP)

    if WORKDIR:
        t.send('cd ' + WORKDIR)
        t.read_until(r'[>$]\s*$', 30, 'cd ' + WORKDIR)
        print('[hop] cwd = %s' % WORKDIR)

    if EDAENV:
        # Ordered EDA-tool environment setup files (e.g. version.csh,
        # env.csh, a vcs/verdi setup script) -- comma-separated, sourced in
        # the order given, BEFORE any --put/--get or trailing command, so
        # every command below already has the site's EDA toolchain on
        # PATH/license-server env set up. Optional: this whole block is a
        # no-op if VCEDAENV is unset, matching how this file worked before
        # this feature existed (per-invocation manual `source xxx.csh` in
        # the trailing command list, as REMOTE_LOGIN_GUIDE.md section 3.5
        # used to be the only documented way to do this).
        for _f in [x.strip() for x in EDAENV.split(',') if x.strip()]:
            t.send('source ' + _f)
            t.read_until(r'[>$]\s*$', 60, 'source ' + _f)
            print('[hop] sourced %s' % _f)

    args = sys.argv[1:]
    while args and args[0] in ('--put', '--get'):
        fn = t.put if args[0] == '--put' else t.get
        if not fn(args[1], args[2]):
            return 1
        args = args[3:]

    rc = 0
    for c in args:
        print('\n' + '=' * 74 + '\n$ ' + c + '\n' + '=' * 74)
        try:
            out, rc = t.run(c)
        except TimeoutError as e:
            print('[hop] TIMEOUT\n%s' % e); return 124
        print(out if out.strip() else '(no output)')
        print('[exit %d]' % rc)
    t.send('exit'); t.send('exit')
    return rc


if __name__ == '__main__':
    sys.exit(main())
