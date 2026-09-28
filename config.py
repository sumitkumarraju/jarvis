import os
from pathlib import Path

OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen3.5:latest")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Set JARVIS_PROVIDER=openai for any OpenAI-compatible endpoint, including a
# local OmniRoute server. Ollama remains the default so existing installs stay
# offline and do not need an API key.
JARVIS_PROVIDER = os.getenv("JARVIS_PROVIDER", "ollama").lower()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:20128/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "agy/claude-opus-4-6-thinking")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "") or None

WAKE_WORD = os.getenv("JARVIS_WAKE", "jarvis")
SAMPLE_RATE = 16000
SILENCE_TIMEOUT = float(os.getenv("JARVIS_SILENCE_TIMEOUT", "2.0"))
SPEECH_THRESHOLD = float(os.getenv("JARVIS_VAD_THRESHOLD", "0.012"))

TTS_VOICE = os.getenv("JARVIS_VOICE", "Samantha")
TTS_RATE = int(os.getenv("JARVIS_RATE", "210"))

CONFIRM_SHELL = os.getenv("JARVIS_CONFIRM_SHELL", "1") == "1"

PROJECT_ROOT = Path(__file__).parent
WORKDIR = Path(os.getenv("JARVIS_WORKDIR", str(Path.home())))
