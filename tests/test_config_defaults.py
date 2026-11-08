"""Defaults: Haas-first on siniku, local as the prepared fallback."""
from voice_paste.config import Config


def test_default_engine_is_haas_with_local_fallback():
    cfg = Config()
    assert cfg.engine == "haas"
    assert cfg.fallback_to_local is True


def test_resolved_model_auto_uses_env_detect():
    cfg = Config()  # whisper_* all "auto"
    model, device, compute = cfg.resolved_model()
    assert model and device and compute
