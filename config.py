import os
from pathlib import Path

OLLAMA_MODEL = os.getenv("JARVIS_MODEL", "qwen3.5:latest")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny.en")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")

WAKE_WORD = os.getenv("JARVIS_WAKE", "jarvis")
SAMPLE_RATE = 16000
SILENCE_TIMEOUT = 1.0
SPEECH_THRESHOLD = float(os.getenv("JARVIS_VAD_THRESHOLD", "0.012"))

TTS_VOICE = os.getenv("JARVIS_VOICE", "Samantha")
TTS_RATE = int(os.getenv("JARVIS_RATE", "210"))

CONFIRM_SHELL = os.getenv("JARVIS_CONFIRM_SHELL", "1") == "1"

PROJECT_ROOT = Path(__file__).parent
WORKDIR = Path(os.getenv("JARVIS_WORKDIR", str(Path.home())))
