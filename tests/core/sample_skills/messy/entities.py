from pydantic import BaseModel


class Note(BaseModel):
    text: str
