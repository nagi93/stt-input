import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_paste.env_detect import EnvInfo, select_model


def test_gpu_high():
    c = select_model(EnvInfo("RTX 4070 Ti", 12282, 32768, 16))
    assert (c.model, c.device, c.compute_type) == ("large-v3-turbo", "cuda", "float16")


def test_gpu_mid():
    c = select_model(EnvInfo("RTX 3060 Laptop", 6144, 16384, 8))
    assert (c.model, c.device, c.compute_type) == ("large-v3-turbo", "cuda", "int8_float16")


def test_gpu_low():
    c = select_model(EnvInfo("GTX 1650", 4096, 16384, 8))
    assert (c.model, c.device) == ("small", "cuda")


def test_cpu_high():
    c = select_model(EnvInfo(None, None, 32768, 16))
    assert (c.model, c.device, c.compute_type) == ("medium", "cpu", "int8")


def test_cpu_standard():
    c = select_model(EnvInfo(None, None, 16384, 4))
    assert (c.model, c.device) == ("small", "cpu")


def test_cpu_minimal_ram():
    c = select_model(EnvInfo(None, None, 4096, 4))
    assert (c.model, c.device) == ("base", "cpu")
