"""Cursor-following status overlay (the "mouse hint").

A small borderless, always-on-top tkinter window that sits next to the
mouse cursor while dictating:

    🔴 録音中 0:03  ▂▄▆   (live partial text, tail)
    ⏳ 認識中…
    ✓ 入力しました
    ⚠ STTサーバーに接続できません

All updates arrive through a queue; a 50 ms ``after`` loop on the tkinter
thread drains it, moves the window to the cursor, and refreshes the timer
and level meter.  Other threads never touch tkinter directly.
"""
from __future__ import annotations

import queue
import time

_BARS = " ▂▃▄▅▆▇█"


class Overlay:
    def __init__(self, root):
        import tkinter as tk

        self._tk = tk
        self.root = root
        self.queue: queue.Queue = queue.Queue()
        self._visible = False
        self._started_at: float | None = None
        self._level = 0.0
        self._status = ""
        self._text = ""
        self._hide_at: float | None = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.92)
        except Exception:
            pass
        self.win.configure(bg="#1e1e24")
        self.label = tk.Label(
            self.win, text="", fg="#f2f2f2", bg="#1e1e24",
            font=("Yu Gothic UI", 10), justify="left", anchor="w",
            padx=10, pady=6)
        self.label.pack()
        self.win.withdraw()
        self.root.after(50, self._tick)

    # -- called from any thread -----------------------------------------
    def show_recording(self) -> None:
        self.queue.put(("recording",))

    def update_partial(self, committed: str, pending: str) -> None:
        self.queue.put(("partial", committed, pending))

    def update_level(self, level: float) -> None:
        self._level = level

    def show_processing(self) -> None:
        self.queue.put(("status", "⏳ 認識中…"))

    def show_result(self, message: str, seconds: float = 0.9) -> None:
        self.queue.put(("flash", message, seconds))

    def hide(self) -> None:
        self.queue.put(("hide",))

    # -- tkinter thread ---------------------------------------------------
    def _tick(self) -> None:
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "recording":
                    self._started_at = time.monotonic()
                    self._status = "🔴 録音中"
                    self._text = ""
                    self._hide_at = None
                    self._visible = True
                elif kind == "partial":
                    self._text = (item[1] + item[2]).strip()
                elif kind == "status":
                    self._status = item[1]
                    self._started_at = None
                    self._visible = True
                elif kind == "flash":
                    self._status = item[1]
                    self._text = ""
                    self._started_at = None
                    self._hide_at = time.monotonic() + item[2]
                    self._visible = True
                elif kind == "hide":
                    self._visible = False
                    self._started_at = None
        except queue.Empty:
            pass

        if self._hide_at and time.monotonic() >= self._hide_at:
            self._visible = False
            self._hide_at = None

        if self._visible:
            self._render()
        else:
            self.win.withdraw()
        self.root.after(50, self._tick)

    def _render(self) -> None:
        from .win32_input import get_cursor_pos

        lines = []
        header = self._status
        if self._started_at is not None:
            elapsed = time.monotonic() - self._started_at
            bar = _BARS[min(len(_BARS) - 1, int(self._level * len(_BARS)))]
            header += f"  {elapsed:0.0f}秒 {bar}"
        lines.append(header)
        if self._text:
            tail = self._text[-46:]
            lines.append(tail)
        self.label.config(text="\n".join(lines))
        x, y = get_cursor_pos()
        self.win.geometry(f"+{x + 18}+{y + 24}")
        self.win.deiconify()
        self.win.lift()
