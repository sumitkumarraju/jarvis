# Jarvis

Local LangChain agent with voice control for macOS. Brain runs on Ollama; speech-to-text on faster-whisper; text-to-speech on pyttsx3 (system voice).

## Setup

```bash
cd /Users/skr/KILO/jarvis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Ollama (one-time, separate terminal)
brew install ollama
ollama serve &
ollama pull llama3.1
```

First voice run downloads the Whisper model (~140 MB for `base.en`).

## Run

```bash
# text mode
python main.py

# push-to-talk voice (press Enter, speak, pause)
python main.py --voice --ptt

# wake-word voice ("jarvis, ...")
python main.py --voice
```

## Capabilities

- Web search + page fetch (DuckDuckGo)
- macOS app control (open / quit / switch / list) via AppleScript
- Shell commands (asks before running; refuses obviously destructive ones)
- File ops (list, read, write, find)

## Configuration

Environment variables:
- `JARVIS_MODEL` — Ollama model (default `llama3.1`)
- `OLLAMA_HOST` — default `http://localhost:11434`
- `WHISPER_MODEL` — `tiny.en`, `base.en`, `small.en` (default `base.en`)
- `JARVIS_WAKE` — wake word (default `jarvis`)
- `JARVIS_CONFIRM_SHELL` — `0` to skip shell confirmation prompts
- `JARVIS_WORKDIR` — base for relative paths (default `$HOME`)

## First-run permissions

macOS will prompt for:
- **Microphone** — for voice input
- **Automation** — when controlling other apps via AppleScript
- **Accessibility** — may be needed for `switch_to_app`

Grant in System Settings → Privacy & Security.

## Notes

- Pick an Ollama model with tool-calling support. `llama3.1`, `qwen2.5`, and `mistral-nemo` work well; smaller distilled models often don't.
- Shell tool prompts before every command. Set `JARVIS_CONFIRM_SHELL=0` only if you trust the agent + model combo.
