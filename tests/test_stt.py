from pathlib import Path

import stt


def test_pick_provider(monkeypatch, tmp_path):
    monkeypatch.delenv("VOSK_MODEL_DIR", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with monkeypatch.context() as m:
        m.setenv("STT_PROVIDER", "vosk")
        assert stt.STT().provider_in_use() == "vosk"
    with monkeypatch.context() as m:
        m.setenv("STT_PROVIDER", "auto")
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        m.setenv("VOSK_MODEL_DIR", str(model_dir))
        assert stt.STT().provider_in_use() == "vosk"
    with monkeypatch.context() as m:
        m.setenv("STT_PROVIDER", "auto")
        m.delenv("VOSK_MODEL_DIR", raising=False)
        m.setenv("OPENAI_API_KEY", "x")
        assert stt.STT().provider_in_use() == "openai"


def test_ensure_wav_calls_ffmpeg(monkeypatch, tmp_path):
    s = stt.STT()
    src = tmp_path / "a.mp3"
    src.write_bytes(b"data")
    calls = []
    def fake_run(cmd, check, stdout, stderr):
        calls.append(cmd)
    monkeypatch.setattr(stt.subprocess, "run", fake_run)
    out = s._ensure_wav_mono16k(str(src))
    assert Path(out).suffix == ".wav"
    assert calls == [[s.ffmpeg_bin, "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-f", "wav", out]]
