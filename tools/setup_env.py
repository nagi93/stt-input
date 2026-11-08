#!/usr/bin/env python3
"""Environment-adaptive setup for stt-input.

Detects this PC's hardware, selects the faster-whisper model that fits
(see voice_paste/env_detect.py for the tier table), installs the CUDA
runtime libraries when an NVIDIA GPU tier was chosen, writes the choice
into config.json (preserving any other settings), and pre-downloads the
model so the first dictation is not spent waiting.

Usage:  python tools/setup_env.py [--no-download]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from voice_paste.env_detect import detect, select_model  # noqa: E402

CUDA_PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12"]


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
    config.update({
        "engine": "local",
        "whisper_model": choice.model,
        "whisper_device": choice.device,
        "whisper_compute": choice.compute_type,
    })
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"config.json に書き込みました: model={choice.model} "
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
