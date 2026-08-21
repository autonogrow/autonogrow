from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the isolated Chromium Playwright journeys.")
    parser.add_argument("--headed", action="store_true", help="Show the Chromium window.")
    parser.add_argument("--debug", action="store_true", help="Open the Playwright inspector.")
    options, pytest_args = parser.parse_known_args(argv)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]

    command = [sys.executable, "-m", "pytest", "e2e", "--browser", "chromium"]
    if options.headed or options.debug:
        command.append("--headed")
    command.extend(pytest_args)

    environment = os.environ.copy()
    if options.debug:
        environment["PWDEBUG"] = "1"
    return subprocess.call(command, cwd=ROOT, env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
