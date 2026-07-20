import json
from pathlib import Path
from typing import Any


STORE_PATH = Path("data/conversations.json")


def _ensure_store_exists() -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not STORE_PATH.exists():
        STORE_PATH.write_text("{}", encoding="utf-8")


def _load_store() -> dict[str, Any]:
    _ensure_store_exists()

    # utf-8-sig handles files created by PowerShell with BOM.
    content = STORE_PATH.read_text(encoding="utf-8-sig").strip()

    if not content:
        return {}

    return json.loads(content)


def _save_store(data: dict[str, Any]) -> None:
    _ensure_store_exists()
    STORE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_conversation(phone: str) -> dict[str, Any]:
    data = _load_store()

    return data.get(phone, {
        "state": "idle",
        "data": {},
    })


def save_conversation(phone: str, conversation: dict[str, Any]) -> None:
    data = _load_store()
    data[phone] = conversation
    _save_store(data)


def reset_conversation(phone: str) -> None:
    data = _load_store()
    data[phone] = {
        "state": "idle",
        "data": {},
    }
    _save_store(data)
