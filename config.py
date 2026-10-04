import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen3.5:latest")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Set JARVIS_PROVIDER=openai for any OpenAI-compatible endpoint, including a
# local OmniRoute server. Ollama remains the default so existing installs stay
# offline and do not need an API key.
JARVIS_PROVIDER = os.getenv("JARVIS_PROVIDER", "ollama").lower()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:20128/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "agy/claude-opus-4-6-thinking")

PROVIDER_LABELS = {
    "ollama": "Ollama (local)",
    "openai": "OpenAI compatible",
    "omniroute": "OmniRoute",
    "claude": "Claude via compatible endpoint",
}


def validate_selection(provider: str, model: str) -> tuple[str, str]:
    if not isinstance(provider, str) or provider.strip().lower() not in PROVIDER_LABELS:
        raise ValueError("Choose ollama, openai, omniroute, or claude.")
    if not isinstance(model, str) or not model.strip() or len(model) > 256:
        raise ValueError("Enter a non-empty model name (at most 256 characters).")
    if any(ord(char) < 32 or ord(char) == 127 for char in model):
        raise ValueError("Model names cannot contain control characters.")
    return provider.strip().lower(), model.strip()


def default_model(provider: str) -> str:
    return OLLAMA_MODEL if provider == "ollama" else OPENAI_MODEL


def display_endpoint(endpoint: str) -> str:
    try:
        parts = urlsplit(endpoint)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return "Invalid configured endpoint"
        return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
    except ValueError:
        return "Invalid configured endpoint"


def safe_error(error: Exception) -> str:
    message = str(error)
    if OPENAI_API_KEY:
        message = message.replace(OPENAI_API_KEY, "[redacted]")
    for endpoint in (OLLAMA_HOST, OPENAI_BASE_URL):
        if endpoint:
            message = message.replace(endpoint, display_endpoint(endpoint))
    return message


def provider_info() -> list[dict]:
    return [
        {
            "id": provider,
            "label": label,
            "endpoint": display_endpoint(OLLAMA_HOST if provider == "ollama" else OPENAI_BASE_URL),
            "requires_key": provider != "ollama",
            "key_configured": bool(OPENAI_API_KEY) if provider != "ollama" else False,
        }
        for provider, label in PROVIDER_LABELS.items()
    ]

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "") or None

WAKE_WORD = os.getenv("JARVIS_WAKE", "jarvis")
WAKE_MODE = os.getenv('JARVIS_WAKE_MODE', 'always')
if WAKE_MODE not in ('always', 'phrase', 'clap', 'phrase_or_clap'):
    WAKE_MODE = 'phrase_or_clap'
SAMPLE_RATE = 16000
SILENCE_TIMEOUT = float(os.getenv("JARVIS_SILENCE_TIMEOUT", "2.0"))
SPEECH_THRESHOLD = float(os.getenv("JARVIS_VAD_THRESHOLD", "0.012"))
CLAP_THRESHOLD = float(os.getenv('JARVIS_CLAP_THRESHOLD', '0.08'))

TTS_VOICE = os.getenv("JARVIS_VOICE", "Samantha")
TTS_RATE = int(os.getenv("JARVIS_RATE", "210"))

CONFIRM_SHELL = os.getenv("JARVIS_CONFIRM_SHELL", "1") == "1"

PROJECT_ROOT = Path(__file__).parent
WORKDIR = Path(os.getenv("JARVIS_WORKDIR", str(Path.home())))
