def extract_text_message(payload: dict) -> dict | None:
    """
    Extracts a basic WhatsApp text message from Meta webhook payload.
    Returns:
        {
            "phone": "...",
            "text": "...",
            "message_id": "..."
        }
    """
    try:
        value = payload["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            return None

        message = value["messages"][0]

        if message.get("type") != "text":
            return None

        return {
            "phone": message["from"],
            "text": message["text"]["body"],
            "message_id": message.get("id", ""),
        }

    except (KeyError, IndexError, TypeError):
        return None
