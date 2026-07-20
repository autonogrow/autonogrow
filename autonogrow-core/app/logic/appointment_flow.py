from app.storage.conversation_store import (
    get_conversation,
    save_conversation,
    reset_conversation,
)


def start_appointment_flow(phone: str) -> str:
    conversation = {
        "state": "waiting_appointment_details",
        "data": {},
    }

    save_conversation(phone, conversation)

    return (
        "Perfecto. Para reservar necesito estos datos:\n\n"
        "Nombre:\n"
        "Servicio:\n"
        "Dia preferido:\n"
        "Hora aproximada:\n\n"
        "Ejemplo:\n"
        "Marta, manicura semipermanente, viernes, 17:30"
    )


def handle_appointment_details(phone: str, text: str) -> str:
    conversation = get_conversation(phone)

    conversation["state"] = "appointment_details_received"
    conversation["data"]["raw_details"] = text

    save_conversation(phone, conversation)

    return (
        "Perfecto. He recibido estos datos para la cita:\n\n"
        f"{text}\n\n"
        "Ahora revisaremos disponibilidad y te confirmaremos el hueco.\n\n"
        "Para cancelar esta solicitud, escribe: cancelar"
    )


def handle_appointment_confirmation(phone: str, text: str) -> str:
    conversation = get_conversation(phone)

    if text.lower().strip() in ["si", "sí", "confirmo", "ok", "vale"]:
        conversation["state"] = "appointment_confirmed"
        save_conversation(phone, conversation)

        return (
            "Cita preconfirmada.\n\n"
            "Te enviaremos la confirmacion final en cuanto quede registrada en agenda."
        )

    return (
        "La solicitud sigue pendiente.\n\n"
        "Puedes escribir 'confirmo' para confirmar o 'cancelar' para anular."
    )


def cancel_appointment_flow(phone: str) -> str:
    reset_conversation(phone)

    return (
        "Solicitud cancelada.\n\n"
        "Si necesitas otra cita, escribe: quiero una cita"
    )
