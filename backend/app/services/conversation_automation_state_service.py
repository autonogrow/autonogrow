import math
from datetime import datetime, timedelta
from typing import Any

from app.models import Conversation, ConversationAutomationSettings

DEFAULT_HUMAN_REPLY_PAUSE_MINUTES = 60
ALLOWED_HUMAN_REPLY_PAUSE_MINUTES = {0, 15, 60, 240, -1}
ALLOWED_CONVERSATION_PAUSE_MINUTES = {15, 60, 240, -1}
MANUAL_PAUSE_MINUTES = -1


def _utcnow() -> datetime:
    return datetime.utcnow()


def automation_block_reason(
    conversation: Conversation,
    *,
    now: datetime | None = None,
) -> str | None:
    now = now or _utcnow()
    if conversation.automation_mode == "manual":
        return "conversation_manual_mode"
    if (
        conversation.automation_paused_until is not None
        and conversation.automation_paused_until > now
    ):
        return "conversation_automation_paused"
    if conversation.automation_paused_until is not None:
        conversation.automation_paused_until = None
        conversation.automation_pause_reason = None
        conversation.automation_pause_updated_at = now
        conversation.updated_at = now
    return None


def pause_conversation_automation(
    conversation: Conversation,
    *,
    duration_minutes: int,
    reason: str,
    updated_by: int | None = None,
    now: datetime | None = None,
) -> None:
    if duration_minutes not in ALLOWED_CONVERSATION_PAUSE_MINUTES:
        raise ValueError("Invalid conversation automation pause duration")
    now = now or _utcnow()
    conversation.automation_pause_reason = reason
    conversation.automation_pause_updated_by = updated_by
    conversation.automation_pause_updated_at = now
    conversation.updated_at = now
    if duration_minutes == MANUAL_PAUSE_MINUTES:
        conversation.automation_mode = "manual"
        conversation.automation_paused_until = None
        return
    conversation.automation_mode = "automatic"
    proposed_until = now + timedelta(minutes=duration_minutes)
    if (
        reason == "human_reply"
        and conversation.automation_paused_until is not None
        and conversation.automation_paused_until > proposed_until
    ):
        return
    conversation.automation_paused_until = proposed_until


def resume_conversation_automation(
    conversation: Conversation,
    *,
    updated_by: int | None = None,
    now: datetime | None = None,
) -> None:
    now = now or _utcnow()
    conversation.automation_mode = "automatic"
    conversation.automation_paused_until = None
    conversation.automation_pause_reason = None
    conversation.automation_pause_updated_by = updated_by
    conversation.automation_pause_updated_at = now
    conversation.updated_at = now


def apply_human_reply_pause(
    conversation: Conversation,
    settings: ConversationAutomationSettings,
    *,
    updated_by: int | None = None,
    now: datetime | None = None,
) -> bool:
    duration = settings.human_reply_pause_minutes
    if duration not in ALLOWED_HUMAN_REPLY_PAUSE_MINUTES:
        duration = DEFAULT_HUMAN_REPLY_PAUSE_MINUTES
    if duration == 0:
        return False
    now = now or _utcnow()
    if conversation.automation_mode == "manual":
        conversation.automation_pause_updated_by = updated_by
        conversation.automation_pause_updated_at = now
        conversation.updated_at = now
        return True
    pause_conversation_automation(
        conversation,
        duration_minutes=duration,
        reason="human_reply",
        updated_by=updated_by,
        now=now,
    )
    return True


def serialize_conversation_automation_state(
    conversation: Conversation,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utcnow()
    block_reason = automation_block_reason(conversation, now=now)
    remaining_seconds = None
    if conversation.automation_paused_until is not None:
        remaining_seconds = max(
            0,
            math.ceil((conversation.automation_paused_until - now).total_seconds() / 60) * 60,
        )
    return {
        "mode": conversation.automation_mode,
        "paused_until": (
            f"{conversation.automation_paused_until.isoformat()}Z"
            if conversation.automation_paused_until
            else None
        ),
        "pause_reason": conversation.automation_pause_reason,
        "pause_updated_by": conversation.automation_pause_updated_by,
        "pause_updated_at": (
            f"{conversation.automation_pause_updated_at.isoformat()}Z"
            if conversation.automation_pause_updated_at
            else None
        ),
        "block_reason": block_reason,
        "remaining_seconds": remaining_seconds,
        "is_active": block_reason is None,
    }
