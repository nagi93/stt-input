"""Push-to-talk orchestration.

State machine:  IDLE -> RECORDING -> PROCESSING -> IDLE

Engines:
* ``haas`` (default when the server exists): an external Haas-ja +
  RE-USE STT server (WebSocket streaming + batch fallback).  A health
  monitor switches sessions to the local engine while it is down.
* ``local``: faster-whisper runs on this PC — no WSL, no server.
  While recording, a partial thread re-transcribes the audio captured
  so far about once a second and shows it in the overlay
  (LocalAgreement-stabilised); on release the full recording is
  transcribed once more at full quality.

* XButton down (hook thread): start recording.  Fast operations only —
  the hook callback must return immediately.
* XButton up (hook thread): hand the finish work to a worker thread.
* Worker: transcribe, format, optionally polish, then click-focus the
  control under the cursor and paste.
* Esc while recording cancels without pasting.
* Presses shorter than ``min_press_ms`` are discarded (accidental clicks).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from . import formatter, polish
from .audio import Recorder
from .config import APP_DIR, Config
from .local_stt import LocalAgreement, LocalEngine, LocalSttError
from .logutil import log_error, log_event
from .stt_client import StreamClient, SttClient, SttError


class VoicePasteApp:
    def __init__(self, cfg: Config, overlay):
        self.cfg = cfg
        self.overlay = overlay
        self.recorder = Recorder(on_chunk=self._on_chunk,
                                 device=cfg.mic_device,
                                 device_name=cfg.mic_name)
        self._state = "idle"
        self._lock = threading.Lock()
        self._active_button: int | None = None
        self._pressed_at = 0.0
        self._cancelled = False

        self.local: LocalEngine | None = None
        self.batch: SttClient | None = None
        self.stream: StreamClient | None = None
        self._streaming_live = False
        self._agreement = LocalAgreement()
        self._haas_up = True
        self._session_local = False
        self._used_fallback = False

        self._build_engine()
        threading.Thread(target=self._haas_monitor, daemon=True,
                         name="haas-monitor").start()

    def _build_engine(self) -> None:
        """(Re)create the engine clients from the current config."""
        cfg = self.cfg
        self.local = None
        self.batch = None
        self.stream = None
        if cfg.engine == "local" or cfg.fallback_to_local:
            model, device, compute = cfg.resolved_model()
            self.local = LocalEngine(model, device, compute,
                                     Path(APP_DIR) / "models")
            if cfg.engine == "local":
                self.local.warm_async()  # load while the user looks at the screen
        if cfg.engine == "haas":
            self.batch = SttClient(cfg.stt_url, cfg.stt_transport)
            if cfg.streaming:
                self.stream = StreamClient(cfg.stt_url)
                threading.Thread(target=self.stream.ensure_connected,
                                 daemon=True).start()
        self._haas_up = True

    def rebuild_engine(self) -> bool:
        """Apply engine-related settings without restarting the app.

        Refused while a dictation is in progress (returns False).
        """
        with self._lock:
            if self._state != "idle":
                return False
        if self.stream is not None:
            try:
                self.stream.abort()
            except Exception:
                pass
        self._build_engine()
        return True

    def is_busy(self) -> bool:
        with self._lock:
            return self._state != "idle"

    def _haas_monitor(self) -> None:
        """Track Haas server health; pre-load the local model if it drops."""
        while True:
            if self.cfg.engine != "haas" or self.batch is None:
                self._haas_up = True
                time.sleep(10)
                continue
            up = bool(self.batch.health())
            if self._haas_up and not up and self.local is not None:
                self.local.warm_async()  # be ready to take over
            self._haas_up = up
            time.sleep(10)

    def describe_engine(self) -> str:
        if self.cfg.engine == "local" and self.local is not None:
            where = self.local.device
            if self.local.fell_back_to_cpu:
                where = "cpu (cuda fallback)"
            return f"ローカル認識: {self.local.model_name} / {where}"
        state = "接続OK" if self._haas_up else "応答なし（ローカルで動作）"
        text = f"Haas優先: {state}"
        if self.local is not None:
            text += f" / 予備 {self.local.model_name}"
        return text

    # -- hook callbacks (must be fast) ------------------------------------
    def on_xbutton(self, button: int, pressed: bool, x: int, y: int) -> bool:
        if pressed:
            return self._press(button)
        return self._release(button)

    def on_escape(self) -> None:
        with self._lock:
            if self._state != "recording":
                return
            self._cancelled = True
            self._state = "idle"
        self.recorder.stop()
        if self.stream is not None:
            self.stream.abort()
        self.overlay.show_result("✕ キャンセル", 0.6)

    # -- internals ----------------------------------------------------------
    def _press(self, button: int) -> bool:
        with self._lock:
            if self._state != "idle":
                return self.cfg.suppress_trigger
            self._state = "recording"
            self._active_button = button
            self._pressed_at = time.monotonic()
            self._cancelled = False
            self._streaming_live = False
            self._used_fallback = False
            # Per-session engine: local when configured local-only, or
            # when the Haas server is currently down (fallback).
            self._session_local = self.local is not None and (
                self.cfg.engine == "local" or not self._haas_up)
        if not self._session_local and self.stream is not None:
            self._streaming_live = self.stream.start(self._on_partial)
        try:
            self.recorder.start()
        except Exception as exc:
            log_error("recorder.start", exc)
            with self._lock:
                self._state = "idle"
            if self.stream is not None:
                self.stream.abort()
            self.overlay.show_result("⚠ マイクを開けません", 1.2)
            return self.cfg.suppress_trigger
        log_event(f"press: engine={'local' if self._session_local else 'haas'} "
                  f"mic_device={self.recorder.active_device}")
        self.overlay.show_recording()
        threading.Thread(target=self._watchdog, daemon=True).start()
        if self._session_local:
            self._agreement.reset()
            threading.Thread(target=self._partial_loop, daemon=True).start()
        return self.cfg.suppress_trigger

    def _release(self, button: int) -> bool:
        with self._lock:
            if self._state != "recording" or button != self._active_button:
                return False
            self._state = "processing"
            held_ms = (time.monotonic() - self._pressed_at) * 1000
        threading.Thread(target=self._finish, args=(held_ms,),
                         daemon=True).start()
        return self.cfg.suppress_trigger

    def _watchdog(self) -> None:
        while True:
            time.sleep(0.5)
            with self._lock:
                if self._state != "recording":
                    return
                elapsed = time.monotonic() - self._pressed_at
            if elapsed >= self.cfg.max_seconds:
                with self._lock:
                    self._state = "processing"
                threading.Thread(
                    target=self._finish,
                    args=(self.cfg.max_seconds * 1000,), daemon=True).start()
                return

    def _partial_loop(self) -> None:
        """Local engine only: re-transcribe the buffer about once a second."""
        while True:
            time.sleep(self.cfg.partial_interval_seconds)
            with self._lock:
                if self._state != "recording":
                    return
            if self.recorder.seconds < 0.4 or self.recorder.seconds > 30:
                continue  # too short to read; too long makes re-reads costly
            try:
                text = self.local.transcribe_pcm(self.recorder.snapshot(),
                                                 fast=True)
            except LocalSttError:
                return
            if text:
                committed, pending = self._agreement.update(text)
                self.overlay.update_partial(committed, pending)

    def _on_chunk(self, data: bytes) -> None:
        self.overlay.update_level(self.recorder.level)
        if self._streaming_live and self.stream is not None:
            self.stream.send_pcm(data)

    def _on_partial(self, committed: str, pending: str) -> None:
        self.overlay.update_partial(committed, pending)

    def _transcribe(self, pcm: bytes) -> str:
        if self._session_local:
            return self.local.transcribe_pcm(pcm)
        raw = ""
        if self._streaming_live and self.stream is not None:
            try:
                raw = self.stream.finish(timeout=30.0)
            except SttError:
                raw = ""
        if not raw:
            try:
                raw = self.batch.transcribe_pcm(pcm)
            except SttError:
                if self.local is None:
                    raise
                # Last resort: the server died mid-session.
                self._used_fallback = True
                return self.local.transcribe_pcm(pcm)
        return raw

    def _finish(self, held_ms: float) -> None:
        from .win32_input import focus_and_paste, focused_edit_text, \
            foreground_title, get_cursor_pos, window_title_at

        try:
            pcm = self.recorder.stop()
            if self._cancelled:
                return
            if held_ms < self.cfg.min_press_ms or len(pcm) < 3200:
                if self.stream is not None:
                    self.stream.abort()
                self.overlay.hide()
                return
            self.overlay.show_processing()

            try:
                raw = self._transcribe(pcm)
            except (SttError, LocalSttError) as exc:
                log_error("transcribe", exc)
                if self._session_local:
                    self.overlay.show_result("⚠ 認識エンジンでエラーが発生しました", 1.4)
                else:
                    self.overlay.show_result("⚠ STTサーバーに接続できません", 1.4)
                return
            if self._cancelled:
                return
            log_event(f"transcribed: {raw!r}")

            text = formatter.format_text(
                raw, remove_fillers=self.cfg.remove_fillers,
                voice_commands=self.cfg.voice_commands,
                aggressive_commands=self.cfg.aggressive_commands)
            if not text:
                log_event("result empty after formatting")
                self.overlay.show_result("⚠ 聞き取れませんでした", 1.0)
                return
            if self.cfg.polish_enabled:
                text = polish.polish(text, self.cfg.polish_base_url,
                                     self.cfg.polish_model,
                                     self.cfg.polish_api_key_env)
            cx, cy = get_cursor_pos()
            log_event(f"paste: target={window_title_at(cx, cy)} "
                      f"at=({cx},{cy}) text={text!r}")
            # The overlay floats next to the cursor; hide it before
            # clicking so it can never be the window that receives the
            # click or the pasted keys.
            self.overlay.hide()
            try:
                used_method = focus_and_paste(
                    text, click_to_focus=self.cfg.click_to_focus,
                    restore_clipboard=self.cfg.restore_clipboard,
                    method=self.cfg.insert_method)
            except Exception as exc:
                log_error("paste", exc)
                self.overlay.show_result("⚠ 貼り付けに失敗しました", 1.4)
                return
            log_event(f"paste: done, foreground={foreground_title()} "
                      f"method={used_method}")
            try:
                landed = focused_edit_text()
                if landed is not None:
                    log_event(f"paste verify: edit contains text: "
                              f"{text[:20] in landed}")
            except Exception as exc:
                log_error("paste-verify", exc)
            note = ""
            if self.cfg.engine == "haas" and (self._session_local
                                              or self._used_fallback):
                note = "（ローカル認識）"
            self.overlay.show_result("✓ 入力しました" + note, 0.8)
        finally:
            with self._lock:
                self._state = "idle"
                self._active_button = None
