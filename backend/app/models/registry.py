"""Explicit model registry used by application startup and Alembic.

Keep every model module in this tuple.  This avoids metadata depending on a
router or service having imported a model as a side effect.
"""

from __future__ import annotations

from importlib import import_module

MODEL_MODULES = (
    "app.models.audit_log",
    "app.models.automation_credit",
    "app.models.availability",
    "app.models.booking",
    "app.models.booking_attachment",
    "app.models.business",
    "app.models.business_channel_control",
    "app.models.business_channel_integration",
    "app.models.business_media",
    "app.models.business_onboarding",
    "app.models.business_user",
    "app.models.business_user_service",
    "app.models.channel_queue",
    "app.models.conversation",
    "app.models.customer",
    "app.models.google_integration",
    "app.models.instagram_oauth_attempt",
    "app.models.instagram_content",
    "app.models.instagram_publish_job",
    "app.models.whatsapp_embedded_signup_attempt",
    "app.models.message_outbox",
    "app.models.meta_integration_job",
    "app.models.operations",
    "app.models.review_request",
    "app.models.service",
    "app.models.sync_job",
    "app.models.system_incident",
    "app.models.user",
)


def register_models() -> None:
    for module_name in MODEL_MODULES:
        import_module(module_name)
