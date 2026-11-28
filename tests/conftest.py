"""Test isolation: never touch the real settings/autostart locations.

`pulse_monitor` computes CONFIG_DIR at import time, so the redirect must happen
before any test module imports it. pytest loads conftest.py first.
"""

import os
import tempfile

_TEST_HOME = tempfile.mkdtemp(prefix="pulse-test-config-")
os.environ["XDG_CONFIG_HOME"] = _TEST_HOME
os.environ["APPDATA"] = _TEST_HOME

# Widget tests run on Qt's offscreen platform so window-manager timing can
# never make the geometry assertions flaky. The real X11 behaviour is covered
# separately by the manual/interactive checks described in tests/README.md.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
