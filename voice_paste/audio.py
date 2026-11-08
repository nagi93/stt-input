"""Microphone capture: 16 kHz / mono / int16 PCM via sounddevice.

Every captured chunk is (a) appended to a local buffer — the batch STT
fallback always has the full recording — and (b) handed to an optional
callback, which the app uses to feed the streaming session.  A running RMS
level is exposed for the overlay meter.
"""
from __future__ import annotations

import threading

import numpy as np

SAMPLE_RATE = 16000
BLOCK_SAMPLES = 3200  # 200 ms


def input_device_names() -> list[str]:
    """Unique names of available input devices (for settings pickers)."""
    try:
        import sounddevice as sd
    except Exception:
        return []
    names: list[str] = []
    for dev in sd.query_devices():
        if dev["max_input_channels"] > 0 and dev["name"] not in names:
            names.append(dev["name"])
    return names


def find_input_device(name_part: str) -> int | None:
    """Index of an input device whose name contains ``name_part``.

    PortAudio indices are NOT stable across processes (re-enumeration
    can reorder them — observed live on siniku, where the same AG06
    moved between indices minutes apart), so a stored integer rots.
    WASAPI is preferred for low latency.  Returns None when no match.
    """
    import sounddevice as sd

    matches = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name_part in dev["name"]:
            hostapi = sd.query_hostapis(dev["hostapi"])["name"]
            matches.append((0 if "WASAPI" in hostapi else 1, idx))
    if not matches:
        return None
    matches.sort()
    return matches[0][1]


class Recorder:
    def __init__(self, on_chunk=None, device: int | None = None,
                 device_name: str = ""):
        self.on_chunk = on_chunk
        self.device = device
        self.device_name = device_name
        self._chunks: list[bytes] = []
        self._lock = threading.Lock()
        self._stream = None
        self.level = 0.0  # 0.0 - 1.0, latest block RMS (smoothed)

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def _resolve_device(self) -> int | None:
        if self.device is not None:
            return self.device
        if self.device_name:
            return find_input_device(self.device_name)
        return None

    def start(self) -> None:
        import sounddevice as sd  # imported lazily: not needed for tests

        with self._lock:
            self._chunks = []
            self.level = 0.0

        def callback(indata, frames, time_info, status):
            data = bytes(indata)
            with self._lock:
                self._chunks.append(data)
            if len(data) >= 2:
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(samples ** 2))) / 32768.0 if len(samples) else 0.0
                self.level = min(1.0, max(rms * 2.5, self.level * 0.6))
            if self.on_chunk is not None:
                self.on_chunk(data)

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=BLOCK_SAMPLES, device=self._resolve_device(),
            callback=callback)
        self._stream.start()

    def stop(self) -> bytes:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            return b"".join(self._chunks)

    def snapshot(self) -> bytes:
        """All audio captured so far, without stopping (for partials)."""
        with self._lock:
            return b"".join(self._chunks)

    @property
    def seconds(self) -> float:
        with self._lock:
            total = sum(len(c) for c in self._chunks)
        return total / 2 / SAMPLE_RATE
