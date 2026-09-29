#!/usr/bin/env python3
import argparse,pathlib,sys,json,subprocess,os
ap=argparse.ArgumentParser(); ap.add_argument("--root",required=True); a=ap.parse_args(); root=pathlib.Path(a.root)
bad=[p.name for p in root.iterdir() if p.is_dir() and p.name.startswith("tests") and not (p/"__init__.py").exists()]
if bad: print(json.dumps({"status":"FAIL","reason":"TESTDIR_NOT_NAMESPACED","dirs":bad})); sys.exit(2)
env=os.environ.copy(); env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"; env["OAI_IS_JUPYTER_KERNEL"]="0"
# TIMEOUT WIDENED 25->90 (2026-09-03, harness-self-test-ci pass), then 90->300 (2026-09-07,
# fixing a real, disclosed flake: dv_harness_tests/test_engine_gates_and_routing.py's
# self-audit test genuinely started failing PYTEST_COLLECTION_TIMEOUT once this repo grew past
# ~13,000 real tests). Real measurement taken THIS session, on this machine, with no special
# isolation (i.e. under whatever ordinary concurrent load a dev/CI box actually has): a plain
# `python -m pytest --collect-only -q` at the repo root collected 13,610 tests in 150.88s. 90s
# was already below that real baseline, not merely low on headroom -- the prior 90s bump's own
# comment assumed a much smaller suite and was never revisited as the suite kept growing.
# Rather than hardcode a second number destined to go stale the same way, the timeout is now
# read from DV_HARNESS_COLLECTION_TIMEOUT_SEC (falls back to a default with real headroom over
# the measured baseline: ~2x 150.88s, rounded up) so a project whose own test tree is larger or
# smaller, or a slower/faster CI box, can override it without another code edit. Collection-time
# behavior itself is still unchanged -- only the fail threshold and how it is set.
_DEFAULT_TIMEOUT_SEC = 300
_timeout = int(os.environ.get("DV_HARNESS_COLLECTION_TIMEOUT_SEC", _DEFAULT_TIMEOUT_SEC))
try: r=subprocess.run([sys.executable,"-m","pytest","--collect-only","-q"],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=_timeout,env=env)
except subprocess.TimeoutExpired: print(json.dumps({"status":"FAIL","reason":"PYTEST_COLLECTION_TIMEOUT"})); sys.exit(3)
if r.returncode: print(json.dumps({"status":"FAIL","reason":"PYTEST_COLLECTION_FAILED","output":r.stdout[-1200:]})); sys.exit(4)
if "import file mismatch" in r.stdout.lower(): print(json.dumps({"status":"FAIL","reason":"PYTEST_IMPORT_FILE_MISMATCH"})); sys.exit(5)
print(json.dumps({"status":"PASS"}))
