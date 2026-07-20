from typing import Any


def create_calendar_event_stub(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "skipped",
        "reason": "google_calendar_not_enabled_yet",
        "payload": payload,
    }
