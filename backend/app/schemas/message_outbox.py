from pydantic import BaseModel


class MessageOutboxStatusUpdate(BaseModel):
    status: str
