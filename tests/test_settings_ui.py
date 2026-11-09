"""Settings window value mapping and validation (pure parts)."""
from voice_paste.config import Config
from voice_paste.settings_ui import (ENGINE_FIELDS, apply_values,
                                     validate, values_from_cfg)


def _valid_values():
    cfg = Config(engine="haas", stt_url="http://127.0.0.1:8790")
    return values_from_cfg(cfg)


def test_values_roundtrip():
    cfg = Config(mic_name="AG06", min_press_ms=500, polish_enabled=True)
    values = values_from_cfg(cfg)
    assert values["mic_name"] == "AG06"
    assert values["min_press_ms"] == 500
    assert values["polish_enabled"] is True
    other = Config()
    changed = apply_values(other, values)
    assert other.mic_name == "AG06" and other.min_press_ms == 500
    assert "mic_name" in changed and "min_press_ms" in changed
    assert apply_values(other, values) == set()  # idempotent


def test_validate_accepts_defaults():
    assert validate(_valid_values()) == []


def test_validate_rejects_bad_url_and_ranges():
    values = _valid_values()
    values["stt_url"] = "localhost:8790"
    values["min_press_ms"] = 99999
    values["partial_interval_seconds"] = 0.05
    values["max_seconds"] = 5
    errors = validate(values)
    assert len(errors) == 4


def test_engine_fields_cover_rebuild_triggers():
    for key in ("engine", "stt_url", "whisper_model", "streaming"):
        assert key in ENGINE_FIELDS
    assert "mic_name" not in ENGINE_FIELDS
    assert "remove_fillers" not in ENGINE_FIELDS


def test_validate_local_engine_choices():
    values = _valid_values()
    for engine in ("auto", "whisper", "haas-cpu"):
        values["local_engine"] = engine
        assert validate(values) == []
    for fmt in ("int4-onecomp", "int8", "fp32"):
        values["haas_cpu_format"] = fmt
        assert validate(values) == []
    values["local_engine"] = "gpu"
    values["haas_cpu_format"] = "int2"
    assert len(validate(values)) == 2


def test_local_engine_fields_rebuild_engine():
    assert {"local_engine", "haas_cpu_format"} <= ENGINE_FIELDS
