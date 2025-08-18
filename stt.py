"""
stt.py
~~~~~~

Speech-to-text abstraction supporting both offline (Vosk) and online
(OpenAI Whisper) transcription.  The provider is selected automatically or
can be forced via environment variables.  Audio files are converted
to a mono 16 kHz WAV using ffmpeg (configured via ``FFMPEG_BIN``).

Environment variables:

* ``STT_PROVIDER`` – ``auto`` (default), ``vosk`` or ``openai``.
* ``VOSK_MODEL_DIR`` – path to a Vosk model directory; required for
  offline transcription.
* ``OPENAI_API_KEY`` – API key for Whisper; used when provider is
  ``openai`` or auto selects it.
* ``OPENAI_BASE_URL`` – optional base URL for OpenAI-compatible endpoints.
* ``OPENAI_STT_MODEL`` – name of the Whisper model (default: ``whisper-1``).
* ``FFMPEG_BIN`` – path to the ffmpeg binary; defaults to ``ffmpeg``.

External dependencies: ``vosk`` (for offline) and ``openai``.

"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional


class STT:
    """Speech-to-text adapter selecting between Vosk and OpenAI Whisper."""

    def __init__(self) -> None:
        self.provider_setting = (os.getenv("STT_PROVIDER") or "auto").lower()
        self.vosk_model_dir: Optional[str] = os.getenv("VOSK_MODEL_DIR") or None
        self.openai_key: Optional[str] = os.getenv("OPENAI_API_KEY") or None
        self.openai_base_url: Optional[str] = os.getenv("OPENAI_BASE_URL") or None
        self.openai_stt_model: str = os.getenv("OPENAI_STT_MODEL") or "whisper-1"
        self.ffmpeg_bin: str = os.getenv("FFMPEG_BIN", "ffmpeg")

    def provider_in_use(self) -> str:
        """Return the effective provider (vosk or openai)."""
        return self._pick_provider()

    def _pick_provider(self) -> str:
        if self.provider_setting in ("vosk", "openai"):
            return self.provider_setting
        # auto mode: prefer Vosk if model dir exists, else test OpenAI
        if self.vosk_model_dir and Path(self.vosk_model_dir).exists():
            return "vosk"
        if self.openai_key and self._ping_openai():
            return "openai"
        raise RuntimeError(
            "No speech-to-text provider available: set VOSK_MODEL_DIR or OPENAI_API_KEY"
        )

    def transcribe(self, audio_path: str, *, lang: str = "ru") -> str:
        """Transcribe the given audio file and return the detected text."""
        provider = self._pick_provider()
        if provider == "vosk":
            return self._transcribe_vosk(audio_path, lang=lang)
        return self._transcribe_openai(audio_path, lang=lang)

    def _transcribe_vosk(self, wav_path: str, *, lang: str = "ru") -> str:
        """Perform offline transcription using Vosk."""
        try:
            from vosk import Model, KaldiRecognizer  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "Vosk is not installed; run `pip install vosk` to enable offline STT"
            ) from exc
        import wave

        # Ensure the audio is mono 16 kHz WAV
        fixed_path = self._ensure_wav_mono16k(wav_path)
        with wave.open(fixed_path, "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
                wf.close()
                fixed_path = self._ensure_wav_mono16k(fixed_path)
                wf = wave.open(fixed_path, "rb")

            model = Model(self.vosk_model_dir)
            rec = KaldiRecognizer(model, 16000)
            rec.SetWords(False)
            result_text = []
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    txt = result.get("text", "")
                    if txt:
                        result_text.append(txt)
            final = json.loads(rec.FinalResult()).get("text", "")
            if final:
                result_text.append(final)
            return " ".join(result_text).strip()

    def _transcribe_openai(self, audio_path: str, *, lang: str = "ru") -> str:
        """Perform transcription via OpenAI Whisper."""
        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "openai package is not installed; run `pip install openai`"
            ) from exc
        client = OpenAI(api_key=self.openai_key, base_url=self.openai_base_url)
        with open(audio_path, "rb") as f:
            try:
                resp = client.audio.transcriptions.create(
                    model=self.openai_stt_model,
                    file=f,
                    language=lang,
                )
            except Exception as exc:
                status = getattr(exc, "status_code", None) or getattr(
                    getattr(exc, "response", None), "status_code", None
                )
                if status == 403:
                    raise RuntimeError(
                        "OpenAI access forbidden (HTTP 403). "
                        "Set VOSK_MODEL_DIR to use the offline Vosk engine."
                    ) from exc
                raise
        return getattr(resp, "text", "").strip()

    def _ping_openai(self) -> bool:
        """Return True if OpenAI API responds successfully."""
        base = self.openai_base_url or "https://api.openai.com/v1"
        url = base.rstrip("/") + "/models"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.openai_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status < 400
        except Exception:
            return False

    def _ensure_wav_mono16k(self, src_path: str) -> str:
        """Ensure audio is a mono 16 kHz WAV.  Uses ffmpeg for conversion."""
        src = Path(src_path)
        # Determine output path: if source is already wav, produce a new tmp file
        if src.suffix.lower() == ".wav":
            out = src.with_suffix(
                ".mono16k.wav"
            )  # avoid overwriting original
        else:
            out = src.with_suffix(".wav")
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            str(out),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            raise RuntimeError(
                f"ffmpeg failed to convert audio: {exc}. Set FFMPEG_BIN if ffmpeg is not in PATH."
            )
        return str(out)
