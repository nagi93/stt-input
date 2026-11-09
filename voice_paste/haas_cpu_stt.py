"""Local speech recognition with the Haas-ja ONNX port — CPU only.

The default local engine on PCs without an NVIDIA GPU, where it beats
CPU faster-whisper for Japanese.  The model is a community ONNX export
of Haas-ja downloaded by ``tools/setup_env.py`` into
``models/haas-onnx``; that folder ships its own Python package
(``haas_cpu``), which is imported lazily from there so the app core has
no hard dependency on onnxruntime.

UTF-8 caveat: the bundle reads a UTF-8 JSON file with the locale's
default encoding, so on Windows outside Python's UTF-8 mode (e.g. cp932
on Japanese Windows) it dies with UnicodeDecodeError.  ``main.py``
relaunches itself with PYTHONUTF8=1 when this engine may be used; the
load step refuses to proceed otherwise, with a clear error instead of a
decode traceback.

The surface mirrors ``LocalEngine`` (model_name / device /
fell_back_to_cpu, warm_async / ensure_loaded / transcribe_pcm) so the
app can use either engine in the same slot.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import numpy as np

from .local_stt import LocalSttError

SAMPLE_RATE = 16000
# The pipeline handles ~28 s per pass; longer audio goes through its
# chunking transcribe_long with some margin.
LONG_AUDIO_SECONDS = 25.0


def _require_utf8_mode(utf8_mode: int) -> None:
    """Refuse to load the bundle outside Python's UTF-8 mode."""
    if utf8_mode == 0:
        raise LocalSttError(
            "Haas CPU engine needs Python UTF-8 mode (PYTHONUTF8=1): its "
            "model files are read with the locale encoding otherwise and "
            "fail to decode. main.py relaunches in UTF-8 mode "
            "automatically; restart the app to fix this.")


class HaasCpuEngine:
    def __init__(self, models_dir: str | Path, fmt: str = "int4-onecomp",
                 threads: int = 4):
        self.models_dir = Path(models_dir)
        self.fmt = fmt
        self.threads = threads
        self.model_name = f"Haas-ja ONNX ({fmt})"
        self.device = "cpu"
        self.fell_back_to_cpu = False  # never on a GPU to fall back from
        self._model = None
        self._load_error: Exception | None = None
        self._ready = threading.Event()
        self._busy = threading.Lock()

    # -- loading ---------------------------------------------------------
    def warm_async(self) -> None:
        threading.Thread(target=self._load_guarded, daemon=True,
                         name="stt-load").start()

    def _load_guarded(self) -> None:
        try:
            self._load()
        except Exception as err:  # surfaced on first transcribe
            self._load_error = err
        finally:
            self._ready.set()

    def _load(self) -> None:
        if not (self.models_dir / "haas_cpu").is_dir():
            raise LocalSttError(
                f"Haas CPU model is not installed ({self.models_dir} has "
                "no haas_cpu package). Run tools/setup_env.py to download it.")
        # Must precede the import: the failure happens at load time.
        _require_utf8_mode(sys.flags.utf8_mode)
        bundle = str(self.models_dir)
        if bundle not in sys.path:
            sys.path.insert(0, bundle)
        from haas_cpu.pipeline import Transcriber

        self._model = Transcriber(models_dir=bundle, fmt=self.fmt,
                                  threads=self.threads)

    def ensure_loaded(self, timeout: float = 120.0) -> None:
        if not self._ready.is_set():
            self.warm_async()
        if not self._ready.wait(timeout):
            raise LocalSttError("model load timed out")
        if self._model is None:
            raise LocalSttError(f"model load failed: {self._load_error}")

    # -- transcription -----------------------------------------------------
    def transcribe_pcm(self, pcm: bytes, *, fast: bool = False) -> str:
        if len(pcm) // 2 < 1600:  # < 0.1 s: nothing to recognise
            return ""
        self.ensure_loaded()
        if not self._busy.acquire(blocking=not fast):
            return ""  # a final is running; skip this partial tick
        try:
            audio = (np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
                     / 32768.0)
            try:
                if len(audio) > LONG_AUDIO_SECONDS * SAMPLE_RATE:
                    result = self._model.transcribe_long(audio)
                else:
                    result = self._model.transcribe(audio)
            except Exception as err:
                raise LocalSttError(f"Haas CPU transcription failed: {err}") \
                    from err
            return (result.text or "").strip()
        finally:
            self._busy.release()
