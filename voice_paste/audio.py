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


def mic_name_key(device_name: str) -> str:
    """Short, stable config key for a device name.

    Windows endpoint names wrap the distinctive part in parentheses
    (e.g. "Line (USB Audio Interface)"); that part is shared by every
    endpoint of the same physical device, while the full name varies
    by host API.  Falls back to the full name when there is none.
    """
    start = device_name.rfind("(")
    end = device_name.rfind(")")
    if 0 <= start < end:
        inner = device_name[start + 1:end].strip()
        if inner:
            return inner
    return device_name


def _candidate_sort_key(hostapi_name: str, default_samplerate: float):
    """Order endpoints of one physical device for a 16 kHz open.

    PortAudio's WASAPI backend does NOT resample: an endpoint whose
    native rate is not 16 kHz fails with PaErrorCode -9997 (observed
    live with a USB audio interface at 44.1 kHz).  DirectSound and MME go through
    the Windows resampler and accept 16 kHz, so they rank first;
    WASAPI ranks first only when its native rate already is 16 kHz;
    WDM-KS is last (its blocking API is unsupported by PortAudio).
    """
    api = hostapi_name.upper()
    if "WASAPI" in api:
        return (0, 0) if default_samplerate == 16000 else (2, 0)
    if "DIRECTSOUND" in api:
        return (0, 1)
    if "MME" in api:
        return (0, 2)
    if "WDM-KS" in api or "WDMKS" in api:
        return (3, 0)
    return (1, 0)


def find_input_devices(name_part: str) -> list[int]:
    """All endpoint indices matching ``name_part``, best first.

    PortAudio indices are NOT stable across processes (re-enumeration
    can reorder them — observed live, where the same USB audio
    interface moved between indices minutes apart), so a stored
    integer rots; the name is re-resolved on every recording start,
    and the caller tries each candidate until one opens.
    """
    import sounddevice as sd

    matches = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name_part in dev["name"]:
            hostapi = sd.query_hostapis(dev["hostapi"])["name"]
            key = _candidate_sort_key(hostapi, dev["default_samplerate"])
            matches.append((key, idx))
    matches.sort()
    return [idx for _, idx in matches]


def find_input_device(name_part: str) -> int | None:
    devices = find_input_devices(name_part)
    return devices[0] if devices else None


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
        self.active_device: int | None = None

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def _candidate_devices(self) -> list[int | None]:
        if self.device is not None:
            return [self.device]
        if self.device_name:
            return find_input_devices(self.device_name) or [None]
        return [None]

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

        # One physical mic appears as several endpoints (MME /
        # DirectSound / WASAPI / WDM-KS) and some cannot open at
        # 16 kHz; try each candidate until one opens.
        errors: list[str] = []
        last_exc: Exception | None = None
        for device in self._candidate_devices():
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                    blocksize=BLOCK_SAMPLES, device=device,
                    callback=callback)
                stream.start()
            except Exception as exc:
                errors.append(f"device={device}: {exc}")
                last_exc = exc
                continue
            self._stream = stream
            self.active_device = device
            return
        raise RuntimeError(
            "no candidate microphone could be opened (" +
            "; ".join(errors) + ")") from last_exc

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
