from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,120}\Z")
FORBIDDEN_NAMES = {".env", "secrets", "keyring", "passwords", "credentials"}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_set_id(value: str | None = None) -> str:
    candidate = value or f"{utc_stamp()}-{secrets.token_hex(4)}"
    if not SAFE_ID.fullmatch(candidate):
        raise ValueError("Invalid backup set identifier")
    return candidate


def safe_output_directory(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path == Path(path.anchor) or path.is_symlink():
        raise ValueError("Unsafe backup output directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def safe_artifact_name(environment: str, release: str, kind: str, suffix: str) -> str:
    clean_environment = environment if SAFE_ID.fullmatch(environment) else "unknown"
    clean_release = release if SAFE_ID.fullmatch(release) else "unknown"
    return f"autonogrow-{clean_environment}-{clean_release}-{utc_stamp()}-{kind}.{suffix}"


def manifest_for(
    *,
    artifact: Path,
    kind: str,
    environment: str,
    release: str,
    set_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "backup_set_id": set_id,
        "backup_type": kind,
        "environment": environment,
        "release_id": release,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact_name": artifact.name,
        "size_bytes": artifact.stat().st_size,
        "sha256": sha256_file(artifact),
        "status": "valid",
        **(extra or {}),
    }


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported manifest")
    return data
