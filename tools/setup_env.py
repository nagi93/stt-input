#!/usr/bin/env python3
"""Environment-adaptive setup for stt-input.

Probes the Haas STT server: when it answers (siniku), the app default
engine is "haas" with the local model as fallback; on PCs without the
server the default is "local".  Either way, this PC's hardware selects
the faster-whisper tier (see voice_paste/env_detect.py), the CUDA
runtime libraries are installed when an NVIDIA GPU tier was chosen, the
choices are written into config.json (preserving other settings), and
the local model is pre-downloaded so the first dictation — or the first
fallback — is not spent waiting.

Usage:  python tools/setup_env.py [--no-download]
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from voice_paste.env_detect import detect, select_model  # noqa: E402

CUDA_PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12"]
DEFAULT_STT_URL = "http://127.0.0.1:8790"


def haas_reachable(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health",
                                    timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> int:
    download = "--no-download" not in sys.argv
    env = detect()
    choice = select_model(env)
    print(f"GPU: {env.gpu_name or 'なし'}"
          + (f" (VRAM {env.vram_mb} MB)" if env.vram_mb else ""))
    print(f"RAM: {env.ram_mb} MB / CPU threads: {env.cpu_threads}")
    print(f"選択モデル: {choice.describe()}")

    if choice.device == "cuda":
        print("CUDA ライブラリをインストールします (cuBLAS / cuDNN)...")
        done = subprocess.run(
            [sys.executable, "-m", "pip", "install", *CUDA_PACKAGES])
        if done.returncode != 0:
            print("CUDA ライブラリのインストールに失敗しました。"
                  "CPU 動作に切り替えます。", file=sys.stderr)
            choice.device = "cpu"
            choice.compute_type = "int8"
            choice.tier += "->cpu-fallback"

    config_path = APP_DIR / "config.json"
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except ValueError:
            config = {}
    stt_url = config.get("stt_url", DEFAULT_STT_URL)
    engine = "haas" if haas_reachable(stt_url) else "local"
    print(f"Haasサーバー ({stt_url}): "
          + ("応答あり → 既定エンジン=haas (ローカルは予備)"
             if engine == "haas" else "応答なし → 既定エンジン=local"))
    config.update({
        "engine": engine,
        "whisper_model": choice.model,
        "whisper_device": choice.device,
        "whisper_compute": choice.compute_type,
    })
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"config.json に書き込みました: engine={engine} model={choice.model} "
          f"device={choice.device} compute={choice.compute_type}")

    if download:
        print("モデルをダウンロードします (初回のみ、回線により数分)...")
        from voice_paste.local_stt import LocalEngine

        engine = LocalEngine(choice.model, choice.device, choice.compute_type,
                             APP_DIR / "models")
        engine.ensure_loaded(timeout=1800)
        if engine.fell_back_to_cpu:
            print("注意: CUDA で読み込めなかったため CPU 動作になりました。")
            config["whisper_device"] = "cpu"
            config["whisper_compute"] = "int8"
            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2,
                           sort_keys=True) + "\n", encoding="utf-8")
        print("モデルの準備ができました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
