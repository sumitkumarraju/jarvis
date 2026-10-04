from __future__ import annotations

from typing import Iterator, Callable
from uuid import uuid4

from agent.reactive import ReactiveRouter
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, AIMessageChunk
from langchain_core.tools import BaseTool

from config import (
    JARVIS_PROVIDER, OLLAMA_MODEL, OLLAMA_HOST,
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, validate_selection,
)

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
    def __init__(
        self, tools: list[BaseTool] | None = None, *,
        provider: str | None = None, model: str | None = None,
    ):
        self.provider = JARVIS_PROVIDER if provider is None else provider
        self.model = model if model is not None else (
            OLLAMA_MODEL if self.provider == "ollama" else OPENAI_MODEL
        )
        self.provider, self.model = validate_selection(self.provider, self.model)
        if self.provider != "ollama" and not OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is required when JARVIS_PROVIDER is openai/omniroute/claude"
            )
        if tools is None:
            from tools import ALL_TOOLS
            tools = ALL_TOOLS
        self.tools = tools
        if self.provider in {"openai", "omniroute", "claude"}:
            from langchain_openai import ChatOpenAI

            self.llm = ChatOpenAI(
                model=self.model,
                base_url=OPENAI_BASE_URL,
                api_key=OPENAI_API_KEY,
                temperature=0.2,
            ).bind_tools(self.tools)
        else:
            from langchain_ollama import ChatOllama

            self.llm = ChatOllama(
                model=self.model, base_url=OLLAMA_HOST, temperature=0.2, reasoning=False
            ).bind_tools(self.tools)
        self.tools_by_name = {t.name: t for t in self.tools}
        self.reactive = ReactiveRouter()
        self.history = [SystemMessage(content=SYSTEM_PROMPT)]

    def reset(self) -> None:
        self.history = [SystemMessage(content=SYSTEM_PROMPT)]

    def chat(self, user_text: str, max_steps: int = 6) -> str:
        self.history.append(HumanMessage(content=user_text))
        reply = self._react(user_text)
        if reply is not None:
            return reply
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
        reply = self._react(user_text, on_tool)
        if reply is not None:
            yield reply
            return

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

    def _react(self, text: str, on_tool=None) -> str | None:
        # Do not load a decision model unless a relevant native tool is available.
        if not {'spotify_playback', 'open_app'}.intersection(self.tools_by_name):
            return None
        action = self.reactive.decide(text)
        if action is None or action['tool'] not in self.tools_by_name:
            return None
        name, args = action['tool'], action['args']
        call_id = 'laya-' + uuid4().hex
        self.history.append(AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': call_id}]))
        if on_tool:
            on_tool(name, args)
        try:
            result = str(self.tools_by_name[name].invoke(args))
        except Exception as error:
            result = f'Error: {error}'
        self.history.append(ToolMessage(content=result, tool_call_id=call_id))
        reply = result if result.lower().startswith(('error:', 'tool error:')) else action['reply']
        self.history.append(AIMessage(content=reply))
        return reply

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
