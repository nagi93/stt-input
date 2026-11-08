"""Settings window (tkinter), opened from the tray.

Three tabs — 基本 / 認識 / 整形 — covering every user-facing config
key.  Values are validated before saving; saving persists to
config.json, applies live-applicable settings immediately (microphone,
trigger, formatting flags), and rebuilds the recognition engine in
place when engine settings changed (refused mid-dictation — then the
saved values take effect on next start, and the window says so).

The value mapping/validation helpers are pure and unit-tested; only
``open_settings`` touches tkinter.
"""
from __future__ import annotations

from .config import Config, save_config

# Changing any of these requires rebuilding the engine clients.
ENGINE_FIELDS = {
    "engine", "fallback_to_local", "stt_url", "stt_transport",
    "streaming", "whisper_model", "whisper_device", "whisper_compute",
}

MODELS = ["auto", "large-v3-turbo", "large-v3", "medium", "small", "base"]
DEVICES = ["auto", "cuda", "cpu"]
COMPUTES = ["auto", "float16", "int8_float16", "int8"]
TRANSPORTS = ["auto", "direct", "wsl"]

EDITABLE_FIELDS = [
    "engine", "stt_url", "stt_transport", "streaming", "fallback_to_local",
    "mic_name", "trigger", "suppress_trigger",
    "whisper_model", "whisper_device", "whisper_compute",
    "partial_interval_seconds", "min_press_ms", "max_seconds",
    "remove_fillers", "voice_commands", "aggressive_commands",
    "click_to_focus", "restore_clipboard",
    "polish_enabled", "polish_base_url", "polish_model",
]


def values_from_cfg(cfg: Config) -> dict:
    return {key: getattr(cfg, key) for key in EDITABLE_FIELDS}


def validate(values: dict) -> list[str]:
    errors: list[str] = []
    if values["engine"] not in ("haas", "local"):
        errors.append("エンジンの値が不正です。")
    url = str(values["stt_url"]).strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        errors.append("サーバーURLは http:// か https:// で始めてください。")
    if values["stt_transport"] not in TRANSPORTS:
        errors.append("サーバー接続方式の値が不正です。")
    if values["trigger"] not in ("xbutton1", "xbutton2", "both"):
        errors.append("トリガーボタンの値が不正です。")
    if values["whisper_model"] not in MODELS:
        errors.append("モデルの値が不正です。")
    if values["whisper_device"] not in DEVICES:
        errors.append("デバイスの値が不正です。")
    if values["whisper_compute"] not in COMPUTES:
        errors.append("計算精度の値が不正です。")
    if not (0 <= int(values["min_press_ms"]) <= 2000):
        errors.append("最小押下は 0〜2000 ミリ秒で指定してください。")
    if not (10 <= float(values["max_seconds"]) <= 600):
        errors.append("最大録音は 10〜600 秒で指定してください。")
    if not (0.3 <= float(values["partial_interval_seconds"]) <= 5.0):
        errors.append("ライブ表示の間隔は 0.3〜5.0 秒で指定してください。")
    polish_url = str(values["polish_base_url"]).strip()
    if polish_url and not (polish_url.startswith("http://")
                            or polish_url.startswith("https://")):
        errors.append("LLM整形のURLは http:// か https:// で始めてください。")
    return errors


def apply_values(cfg: Config, values: dict) -> set[str]:
    """Copy validated values into cfg; returns the set of changed keys."""
    changed: set[str] = set()
    for key in EDITABLE_FIELDS:
        new = values[key]
        if getattr(cfg, key) != new:
            setattr(cfg, key, new)
            changed.add(key)
    return changed


def mic_choices() -> list[tuple[str, str]]:
    """(display label, mic_name value) pairs for the microphone picker."""
    from .audio import input_device_names

    choices = [("自動（Windowsの既定）", "")]
    for name in input_device_names():
        key = name
        for known in ("AG06", "AG03"):
            if known in name:
                key = known
                break
        choices.append((name, key))
    return choices


# ------------------------------------------------------------------ UI
def open_settings(root, cfg: Config, app, hook) -> None:
    import tkinter as tk
    from tkinter import ttk

    existing = getattr(root, "_settings_win", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        existing.focus_force()
        return

    win = tk.Toplevel(root)
    root._settings_win = win
    win.title("stt-input 設定")
    win.resizable(False, False)
    win.attributes("-topmost", True)

    current = values_from_cfg(cfg)
    vars: dict[str, tuple[object, str]] = {}

    def var(key, kind, initial):
        if kind == "bool":
            v = tk.BooleanVar(value=bool(initial))
        elif kind == "int":
            v = tk.IntVar(value=int(initial))
        elif kind == "float":
            v = tk.DoubleVar(value=float(initial))
        else:
            v = tk.StringVar(value=str(initial))
        vars[key] = (v, kind)
        return v

    def grid_row(parent, row, label, widget):
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=10, pady=5)
        widget.grid(row=row, column=1, sticky="ew", padx=10, pady=5)
        parent.columnconfigure(1, weight=1)

    notebook = ttk.Notebook(win)
    notebook.pack(fill="both", expand=True, padx=8, pady=8)

    # ---- 基本 ------------------------------------------------------------
    tab = ttk.Frame(notebook)
    notebook.add(tab, text="基本")
    r = 0
    ttk.Label(tab, text="認識エンジン").grid(
        row=r, column=0, sticky="w", padx=10, pady=5)
    engine_box = ttk.Frame(tab)
    engine_box.grid(row=r, column=1, sticky="w", padx=10, pady=5)
    ev = var("engine", "str", current["engine"])
    ttk.Radiobutton(engine_box, text="Haasサーバー優先 (siniku)",
                    variable=ev, value="haas").pack(side="left")
    ttk.Radiobutton(engine_box, text="ローカル認識のみ",
                    variable=ev, value="local").pack(side="left", padx=8)
    r += 1
    grid_row(tab, r, "サーバーURL",
             ttk.Entry(tab, textvariable=var("stt_url", "str",
                                             current["stt_url"]), width=34))
    r += 1
    grid_row(tab, r, "サーバー接続方式",
             ttk.Combobox(tab, textvariable=var("stt_transport", "str",
                                                current["stt_transport"]),
                          values=TRANSPORTS, state="readonly", width=12))
    r += 1
    for key, label in (
            ("streaming", "ストリーミングでライブ表示する"),
            ("fallback_to_local", "サーバーが落ちたらローカル認識に切り替える")):
        ttk.Checkbutton(tab, text=label,
                        variable=var(key, "bool", current[key])).grid(
            row=r, column=0, columnspan=2, sticky="w", padx=10, pady=3)
        r += 1
    choices = mic_choices()
    mic_display = {value: label for label, value in choices}
    mic_var = var("mic_name", "str", current["mic_name"])
    mic_combo = ttk.Combobox(tab, state="readonly", width=34,
                             values=[label for label, _ in choices])
    mic_combo.set(mic_display.get(current["mic_name"],
                                  "自動（Windowsの既定）"))
    grid_row(tab, r, "マイク", mic_combo)
    r += 1
    ttk.Label(tab, text="トリガーボタン").grid(
        row=r, column=0, sticky="w", padx=10, pady=5)
    trig_box = ttk.Frame(tab)
    trig_box.grid(row=r, column=1, sticky="w", padx=10, pady=5)
    tv = var("trigger", "str", current["trigger"])
    for value, label in (("xbutton1", "戻る側"), ("xbutton2", "進む側"),
                         ("both", "両方")):
        ttk.Radiobutton(trig_box, text=label, variable=tv,
                        value=value).pack(side="left", padx=2)
    r += 1
    ttk.Checkbutton(tab, text="ボタンの本来の動作（戻る/進む）を止める",
                    variable=var("suppress_trigger", "bool",
                                 current["suppress_trigger"])).grid(
        row=r, column=0, columnspan=2, sticky="w", padx=10, pady=3)

    # ---- 認識 ------------------------------------------------------------
    tab = ttk.Frame(notebook)
    notebook.add(tab, text="認識")
    r = 0
    for key, label, values in (
            ("whisper_model", "ローカルモデル", MODELS),
            ("whisper_device", "実行デバイス", DEVICES),
            ("whisper_compute", "計算精度", COMPUTES)):
        grid_row(tab, r, label,
                 ttk.Combobox(tab, textvariable=var(key, "str", current[key]),
                              values=values, state="readonly", width=16))
        r += 1
    grid_row(tab, r, "ライブ表示の間隔（秒）",
             ttk.Spinbox(tab, from_=0.3, to=5.0, increment=0.1, width=8,
                         textvariable=var("partial_interval_seconds",
                                          "float",
                                          current["partial_interval_seconds"])))
    r += 1
    grid_row(tab, r, "最小押下（ミリ秒）",
             ttk.Spinbox(tab, from_=0, to=2000, increment=50, width=8,
                         textvariable=var("min_press_ms", "int",
                                          current["min_press_ms"])))
    r += 1
    grid_row(tab, r, "最大録音（秒）",
             ttk.Spinbox(tab, from_=10, to=600, increment=10, width=8,
                         textvariable=var("max_seconds", "float",
                                          current["max_seconds"])))
    r += 1
    ttk.Label(tab, text="モデルを変えると、初回はダウンロードで"
                        "数分かかることがあります。",
              foreground="#888").grid(row=r, column=0, columnspan=2,
                                      sticky="w", padx=10, pady=5)

    # ---- 整形 ------------------------------------------------------------
    tab = ttk.Frame(notebook)
    notebook.add(tab, text="整形・貼り付け")
    r = 0
    for key, label in (
            ("remove_fillers", "フィラー（えーと等）を除去する"),
            ("voice_commands", "音声コマンド（くてん・とうてん・かいぎょう）"),
            ("aggressive_commands", "文中の「まる」「てん」も変換する（誤変換あり）"),
            ("click_to_focus", "離した場所をクリックしてから貼り付ける"),
            ("restore_clipboard", "貼り付け後にクリップボードを元に戻す"),
            ("polish_enabled", "LLM整形を使う（任意）")):
        ttk.Checkbutton(tab, text=label,
                        variable=var(key, "bool", current[key])).grid(
            row=r, column=0, columnspan=2, sticky="w", padx=10, pady=3)
        r += 1
    grid_row(tab, r, "LLMエンドポイント",
             ttk.Entry(tab, width=34,
                       textvariable=var("polish_base_url", "str",
                                        current["polish_base_url"])))
    r += 1
    grid_row(tab, r, "LLMモデル名",
             ttk.Entry(tab, width=34,
                       textvariable=var("polish_model", "str",
                                        current["polish_model"])))

    # ---- footer ----------------------------------------------------------
    footer = ttk.Frame(win)
    footer.pack(fill="x", padx=8, pady=(0, 8))
    message = ttk.Label(footer, text="", foreground="#c0272d", wraplength=420)
    message.pack(side="left", fill="x", expand=True)

    label_to_mic = {label: value for label, value in choices}

    def collect() -> dict | None:
        values = {}
        for key, (v, kind) in vars.items():
            try:
                raw = v.get()
            except tk.TclError:
                message.config(text=f"「{key}」の入力が不正です。")
                return None
            if kind == "int":
                values[key] = int(raw)
            elif kind == "float":
                values[key] = float(raw)
            elif kind == "bool":
                values[key] = bool(raw)
            else:
                values[key] = str(raw)
        values["mic_name"] = label_to_mic.get(mic_combo.get(), "")
        return values

    def on_save():
        values = collect()
        if values is None:
            return
        errors = validate(values)
        if errors:
            message.config(text=" ".join(errors))
            return
        changed = apply_values(cfg, values)
        save_config(cfg)
        # Live-applicable settings take effect immediately.
        app.recorder.device = cfg.mic_device
        app.recorder.device_name = cfg.mic_name
        hook.watched = cfg.watched_buttons
        hook.suppress = cfg.suppress_trigger
        if changed & ENGINE_FIELDS:
            if not app.rebuild_engine():
                message.config(
                    text="保存しました。録音中のため、エンジン設定は"
                         "次回起動時に反映されます。",
                    foreground="#888")
                return
        app.overlay.show_result("✓ 設定を保存しました", 1.0)
        win.destroy()

    ttk.Button(footer, text="キャンセル",
               command=win.destroy).pack(side="right", padx=4)
    ttk.Button(footer, text="保存", command=on_save).pack(side="right")
    win.protocol("WM_DELETE_WINDOW", win.destroy)
