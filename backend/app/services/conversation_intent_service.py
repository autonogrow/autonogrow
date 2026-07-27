import re
import unicodedata
from dataclasses import asdict, dataclass


INTENT_PATTERNS = {
    "booking_intent": (
        "cita",
        "reservar",
        "reserva",
        "hueco",
        "teneis hueco",
        "hay hueco",
        "hay que pedir cita",
        "puedo pedir cita",
        "quiero pedir cita",
        "quiero una cita",
        "me das hora",
        "me puedes dar hora",
        "cuando podeis",
        "disponibilidad",
        "agenda",
        "turno",
        "puedo ir mañana",
        "puedo pasar mañana",
    ),
    "price_intent": (
        "precio",
        "precios",
        "tarifa",
        "tarifas",
        "cuanto cuesta",
        "cuanto vale",
        "que vale",
        "coste",
    ),
    "service_intent": (
        "servicios",
        "que haceis",
        "que servicios",
        "manicura",
        "pedicura",
        "uñas",
        "tratamiento",
        "corte",
        "barba",
        "diseño",
    ),
    "location_intent": (
        "donde estais",
        "ubicacion",
        "direccion",
        "local",
        "como llegar",
    ),
    "hours_intent": (
        "horario",
        "horarios",
        "a que hora abris",
        "cuando abris",
        "cuando cerrais",
        "esta abierto",
    ),
    "human_intent": (
        "hablar con alguien",
        "persona",
        "humano",
        "llamame",
        "me llamas",
        "telefono",
    ),
    "complaint_intent": (
        "queja",
        "reclamacion",
        "problema",
        "mal servicio",
        "me habeis cobrado mal",
        "no estoy contenta",
        "no me gusto",
        "me hicisteis mal",
    ),
    "cancel_reschedule_intent": (
        "cancelar",
        "cancelo",
        "anular",
        "cambiar cita",
        "modificar cita",
        "reagendar",
        "no puedo ir",
        "llego tarde",
    ),
    "welcome_intent": (
        "hola",
        "buenas",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
    ),
}

INTENT_TEMPLATE_NAMES = {
    "welcome_intent": "Mensaje de bienvenida",
    "booking_intent": "Enviar enlace de reserva",
    "price_intent": "Enviar servicios",
    "service_intent": "Enviar servicios",
    "location_intent": "Enviar ubicación",
    "hours_intent": "Mensaje de bienvenida",
    "complaint_intent": "Respuesta segura a queja",
    "human_intent": "Derivación a atención humana",
    "cancel_reschedule_intent": "Acuse de cambio o cancelación",
    "unknown": "Respuesta segura sin intención",
}

SAFE_AUTO_INTENTS = {
    "welcome_intent",
    "booking_intent",
    "price_intent",
    "service_intent",
    "location_intent",
    "hours_intent",
    "complaint_intent",
    "human_intent",
    "cancel_reschedule_intent",
    "unknown",
}

SENSITIVE_INTENTS = (
    "complaint_intent",
    "cancel_reschedule_intent",
    "human_intent",
)

INTENT_PRIORITY = (
    *SENSITIVE_INTENTS,
    "booking_intent",
    "price_intent",
    "location_intent",
    "hours_intent",
    "service_intent",
    "welcome_intent",
)

AVAILABLE_INTENTS = (*INTENT_PRIORITY, "unknown")

INTENT_LABELS = {
    "welcome_intent": "Bienvenida",
    "booking_intent": "Reserva",
    "price_intent": "Precio",
    "service_intent": "Servicios",
    "location_intent": "Ubicación",
    "hours_intent": "Horario",
    "human_intent": "Atención humana",
    "complaint_intent": "Queja",
    "cancel_reschedule_intent": "Cancelar o cambiar cita",
    "unknown": "Desconocida",
}


@dataclass(frozen=True)
class IntentDetection:
    intent: str
    confidence: int
    matched_patterns: list[str]
    recommended_template_key: str | None
    safe_for_auto: bool

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    safe_text = re.sub(r"[^a-z0-9\s]", " ", without_accents)
    return re.sub(r"\s+", " ", safe_text).strip()


def _contains_pattern(normalized_text: str, pattern: str) -> bool:
    return re.search(rf"(?:^|\s){re.escape(pattern)}(?:$|\s)", normalized_text) is not None


def _confidence(matches: list[str]) -> int:
    longest_pattern_words = max(len(pattern.split()) for pattern in matches)
    return min(99, 78 + (longest_pattern_words * 7) + ((len(matches) - 1) * 3))


def detect_intent(value: str) -> IntentDetection:
    normalized = normalize_text(value)
    matches_by_intent: dict[str, list[str]] = {}
    for intent, patterns in INTENT_PATTERNS.items():
        normalized_patterns = tuple(dict.fromkeys(normalize_text(item) for item in patterns))
        matches = [
            pattern
            for pattern in normalized_patterns
            if pattern and _contains_pattern(normalized, pattern)
        ]
        if matches:
            matches_by_intent[intent] = matches

    if not matches_by_intent:
        return IntentDetection(
            intent="unknown",
            confidence=0,
            matched_patterns=[],
            recommended_template_key=INTENT_TEMPLATE_NAMES["unknown"],
            safe_for_auto=True,
        )

    sensitive_match = next(
        (intent for intent in SENSITIVE_INTENTS if intent in matches_by_intent),
        None,
    )
    if sensitive_match:
        selected_intent = sensitive_match
    else:
        selected_intent = max(
            matches_by_intent,
            key=lambda intent: (
                _confidence(matches_by_intent[intent]),
                -INTENT_PRIORITY.index(intent),
            ),
        )
    matches = matches_by_intent[selected_intent]
    return IntentDetection(
        intent=selected_intent,
        confidence=_confidence(matches),
        matched_patterns=matches,
        recommended_template_key=INTENT_TEMPLATE_NAMES.get(selected_intent),
        safe_for_auto=selected_intent in SAFE_AUTO_INTENTS,
    )
