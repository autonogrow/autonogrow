from __future__ import annotations

from urllib.parse import urlencode

from itsdangerous import BadSignature, URLSafeSerializer

from app.core.config import get_settings
from app.models import Business, CustomerOpportunity, OpportunityAction

BOOKING_ATTRIBUTION_SALT = "autonogrow-opportunity-booking-v1"


def _serializer() -> URLSafeSerializer:
    secret = get_settings().session_secret
    if not secret:
        raise RuntimeError("SESSION_SECRET no está configurado")
    return URLSafeSerializer(secret, salt=BOOKING_ATTRIBUTION_SALT)


def create_attribution_token(action: OpportunityAction) -> str:
    if action.id is None:
        raise ValueError("Opportunity action must be persisted before creating a link")
    return _serializer().dumps(
        {"action_id": action.id, "business_id": action.business_id}
    )


def read_attribution_token(token: str) -> tuple[int, int] | None:
    try:
        payload = _serializer().loads(token)
        return int(payload["action_id"]), int(payload["business_id"])
    except (BadSignature, KeyError, TypeError, ValueError, RuntimeError):
        return None


def booking_url(business: Business, action: OpportunityAction) -> str:
    origins = get_settings().frontend_origin_list
    base = f"{origins[0].rstrip('/')}/autonogrow-landing/" if origins else "/autonogrow-landing/"
    params = {"b": business.slug, "oa": create_attribution_token(action)}
    if action.opportunity.source_service_id is not None:
        params["service_id"] = str(action.opportunity.source_service_id)
    return f"{base}?{urlencode(params)}"


def _service_name(opportunity: CustomerOpportunity) -> str:
    if opportunity.source_service is not None:
        return opportunity.source_service.name
    if opportunity.source_booking is not None:
        return opportunity.source_booking.service_name
    return "el servicio"


class OpportunityMessageTemplateService:
    """Deterministic V1 templates kept outside routers for future business overrides."""

    def render(
        self,
        *,
        business: Business,
        opportunity: CustomerOpportunity,
        action: OpportunityAction,
    ) -> str:
        name = (opportunity.customer.name or "").strip() or ""
        greeting = f"Hola {name}," if name else "Hola,"
        service = _service_name(opportunity)
        if opportunity.type == "service_due":
            days = opportunity.follow_up_interval_days_snapshot
            period = f"{days} días" if days else "un tiempo"
            text = (
                f"{greeting} hace aproximadamente {period} desde tu último servicio de "
                f"{service}. Si quieres volver a reservar, podemos ayudarte a encontrar un hueco."
            )
        elif opportunity.type == "cancelled_not_rebooked":
            text = (
                f"{greeting} vimos que tu última cita quedó cancelada. Si quieres, podemos "
                "ayudarte a encontrar una nueva fecha."
            )
        elif opportunity.type == "no_show_not_rebooked":
            text = (
                f"{greeting} si quieres retomar tu cita, podemos ayudarte a buscar una nueva fecha."
            )
        elif opportunity.type == "lead_not_converted":
            context = service if service != "el servicio" else "una reserva"
            text = (
                f"{greeting} hace poco nos preguntaste por {context}. Si sigues interesado, "
                "podemos ayudarte con disponibilidad o reserva."
            )
        else:
            context = (opportunity.reason_text or "").strip()
            if len(context) > 240:
                context = f"{context[:237].rstrip()}..."
            text = (
                f"{greeting} retomamos el seguimiento que quedó pendiente."
                + (f" {context}" if context else "")
                + " Si quieres, podemos ayudarte con el siguiente paso."
            )
        return f"{text}\n\nSi quieres reservar, puedes hacerlo aquí: {booking_url(business, action)}"
