from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


class SubserverConfig(BaseModel):
    name: str
    url: str
    size: int = 0
    # Model details as reported by llama-server (or set in config).
    # Empty means unknown; nothing is guessed.
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""
    context_length: int = 4096
    parallel: int = 1
    upstream_model_id: Optional[str] = None
    upstream_meta: dict[str, Any] = Field(default_factory=dict)
    reachable: bool = False
    # Whether the upstream model supports vision (multimodal projector / mmproj).
    # Detected from llama-server's /props -> modalities.vision during probing.
    vision: bool = False
    # Chat-template capabilities detected from /props: whether the model emits
    # thinking and whether its template accepts tools (Ollama `capabilities`).
    thinking: bool = False
    tools: bool = True
    # True once /props has actually reported modalities (False = vision is unknown,
    # not "text-only"), so listings can omit what they can't state.
    vision_known: bool = False
    # Reasoning-effort values the model's chat template actually supports,
    # inferred from /props -> chat_template during probing (e.g. ["low","xhigh"]).
    supported_reasoning_efforts: list[str] = Field(default_factory=list)
    # Effort the template applies when a request sends none (e.g. "xhigh").
    default_reasoning_effort: Optional[str] = None
    # Reasoning-effort values the user ALLOWS on this server (e.g. ["low", "xhigh"]).
    # The effective set is allowed ∩ supported; empty = efforts aren't policed.
    reasoning_efforts: list[str] = Field(default_factory=list)
    # Whether allowed efforts are also exposed as virtual "name:effort" models.
    virtualize_efforts: bool = False


class AppConfig(BaseModel):
    subservers: list[SubserverConfig] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Ollama request/response schemas
# ---------------------------------------------------------------------------

class OllamaChatMessage(BaseModel):
    """Chat message — keeps tool-calling fields so agents work through the gateway."""

    role: str
    content: str = ""
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    images: Optional[list[str]] = None

    class Config:
        extra = "allow"


class OllamaChatRequest(BaseModel):
    model: str
    messages: list[OllamaChatMessage]
    stream: bool = True
    tools: Optional[list[dict[str, Any]]] = None
    format: Optional[Any] = None
    keep_alive: Optional[Any] = None
    options: Optional[dict[str, Any]] = None

    class Config:
        extra = "allow"


class OllamaGenerateRequest(BaseModel):
    model: str
    prompt: str = ""
    system: Optional[str] = None
    images: Optional[list[str]] = None
    raw: bool = False
    stream: bool = True
    format: Optional[Any] = None
    keep_alive: Optional[Any] = None
    options: Optional[dict[str, Any]] = None

    class Config:
        extra = "allow"


class OllamaShowRequest(BaseModel):
    model: Optional[str] = None
    name: Optional[str] = None

    @model_validator(mode="after")
    def validate_model_or_name(self) -> "OllamaShowRequest":
        if not self.model and not self.name:
            raise ValueError("Either 'model' or 'name' must be provided")
        return self

    @property
    def model_name(self) -> str:
        return self.model or self.name or ""


# ---------------------------------------------------------------------------
# OpenAI passthrough schemas (minimal — bodies forwarded as-is)
# ---------------------------------------------------------------------------

class OpenAIChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    stream: bool = False

    class Config:
        extra = "allow"


class OpenAICompletionRequest(BaseModel):
    model: str
    prompt: str
    stream: bool = False

    class Config:
        extra = "allow"


class OpenAIEmbeddingRequest(BaseModel):
    model: str
    input: Any

    class Config:
        extra = "allow"
