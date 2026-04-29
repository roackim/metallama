from __future__ import annotations

from .config import get_server_config
from .models import ModelProfile


MODEL_PROFILES: dict[str, ModelProfile] = {
    "llamacpp-coding": ModelProfile(
        id="llamacpp-coding",
        display_name="Assistant",
        engine="llama",
        service="LLM",
        family="Qwen 3.5",
        size="27B",
        description="Primary coding model for chat and generation tasks.",
        model_path="/envs/local/llm/models/Qwen3.6-27B-Q8_0.gguf",
        port=8011,
        extra_args=[
            "--ctx-size 229376",
            "--threads 16",
            "--n-gpu-layers 999",
            "--temp 1.0",
            "--top-p 0.95",
            "--top-k 20",
            "--min-p 0.00",
            "--presence_penalty 0.0",
            "--repeat-penalty 1.0",
        ],
        context_window=get_server_config("llamacpp-coding").get("context_window"),
    ),
    "whisper-audio": ModelProfile(
        id="whisper-audio",
        display_name="Scribe",
        engine="whisper",
        service="AUDIO",
        family="Whisper",
        size="Large",
        description="Advanced transcription model for diverse audio processing.",
        model_path="/local_home/debian/llm/whisper.cpp/models/ggml-large-v3-turbo.bin",
        port=8012,
        extra_args=[],
        context_window=None,
    ),
    "mineru-ocr": ModelProfile(
        id="mineru-ocr",
        display_name="Reader",
        engine="mineru",
        service="OCR",
        family="MinerU",
        size="N/A",
        description="OCR API server powered by mineru-api.",
        model_path="",
        port=8013,
        extra_args=[],
        context_window=None,
    ),
}
