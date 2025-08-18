"""
llm_provider.py
~~~~~~~~~~~~~~~~~

This module defines the LLM class used throughout the project to
communicate with a language model.  It supports both local (Ollama)
and remote (OpenAI or any compatible endpoint) providers and is
configured via environment variables.  The ask_json method wraps
ask() to enforce a strict JSON output from the model.

Environment variables:

* ``LLM_PROVIDER`` – either ``ollama`` (default) or ``openai``.
* ``OLLAMA_MODEL`` – the name of the local model to use (default: ``llama3.1:8b``).
* ``OPENAI_MODEL`` – the name of the OpenAI model to use (default: ``gpt-4o``).
* ``OPENAI_API_KEY`` – API key for OpenAI or a compatible service.
* ``OPENAI_BASE_URL`` – optional base URL to override the default.

When running locally, be sure to have ``ollama`` installed and the
chosen model pulled.  See the README for details.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional


class LLM:
    """Simple abstraction over local and remote language models."""

    def __init__(self) -> None:
        # Determine which provider to use based on environment variables.
        self.provider: str = os.getenv("LLM_PROVIDER", "ollama").lower()
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self.openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.openai_base_url: Optional[str] = os.getenv("OPENAI_BASE_URL") or None
        self.openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY") or None

        if self.provider == "openai" and not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY must be set when LLM_PROVIDER=openai"
            )

    @staticmethod
    def _as_messages(system_prompt: str, user_prompt: str) -> List[Dict[str, str]]:
        """Assemble messages for chat-based models."""
        msgs: List[Dict[str, str]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": user_prompt})
        return msgs

    def ask(self, system_prompt: str, user_prompt: str, *, temperature: float = 0.1) -> str:
        """
        Query the underlying language model with a system prompt and a user prompt.

        :param system_prompt: instructions for the assistant
        :param user_prompt: the user's question or request
        :param temperature: sampling temperature (model-specific)
        :return: raw model output as a string
        """
        messages = self._as_messages(system_prompt, user_prompt)

        if self.provider == "ollama":
            import ollama

            # For Ollama, call the chat API.  If the model has not been
            # pulled, this will trigger a download.  See README for details.
            resp = ollama.chat(
                model=self.ollama_model,
                messages=messages,
                options={"temperature": temperature},
            )
            return resp["message"]["content"]

        elif self.provider == "openai":
            from openai import OpenAI

            client = OpenAI(
                api_key=self.openai_api_key,
                base_url=self.openai_base_url,
            )
            resp = client.chat.completions.create(
                model=self.openai_model,
                messages=messages,
                temperature=temperature,
            )
            return resp.choices[0].message.content

        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {self.provider}")

    def ask_json(
        self, system_prompt: str, user_prompt: str, *, temperature: float = 0.1
    ) -> Dict[str, object]:
        """
        Ask the model to return structured JSON.  A wrapper around ask()
        that enforces a JSON-only response and parses it into Python objects.

        :raises json.JSONDecodeError: if the model output is not valid JSON
        """
        wrapper = (
            "\nВерни ТОЛЬКО JSON без пояснений и форматирования кода."
            " Например: {\"ok\": true}\n"
        )
        raw = self.ask(system_prompt + wrapper, user_prompt, temperature=temperature)
        # Strip code fences if model returned them
        cleaned = raw.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        return json.loads(cleaned)