"""Local UI selection only; endpoints and credentials stay in the environment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import config


def preferences_path() -> Path:
    return Path.home() / ".jarvis" / "ui-settings.json"


def load_selection(path: Path | None = None) -> tuple[str, str]:
    path = path or preferences_path()
    saved = None
    try:
        with path.open(encoding="utf-8") as stream:
            raw = stream.read(4097)
        if len(raw) <= 4096:
            data = json.loads(raw)
            saved = config.validate_selection(data["provider"], data["model"])
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        pass
    provider = os.environ.get("JARVIS_PROVIDER", saved[0] if saved else config.JARVIS_PROVIDER)
    provider = provider.strip().lower()
    variable = "JARVIS_MODEL" if provider == "ollama" else "OPENAI_MODEL"
    model = os.environ.get(variable)
    if model is None:
        model = saved[1] if saved and saved[0] == provider else config.default_model(provider)
    return provider, model


def save_selection(provider: str, model: str, path: Path | None = None) -> None:
    provider, model = config.validate_selection(provider, model)
    path = path or preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".ui-settings-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"provider": provider, "model": model}, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # Never forward an environment credential to a redirect destination.
        return None


def discover_models(provider: str) -> dict:
    result = {"models": [], "provider": provider, "error": None}
    try:
        provider, _ = config.validate_selection(provider, "discovery")
        result["provider"] = provider
        if provider != "ollama" and not config.OPENAI_API_KEY:
            result["error"] = "Set OPENAI_API_KEY in the environment, then restart Jarvis."
            return result
        endpoint = config.OLLAMA_HOST if provider == "ollama" else config.OPENAI_BASE_URL
        parts = urlsplit(endpoint)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("Invalid endpoint")
        suffix = "/api/tags" if provider == "ollama" else "/models"
        url = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") + suffix, parts.query, ""))
        headers = {"Accept": "application/json"}
        if provider != "ollama":
            headers["Authorization"] = "Bearer " + config.OPENAI_API_KEY
        request = Request(url, headers=headers, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=5.0) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Response too large")
        data = json.loads(raw)
        entries = data["models" if provider == "ollama" else "data"]
        if not isinstance(entries, list):
            raise ValueError("Invalid model list")
        field = "name" if provider == "ollama" else "id"
        models = []
        for entry in entries:
            name = entry.get(field) if isinstance(entry, dict) else None
            if isinstance(name, str) and name.strip() and name not in models:
                models.append(name)
        result["models"] = models
    except Exception as error:
        if isinstance(error, HTTPError):
            error.close()
        result["error"] = "Model discovery unavailable. Check the configured endpoint, credentials, and running service."
    return result
