from app.whatsapp.parser import extract_text_message
from app.logic.intent_detector import detect_intent
from app.logic.appointment_flow import (
    start_appointment_flow,
    handle_appointment_details,
    handle_appointment_confirmation,
    cancel_appointment_flow,
)
from app.storage.conversation_store import get_conversation


def route_incoming_payload(payload: dict) -> dict | None:
    message = extract_text_message(payload)

    if message is None:
        return None

    phone = message["phone"]
    text = message["text"].strip()
    intent = detect_intent(text)

    conversation = get_conversation(phone)
    state = conversation.get("state", "idle")

    if intent == "cancel":
        reply = cancel_appointment_flow(phone)

    elif state == "waiting_appointment_details":
        reply = handle_appointment_details(phone, text)

    elif state == "appointment_details_received":
        reply = handle_appointment_confirmation(phone, text)

    elif intent == "appointment_request":
        reply = start_appointment_flow(phone)

    elif intent == "pricing_request":
        reply = (
            "Claro. Estos son nuestros servicios principales:\n\n"
            "- Servicio 1: __ euros\n"
            "- Servicio 2: __ euros\n"
            "- Servicio 3: __ euros\n\n"
            "Quieres que te pase huecos disponibles?"
        )

    elif intent == "review_request":
        reply = (
            "Gracias por confiar en nosotros.\n\n"
            "Si has quedado contento/a, nos ayudaria mucho que dejaras una resena aqui:\n"
            "[ENLACE A GOOGLE RESENAS]"
        )

    elif intent == "greeting":
        reply = (
            "Hola. Soy el asistente de AutonoGrow.\n\n"
            "Puedo ayudarte con:\n"
            "- Citas\n"
            "- Precios\n"
            "- Disponibilidad\n"
            "- Resenas\n\n"
            "Escribe por ejemplo: quiero una cita."
        )

    else:
        reply = (
            "No te he entendido del todo.\n\n"
            "Puedes escribir:\n"
            "- quiero una cita\n"
            "- ver precios\n"
            "- dejar una resena\n"
            "- cancelar"
        )

    return {
        "to": phone,
        "text": reply,
    }
