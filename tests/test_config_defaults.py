"""Defaults: server-first (Haas), local as the prepared fallback."""
from voice_paste.config import Config, load_config, save_config


def test_default_engine_is_haas_with_local_fallback():
    cfg = Config()
    assert cfg.engine == "haas"
    assert cfg.fallback_to_local is True


def test_resolved_model_auto_uses_env_detect():
    cfg = Config()  # whisper_* all "auto"
    model, device, compute = cfg.resolved_model()
    assert model and device and compute


def test_local_engine_defaults():
    cfg = Config()
    assert cfg.local_engine == "auto"
    assert cfg.haas_cpu_format == "int4-onecomp"
    assert cfg.haas_cpu_threads == 4


def test_local_engine_keys_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(local_engine="haas-cpu", haas_cpu_format="int8",
                       haas_cpu_threads=2), path)
    loaded = load_config(path)
    assert loaded.local_engine == "haas-cpu"
    assert loaded.haas_cpu_format == "int8"
    assert loaded.haas_cpu_threads == 2
