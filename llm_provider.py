import os
import json
from typing import List, Dict

def _as_messages(system_prompt: str, user_prompt: str) -> List[Dict[str, str]]:
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.append({"role": "user", "content": user_prompt})
    return msgs

class LLM:
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "ollama").lower()
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL") or None
        self.openai_api_key = os.getenv("OPENAI_API_KEY") or None

        if self.provider == "openai" and not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY не задан, а LLM_PROVIDER=openai")

    def ask(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        if self.provider == "ollama":
            import ollama
            resp = ollama.chat(
                model=self.ollama_model,
                messages=_as_messages(system_prompt, user_prompt),
                options={"temperature": temperature},
            )
            return resp["message"]["content"]

        elif self.provider == "openai":
            # OpenAI совместимый клиент (официальный SDK)
            from openai import OpenAI
            client = OpenAI(api_key=self.openai_api_key, base_url=self.openai_base_url)
            resp = client.chat.completions.create(
                model=self.openai_model,
                messages=_as_messages(system_prompt, user_prompt),
                temperature=temperature,
            )
            return resp.choices[0].message.content

        else:
            raise ValueError(f"Неизвестный LLM_PROVIDER: {self.provider}")

    def ask_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict:
        """
        Требует от модели вернуть строгий JSON (без подсказок и комментариев).
        """
        wrapper = f"""
Верни ТОЛЬКО JSON без пояснений и форматирования кода.
Например: {{"ok": true}}
"""
        text = self.ask(system_prompt + "\n" + wrapper, user_prompt, temperature=temperature)
        # На случай, если модель всё-таки добавила «```json ...```»
        text = text.strip().strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
        return json.loads(text)
