from __future__ import annotations

from typing import Any

import requests


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout_seconds: int = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def generate(self, *, model: str, prompt: str, options: dict[str, Any] | None = None) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if options:
            payload["options"] = options
        response = self.session.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code == 404:
            raise RuntimeError(self._unknown_model_message(model))
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        output = body.get("response", "")
        if not isinstance(output, str):
            raise RuntimeError("Ollama returned a non-string response")
        return output.strip()

    def list_models(self) -> list[str]:
        response = self.session.get(f"{self.base_url}/api/tags", timeout=self.timeout_seconds)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        models = body.get("models", [])
        names: list[str] = []
        for entry in models:
            name = entry.get("name") if isinstance(entry, dict) else None
            if isinstance(name, str):
                names.append(name)
        return sorted(names)

    def _unknown_model_message(self, model: str) -> str:
        try:
            available = self.list_models()
        except requests.RequestException:
            return (
                f"Ollama returned 404 for model '{model}'. The tag is not installed, "
                f"and listing available models also failed. Try: ollama list"
            )
        if not available:
            return (
                f"Ollama returned 404 for model '{model}'. No models are installed. "
                f"Pull one with: ollama pull <model>"
            )
        listing = "\n  - ".join(available)
        return (
            f"Ollama has no model tagged '{model}'. Available models:\n  - {listing}\n"
            f"Pull a new tag with: ollama pull {model}"
        )
