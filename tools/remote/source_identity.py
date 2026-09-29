# -*- coding: utf-8 -*-
"""source_identity.py -- git-free source-identity verification: md5sum
three-way diff + a single aggregate SOURCE_ID token, standing in for a git
commit SHA when no git remote exists between PC and the Linux workdir.

See docs/superpowers/specs/2026-08-30-persistent-remote-relay-design.md
(in the v50 project), section 4.
"""
import hashlib


def parse_md5sum_output(text):
    """Parse `md5sum <files>` output ("<hex>  <path>" per line, GNU
    coreutils format -- two spaces, or one space + '*' for binary mode)
    into {path: hex_md5}. Blank lines are skipped."""
    out = {}
    for line in text.splitlines():
        line = line.rstrip('\n')
        if not line.strip():
            continue
        digest, _, path = line.partition(' ')
        path = path.lstrip('* ')
        if len(digest) != 32 or not path:
            continue
        out[path] = digest
    return out


def three_way_diff(local, remote):
    """local/remote: {path: md5}. Returns local_only/remote_only/different
    path lists, each sorted for deterministic output."""
    local_only = sorted(p for p in local if p not in remote)
    remote_only = sorted(p for p in remote if p not in local)
    different = sorted(p for p in local if p in remote and local[p] != remote[p])
    return {'local_only': local_only, 'remote_only': remote_only, 'different': different}


def aggregate_source_id(manifest):
    """Collapse a {path: md5} manifest into one sha256 token: sorted
    "path:md5" lines, newline-joined, hashed. Deterministic regardless of
    dict insertion order."""
    lines = sorted('%s:%s' % (path, md5) for path, md5 in manifest.items())
    return hashlib.sha256('\n'.join(lines).encode('utf-8')).hexdigest()


def compute_source_identity(local_manifest, remote_manifest):
    """Full verdict: diff + both aggregate ids + a single match bool.
    match is True iff the three-way diff is empty (ids agreeing is implied
    by that, but computed independently, never derived from match itself,
    so a bug in one code path can't silently mask a bug in the other)."""
    diff = three_way_diff(local_manifest, remote_manifest)
    local_id = aggregate_source_id(local_manifest)
    remote_id = aggregate_source_id(remote_manifest)
    clean = not (diff['local_only'] or diff['remote_only'] or diff['different'])
    return {
        'match': clean and local_id == remote_id,
        'local_id': local_id,
        'remote_id': remote_id,
        'diff': diff,
    }
