"""Generate non-secret release metadata. Prints a dry-run unless --write is supplied."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def metadata(release_id: str | None = None) -> dict[str, str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    commit = result.stdout.strip() if result.returncode == 0 else "unknown"
    build_time = datetime.now(timezone.utc).isoformat()
    return {
        "release_id": release_id or f"local-{build_time[:19].replace(':', '').replace('-', '')}",
        "git_commit": commit,
        "build_time": build_time,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id")
    parser.add_argument("--output", type=Path, default=ROOT / "release.json")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    payload = metadata(args.release_id)
    if args.write:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".partial")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
        print(f"Wrote {args.output.name}")
    else:
        print(json.dumps({**payload, "dry_run": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
