import os
import subprocess
import sys


def test_non_loopback_refused():
    proc = subprocess.run(
        [sys.executable, "-m", "valscanner.web.server",
         "--host", "0.0.0.0", "--db", "/tmp/x.db"],
        capture_output=True,
        text=True,
        timeout=5,
        env=os.environ.copy(),
    )
    assert proc.returncode == 2
    assert "refusing to bind" in proc.stderr.lower()
