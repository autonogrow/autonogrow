from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_e2e_server_refuses_to_install_auth_mock_outside_test() -> None:
    environment = os.environ.copy()
    environment["APP_ENV"] = "production"
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(ROOT / "backend")))

    result = subprocess.run(
        [sys.executable, "-c", "import e2e.server"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "The E2E Google mock can only run with APP_ENV=test" in result.stderr
