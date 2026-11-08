"""Tray settings: mic/trigger choices apply live and persist."""
import json
from pathlib import Path
from types import SimpleNamespace

import main as app_main
from voice_paste.config import Config, load_config, save_config


def test_save_load_roundtrip(tmp_path=None):
    path = Path("tests/_tmp_config.json")
    try:
        cfg = Config(mic_name="AG06", trigger="both", engine="local")
        save_config(cfg, path)
        loaded = load_config(path)
        assert loaded.mic_name == "AG06"
        assert loaded.trigger == "both"
        assert loaded.engine == "local"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["mic_name"] == "AG06"
    finally:
        path.unlink(missing_ok=True)


def test_apply_mic_choice():
    path = Path("tests/_tmp_config.json")
    try:
        cfg = Config()
        recorder = SimpleNamespace(device=5, device_name="")
        app = SimpleNamespace(recorder=recorder)
        app_main.apply_mic_choice(cfg, app, "AG06", path)
        assert cfg.mic_name == "AG06" and cfg.mic_device is None
        assert recorder.device is None and recorder.device_name == "AG06"
        assert load_config(path).mic_name == "AG06"
        app_main.apply_mic_choice(cfg, app, "", path)
        assert cfg.mic_name == "" and recorder.device_name == ""
    finally:
        path.unlink(missing_ok=True)


def test_apply_trigger_choice():
    path = Path("tests/_tmp_config.json")
    try:
        cfg = Config()
        hook = SimpleNamespace(watched={1})
        app_main.apply_trigger_choice(cfg, hook, "xbutton2", path)
        assert cfg.trigger == "xbutton2" and hook.watched == {2}
        app_main.apply_trigger_choice(cfg, hook, "both", path)
        assert hook.watched == {1, 2}
        assert load_config(path).trigger == "both"
    finally:
        path.unlink(missing_ok=True)
