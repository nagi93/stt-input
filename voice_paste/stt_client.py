"""Client for an external STT server (Haas-ja + RE-USE, e.g. in WSL).

The server API provides everything this app needs:

  POST /transcribe   body = audio file bytes -> {"ok": true, "text": "..."}
  GET  /health       -> {"ok": true}
  WebSocket (any path on the same port):
      client {"type": "start", "session": "<id>"} + binary PCM16 16 kHz mono
             + {"type": "stop"}
      server {"type": "partial", "committed": "...", "pending": "..."}
             {"type": "final", "text": "..."} / {"type": "error", ...}

Access pattern: try a direct HTTP request to 127.0.0.1:8790 first, and
if that fails fall back to ``wsl.exe ... curl`` because WSL's localhost
port relay can hang
after the server restarts.  The WebSocket path is direct-only; if it cannot
connect, the caller records locally and uses the batch path instead.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
import wave

DEFAULT_URL = "http://127.0.0.1:8790"
SAMPLE_RATE = 16000


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class SttError(RuntimeError):
    pass


class SttClient:
    def __init__(self, base_url: str = DEFAULT_URL, transport: str = "auto",
                 wsl_distro: str = "Ubuntu", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.transport = transport  # auto | direct | wsl
        self.wsl_distro = wsl_distro
        self.timeout = timeout

    # -- batch ---------------------------------------------------------
    def health(self) -> bool:
        try:
            with urllib.request.urlopen(self.base_url + "/health", timeout=3) as r:
                return bool(json.loads(r.read().decode("utf-8")).get("ok"))
        except Exception:
            return False

    def transcribe_wav(self, wav_bytes: bytes) -> str:
        errors = []
        if self.transport in ("auto", "direct"):
            try:
                return self._transcribe_direct(wav_bytes)
            except Exception as err:  # fall through to the wsl route
                errors.append(f"direct: {err}")
                if self.transport == "direct":
                    raise SttError(errors[-1]) from err
        if self.transport in ("auto", "wsl"):
            if sys.platform != "win32":
                raise SttError("wsl transport is Windows-only; " + "; ".join(errors))
            try:
                return self._transcribe_wsl(wav_bytes)
            except Exception as err:
                errors.append(f"wsl: {err}")
        raise SttError("STT server unreachable (" + "; ".join(errors) + ")")

    def transcribe_pcm(self, pcm: bytes) -> str:
        return self.transcribe_wav(pcm_to_wav(pcm))

    def _transcribe_direct(self, wav_bytes: bytes) -> str:
        req = urllib.request.Request(
            self.base_url + "/transcribe", data=wav_bytes, method="POST",
            headers={"Content-Type": "application/octet-stream", "Expect": ""})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            result = json.loads(r.read().decode("utf-8"))
        return _text_from_result(result)

    def _transcribe_wsl(self, wav_bytes: bytes) -> str:
        command = [
            "wsl.exe", "-d", self.wsl_distro, "--",
            "curl", "--silent", "--show-error",
            "--connect-timeout", "3", "--max-time", str(int(self.timeout)),
            "-H", "Content-Type: application/octet-stream", "-H", "Expect:",
            "--data-binary", "@-", self.base_url + "/transcribe",
        ]
        done = subprocess.run(command, input=wav_bytes, capture_output=True,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if done.returncode != 0:
            raise SttError(done.stderr.decode("utf-8", "replace").strip()
                           or f"curl exited {done.returncode}")
        try:
            result = json.loads(done.stdout.decode("utf-8"))
        except ValueError as err:
            raise SttError(f"invalid STT response: {done.stdout[:200]!r}") from err
        return _text_from_result(result)


def _text_from_result(result: dict) -> str:
    if not result.get("ok"):
        raise SttError(str(result.get("error") or "unknown STT error"))
    return (result.get("text") or "").strip()


# -- streaming -----------------------------------------------------------
class StreamClient:
    """Persistent WebSocket connection to the same STT server.

    The connection is kept open while the app idles, so pressing the talk
    button only has to send ``{"type": "start"}`` — no connect latency in
    the push-to-talk path, and the stream final is produced from the full
    streamed audio (the server runs it through RE-USE + Haas).  The server
    accepts a new session on the same connection after each final.  If the
    connection is down, ``start()`` tries one reconnect and otherwise
    returns False; the caller then relies on the local recording + batch
    transcription.
    """

    def __init__(self, base_url: str = DEFAULT_URL, connect_timeout: float = 2.0):
        import threading

        self.base_url = base_url
        self.connect_timeout = connect_timeout
        self._ws = None
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._done.set()
        self._final: str | None = None
        self._error: str | None = None
        self._on_partial = None
        self._active = False

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def ensure_connected(self) -> bool:
        if self._ws is not None:
            return True
        import threading

        try:
            from websockets.sync.client import connect
        except ImportError:
            return False
        ws_url = (self.base_url.replace("http://", "ws://")
                  .replace("https://", "wss://") + "/")
        try:
            self._ws = connect(ws_url, open_timeout=self.connect_timeout,
                               max_size=16 * 1024 * 1024)
        except Exception:
            self._ws = None
            return False
        threading.Thread(target=self._recv_loop, daemon=True).start()
        return True

    def start(self, on_partial) -> bool:
        """Begin a streaming session.  False = streaming unavailable."""
        if not self.ensure_connected():
            return False
        with self._lock:
            self._final = None
            self._error = None
            self._on_partial = on_partial
            self._done.clear()
            self._active = True
            try:
                self._ws.send(json.dumps({"type": "start",
                                          "session": uuid.uuid4().hex}))
            except Exception:
                self._active = False
                self._ws = None
                return False
        return True

    def _recv_loop(self) -> None:
        ws = self._ws
        try:
            for raw in ws:
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                kind = msg.get("type")
                if kind == "partial":
                    if self._on_partial and self._active:
                        self._on_partial(msg.get("committed", ""),
                                         msg.get("pending", ""))
                elif kind == "final":
                    self._final = (msg.get("text") or "").strip()
                    self._active = False
                    self._done.set()
                elif kind == "error":
                    self._error = str(msg.get("message") or "stream error")
                    self._active = False
                    self._done.set()
        except Exception as err:  # connection dropped
            if self._active and self._final is None and self._error is None:
                self._error = f"stream closed: {err}"
            self._active = False
            self._done.set()
        finally:
            if self._ws is ws:
                self._ws = None

    def send_pcm(self, chunk: bytes) -> None:
        if self._ws is not None and self._active:
            try:
                self._ws.send(chunk)
            except Exception:
                pass  # the batch fallback still has the local recording

    def finish(self, timeout: float = 30.0) -> str:
        """Send stop and wait for the final text.  Raises SttError."""
        if self._ws is None or not self._active:
            raise SttError("stream not active")
        try:
            self._ws.send(json.dumps({"type": "stop"}))
        except Exception as err:
            raise SttError(f"stream stop failed: {err}") from err
        if not self._done.wait(timeout):
            raise SttError("stream final timed out")
        if self._error:
            raise SttError(self._error)
        return self._final or ""

    def abort(self) -> None:
        """Drop the connection; the server discards the open session."""
        self._active = False
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws = None
        self._done.set()
