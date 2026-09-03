#!/usr/bin/env python3
import argparse,pathlib,sys,json,subprocess,os
ap=argparse.ArgumentParser(); ap.add_argument("--root",required=True); a=ap.parse_args(); root=pathlib.Path(a.root)
bad=[p.name for p in root.iterdir() if p.is_dir() and p.name.startswith("tests") and not (p/"__init__.py").exists()]
if bad: print(json.dumps({"status":"FAIL","reason":"TESTDIR_NOT_NAMESPACED","dirs":bad})); sys.exit(2)
env=os.environ.copy(); env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"; env["OAI_IS_JUPYTER_KERNEL"]="0"
# TIMEOUT WIDENED 25->90 (2026-09-03, harness-self-test-ci pass): flagged as a known,
# load-sensitive flake by the just-completed governance effort's finish report. 25s left little
# headroom under real observed conditions -- confirmed this session: this exact script alone took
# several seconds even on an idle machine, and the self-audit ROOT_SCAN path that invokes it
# (dv_harness/self_audit.py) runs it alongside CPU contention from concurrent CI/dev activity.
# Small, low-risk touch-up only -- collection-time behavior itself is unchanged, just the fail
# threshold.
try: r=subprocess.run([sys.executable,"-m","pytest","--collect-only","-q"],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90,env=env)
except subprocess.TimeoutExpired: print(json.dumps({"status":"FAIL","reason":"PYTEST_COLLECTION_TIMEOUT"})); sys.exit(3)
if r.returncode: print(json.dumps({"status":"FAIL","reason":"PYTEST_COLLECTION_FAILED","output":r.stdout[-1200:]})); sys.exit(4)
if "import file mismatch" in r.stdout.lower(): print(json.dumps({"status":"FAIL","reason":"PYTEST_IMPORT_FILE_MISMATCH"})); sys.exit(5)
print(json.dumps({"status":"PASS"}))
