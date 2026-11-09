"""Haas CPU (ONNX) local engine: selection rule, UTF-8 guard, failure paths."""
import pytest

from voice_paste.config import Config
from voice_paste.haas_cpu_stt import HaasCpuEngine, _require_utf8_mode
from voice_paste.local_stt import LocalSttError


@pytest.mark.parametrize("setting, has_cuda, expected", [
    ("auto", True, "whisper"),
    ("auto", False, "haas-cpu"),
    ("whisper", False, "whisper"),
    ("whisper", True, "whisper"),
    ("haas-cpu", True, "haas-cpu"),
    ("haas-cpu", False, "haas-cpu"),
])
def test_resolved_local_kind(setting, has_cuda, expected):
    assert Config(local_engine=setting).resolved_local_kind(has_cuda) == expected


def test_require_utf8_mode():
    with pytest.raises(LocalSttError):
        _require_utf8_mode(0)
    _require_utf8_mode(1)  # no error


def test_missing_models_dir_raises_on_ensure_loaded(tmp_path):
    engine = HaasCpuEngine(tmp_path / "does-not-exist")
    assert engine.device == "cpu" and engine.fell_back_to_cpu is False
    assert "int4-onecomp" in engine.model_name
    with pytest.raises(LocalSttError, match="not installed"):
        engine.ensure_loaded(timeout=10)


def test_short_audio_returns_empty_without_loading(tmp_path):
    engine = HaasCpuEngine(tmp_path / "does-not-exist")
    assert engine.transcribe_pcm(b"\x00\x00" * 1599) == ""
    assert not engine._ready.is_set()  # no load was attempted
