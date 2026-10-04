<div align="center">

# 🤖 JARVIS

### Local AI Personal Assistant for macOS

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![LangChain](https://img.shields.io/badge/LangChain-0.3+-1C3C3C?style=for-the-badge&logo=chainlink&logoColor=white)](https://langchain.com)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-000000?style=for-the-badge&logo=ollama&logoColor=white)](https://ollama.ai)
[![macOS](https://img.shields.io/badge/macOS-Sonoma+-000000?style=for-the-badge&logo=apple&logoColor=white)](https://apple.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

**Jarvis is a voice-enabled macOS agent with a local Ollama brain by default, plus optional support for Claude through an OpenAI-compatible endpoint such as a local OmniRoute gateway.**

[Features](#-features) · [Architecture](#-architecture) · [Tech Stack](#-tech-stack) · [Installation](#-installation) · [Usage](#-usage) · [Configuration](#-configuration) · [Tools Reference](#-tools-reference)

</div>

---

## ✨ Overview

Jarvis is a production-grade, offline AI assistant that combines a locally-running large language model (via **Ollama**) with an extensible LangChain tool-calling agent. It can listen to your voice, think through multi-step tasks, invoke tools, and speak back — all without touching the internet (unless you ask it to search).

It ships with a native **desktop GUI** (via pywebview) and a lightweight **text REPL**, making it suitable for both daily use and developer experimentation.

```
You (voice/text) → local Whisper STT → Laya reactive decision / selected processing LLM → Tool Calls → macOS TTS → You
```

Double-click **`Jarvis.command`** to open the desktop interface with voice enabled automatically. Wait for **Waiting for a wake phrase or clap** after speech recognition warms up, then say **Hey Jarvis** or **Wake up Jarvis**, or clap twice. Press **Pause listening** to stop the microphone, or launch with `./Jarvis.command --no-voice` to keep it paused. Speak a command, stop speaking, and Jarvis submits it after two seconds of silence. Adjust the pause with `JARVIS_SILENCE_TIMEOUT=3.0` or `JARVIS_SILENCE_TIMEOUT=1.0`.

### Claude through OmniRoute

Jarvis can use your local OmniRoute gateway as its brain while keeping microphone capture, TTS, and desktop tools local:

```bash
export JARVIS_PROVIDER=omniroute
export OPENAI_BASE_URL=http://127.0.0.1:20128/v1
export OPENAI_API_KEY='your-local-omniroute-key'
export OPENAI_MODEL='agy/claude-opus-4-6-thinking'
python main.py
```

Use the model name exposed by your gateway. Keep the key in the environment and never commit it. The gateway may forward requests to an upstream provider, so this mode is not fully offline. Remove those variables to return to Ollama.

---

## 🚀 Features

| Category | Capability |
|---|---|
| 🧠 **AI Brain** | Local LLM via Ollama — runs `qwen3.5`, `llama3.1`, `mistral-nemo`, and more |
| 🎤 **Voice Input** | Always-on GUI listening with local Whisper and automatic submit after a pause |
| 🔊 **Voice Output** | Offline macOS TTS through the built-in `say` command (Samantha by default) |
| 🌐 **Web** | DuckDuckGo search + full-page scraping |
| 🖥️ **App Control** | Open, quit, switch, and list macOS applications via AppleScript, including Spotify playback |
| 🔧 **Shell** | Run terminal commands (with confirmation gate before execution) |
| 📁 **Files** | List, read, write, and find files across the filesystem |
| ⌨️ **Automation** | Type text, press key combos, move/click mouse, take screenshots |
| 🔔 **System** | Volume control, clipboard R/W, battery status, lock screen, notifications |
| 💾 **Memory** | Persistent key-value memory — remember facts across sessions |
| 🖼️ **Desktop GUI** | Native webview with streaming chat, light/dark themes, voice controls, and a runtime model picker |

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
│   ├── apps.py           ← app control plus Spotify playback
│   ├── shell.py          ← run_shell (with confirmation guard)
│   ├── files.py          ← list_dir, read_file, write_file, find_files
│   ├── keyboard.py       ← type_text, press_keys, mouse_click, mouse_move, get_screen_size
│   ├── screen.py         ← take_screenshot
│   ├── system.py         ← volume, clipboard, battery, lock_screen, notifications
│   └── memory.py         ← remember, recall, list_memory, forget
│
├── voice/
│   ├── listen.py         ← ContinuousListener — VAD + faster-whisper transcription
│   └── speak.py          ← TTS output via macOS `say`
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
 Ollama or ChatOpenAI ──→ Bound with ALL_TOOLS (via bind_tools)
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
| **langchain-openai** | `>=0.3.0` | Optional OpenAI-compatible client for OmniRoute and other gateways |
| **[Ollama](https://ollama.ai)** | latest | Default local LLM runtime — serves models like `qwen3.5`, `llama3.1` via REST |

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
3. Audio is buffered until `JARVIS_SILENCE_TIMEOUT` seconds of quiet (default 2.0s) is detected.
4. The buffered `float32` array is passed to `faster-whisper` (default model: `base`) for transcription.
5. While TTS is speaking, the listener suppresses all audio to prevent self-echo.

### Text-to-Speech (TTS)

| Library | Version | Role |
|---|---|---|
| **macOS `say`** | built in | Offline TTS using the selected macOS system voice |

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
git clone https://github.com/sumitkumarraju/jarvis.git
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
ollama pull qwen3.5:latest

# Or try other compatible models:
ollama pull llama3.1
ollama pull qwen2.5
ollama pull mistral-nemo
```

> **Note:** First voice run downloads the Whisper checkpoint. The default `base` model is multilingual; use `WHISPER_MODEL=tiny.en` for the smallest English-only setup.

---

## 🎮 Usage

### Desktop GUI (Recommended)

**Easiest:** double-click `Jarvis.command` in Finder. The launcher runs from this project folder and creates a local `.venv` with the required dependencies on first launch. Python 3.11 is preferred when available; set `JARVIS_PYTHON` to override the setup interpreter. No global Python packages are installed. First-time setup needs internet access, and microphone permissions may be requested when you enable voice.

Or launch from Terminal:

```bash
cd "/Users/skr/Documents/New project/jarvis"
./Jarvis.command                # GUI with voice enabled automatically
./Jarvis.command --no-voice     # GUI with microphone paused
./jarvis --no-voice              # Same GUI, portable terminal launcher
python main.py                  # GUI with voice enabled (activate .venv first)
python main.py --no-voice        # GUI with voice disabled
```

**Switch models without restarting:**

1. Under **Model & connection**, select a provider.
2. Choose a discovered model, or select **Enter a custom model…** and type the exact model ID.
3. Click **Apply model**. The active model appears above the chat, and the conversation is retained.

**Refresh** queries your configured Ollama or OpenAI-compatible endpoint; it does not start servers or download models. If discovery fails, the interface shows a connection error and still allows a custom model ID. Run `ollama serve` and `ollama pull <model>` separately when needed. Model application configures the client; availability and tool support are ultimately verified when you send a request.

Gateway providers use the existing `OPENAI_BASE_URL` and `OPENAI_API_KEY` environment variables. The interface never requests, displays, or saves your key. Models should support tool calling to perform desktop actions. Changes and conversation reset are disabled while Jarvis is responding.

**Voice and chat:**

- Voice starts automatically. **Start listening / Pause listening** controls the microphone; the meter reflects actual audio input.
- The voice panel shows microphone warm-up, **Waiting for a wake phrase or clap**, **Awake. Say your command**, **Hearing you**, and transcription so preparation is not mistaken for recognition.
- Under **Wake-up method**, choose **Always listen / manual toggle** (default), **Wake phrase or double clap**, **Wake phrase only**, or **Double clap only**.
- Say **“Hey Jarvis, open Safari”** in one utterance, or say **“Wake up Jarvis”**, pause, then give a command. **“Jarvis”** alone also works. A wake signal arms one command for 12 seconds; after the command or timeout, Jarvis waits for another wake signal.
- Clap **twice**, about 0.12–0.8 seconds apart, then say your command. Clap detection uses loud audio impulses, not a dedicated sound classifier, so other loud paired sounds can also wake it. Tune `JARVIS_CLAP_THRESHOLD` if necessary.
- To use only the manual toggle, select **Always listen / manual toggle**, then use **Start listening / Pause listening**. A paused microphone cannot hear a wake phrase or clap. In wake modes the microphone stays on to detect activation; this is not an OS-level wake-from-sleep feature.
- The first voice session may download the configured Whisper checkpoint.
- Type a message and press **Enter** to send; **Shift+Enter** adds a line break.
- The suggestion buttons fill the composer; review the command before sending it.
- Shell actions ask for approval in a **native desktop dialog**, not a hidden terminal prompt. Denial or a closed dialog never executes the command; the text REPL keeps its original terminal prompt.
- **Stop speech** (or **Esc**) stops spoken audio only, not an in-progress model request or tool action.
- **New conversation** clears chat history. **⌘N** is the shortcut; **⌘Shift+V** toggles voice.
- The theme button switches light/dark appearance; the initial theme follows your system.

Opening `webui/index.html` in a browser is a **visual preview only**. Real chat, model discovery, and voice need the native desktop app.

### Laya reactive + processing architecture

Whisper still handles speech recognition. **Laya 0.3.20** adds a local System 1 decision layer for explicit short commands: Spotify play/pause/next/previous, and opening Safari, Notes, Spotify, or Calculator. A confident Laya decision must match a fixed allowlist before a native tool runs. Negated, compound, uncertain, and parameterized requests go to the selected Ollama or OpenAI-compatible model (System 2). Reactive actions preserve chat history and never bypass shell confirmation.

The first reactive command loads a Laya checkpoint and may be slower; subsequent decisions reuse the loaded model. The composer status shows loading/routing/fallback. If Laya cannot load or is uncertain, normal model processing remains available. Laya does not generate open-ended replies or replace Whisper. Dependency/checkpoint setup may need internet access on a new installation; this Mac uses the existing local Laya checkout and cached checkpoint.

If the microphone cannot start, allow the launching terminal/Python app in **System Settings > Privacy & Security > Microphone**. In the default wake mode say **“Hey Jarvis, open Safari”** and pause for two seconds; in **Always listen / manual toggle**, no wake phrase is required. If the meter moves but **Hearing you** never appears, try `JARVIS_VAD_THRESHOLD=0.006 ./Jarvis.command`; if room noise prevents submission, increase the threshold instead.

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

Connection endpoints, API keys, voice options, and safety settings use **environment variables**. Set them in your shell profile (`~/.zshrc`) or prefix commands with them. Provider/model selection is also available in the GUI; its last selection is saved locally (no credentials). Explicit model/provider environment variables override saved GUI preferences on the next launch. Finder launches do not necessarily inherit your shell profile, so launch from your configured Terminal when using a gateway.

| Variable | Default | Description |
|---|---|---|
| `JARVIS_PROVIDER` | `ollama` | `ollama`, `openai`, `omniroute`, or `claude` |
| `JARVIS_MODEL` | `qwen3.5:latest` | Ollama model name to use |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `OPENAI_BASE_URL` | `http://127.0.0.1:20128/v1` | OpenAI-compatible endpoint |
| `OPENAI_API_KEY` | empty | Key for the selected OpenAI-compatible endpoint |
| `OPENAI_MODEL` | `agy/claude-opus-4-6-thinking` | Model sent to the OpenAI-compatible endpoint |
| `WHISPER_MODEL` | `base` | Whisper model size: `tiny.en`, `base`, `small` |
| `WHISPER_LANGUAGE` | auto | Optional language code; empty enables automatic detection |
| `WHISPER_DEVICE` | `cpu` | Whisper inference device: `cpu` or `cuda` |
| `WHISPER_COMPUTE` | `int8` | Compute type: `int8`, `float16`, `float32` |
| `JARVIS_SILENCE_TIMEOUT` | `2.0` | Seconds of silence before the voice command is submitted |
| `JARVIS_VAD_THRESHOLD` | `0.012` | RMS energy threshold for voice activity detection |
| `JARVIS_WAKE_MODE` | `always` | `always`, `phrase_or_clap`, `phrase`, or `clap`; also changeable in the GUI for the current session |
| `JARVIS_CLAP_THRESHOLD` | `0.08` | RMS threshold for each of the two clap-like impulses |
| `JARVIS_VOICE` | `Samantha` | macOS TTS voice name |
| `JARVIS_RATE` | `210` | TTS speech rate (words per minute) |
| `JARVIS_CONFIRM_SHELL` | `1` | Set to `0` to disable shell command confirmation prompts |
| `JARVIS_WORKDIR` | `$HOME` | Base directory for relative file path operations |

### Example `.env`-style setup

```bash
export JARVIS_MODEL=llama3.1
export WHISPER_MODEL=base
export JARVIS_SILENCE_TIMEOUT=2.0
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
| `spotify_playback(action)` | Open Spotify and play, pause, skip, or go to the previous track |

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
| `qwen3.5` ⭐ | ✅ | Excellent | Default local model — fast, accurate tool use |
| `qwen2.5` | ✅ | Excellent | Great alternative |
| `llama3.1` | ✅ | Very Good | Solid all-rounder |
| Claude through OmniRoute | ✅ | Excellent | Optional OpenAI-compatible provider; requires a running gateway and valid key |
| `mistral-nemo` | ✅ | Good | Lightweight option |
| Small distilled models | ❌ | Poor | Often fail to call tools correctly |

> **Tip:** Smaller/distilled models frequently fail to emit properly formatted tool calls, causing the agent to silently fall back to text replies. Stick to the models in the table above.

---

## 🗺️ Roadmap

- [ ] Multi-modal support (image input via LLaVA)
- [ ] Calendar & reminders integration (EventKit)
- [x] Spotify / music control via AppleScript
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
