import os
import json
import subprocess
from pathlib import Path
from typing import Optional

class STT:
    """
    Локально: Vosk (офлайн), нужен скачанный rus-модельный каталог.
    Онлайн: OpenAI Whisper (если задан OPENAI_API_KEY). Выбирается автоматически.
    """

    def __init__(self):
        self.provider = (os.getenv("STT_PROVIDER") or "auto").lower()
        self.vosk_model_dir = os.getenv("VOSK_MODEL_DIR")  # напр. models/vosk-ru
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL") or None
        self.openai_stt_model = os.getenv("OPENAI_STT_MODEL") or "whisper-1"

    def _pick_provider(self) -> str:
        if self.provider in ("vosk", "openai"):
            return self.provider
        # auto: сначала Vosk при наличии модели, иначе OpenAI при наличии ключа
        if self.vosk_model_dir and Path(self.vosk_model_dir).exists():
            return "vosk"
        if self.openai_key:
            return "openai"
        raise RuntimeError("Нет доступного STT: укажи VOSK_MODEL_DIR или OPENAI_API_KEY")

    def transcribe(self, audio_path: str, lang: str = "ru") -> str:
        prov = self._pick_provider()
        if prov == "vosk":
            return self._transcribe_vosk(audio_path, lang=lang)
        else:
            return self._transcribe_openai(audio_path, lang=lang)

    def _transcribe_vosk(self, wav_path: str, lang: str = "ru") -> str:
        # Требует: pip install vosk, и скачанный VOSK_MODEL_DIR (русская модель)
        from vosk import Model, KaldiRecognizer
        import wave

        # Убедимся, что WAV моно 16k — если нет, перекодируем через ffmpeg
        fixed_path = self._ensure_wav_mono16k(wav_path)
        wf = wave.open(fixed_path, "rb")
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
                j = rec.Result()
                text = json.loads(j).get("text", "")
                if text:
                    result_text.append(text)
        wf.close()
        final = json.loads(rec.FinalResult()).get("text", "")
        if final:
            result_text.append(final)
        return " ".join(result_text).strip()

    def _transcribe_openai(self, audio_path: str, lang: str = "ru") -> str:
        from openai import OpenAI
        client = OpenAI(api_key=self.openai_key, base_url=self.openai_base_url)
        with open(audio_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model=self.openai_stt_model,
                file=f,
                language=lang
            )
        # resp.text у whisper-совместимых моделей
        return getattr(resp, "text", "").strip()

    @staticmethod
    def _ensure_wav_mono16k(src_path: str) -> str:
        # Конвертируем через ffmpeg (должен быть установлен в PATH)
        src = Path(src_path)
        if src.suffix.lower() == ".wav":
            # Попробуем всё равно перегнать, чтобы гарантировать параметры
            out = src.with_suffix(".mono16k.wav")
        else:
            out = src.with_suffix(".wav")
        cmd = ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-f", "wav", str(out)]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            raise RuntimeError(f"ffmpeg конверсия не удалась: {e}")
        return str(out)
