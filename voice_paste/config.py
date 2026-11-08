"""App configuration: a plain JSON file next to the entry point.

Copy ``config.example.json`` to ``config.json`` and edit.  Every key has a
sane default, so an empty file is valid.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .stt_client import DEFAULT_URL

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = APP_DIR / "config.json"


@dataclass
class Config:
    # Push-to-talk trigger: "xbutton1" (back), "xbutton2" (forward), "both"
    trigger: str = "xbutton1"
    # Swallow the XButton event so the browser does not navigate back/forward
    suppress_trigger: bool = True
    # Ignore presses shorter than this (accidental clicks)
    min_press_ms: int = 350
    max_seconds: float = 120.0

    # Recognition engine: "local" (faster-whisper on this PC, no WSL —
    # the default) or "haas" (the existing WSL Haas-ja server on siniku).
    engine: str = "local"
    # Local engine model. "auto" = chosen from the detected hardware at
    # first run (see env_detect); the installer writes concrete values.
    whisper_model: str = "auto"
    whisper_device: str = "auto"   # auto | cuda | cpu
    whisper_compute: str = "auto"  # auto | float16 | int8_float16 | int8
    partial_interval_seconds: float = 1.0

    # Optional Haas server engine (WSL, siniku only)
    stt_url: str = DEFAULT_URL
    stt_transport: str = "auto"  # auto | direct | wsl
    streaming: bool = True       # live partials in the overlay when possible

    # What happens on release
    click_to_focus: bool = True  # click the control under the cursor first
    restore_clipboard: bool = True

    # Formatter
    remove_fillers: bool = True
    voice_commands: bool = True
    aggressive_commands: bool = False

    # Optional LLM polish (OpenAI-compatible chat endpoint). Off by default:
    # the rule-based formatter keeps the release-to-paste path fast.
    polish_enabled: bool = False
    polish_base_url: str = ""
    polish_model: str = ""
    polish_api_key_env: str = "VOICE_PASTE_LLM_KEY"

    mic_device: int | None = None

    @property
    def watched_buttons(self) -> set[int]:
        return {"xbutton1": {1}, "xbutton2": {2}, "both": {1, 2}}.get(
            self.trigger, {1})

    def resolved_model(self) -> tuple[str, str, str]:
        """(model, device, compute_type) with "auto" resolved for this PC."""
        if "auto" not in (self.whisper_model, self.whisper_device,
                          self.whisper_compute):
            return self.whisper_model, self.whisper_device, self.whisper_compute
        from .env_detect import detect, select_model

        choice = select_model(detect())
        return (
            choice.model if self.whisper_model == "auto" else self.whisper_model,
            choice.device if self.whisper_device == "auto" else self.whisper_device,
            choice.compute_type if self.whisper_compute == "auto" else self.whisper_compute,
        )


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    cfg = Config()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    known = set(asdict(cfg))
    for key, value in data.items():
        if key in known:
            setattr(cfg, key, value)
    return cfg
