from pydantic import BaseModel, Field
from typing import List, Optional


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32_000)
    session_id: Optional[str] = None
    tts: bool = False
    imgbase64: Optional[str] = None
    input_source: str = "text"
    voice_audio_base64: Optional[str] = None
    face_session_id: Optional[str] = None
    step_up_token: Optional[str] = None
    client_request_id: Optional[str] = None


class FaceEnrollStartRequest(BaseModel):
    user_name: str = "Moksh"
    replace_existing: bool = True


class FaceEnrollSampleRequest(BaseModel):
    enrollment_session_id: str
    frames: List[str] = Field(default_factory=list)


class FaceEnrollBatchRequest(BaseModel):
    enrollment_session_id: str
    frames: List[str] = Field(default_factory=list)


class FaceEnrollCompleteRequest(BaseModel):
    enrollment_session_id: str


class FaceVerifyRequest(BaseModel):
    frames: List[str] = Field(default_factory=list)
    client_id: str = "web"
    request_id: Optional[str] = None


class CommandRiskRequest(BaseModel):
    command_text: str = Field(..., min_length=1)
    command_action: str = ""


class StepUpStartRequest(BaseModel):
    face_session_id: str
    command_text: str = Field(..., min_length=1)
    command_action: str = ""


class StepUpVerifyRequest(BaseModel):
    challenge_id: str
    face_session_id: str
    command_text: str = Field(..., min_length=1)
    command_action: str = ""
    frames: List[str] = Field(default_factory=list)
    client_id: str = "web"


class LauncherBootstrapCreateRequest(BaseModel):
    face_session_id: str


class LauncherBootstrapExchangeRequest(BaseModel):
    bootstrap_token: str


class ChatResponse(BaseModel):
    response: str
    session_id: str


class ChatHistory(BaseModel):
    session_id: str
    messages: List[ChatMessage]


class JarvisActions(BaseModel):
    wopens: List[str] = Field(default_factory=list)
    plays: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    contents: List[str] = Field(default_factory=list)
    googlesearches: List[str] = Field(default_factory=list)
    youtubesearches: List[str] = Field(default_factory=list)
    cam: Optional[dict] = None


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
