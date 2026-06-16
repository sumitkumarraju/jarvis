<div align="center">

# 🤖 JARVIS

### Local AI Personal Assistant for macOS

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![LangChain](https://img.shields.io/badge/LangChain-0.3+-1C3C3C?style=for-the-badge&logo=chainlink&logoColor=white)](https://langchain.com)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-000000?style=for-the-badge&logo=ollama&logoColor=white)](https://ollama.ai)
[![macOS](https://img.shields.io/badge/macOS-Sonoma+-000000?style=for-the-badge&logo=apple&logoColor=white)](https://apple.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

**Jarvis is a fully local, voice-enabled AI agent that runs entirely on your Mac — no cloud, no API keys, no data leaving your machine.**

[Features](#-features) · [Architecture](#-architecture) · [Tech Stack](#-tech-stack) · [Installation](#-installation) · [Usage](#-usage) · [Configuration](#-configuration) · [Tools Reference](#-tools-reference)

</div>

---

## ✨ Overview

Jarvis is a production-grade, offline AI assistant that combines a locally-running large language model (via **Ollama**) with an extensible LangChain tool-calling agent. It can listen to your voice, think through multi-step tasks, invoke tools, and speak back — all without touching the internet (unless you ask it to search).

It ships with a native **desktop GUI** (via pywebview) and a lightweight **text REPL**, making it suitable for both daily use and developer experimentation.

```
You (voice/text) → Whisper STT → LangChain Agent (Ollama LLM) → Tool Calls → pyttsx3 TTS → You
```

---

## 🚀 Features

| Category | Capability |
|---|---|
| 🧠 **AI Brain** | Local LLM via Ollama — runs `qwen3.5`, `llama3.1`, `mistral-nemo`, and more |
| 🎤 **Voice Input** | Continuous wake-word listening (`"Jarvis, ..."`) or push-to-talk |
| 🔊 **Voice Output** | Natural TTS via pyttsx3 (macOS Samantha voice by default) |
| 🌐 **Web** | DuckDuckGo search + full-page scraping |
| 🖥️ **App Control** | Open, quit, switch, and list macOS applications via AppleScript |
| 🔧 **Shell** | Run terminal commands (with confirmation gate before execution) |
| 📁 **Files** | List, read, write, and find files across the filesystem |
| ⌨️ **Automation** | Type text, press key combos, move/click mouse, take screenshots |
| 🔔 **System** | Volume control, clipboard R/W, battery status, lock screen, notifications |
| 💾 **Memory** | Persistent key-value memory — remember facts across sessions |
| 🖼️ **Desktop GUI** | Electron-style webview window with a dark-themed chat interface |

---

## 🏗️ Architecture

```
jarvis/
├── main.py               ← Entry point — CLI args, mode selection
├── config.py             ← All configuration via environment variables
│
├── agent/
│   └── jarvis.py         ← Core LangChain agent (chat loop, streaming, tool dispatch)
│
├── tools/
│   ├── __init__.py       ← ALL_TOOLS registry — single source of truth
│   ├── web.py            ← web_search, fetch_page
│   ├── apps.py           ← open_app, quit_app, list_running_apps, switch_to_app
│   ├── shell.py          ← run_shell (with confirmation guard)
│   ├── files.py          ← list_dir, read_file, write_file, find_files
│   ├── keyboard.py       ← type_text, press_keys, mouse_click, mouse_move, get_screen_size
│   ├── screen.py         ← take_screenshot
│   ├── system.py         ← volume, clipboard, battery, lock_screen, notifications
│   └── memory.py         ← remember, recall, list_memory, forget
│
├── voice/
│   ├── listen.py         ← ContinuousListener — VAD + faster-whisper transcription
│   └── speak.py          ← TTS output via pyttsx3
│
└── webui/
    ├── index.html        ← Chat UI markup
    ├── style.css         ← Dark-mode design system
    ├── app.js            ← Frontend JS — message handling, voice toggle, streaming
    └── bridge.py         ← Python ↔ JS bridge (pywebview JS API)
```

### How the Agent Loop Works

```
User Input (text or transcribed voice)
        │
        ▼
 LangChain ChatOllama ──→ Bound with ALL_TOOLS (via bind_tools)
        │
  ┌─────┴──────────────────────────────────┐
  │  Step N                                │
  │  AI generates response                 │
  │  ├── No tool_calls → stream text out   │
  │  └── Has tool_calls → execute tools    │
  │       └── Append ToolMessage(result)   │
  │           └── Loop back (max 6 steps)  │
  └────────────────────────────────────────┘
        │
        ▼
   Spoken/displayed response
```

1. **Message History** — The agent maintains a rolling `history` list: `[SystemMessage, HumanMessage, AIMessage, ToolMessage, ...]`
2. **Streaming** — The `stream()` method yields text chunks in real-time while transparently handling tool calls mid-stream.
3. **Tool Chaining** — Up to 6 tool-call steps per query (configurable via `max_steps`). Handles multi-hop tasks like: *"search for X, then open the top result in Safari"*.
4. **Self-Echo Prevention** — The voice listener drops all audio while TTS is speaking, preventing feedback loops.

---

## 🛠️ Tech Stack

### Core AI & Agent Framework

| Library | Version | Role |
|---|---|---|
| **[LangChain](https://langchain.com)** | `>=0.3.0` | Agent orchestration, message history, tool dispatch |
| **[langchain-core](https://python.langchain.com/docs/concepts/)** | `>=0.3.0` | Message types (`HumanMessage`, `AIMessage`, `ToolMessage`), `@tool` decorator |
| **[langchain-ollama](https://python.langchain.com/docs/integrations/llms/ollama/)** | `>=0.2.0` | `ChatOllama` — connects LangChain to a local Ollama instance |
| **[langchain-community](https://python.langchain.com/docs/integrations/providers/)** | `>=0.3.0` | Community integrations (DuckDuckGo wrapper, utilities) |
| **[Ollama](https://ollama.ai)** | latest | Local LLM runtime — serves models like `qwen3.5`, `llama3.1` via REST |

> **Why LangChain?** LangChain's `bind_tools()` API converts Python functions decorated with `@tool` into the JSON schema that Ollama's tool-calling API expects. It also manages the `AIMessage → ToolMessage → AIMessage` conversation cycle automatically, letting the agent chain multiple tool calls without custom parsing.

### Speech-to-Text (STT)

| Library | Version | Role |
|---|---|---|
| **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** | `>=1.0.3` | OpenAI Whisper, reimplemented with CTranslate2 — ~4× faster than original |
| **[sounddevice](https://python-sounddevice.readthedocs.io/)** | `>=0.5.0` | Cross-platform microphone access via PortAudio |
| **[NumPy](https://numpy.org)** | `>=1.26.0` | RMS-based Voice Activity Detection (VAD) on raw audio blocks |

**How STT works:**
1. `sounddevice` streams 1024-sample blocks at 16 kHz from the mic.
2. A simple RMS energy VAD (threshold configurable via `JARVIS_VAD_THRESHOLD`) detects speech onset.
3. Audio is buffered until `SILENCE_TIMEOUT` seconds of quiet (default 1.0s) is detected.
4. The buffered `float32` array is passed to `faster-whisper` (model: `tiny.en` / `base.en`) for transcription.
5. While TTS is speaking, the listener suppresses all audio to prevent self-echo.

### Text-to-Speech (TTS)

| Library | Version | Role |
|---|---|---|
| **[pyttsx3](https://pyttsx3.readthedocs.io/)** | `>=2.90` | Offline TTS using macOS NSSpeechSynthesizer (no network required) |

Default voice: **Samantha** (macOS system voice). Speech rate defaults to **210 WPM** — both configurable.

### macOS System Automation

| Library | Version | Role |
|---|---|---|
| **[pyautogui](https://pyautogui.readthedocs.io/)** | `>=0.9.54` | Mouse control, keyboard simulation, screenshots |
| **[pyobjc-core](https://pyobjc.readthedocs.io/)** | `>=10.3` | Python ↔ Objective-C bridge for native macOS APIs |
| **[pyobjc-framework-Quartz](https://pyobjc.readthedocs.io/en/latest/api/module-Quartz.html)** | `>=10.3` | Screen capture, window management via macOS Quartz framework |

Apps are controlled via **AppleScript** (`osascript` subprocess calls) for operations like `open_app`, `quit_app`, and `switch_to_app`.

### Web & Scraping

| Library | Version | Role |
|---|---|---|
| **[duckduckgo-search](https://github.com/deedy5/duckduckgo_search)** | `>=6.3.0` | Privacy-respecting web search — no API key required |
| **[httpx](https://www.python-httpx.org/)** | `>=0.27.0` | Async-capable HTTP client for page fetching |
| **[beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/)** | `>=4.12.0` | HTML parsing — strips scripts/nav/footer, returns clean readable text |

### Desktop GUI

| Library | Version | Role |
|---|---|---|
| **[pywebview](https://pywebview.app/)** | `>=5.3.0` | Native OS webview window (WKWebView on macOS) hosting the chat UI |
| **Vanilla JS + CSS** | — | Chat frontend — streaming rendering, voice toggle, message history |

The `Bridge` class in `webui/bridge.py` exposes Python methods to JavaScript via pywebview's `js_api`, enabling the frontend to call `bridge.send_message()`, `bridge.toggle_voice()`, etc.

### Developer UX

| Library | Version | Role |
|---|---|---|
| **[rich](https://rich.readthedocs.io/)** | `>=13.9.0` | Beautiful terminal output with color, markup, and streaming in text mode |

---

## 📋 Prerequisites

- **macOS** Ventura (13) or later
- **Python** 3.11+
- **Homebrew** (for Ollama)
- **Microphone** (for voice mode)

---

## ⚙️ Installation

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/jarvis.git
cd jarvis
```

### 2. Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install & Start Ollama

```bash
# Install Ollama (one-time)
brew install ollama

# Start the Ollama server (keep running in a separate terminal)
ollama serve

# Pull a model (qwen3.5 is the default)
ollama pull qwen3:latest

# Or try other compatible models:
ollama pull llama3.1
ollama pull qwen2.5
ollama pull mistral-nemo
```

> **Note:** First voice run will download the Whisper model (~140 MB for `base.en`, ~39 MB for `tiny.en`).

---

## 🎮 Usage

### Desktop GUI (Recommended)

```bash
python main.py                  # GUI with voice enabled by default
python main.py --no-voice       # GUI with voice disabled
```

### Text REPL

```bash
python main.py --text           # Plain terminal REPL with streaming output
```

**REPL commands:**
- `exit` / `quit` — exit the program
- `reset` — clear conversation history

### Example Interactions

```
> search for the latest Python 3.13 release notes and summarize them
> open Spotify and play something
> what files are in my Downloads folder larger than 100MB?
> remember that my standup is at 9:30am
> take a screenshot and save it to the Desktop
> set volume to 50%
> what's on my clipboard?
```

---

## 🔧 Configuration

All configuration is done via **environment variables**. Set them in your shell profile (`~/.zshrc`) or prefix commands with them.

| Variable | Default | Description |
|---|---|---|
| `JARVIS_MODEL` | `qwen3.5:latest` | Ollama model name to use |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `WHISPER_MODEL` | `tiny.en` | Whisper model size: `tiny.en`, `base.en`, `small.en` |
| `WHISPER_DEVICE` | `cpu` | Whisper inference device: `cpu` or `cuda` |
| `WHISPER_COMPUTE` | `int8` | Compute type: `int8`, `float16`, `float32` |
| `JARVIS_WAKE` | `jarvis` | Wake word for continuous listening mode |
| `JARVIS_VAD_THRESHOLD` | `0.012` | RMS energy threshold for voice activity detection |
| `JARVIS_VOICE` | `Samantha` | macOS TTS voice name |
| `JARVIS_RATE` | `210` | TTS speech rate (words per minute) |
| `JARVIS_CONFIRM_SHELL` | `1` | Set to `0` to disable shell command confirmation prompts |
| `JARVIS_WORKDIR` | `$HOME` | Base directory for relative file path operations |

### Example `.env`-style setup

```bash
export JARVIS_MODEL=llama3.1
export WHISPER_MODEL=base.en
export JARVIS_VOICE=Alex
export JARVIS_CONFIRM_SHELL=0  # ⚠️ Only if you fully trust the model
```

---

## 🧰 Tools Reference

The agent has access to **30 tools** across 8 categories. Each tool is a Python function decorated with LangChain's `@tool` decorator, which automatically generates the JSON schema for the LLM.

### 🌐 Web
| Tool | Description |
|---|---|
| `web_search(query, max_results)` | DuckDuckGo search — returns titles, snippets, and URLs |
| `fetch_page(url, max_chars)` | Fetches a URL and returns clean readable text (strips nav/scripts) |

### 🖥️ App Control
| Tool | Description |
|---|---|
| `open_app(name)` | Open a macOS application by name |
| `quit_app(name)` | Quit a running application |
| `list_running_apps()` | List all currently running applications |
| `switch_to_app(name)` | Bring an application to the foreground |

### 🔧 Shell
| Tool | Description |
|---|---|
| `run_shell(command)` | Execute a shell command (prompts user for confirmation by default) |

### 📁 Files
| Tool | Description |
|---|---|
| `list_dir(path)` | List contents of a directory |
| `read_file(path)` | Read a file's contents |
| `write_file(path, content)` | Write content to a file |
| `find_files(pattern, directory)` | Find files matching a glob pattern |

### ⌨️ Keyboard & Mouse
| Tool | Description |
|---|---|
| `type_text(text)` | Type text at the current cursor position |
| `press_keys(*keys)` | Press a key combination (e.g., `cmd+c`) |
| `mouse_click(x, y, button)` | Click at screen coordinates |
| `mouse_move(x, y)` | Move mouse to screen coordinates |
| `get_screen_size()` | Return the current screen resolution |

### 📸 Screen
| Tool | Description |
|---|---|
| `take_screenshot(path)` | Capture the screen and save to a file |

### 🔔 System
| Tool | Description |
|---|---|
| `set_volume(level)` | Set system volume (0–100) |
| `mute_volume()` | Mute system audio |
| `unmute_volume()` | Unmute system audio |
| `system_notification(title, message)` | Show a macOS notification |
| `lock_screen()` | Lock the screen |
| `get_battery()` | Return battery status and percentage |
| `get_clipboard()` | Read the current clipboard contents |
| `set_clipboard(text)` | Write text to the clipboard |

### 💾 Memory
| Tool | Description |
|---|---|
| `remember(key, value)` | Store a named fact persistently |
| `recall(key)` | Retrieve a stored fact by name |
| `list_memory()` | List all stored memory keys |
| `forget(key)` | Delete a stored fact |

---

## 🔒 macOS Permissions

macOS will prompt for these permissions on first use. Grant them in **System Settings → Privacy & Security**:

| Permission | Required For |
|---|---|
| **Microphone** | Voice input / STT |
| **Automation** | Controlling other apps via AppleScript (`open_app`, `quit_app`, etc.) |
| **Accessibility** | `switch_to_app`, mouse/keyboard automation |
| **Screen Recording** | `take_screenshot` |

---

## 🤖 Model Compatibility

Jarvis requires a model with **native tool-calling support** (function calling). Not all Ollama models support this.

| Model | Tool Calling | Quality | Notes |
|---|---|---|---|
| `qwen3.5` ⭐ | ✅ | Excellent | Default — fast, accurate tool use |
| `qwen2.5` | ✅ | Excellent | Great alternative |
| `llama3.1` | ✅ | Very Good | Solid all-rounder |
| `mistral-nemo` | ✅ | Good | Lightweight option |
| Small distilled models | ❌ | Poor | Often fail to call tools correctly |

> **Tip:** Smaller/distilled models frequently fail to emit properly formatted tool calls, causing the agent to silently fall back to text replies. Stick to the models in the table above.

---

## 🗺️ Roadmap

- [ ] Multi-modal support (image input via LLaVA)
- [ ] Calendar & reminders integration (EventKit)
- [ ] Spotify / music control via AppleScript
- [ ] Plugin system for custom tools
- [ ] Conversation export & history search
- [ ] Hotkey-activated push-to-talk from any app

---

## 🤝 Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you'd like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-tool`)
3. Add your tool in `tools/` using the `@tool` decorator
4. Register it in `tools/__init__.py`'s `ALL_TOOLS` list
5. Commit and open a PR

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

Built with ❤️ on macOS · Powered by [Ollama](https://ollama.ai) + [LangChain](https://langchain.com) + [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

</div>
