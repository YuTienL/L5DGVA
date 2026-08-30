#!/usr/bin/env python3
import os,subprocess,sys
env=os.environ.copy(); env["OAI_IS_JUPYTER_KERNEL"]="0"; env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"
raise SystemExit(subprocess.call([sys.executable,"-m","pytest","-q",*sys.argv[1:]],env=env))
