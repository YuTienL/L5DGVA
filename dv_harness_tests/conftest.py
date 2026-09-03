"""Suite-wide safety pin for the DEGRADED-mode resource probe (2026-09-04).

`degradation.transport` defaults to "auto", and on a real developer machine
"auto" can genuinely resolve to a LIVE transport -- this project's own PC-side
session has a READY persistent relay to the real Linux DV server, so an
unpinned test suite would start issuing real `lmutil lmstat` / `bqueues` round
trips to production infrastructure from `DVHarness.__init__` onward.

That would violate the rule dv_harness/preflight.py's module docstring already
states for itself ("this module itself never talks to a live license/scheduler
server in a test") and would make test outcomes depend on the real farm's
current state. Pinning the documented override to "off" for the whole suite
keeps every DVHarness constructed by a test transport-less by default.

Tests that need a transport still get one exactly as before, and are unaffected
by this: they assign their own pure-mock Runner to `h.degradation_runner` (or
pass `runner=` to degradation.evaluate/probe_resources), which arms the probe at
call time regardless of this setting. Tests of the RESOLVER itself
(test_harness_reliability.py's TestDegradationTransportResolution) inject an
explicit `env=` dict and never read os.environ, so they are unaffected too.

Set at conftest IMPORT time, not only from a fixture: pytest imports conftest.py
before it collects anything, and a module-level `DVHarness(...)` in some test
module would otherwise be constructed before any fixture could run. The
session-scoped autouse fixture below only restores the caller's original value
afterwards.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Same explicit repo-root insertion every test module in this directory already
# does -- pytest's prepend import mode puts dv_harness_tests/ on sys.path, not
# the repo root that `import dv_harness` needs.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness.degradation import ENV_TRANSPORT_OVERRIDE  # noqa: E402

_PREVIOUS_TRANSPORT = os.environ.get(ENV_TRANSPORT_OVERRIDE)
os.environ[ENV_TRANSPORT_OVERRIDE] = "off"


@pytest.fixture(autouse=True, scope="session")
def _no_live_resource_probe_in_tests():
    yield
    if _PREVIOUS_TRANSPORT is None:
        os.environ.pop(ENV_TRANSPORT_OVERRIDE, None)
    else:
        os.environ[ENV_TRANSPORT_OVERRIDE] = _PREVIOUS_TRANSPORT
