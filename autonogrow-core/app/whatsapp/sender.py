import requests

from app.config import settings


def send_whatsapp_message(to: str, text: str) -> dict:
    if settings.WHATSAPP_FAKE_MODE:
        return send_fake_whatsapp_message(to=to, text=text)

    return send_real_whatsapp_message(to=to, text=text)


def send_fake_whatsapp_message(to: str, text: str) -> dict:
    print("=" * 60)
    print("FAKE WHATSAPP SEND")
    print(f"TO: {to}")
    print("TEXT:")
    print(text)
    print("=" * 60)

    return {
        "status": "fake_sent",
        "to": to,
        "text": text,
    }


def send_real_whatsapp_message(to: str, text: str) -> dict:
    url = (
        f"https://graph.facebook.com/"
        f"{settings.WHATSAPP_API_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": text,
        },
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=10,
    )

    response.raise_for_status()
    return response.json()
