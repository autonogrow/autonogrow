from __future__ import annotations

import json
from dataclasses import dataclass

from app.models import SocialContentProposal

TEMPLATE_VERSION = "owner_idea_es_v1"

FORMAT_LABELS = {
    "story": "Story",
    "reel": "Reel",
    "carousel": "Carrusel",
    "static_post": "Publicación",
}


@dataclass(frozen=True)
class IdeaPresentation:
    title: str
    explanation: str
    suggested_action: str
    suggested_formats: tuple[str, ...]
    human_reasons: tuple[str, ...]
    template_version: str = TEMPLATE_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "explanation": self.explanation,
            "suggested_action": self.suggested_action,
            "suggested_formats": list(self.suggested_formats),
            "human_reasons": list(self.human_reasons),
            "template_version": self.template_version,
        }


def _signal_types(proposal: SocialContentProposal) -> set[str]:
    return {link.signal.type for link in proposal.signal_links}


def _format_labels(proposal: SocialContentProposal) -> tuple[str, ...]:
    try:
        formats = json.loads(proposal.recommended_formats_json)
    except (TypeError, json.JSONDecodeError):
        formats = []
    return tuple(FORMAT_LABELS.get(item, str(item)) for item in formats)


def present_social_content_proposal(proposal: SocialContentProposal) -> IdeaPresentation:
    service = proposal.service.name if proposal.service else "tu negocio"
    signals = _signal_types(proposal)
    formats = _format_labels(proposal)

    if {"low_future_occupancy", "service_demand_drop"} <= signals:
        return IdeaPresentation(
            title=f"¿Damos más visibilidad a {service}?",
            explanation=(
                "Este servicio está teniendo menos reservas de lo habitual y tienes más "
                "disponibilidad durante los próximos días."
            ),
            suggested_action="Podría ser buen momento para recordárselo a tus clientes.",
            suggested_formats=formats,
            human_reasons=(
                "Este servicio tiene menos demanda de la habitual.",
                "Hay disponibilidad futura que podría aprovecharse.",
                "Es un servicio activo del negocio.",
            ),
        )
    if "low_future_occupancy" in signals:
        return IdeaPresentation(
            title="¿Comunicamos la disponibilidad de los próximos días?",
            explanation="Tienes más huecos disponibles de lo habitual en la próxima ventana.",
            suggested_action="Podemos dar visibilidad a la disponibilidad sin aplicar descuentos.",
            suggested_formats=formats,
            human_reasons=("La ocupación futura está por debajo de su referencia.",),
        )
    if "service_demand_drop" in signals:
        return IdeaPresentation(
            title=f"¿Recordamos a tus clientes el servicio de {service}?",
            explanation="Este servicio está recibiendo menos reservas que en periodos comparables.",
            suggested_action="Podemos explicar el servicio y darle más visibilidad.",
            suggested_formats=formats,
            human_reasons=("La demanda reciente está por debajo de su patrón observable.",),
        )
    if "high_due_customer_pool" in signals:
        return IdeaPresentation(
            title=f"¿Volvemos a poner {service} en mente de tus clientes?",
            explanation="Hay un grupo suficiente de clientes en su periodo habitual de retorno.",
            suggested_action="Podemos recordar el servicio de forma general, sin dirigirnos a personas concretas.",
            suggested_formats=formats,
            human_reasons=("Existe una oportunidad agregada de recurrencia.",),
        )
    if "low_return_rate" in signals:
        return IdeaPresentation(
            title="¿Ayudamos a recuperar el ritmo de retorno?",
            explanation="Está regresando una proporción menor de clientes recurrentes.",
            suggested_action="Podemos reforzar el recuerdo de los servicios del negocio.",
            suggested_formats=formats,
            human_reasons=("El retorno reciente es inferior a su referencia observable.",),
        )
    if "new_service" in signals or proposal.reason_code == "new_service":
        return IdeaPresentation(
            title=f"¿Presentamos tu nuevo servicio de {service}?",
            explanation="Lo has añadido recientemente y puede que tus clientes todavía no lo conozcan.",
            suggested_action="Podemos preparar una presentación clara del nuevo servicio.",
            suggested_formats=formats,
            human_reasons=("Es un servicio activo incorporado recientemente.",),
        )
    if "seasonal_window" in signals or proposal.source_event_id is not None:
        return IdeaPresentation(
            title="¿Preparamos una comunicación para la próxima fecha importante?",
            explanation="Se acerca un evento configurado por tu negocio dentro de su ventana de preparación.",
            suggested_action="Podemos decidir con tiempo si merece la pena comunicarlo.",
            suggested_formats=formats,
            human_reasons=("La fecha fue configurada por el negocio y está próxima.",),
        )
    if proposal.source_review_id is not None:
        return IdeaPresentation(
            title="¿Compartimos una experiencia positiva de tus clientes?",
            explanation="Tienes una reseña positiva reciente autorizada para uso social.",
            suggested_action="Podemos convertirla en prueba social sin exponer datos personales.",
            suggested_formats=formats,
            human_reasons=("Existe una reseña real, positiva y utilizable.",),
        )
    return IdeaPresentation(
        title=f"¿Explicamos algo útil sobre {service}?",
        explanation="No hay una necesidad urgente, pero una pieza informativa puede mantener tu presencia activa.",
        suggested_action="Podemos responder una pregunta frecuente de tus clientes.",
        suggested_formats=formats,
        human_reasons=("Es una sugerencia editorial de continuidad, no una urgencia comercial.",),
    )
