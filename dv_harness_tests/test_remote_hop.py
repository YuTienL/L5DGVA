"""Regression test for the real live bug found 2026-09-02: Session.put()'s
chunk-flush detection used a generic prompt pattern ([>$]\\s*$) that could
match as soon as the FIRST of many rapid-fire `echo ... >> tmp` commands
redrew a prompt -- long before the LAST of them had actually been
processed by the remote shell. This exercises Session.put() against a real
socket-backed fake server that deliberately echoes a prompt-looking line
after EVERY chunk (the exact condition that broke the old regex), proving
the marker-based flush fix (`tools/remote/remote_hop.py`) is immune to it.
"""
import base64
import hashlib
import re
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

from remote_hop import Session


class _FakeTcshServer(threading.Thread):
    """Enough of a real tcsh remote shell over a raw socket to exercise
    Session.put() against real recv() timing -- echoes a prompt-looking
    line after every single command, not just the last."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.files = {}
        self._stop = False

    def run(self):
        conn, _ = self.sock.accept()
        conn.settimeout(0.2)
        buf = b""
        while not self._stop:
            try:
                chunk = conn.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                try:
                    self._handle_line(conn, line.decode("utf-8", "replace"))
                except OSError:
                    return
        try:
            conn.close()
        except OSError:
            pass

    def _handle_line(self, conn, line):
        m = re.match(r"^echo (\S+)\$status$", line)
        if m:
            conn.sendall(("host> %s\n%s0\nhost>\n" % (line, m.group(1))).encode())
            return
        m = re.match(r"^echo (.*) >> (\S+)$", line)
        if m:
            payload, path = m.group(1), m.group(2)
            self.files.setdefault(path, []).append(payload)
            # Deliberately noisy: a real tcsh redraws its prompt after
            # EVERY command, which is exactly what broke the old generic
            # [>$]\s*$ flush regex (it could match after chunk 1 of 21).
            conn.sendall(("host> %s\nhost>\n" % line).encode())
            return
        m = re.match(r"^base64 -d (\S+) > (\S+) && md5sum (\S+) && rm -f (\S+)$", line)
        if m:
            tmp, remote = m.group(1), m.group(2)
            data = base64.b64decode("".join(self.files.get(tmp, [])))
            digest = hashlib.md5(data).hexdigest()
            self.files[remote] = data
            self.files.pop(tmp, None)
            conn.sendall(("host> %s\n%s  %s\nhost>\n" % (line, digest, remote)).encode())
            return
        m = re.match(r"^echo (\S+)$", line)
        if m:
            conn.sendall(("host> %s\n%s\nhost>\n" % (line, m.group(1))).encode())
            return
        conn.sendall(("host> %s\nhost>\n" % line).encode())

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass


def _connected_session(server):
    session = Session.__new__(Session)
    session.s = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    session.s.settimeout(5)
    return session


def test_put_survives_a_prompt_redrawn_after_every_chunk():
    server = _FakeTcshServer()
    server.start()
    try:
        session = _connected_session(server)
        payload = ("x" * 3000).encode()  # several 400-byte chunks
        import tempfile, os
        fd, local_path = tempfile.mkstemp()
        os.close(fd)
        try:
            with open(local_path, "wb") as f:
                f.write(payload)
            ok = session.put(local_path, "/remote/target.bin")
        finally:
            os.unlink(local_path)
        assert ok is True
        assert server.files["/remote/target.bin"] == payload
        assert hashlib.md5(server.files["/remote/target.bin"]).hexdigest() == hashlib.md5(payload).hexdigest()
    finally:
        server.stop()
        server.join(timeout=5)
