from typing import Iterator, Callable
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, AIMessageChunk
from langchain_core.tools import BaseTool

from config import (
    JARVIS_PROVIDER, OLLAMA_MODEL, OLLAMA_HOST,
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
)
from tools import ALL_TOOLS

SYSTEM_PROMPT = """You are Jarvis, a personal assistant running on the user's macOS laptop.

You have tools to:
- search the web and read pages
- open, quit, and switch macOS applications
- run shell commands (the user is asked to confirm)
- read, write, list, and find files
- control keyboard, mouse, screenshots, volume, clipboard
- control Spotify playback with the spotify_playback tool
- remember and recall facts across sessions

Behavior:
- Be concise. Replies are spoken aloud — short, natural, one or two sentences.
- When the user asks for an action, do it via tools. Don't just describe it.
- For short desktop commands, call the native tool immediately; do not explain a plan first.
- For Spotify play, pause, next, or previous requests, use spotify_playback instead of a shell command.
- Chain tool calls when needed. After tools return, give a brief spoken summary.
- If a request is ambiguous or destructive, ask one quick clarifying question.
- Never invent file paths or URLs. Use list_dir, find_files, or web_search to discover them.
"""


class Jarvis:
    def __init__(self, tools: list[BaseTool] | None = None):
        self.tools = tools or ALL_TOOLS
        if JARVIS_PROVIDER in {"openai", "omniroute", "claude"}:
            from langchain_openai import ChatOpenAI

            if not OPENAI_API_KEY:
                raise RuntimeError(
                    "OPENAI_API_KEY is required when JARVIS_PROVIDER is openai/omniroute/claude"
                )
            self.llm = ChatOpenAI(
                model=OPENAI_MODEL,
                base_url=OPENAI_BASE_URL,
                api_key=OPENAI_API_KEY,
                temperature=0.2,
            ).bind_tools(self.tools)
        else:
            self.llm = ChatOllama(
                model=OLLAMA_MODEL, base_url=OLLAMA_HOST, temperature=0.2, reasoning=False
            ).bind_tools(self.tools)
        self.tools_by_name = {t.name: t for t in self.tools}
        self.history = [SystemMessage(content=SYSTEM_PROMPT)]

    def reset(self) -> None:
        self.history = [SystemMessage(content=SYSTEM_PROMPT)]

    def chat(self, user_text: str, max_steps: int = 6) -> str:
        self.history.append(HumanMessage(content=user_text))
        for _ in range(max_steps):
            ai: AIMessage = self.llm.invoke(self.history)
            self.history.append(ai)
            if not ai.tool_calls:
                content = ai.content or ai.additional_kwargs.get("reasoning_content", "") or ""
                return content.strip()
            self._run_tools(ai)
        return "I hit the tool limit. Want me to continue?"

    def stream(
        self,
        user_text: str,
        on_tool: Callable[[str, dict], None] | None = None,
        max_steps: int = 6,
    ) -> Iterator[str]:
        """Yield text chunks as the model produces them. Runs tools transparently."""
        self.history.append(HumanMessage(content=user_text))

        for _ in range(max_steps):
            agg: AIMessageChunk | None = None
            text_so_far = ""
            for chunk in self.llm.stream(self.history):
                agg = chunk if agg is None else agg + chunk
                if chunk.content:
                    text_so_far += chunk.content
                    yield chunk.content

            if agg is None:
                return
            ai = AIMessage(
                content=agg.content or "",
                tool_calls=agg.tool_calls or [],
                additional_kwargs=agg.additional_kwargs or {},
            )
            self.history.append(ai)

            if not ai.tool_calls:
                if not text_so_far.strip():
                    fallback = ai.additional_kwargs.get("reasoning_content", "")
                    if fallback:
                        yield fallback
                return

            for call in ai.tool_calls:
                if on_tool:
                    try: on_tool(call["name"], call.get("args", {}))
                    except Exception: pass
            self._run_tools(ai)

    def _run_tools(self, ai: AIMessage) -> None:
        for call in ai.tool_calls:
            tool = self.tools_by_name.get(call["name"])
            if tool is None:
                result = f"Unknown tool: {call['name']}"
            else:
                try:
                    result = tool.invoke(call["args"])
                except Exception as e:
                    result = f"Tool error: {e}"
            self.history.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
