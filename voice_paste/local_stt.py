"""Local speech recognition with faster-whisper — no WSL, no server.

The model runs in-process on this PC (CUDA when available, CPU int8
otherwise; the installer picks the model size from the detected
hardware, see ``env_detect``).  If a CUDA load fails at runtime the
engine retries once on CPU int8 rather than failing the dictation.

Live partials reuse the same idea as the Haas streaming server: while
recording, the audio captured so far is re-transcribed about once a
second and stabilised with a character-level LocalAgreement-2, so the
overlay can show committed text plus a pending tail.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import numpy as np


class LocalSttError(RuntimeError):
    pass


def _cuda_bin_dirs() -> list[str]:
    """bin/ dirs of the pip-installed nvidia-*-cu12 wheels, if present."""
    if sys.platform != "win32":
        return []
    try:
        import nvidia  # namespace package from nvidia-*-cu12 wheels

        roots = list(nvidia.__path__)
    except ImportError:
        return []
    dirs = []
    for root in roots:
        for bin_dir in sorted(Path(root).glob("*/bin")):
            if bin_dir.is_dir():
                dirs.append(str(bin_dir))
    return dirs


def _add_cuda_dll_dirs() -> None:
    """Make pip-installed cuBLAS/cuDNN DLLs loadable on Windows.

    Both mechanisms are needed: CTranslate2's loader resolves
    cublas64_12.dll through the PATH, while dependent DLLs of those
    libraries are found through the add_dll_directory search list.
    Must run before ctranslate2/faster-whisper is imported.
    """
    for bin_dir in _cuda_bin_dirs():
        try:
            os.add_dll_directory(bin_dir)
        except OSError:
            pass
        if bin_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


class LocalAgreement:
    """Character-level LocalAgreement-2 for Japanese partial text."""

    def __init__(self) -> None:
        self.committed = ""
        self._prev = ""

    def reset(self) -> None:
        self.committed = ""
        self._prev = ""

    def update(self, text: str) -> tuple[str, str]:
        limit = min(len(self._prev), len(text))
        i = 0
        while i < limit and self._prev[i] == text[i]:
            i += 1
        if i > len(self.committed):
            self.committed = text[:i]
        self._prev = text
        if text.startswith(self.committed):
            return self.committed, text[len(self.committed):]
        return self.committed, text


class LocalEngine:
    def __init__(self, model: str, device: str, compute_type: str,
                 download_root: str | Path):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.download_root = str(download_root)
        self.fell_back_to_cpu = False
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
        _add_cuda_dll_dirs()
        from faster_whisper import WhisperModel

        try:
            self._model = WhisperModel(
                self.model_name, device=self.device,
                compute_type=self.compute_type,
                download_root=self.download_root)
        except Exception:
            if self.device != "cuda":
                raise
            # CUDA present at install time but unusable now: CPU int8.
            self.device = "cpu"
            self.compute_type = "int8"
            self.fell_back_to_cpu = True
            self._model = WhisperModel(
                self.model_name, device="cpu", compute_type="int8",
                download_root=self.download_root)

    def ensure_loaded(self, timeout: float = 120.0) -> None:
        if not self._ready.is_set():
            self.warm_async()
        if not self._ready.wait(timeout):
            raise LocalSttError("model load timed out")
        if self._model is None:
            raise LocalSttError(f"model load failed: {self._load_error}")

    # -- transcription -----------------------------------------------------
    def transcribe_pcm(self, pcm: bytes, *, fast: bool = False) -> str:
        self.ensure_loaded()
        if not self._busy.acquire(blocking=not fast):
            return ""  # a final is running; skip this partial tick
        try:
            audio = (np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
                     / 32768.0)
            if len(audio) < 1600:  # < 0.1 s: nothing to recognise
                return ""
            segments, _info = self._model.transcribe(
                audio, language="ja",
                beam_size=1 if fast else 5,
                vad_filter=not fast,
                condition_on_previous_text=False)
            return "".join(seg.text for seg in segments).strip()
        finally:
            self._busy.release()
