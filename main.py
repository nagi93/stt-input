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

    _start_tray(root, app)
    root.mainloop()
    return 0


def _start_tray(root, app) -> None:
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

    def on_status(icon, item):
        icon.notify(app.describe_engine(), "Muse Voice Paste")

    def on_quit(icon, item):
        icon.stop()
        root.after(0, root.destroy)

    icon = pystray.Icon("muse-voice-paste", image, "Muse Voice Paste",
                        menu=pystray.Menu(
                            pystray.MenuItem("STT接続を確認", on_status),
                            pystray.MenuItem("終了", on_quit)))
    threading.Thread(target=icon.run, daemon=True, name="tray").start()


if __name__ == "__main__":
    raise SystemExit(main())
