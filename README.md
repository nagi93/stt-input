# stt-input (Muse Voice Paste)

Windows 常駐のプッシュ・トゥ・トーク音声入力。**マウスのサイドボタンを押している間だけ録音し、離すと整形済みのテキストがカーソルの下の入力欄に貼り付く。** 音声認識はこの PC の中で完結する（faster-whisper）。**WSL もサーバーも不要。**

```
[サイドボタン押下] 録音開始 → カーソル横に 🔴録音中 + ライブ文字起こし
[話す]             整形ルールが効いた状態で認識
[離す]             確定 → 整形 → カーソル下のウィンドウをクリックでフォーカス → 貼り付け
```

## 環境に合わせたモデル選択

インストーラーが PC の環境（GPU / VRAM / RAM / CPU）を見て、認識モデルを自動で選ぶ。判断は `voice_paste/env_detect.py` のティア表：

| 環境 | モデル | 実行 |
|---|---|---|
| VRAM 10GB 以上 | large-v3-turbo | CUDA float16 |
| VRAM 4.5GB 以上 | large-v3-turbo | CUDA int8_float16 |
| その他の NVIDIA GPU | small | CUDA int8_float16 |
| GPUなし・RAM 16GB 以上・8スレッド以上 | medium | CPU int8 |
| GPUなし・その他 | small | CPU int8 |
| RAM 6GB 未満 | base | CPU int8 |

- GPU ティアでは CUDA ライブラリ（cuBLAS / cuDNN の pip パッケージ）も自動で入る。実行時に CUDA が使えなかった場合は CPU int8 に自動で落ちる（ dictation を失敗させない）。
- モデルは `models/` にダウンロードされる（初回のみ、数百MB〜約1.6GB）。
- 手動で固定したい場合は `config.json` の `whisper_model` / `whisper_device` / `whisper_compute` を `"auto"` 以外に変える。再判定は `python tools/setup_env.py` を再実行。

## ライブ表示の仕組み

録音中は約1秒ごとに「ここまでの音声」を再認識し、LocalAgreement（文字単位）で安定した部分を確定表示、揺れている末尾を pending としてオーバーレイに出す。離した瞬間に全体を高品質設定（beam 5 + VAD）で再認識して確定する。30秒を超える発話では再認識コストの都合でライブ表示は止まり、経過時間のみ表示する（確定認識は通常どおり行う）。

## インストール

1. Python 3.11+ を用意する。
2. `install.bat` を実行する。依存導入 → 環境判定とモデル選択（`tools/setup_env.py`）→ モデルの事前ダウンロード → スタートアップ登録、まで一括で行う。
3. 起動は次回ログインから自動。手動なら `run.bat`。

## 使い方

- **サイドボタン（既定: 戻る側 XButton1）を押しながら話し、離す** → 貼り付け
- **Esc**（録音中）→ キャンセル
- 0.35 秒未満の短い押下は誤クリックとして破棄
- 上限 120 秒で自動確定
- トレイの右クリックメニューで認識エンジンの状態確認 / 終了

## 整形（formatter）

速さを優先し、既定ではルールベース整形のみ（ネットワーク待ちなし）。

- フィラー除去: 文頭・節頭の「えーと / あのー / そのー / えっと / うーん / なんか」
- 音声コマンド:
  - `くてん` → `。`、`とうてん` → `、`(誤変換のない長い形。どこでも有効)
  - `かいぎょう` → 改行、`くうぎょう` → 空行
  - 区切りで独立した `まる` → `。`、`てん` → `、`
  - `aggressive_commands: true` にすると文中の `まる/てん` も変換する（誤変換リスクあり、任意）
- 正規化: `?→？`、`!→！`、句読点の重複圧縮、日本語間の空白除去、文末の `。` 補完

任意で LLM 整形も可能（`polish_enabled` + OpenAI 互換エンドポイント）。整形のみ・内容追加なしのプロンプトで、失敗時はルール整形の結果にフォールバックする。既定は OFF。

## 設定（config.json）

| キー | 既定 | 意味 |
|---|---|---|
| `engine` | `local` | `local`（この PC で認識）/ `haas`（siniku の WSL サーバー、任意） |
| `whisper_model` | `auto` | モデル名 or `auto`（環境判定） |
| `whisper_device` | `auto` | `cuda` / `cpu` / `auto` |
| `whisper_compute` | `auto` | `float16` / `int8_float16` / `int8` / `auto` |
| `partial_interval_seconds` | `1.0` | ライブ表示の再認識間隔 |
| `trigger` | `xbutton1` | `xbutton1`（戻る）/ `xbutton2`（進む）/ `both` |
| `suppress_trigger` | `true` | サイドボタンの本来の動作（ブラウザの戻る/進む）を抑止 |
| `min_press_ms` | `350` | これ未満の押下は破棄 |
| `max_seconds` | `120` | 録音上限 |
| `click_to_focus` | `true` | 離した位置のウィンドウをクリックしてから貼る |
| `restore_clipboard` | `true` | 貼り付け後に元のクリップボードを復元 |
| `mic_device` | `null` | マイクのデバイス番号（sounddevice の index）。null は既定マイク |

### 任意エンジン: Haas サーバー（siniku 専用）

`engine: "haas"` にすると、siniku の WSL で動く既存の STT サーバー（RE-USE + Haas-ja、:8790）を使う従来構成になる。partial は WebSocket ストリーミング、確定は RE-USE + Haas のフル品質パス。サーバーが固まった時の復旧はタスクスケジューラの `EchoBridge-G2-start` を再実行する（`/health` が返るのに認識が返らない症状がある）。

## 構成

```
main.py                  エントリ（tkinter 本体 + トレイ）
tools/setup_env.py       環境判定 → モデル選択 → CUDA導入 → config書込 → 事前DL
voice_paste/
  app.py                 状態機械（押下→録音→確定→整形→貼付）
  local_stt.py           faster-whisper ローカル認識 + LocalAgreement
  env_detect.py          GPU/VRAM/RAM/CPU 検出とモデル選択ティア
  stt_client.py          Haas サーバー用クライアント（任意エンジン）
  formatter.py           整形ルール（単体テスト対象）
  polish.py              任意の LLM 整形
  audio.py               sounddevice 録音（16kHz mono）
  overlay.py             カーソル追従オーバーレイ（tkinter）
  win32_input.py         低レベルマウス/キーボードフック、クリップボード、SendInput 貼付（ctypes のみ）
  config.py              設定
tests/                   formatter / stt_client / env_detect / agreement の単体テスト
models/                  ダウンロードされたモデル（git 管理外）
```

## テスト

```
python -m pytest tests/
```

## 既知の注意

- サイドボタンの抑止はこのアプリが掴んだボタンのみ。他アプリの XButton 割り当てと競合する場合は `trigger` を変える。
- 管理者権限で動くウィンドウへの貼り付けは、このアプリも管理者で起動した場合のみ効く（Windows の UIPI）。
- CPU ティアでは長い発話の確定認識に数秒かかることがある。GPU ティア（large-v3-turbo）では 10 秒の発話でも 1 秒未満が目安。
- モデルの初回ダウンロードにはネットワークが必要。
