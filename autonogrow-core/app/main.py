from fastapi import FastAPI, Request, Query, HTTPException

from app.config import settings
from app.logic.router import route_incoming_payload
from app.whatsapp.sender import send_whatsapp_message

app = FastAPI(title="AutonoGrow Core")


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "AutonoGrow Core"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.get("/webhook/whatsapp")
def verify_whatsapp_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return int(hub_challenge)

    raise HTTPException(status_code=403, detail="Invalid verification token")


@app.post("/webhook/whatsapp")
async def receive_whatsapp_webhook(request: Request):
    payload = await request.json()

    response = route_incoming_payload(payload)

    if response:
        send_whatsapp_message(
            to=response["to"],
            text=response["text"],
        )

    return {
        "status": "ok",
        "processed": response is not None,
    }
