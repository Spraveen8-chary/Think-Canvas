"""Request bodies (validated by FastAPI/pydantic before any code runs)."""
from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    name: str = Field(max_length=200)
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)
    organisation: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class ProfileIn(BaseModel):
    name: str = Field(max_length=200)
    organisation: str = Field(default="", max_length=200)


class CanvasIn(BaseModel):
    title: str = Field(default="Untitled", max_length=200)
    items: list = Field(default_factory=list, max_length=20000)


class ActiveIn(BaseModel):
    active: bool


class AskIn(BaseModel):
    image: str | None = Field(default=None, max_length=4_000_000)    # PNG data URL of the newest writing (already shrunk by the browser)
    typed: str = Field(default="", max_length=2000)                    # typed question(s) near the writing
    canvas_id: str | None = None
    use_library: bool = True
    earlier: str = Field(default="", max_length=2000)                  # typed text that was already answered (context, not a new question)
    grey_ink: bool = False                                              # the picture shows already-answered writing in grey
    source: str = Field(default="", max_length=12)                     # "type" | "voice" | "" (handwriting/other); used in abuse reports


class SttTokenIn(BaseModel):
    speech_model: str = Field(default="universal-streaming-multilingual", max_length=80)


class LiveBlockIn(BaseModel):
    name: str = Field(max_length=40)
    args: dict = Field(default_factory=dict)


class LiveHistoryIn(BaseModel):
    canvas_id: str | None = None
    transcript: list[dict] = Field(default_factory=list, max_length=200)
    kinds: list[str] = Field(default_factory=list, max_length=50)
