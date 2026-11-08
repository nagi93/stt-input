"""PC environment detection and STT model selection.

The installer (and first run) uses this to pick a faster-whisper model
that fits the machine, so the same app works on a gaming PC and on a
plain laptop without WSL or a remote server:

    VRAM >= 10 GB            large-v3-turbo / CUDA float16
    VRAM >= 4.5 GB           large-v3-turbo / CUDA int8_float16
    other NVIDIA GPU         small          / CUDA int8_float16
    no GPU, RAM >= 16 GB
      and >= 8 CPU threads   medium         / CPU int8
    no GPU, otherwise        small          / CPU int8
    very small RAM (< 6 GB)  base           / CPU int8

``detect()`` does the probing; ``select_model()`` is a pure function of
the probe result so the tier table is unit-testable anywhere.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class EnvInfo:
    gpu_name: str | None = None
    vram_mb: int | None = None
    ram_mb: int = 0
    cpu_threads: int = 1


@dataclass
class ModelChoice:
    model: str
    device: str        # "cuda" | "cpu"
    compute_type: str  # faster-whisper compute type
    tier: str

    def describe(self) -> str:
        return f"{self.tier}: {self.model} on {self.device} ({self.compute_type})"


def _detect_gpu() -> tuple[str | None, int | None]:
    try:
        done = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    for line in done.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0], int(parts[1])
    return None, None


def _detect_ram_mb() -> int:
    if sys.platform == "win32":
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.ullTotalPhys // (1024 * 1024))
        return 0
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size // (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        return 0


def detect() -> EnvInfo:
    gpu_name, vram_mb = _detect_gpu()
    return EnvInfo(gpu_name=gpu_name, vram_mb=vram_mb,
                   ram_mb=_detect_ram_mb(),
                   cpu_threads=os.cpu_count() or 1)


def select_model(env: EnvInfo) -> ModelChoice:
    if env.vram_mb is not None and env.gpu_name:
        if env.vram_mb >= 10000:
            return ModelChoice("large-v3-turbo", "cuda", "float16", "gpu-high")
        if env.vram_mb >= 4500:
            return ModelChoice("large-v3-turbo", "cuda", "int8_float16", "gpu-mid")
        return ModelChoice("small", "cuda", "int8_float16", "gpu-low")
    if env.ram_mb and env.ram_mb < 6000:
        return ModelChoice("base", "cpu", "int8", "cpu-minimal")
    if env.ram_mb >= 16000 and env.cpu_threads >= 8:
        return ModelChoice("medium", "cpu", "int8", "cpu-high")
    return ModelChoice("small", "cpu", "int8", "cpu-standard")
