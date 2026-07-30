from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import get_settings, get_uploads_dir

_cache: tuple[float, dict[str, Any]] | None = None
_lock = Lock()


def _bounded_tree_size(path: Path, max_files: int) -> tuple[int, int, bool]:
    if not path.exists():
        return 0, 0, False
    size = 0
    count = 0
    truncated = False
    for root, directories, files in os.walk(path, followlinks=False):
        directories[:] = [name for name in directories if not (Path(root) / name).is_symlink()]
        for name in files:
            item = Path(root) / name
            if item.is_symlink():
                continue
            try:
                size += item.stat().st_size
            except OSError:
                continue
            count += 1
            if count >= max_files:
                truncated = True
                return size, count, truncated
    return size, count, truncated


def storage_health(*, force: bool = False) -> dict[str, Any]:
    global _cache
    settings = get_settings()
    now = time.monotonic()
    with _lock:
        if not force and _cache and now - _cache[0] < settings.storage_cache_seconds:
            return dict(_cache[1])
        uploads = get_uploads_dir()
        backup = Path(settings.backup_dir).resolve() if settings.backup_dir else None
        usage = shutil.disk_usage(uploads)
        uploads_size, uploads_files, uploads_truncated = _bounded_tree_size(
            uploads, settings.storage_scan_max_files
        )
        backup_size, backup_files, backup_truncated = (
            _bounded_tree_size(backup, settings.storage_scan_max_files) if backup else (0, 0, False)
        )
        partial_count = 0
        for directory in (uploads, backup):
            if not directory or not directory.exists():
                continue
            partial_count += sum(
                1
                for item in directory.glob("*.partial")
                if item.is_file() and not item.is_symlink()
            )
        result = {
            "total_bytes": usage.total,
            "free_bytes": usage.free,
            "free_percent": round((usage.free / usage.total) * 100, 2) if usage.total else 0.0,
            "used_percent": round((usage.used / usage.total) * 100, 2) if usage.total else 0.0,
            "uploads": {
                "size_bytes": uploads_size,
                "files_scanned": uploads_files,
                "scan_truncated": uploads_truncated,
            },
            "backups": {
                "size_bytes": backup_size,
                "files_scanned": backup_files,
                "scan_truncated": backup_truncated,
            },
            "stale_partial_files": partial_count,
        }
        _cache = (now, result)
        return dict(result)
