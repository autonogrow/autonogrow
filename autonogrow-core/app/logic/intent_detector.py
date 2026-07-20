def detect_intent(text: str) -> str:
    normalized = text.lower().strip()

    if any(word in normalized for word in ["cancelar", "anular", "salir", "reset"]):
        return "cancel"

    if any(word in normalized for word in ["cita", "reservar", "reserva", "hueco"]):
        return "appointment_request"

    if any(word in normalized for word in ["precio", "precios", "tarifa", "cuanto"]):
        return "pricing_request"

    if any(word in normalized for word in ["resena", "reseña", "review", "opinion"]):
        return "review_request"

    if any(word in normalized for word in ["hola", "buenas", "buenos dias", "buenas tardes"]):
        return "greeting"

    return "unknown"
