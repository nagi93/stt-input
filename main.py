#!/usr/bin/env python3
"""Muse Voice Paste (stt-input) — push-to-talk dictation for Windows.

Hold the mouse side button, speak, release: the formatted transcript is
pasted into whatever is under the cursor.  Speech recognition runs
locally with faster-whisper (the installer picks the model size from
this PC's GPU/RAM); no WSL and no server are required.  An optional
engine can still use the WSL Haas-ja server on siniku.

Run:  pythonw main.py     (tray resident; close from the tray menu)
      python  main.py     (same, with a console for debugging)
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from voice_paste.config import load_config  # noqa: E402


def main() -> int:
    if sys.platform != "win32":
        print("This app runs on Windows (it uses the Win32 mouse hook).",
              file=sys.stderr)
        return 2

    import tkinter as tk

    from voice_paste.app import VoicePasteApp
    from voice_paste.overlay import Overlay
    from voice_paste.win32_input import PushToTalkHook

    cfg = load_config()
    root = tk.Tk()
    root.withdraw()  # only the overlay toplevel and the tray are visible
    root.title("Muse Voice Paste")

    overlay = Overlay(root)
    app = VoicePasteApp(cfg, overlay)

    hook = PushToTalkHook(on_xbutton=app.on_xbutton,
                          on_escape=app.on_escape,
                          watched=cfg.watched_buttons,
                          suppress=cfg.suppress_trigger)
    hook.start()
    if not hook.installed.wait(timeout=5) or hook.install_error:
        # Never fail silently: with pythonw there is no console, so
        # surface a dead hook on the overlay as well as stderr.
        print(f"hook install failed: {hook.install_error}", file=sys.stderr)
        overlay.show_result("⚠ ボタンのフックを登録できませんでした", 3.0)

    _start_tray(root, app, hook, cfg)
    root.mainloop()
    return 0


# ------------------------------------------------------------ tray settings
from voice_paste.audio import input_device_names  # noqa: E402,F401  (re-export)


def apply_mic_choice(cfg, app, name: str, path=None) -> None:
    """Select the microphone by name (\"\" = system default).

    Applied live (the recorder resolves the name on every start) and
    persisted to config.json.
    """
    from voice_paste.config import save_config

    cfg.mic_name = name
    cfg.mic_device = None
    app.recorder.device = None
    app.recorder.device_name = name
    save_config(cfg, path)


def apply_trigger_choice(cfg, hook, value: str, path=None) -> None:
    """Select the push-to-talk button; applied live and persisted."""
    from voice_paste.config import save_config

    cfg.trigger = value
    hook.watched = cfg.watched_buttons
    save_config(cfg, path)


def build_tray_menu(root, app, hook, cfg):
    """Tray menu: status, settings window, mic/trigger quick pickers."""
    import pystray

    def on_status(icon, item):
        icon.notify(app.describe_engine(), "Muse Voice Paste")

    def on_settings(icon, item):
        from voice_paste.settings_ui import open_settings
        root.after(0, lambda: open_settings(root, cfg, app, hook))

    def on_quit(icon, item):
        icon.stop()
        root.after(0, root.destroy)

    def mic_item(name: str, label: str):
        def choose(icon, item):
            apply_mic_choice(cfg, app, name)
            icon.update_menu()
        return pystray.MenuItem(
            label, choose,
            checked=lambda item: cfg.mic_name == name, radio=True)

    mic_entries = [mic_item("", "自動（Windowsの既定）")]
    for dev_name in input_device_names():
        # The stored value is a short unique substring of the device
        # name; the menu shows the full name.
        key = dev_name
        for known in ("AG06", "AG03"):
            if known in dev_name:
                key = known
                break
        mic_entries.append(mic_item(key, dev_name))

    def trigger_item(value: str, label: str):
        def choose(icon, item):
            apply_trigger_choice(cfg, hook, value)
            icon.update_menu()
        return pystray.MenuItem(
            label, choose,
            checked=lambda item: cfg.trigger == value, radio=True)

    return pystray.Menu(
        pystray.MenuItem("STT接続を確認", on_status),
        pystray.MenuItem("設定...", on_settings),
        pystray.MenuItem("マイク", pystray.Menu(*mic_entries)),
        pystray.MenuItem("トリガーボタン", pystray.Menu(
            trigger_item("xbutton1", "サイドボタン（戻る）"),
            trigger_item("xbutton2", "サイドボタン（進む）"),
            trigger_item("both", "両方"))),
        pystray.MenuItem("終了", on_quit))


def _start_tray(root, app, hook, cfg) -> None:
    """System-tray icon (pystray) on its own thread; tkinter stays main."""
    try:
        from PIL import Image, ImageDraw
        import pystray
    except ImportError:
        return  # tray is optional; the app still works without it

    image = Image.new("RGB", (64, 64), "#1e1e24")
    draw = ImageDraw.Draw(image)
    draw.ellipse([14, 8, 50, 44], fill="#e5484d")   # mic body
    draw.rectangle([28, 40, 36, 54], fill="#e5484d")
    draw.rectangle([18, 54, 46, 58], fill="#e5484d")

    icon = pystray.Icon("muse-voice-paste", image, "Muse Voice Paste",
                        menu=build_tray_menu(root, app, hook, cfg))
    threading.Thread(target=icon.run, daemon=True, name="tray").start()


if __name__ == "__main__":
    raise SystemExit(main())
